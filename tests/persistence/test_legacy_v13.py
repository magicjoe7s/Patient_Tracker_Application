"""Read-only version-13 parser, validation, and safe-report tests."""

from pathlib import Path
from urllib.parse import quote

import pytest

from icu_patient_tracker.persistence.legacy_v13 import LegacyFormatError, LegacyV13Parser


def encoded(value: str) -> str:
    return quote(value, safe="-_.~", encoding="utf-8")


def patient_line(*, mrn: str = "", name: str = "Bella | Test") -> str:
    return "|".join(
        (
            "PATIENT",
            encoded("legacy-1"),
            encoded(name),
            "Active",
            "Stable",
            "CPR",
            encoded("Anemia\nHypotension"),
            encoded("Synthetic patient"),
            "",
            "",
            "",
            encoded("2026-07-20"),
            "",
            encoded(mrn),
        )
    )


def day_line(*, owner: str = "legacy-1") -> str:
    return "|".join(
        (
            "DAY",
            encoded(owner),
            encoded("2026-07-20"),
            "",
            "",
            "",
            "",
            "",
            "1",
            encoded("# SOAP\nSynthetic text"),
            "",
            "",
            "0",
            "",
            "",
            "",
            "",
            "Stable",
        )
    )


def write_pair(
    tmp_path: Path, *, patient: str | None = None, day: str | None = None
) -> tuple[Path, Path]:
    main = tmp_path / "patient_tracker_data.txt"
    archive = tmp_path / "patient_tracker_archive.txt"
    main.write_text(
        "\n".join(("VERSION|13", patient or patient_line(), day or day_line())),
        encoding="utf-8",
    )
    archive.write_text("VERSION|13\nFILE_ROLE|ARCHIVE", encoding="utf-8")
    return main, archive


def test_parser_decodes_losslessly_without_modifying_sources(tmp_path: Path) -> None:
    main, archive = write_pair(tmp_path)
    before = (main.read_bytes(), archive.read_bytes())

    dataset = LegacyV13Parser().parse_pair(main, archive)

    assert dataset.patients[0].name == "Bella | Test"
    assert dataset.patients[0].problem_list == "Anemia\nHypotension"
    assert dataset.patients[0].mrn is None
    assert dataset.days[0].soap_markdown == "# SOAP\nSynthetic text"
    assert (main.read_bytes(), archive.read_bytes()) == before


def test_dry_run_reports_only_safe_counts_and_fingerprints(tmp_path: Path) -> None:
    main, archive = write_pair(tmp_path)

    report = LegacyV13Parser().dry_run(main, archive)

    assert report.valid
    assert report.patient_count == 1
    assert report.day_count == 1
    assert report.missing_mrn_count == 1
    assert report.status_counts == {"Active": 1}
    assert report.setting_count == 0
    assert report.task_count == 0
    assert report.warning_codes == ()
    assert report.main_fingerprint is not None
    assert report.archive_fingerprint is not None
    assert report.errors == ()


def test_parser_rejects_orphan_day_without_exposing_clinical_text(tmp_path: Path) -> None:
    main, archive = write_pair(tmp_path, day=day_line(owner="missing-owner"))

    report = LegacyV13Parser().dry_run(main, archive)

    assert not report.valid
    assert report.errors and "orphan-day" in report.errors[0]
    assert "Bella" not in report.errors[0]
    assert "SOAP" not in report.errors[0]


@pytest.mark.parametrize(
    ("first_line", "code"),
    [("VERSION|12", "unsupported-version"), ("VERSION|14", "unsupported-version")],
)
def test_parser_rejects_non_v13_sources(tmp_path: Path, first_line: str, code: str) -> None:
    main, archive = write_pair(tmp_path)
    main.write_text(first_line, encoding="utf-8")

    with pytest.raises(LegacyFormatError, match=code):
        LegacyV13Parser().parse_pair(main, archive)


def test_parser_accepts_a_valid_optional_six_digit_mrn(tmp_path: Path) -> None:
    main, archive = write_pair(tmp_path, patient=patient_line(mrn="123456"))

    dataset = LegacyV13Parser().parse_pair(main, archive)

    assert dataset.patients[0].mrn == "123456"
