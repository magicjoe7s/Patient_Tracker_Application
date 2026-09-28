"""Free-form diagnostic checklist parsing."""

from icu_patient_tracker.utils.diagnostic_text import parse_diagnostic_text


def test_diagnostic_text_supports_pending_completed_and_result_lines() -> None:
    entries = parse_diagnostic_text("[ ] Culture\n[x] CBC: mild anemia\nChemistry: normal")

    assert [(entry.title, entry.completed, entry.result) for entry in entries] == [
        ("Culture", False, ""),
        ("CBC", True, "mild anemia"),
        ("Chemistry", True, "normal"),
    ]
