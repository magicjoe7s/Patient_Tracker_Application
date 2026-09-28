"""Atomic staging-import, reconciliation, and idempotency tests."""

from pathlib import Path
from urllib.parse import quote

import pytest
from sqlalchemy import URL, create_engine, func, select, text
from sqlalchemy.orm import Session

import icu_patient_tracker.persistence.legacy_import as import_module
from icu_patient_tracker.persistence.legacy_import import LegacyImportError, LegacyV13Importer
from icu_patient_tracker.persistence.orm_models import PatientRecord


def _encoded(value: str) -> str:
    return quote(value, safe="-_.~", encoding="utf-8")


def _patient(identifier: str, day_key: str, *, name: str = "Synthetic") -> str:
    return "|".join(
        (
            "PATIENT",
            _encoded(identifier),
            _encoded(name),
            "Active",
            "Watcher",
            "DNR Assist",
            _encoded("Anemia"),
            _encoded("Synthetic summary"),
            _encoded("DEA 1.1"),
            "",
            "",
            _encoded(day_key),
            "",
            "",
        )
    )


def _day(identifier: str, day_key: str) -> str:
    task = "[ ] Recheck synthetic value | p:urgent | r:60m | a:20260720120000 | id:t_1"
    return "|".join(
        (
            "DAY",
            _encoded(identifier),
            _encoded(day_key),
            _encoded(task),
            "",
            _encoded("Continue synthetic treatment"),
            _encoded("Legacy reminder summary"),
            _encoded("Synthetic assessment"),
            "1",
            _encoded("# SOAP\nLossless synthetic Markdown"),
            _encoded("Peripheral IV catheter, left cephalic"),
            _encoded("Synthetic examination"),
            "1",
            _encoded("Synthetic sandbox"),
            "",
            _encoded("Resident"),
            _encoded("Faculty"),
            "Watcher",
        )
    )


def _write_pair(tmp_path: Path, *, two_patients: bool = False) -> tuple[Path, Path]:
    main = tmp_path / "main.txt"
    archive = tmp_path / "archive.txt"
    lines = [
        "VERSION|13",
        "ACTIVE_ORDER|legacy-1",
        "THEME_MODE|clinical_blue",
        "HOUSEKEEPING|",
        _patient("legacy-1", "day:20260720:2026-07-20:synthetic"),
        _day("legacy-1", "day:20260720:2026-07-20:synthetic"),
    ]
    if two_patients:
        lines.extend(
            (
                _patient("legacy-2", "2026-07-21", name="Second"),
                _day("legacy-2", "2026-07-21"),
            )
        )
    main.write_text("\n".join(lines), encoding="utf-8")
    archive.write_text("VERSION|13\nFILE_ROLE|ARCHIVE", encoding="utf-8")
    return main, archive


def test_confirmed_import_reconciles_and_refuses_repeat(tmp_path: Path) -> None:
    main, archive = _write_pair(tmp_path)
    source_before = (main.read_bytes(), archive.read_bytes())
    target = tmp_path / "staging.sqlite3"
    importer = LegacyV13Importer(timezone_name="UTC")
    dataset = importer._parser.parse_pair(main, archive)

    report = importer.import_to(
        main,
        archive,
        target,
        tmp_path / "backups",
        confirmation=importer.confirmation_token(dataset),
    )

    assert report.imported and report.reconciled
    assert report.counts.patient_count == 1
    assert report.counts.day_count == 1
    assert report.counts.task_count == 1
    assert report.counts.reminder_count == 1
    assert Path(report.backup_path).is_file()
    assert (main.read_bytes(), archive.read_bytes()) == source_before
    with pytest.raises(LegacyImportError, match="source-pair-already-imported"):
        importer.import_to(
            main,
            archive,
            target,
            tmp_path / "backups",
            confirmation=importer.confirmation_token(dataset),
        )


def test_confirmation_mismatch_never_creates_target(tmp_path: Path) -> None:
    main, archive = _write_pair(tmp_path)
    target = tmp_path / "not-created.sqlite3"

    with pytest.raises(LegacyImportError, match="source-confirmation-mismatch"):
        LegacyV13Importer(timezone_name="UTC").import_to(
            main, archive, target, tmp_path / "backups", confirmation="wrong"
        )

    assert not target.exists()


def test_failure_rolls_back_every_clinical_row_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, archive = _write_pair(tmp_path, two_patients=True)
    target = tmp_path / "rollback.sqlite3"
    importer = LegacyV13Importer(timezone_name="UTC")
    dataset = importer._parser.parse_pair(main, archive)
    real_mapper = import_module.patient_to_record
    calls = 0

    def fail_second(patient: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced synthetic failure")
        return real_mapper(patient)  # type: ignore[arg-type]

    monkeypatch.setattr(import_module, "patient_to_record", fail_second)
    with pytest.raises(RuntimeError, match="forced synthetic failure"):
        importer.import_to(
            main,
            archive,
            target,
            tmp_path / "backups",
            confirmation=importer.confirmation_token(dataset),
        )

    engine = create_engine(URL.create("sqlite", database=str(target)))
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(PatientRecord)) == 0
            assert session.scalar(text("SELECT count(*) FROM legacy_import_runs")) == 0
    finally:
        engine.dispose()
