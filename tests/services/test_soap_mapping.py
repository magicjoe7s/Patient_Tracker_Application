"""Golden and lossless tests for the canonical Slice 8 SOAP mapper."""

from dataclasses import replace
from datetime import date

from icu_patient_tracker.services.soap_mapping import (
    CanonicalSOAPMapper,
    SOAPDiagnosticResult,
    SOAPRenderContext,
)


def context() -> SOAPRenderContext:
    return SOAPRenderContext(
        day_number=2,
        calendar_date=date(2026, 7, 22),
        code_status="CPR",
        clinical_trend="Watcher",
        one_liner="Post-operative monitoring",
        problems=("Anemia", "Hypotension"),
        physical_examination="HR 110 bpm\nMM pink",
        diagnostic_summary="CBC: mild anemia\nCulture: pending",
        treatment_changes="Reduce fluids",
        instrumentation=("- Urinary Catheter: indwelling",),
        device_output_labels=("UOP",),
        assessment="Perfusion improving",
        daytime_resident="Dr. Day",
        overnight_resident="Dr. Night",
        faculty="Dr. Faculty",
    )


def test_canonical_template_matches_reference_order_and_values() -> None:
    markdown = CanonicalSOAPMapper().render(context())

    assert (
        markdown
        == """# Day #INPUT# ICU hospitalization #INPUT# 07/22/2026 - 9am 07/23/2026
**Code Status:** CPR
**Clinical Trend:** Watcher

---
**One Liner:** #INPUT#

---
## **Problem list**
1. #INPUT#

---
## **Pertinent exam findings**
**AM:**
- #INPUT#

**PM:**
- #INPUT#

---
**Diagnostic Summary**
- #INPUT#

**Treatment changes**
- #INPUT#

**instrumentation:**

**Ins/Out:**
- *IVF:* #INPUT#
- *Medications:* #INPUT#
- *Diet:* #INPUT#

---

## **Assessment**
**AM**
- #INPUT#

**PM**
- #INPUT#

## **Recommendations**
*Diagnostics*
- #INPUT#

*Therapies*
- #INPUT#

---

*Daytime primary ICU resident:* Dr. Day
*Overnight ICU Resident:* #INPUT#
*Faculty:* #INPUT#"""
    )


def test_unfilled_template_does_not_map_placeholders_to_empty_clinical_values() -> None:
    parsed = CanonicalSOAPMapper().parse(CanonicalSOAPMapper().render(context()))

    assert parsed.code_status == "CPR"
    assert parsed.clinical_trend == "Watcher"
    assert parsed.one_liner is None
    assert parsed.problems is None
    assert parsed.physical_examination is None
    assert parsed.diagnostic_summary is None
    assert parsed.treatment_changes is None
    assert parsed.assessment is None
    assert parsed.overnight_resident is None
    assert parsed.faculty is None


def test_diagnostic_results_render_on_one_line_and_free_summary_round_trips() -> None:
    mapper = CanonicalSOAPMapper()
    markdown = mapper.refresh(
        mapper.render(context()),
        replace(
            context(),
            diagnostic_summary="Additional context",
            diagnostic_results=(
                SOAPDiagnosticResult("CBC", "Mild anemia; platelets adequate", True),
                SOAPDiagnosticResult("Thoracic radiographs", "Improving infiltrates", False),
            ),
        ),
        ("diagnostics",),
    )

    assert "- [x] CBC: Mild anemia; platelets adequate" in markdown
    assert "- [ ] Thoracic radiographs: Improving infiltrates" in markdown
    assert mapper.parse(markdown).diagnostic_summary == "Additional context"


def test_parser_extracts_recognized_fields_without_consuming_unknown_text() -> None:
    mapper = CanonicalSOAPMapper()
    markdown = mapper.refresh(
        mapper.render(context()),
        context(),
        (
            "one_liner",
            "problem_list",
            "physical_examination",
            "diagnostics",
            "treatment_changes",
            "instrumentation",
            "assessment",
            "staff",
        ),
    ).replace(
        "## **Recommendations**",
        "Custom unknown heading\nDo not alter this text\n\n## **Recommendations**",
    )

    parsed = mapper.parse(markdown)

    assert parsed.one_liner == "Post-operative monitoring"
    assert parsed.problems == ("Anemia", "Hypotension")
    assert parsed.physical_examination == "HR 110 bpm\nMM pink"
    assert parsed.diagnostic_summary == "CBC: mild anemia\nCulture: pending"
    assert parsed.treatment_changes == "Reduce fluids"
    assert parsed.assessment == "Perfusion improving"
    assert parsed.overnight_resident == "Dr. Night"
    assert parsed.faculty == "Dr. Faculty"
    assert "Do not alter this text" in markdown


def test_targeted_refresh_preserves_every_unrelated_byte_around_diagnostic_summary() -> None:
    mapper = CanonicalSOAPMapper()
    original = mapper.refresh(mapper.render(context()), context(), ("diagnostics",))
    original = original.replace(
        "## **Recommendations**",
        "UNRECOGNIZED CUSTOM TEXT\n\n## **Recommendations**",
    )
    changed_context = replace(
        context(),
        diagnostic_summary="CBC: stable\nChemistry: normal",
    )

    refreshed = mapper.refresh(original, changed_context, ("diagnostics",))

    before_suffix = original[original.index("**Treatment changes**") :]
    after_suffix = refreshed[refreshed.index("**Treatment changes**") :]
    assert before_suffix == after_suffix
    assert "UNRECOGNIZED CUSTOM TEXT" in refreshed
    assert "- CBC: stable" in refreshed
    assert "- Chemistry: normal" in refreshed


def test_legacy_diagnostic_checklist_is_not_reverse_mapped_as_summary() -> None:
    mapper = CanonicalSOAPMapper()
    markdown = mapper.render(context()).replace(
        "**Diagnostic Summary**\n- #INPUT#",
        "**Diagnostic Summary**\n- [x] CBC: mild anemia",
    )

    assert mapper.parse(markdown).diagnostic_summary is None


def test_device_refresh_retains_recorded_output_after_device_removal() -> None:
    mapper = CanonicalSOAPMapper()
    original = mapper.refresh(mapper.render(context()), context(), ("instrumentation",)).replace(
        "- *UOP* - #INPUT#", "- *UOP* - 2 mL/kg/hr"
    )
    without_device = replace(
        context(),
        instrumentation=(),
        device_output_labels=(),
    )

    refreshed = mapper.refresh(original, without_device, ("instrumentation",))

    assert "- *UOP* - 2 mL/kg/hr" in refreshed
    assert "**instrumentation:**\n\n**Ins/Out:**" in refreshed


def test_device_refresh_preserves_location_aware_output_values() -> None:
    mapper = CanonicalSOAPMapper()
    with_devices = replace(
        context(),
        device_output_labels=("Left chest tube output", "Right abdominal drain output"),
    )
    original = mapper.refresh(mapper.render(with_devices), with_devices, ("instrumentation",))
    original = original.replace(
        "- *Left chest tube output* - #INPUT#", "- *Left chest tube output* - 40 mL"
    )

    refreshed = mapper.refresh(original, with_devices, ("instrumentation",))

    assert "- *Left chest tube output* - 40 mL" in refreshed
    assert "- *Right abdominal drain output* - #INPUT#" in refreshed
