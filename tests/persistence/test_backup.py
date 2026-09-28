"""Consistent backup, verification, retention, and safe restoration tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.backup import BackupManager
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.persistence.exceptions import RestoreError
from icu_patient_tracker.services.backup_service import BackupService
from icu_patient_tracker.services.exceptions import BackupServiceError


class AdvancingNow:
    """Return a unique deterministic timestamp for each backup name."""

    def __init__(self) -> None:
        self.current = datetime(2026, 7, 20, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        result = self.current
        self.current += timedelta(seconds=1)
        return result


def add_patient(database: DatabaseManager, mrn: str, name: str) -> UUID:
    """Persist one small aggregate for backup assertions."""
    with database.unit_of_work() as unit_of_work:
        patient = Patient(name, "Canine", mrn=mrn)
        unit_of_work.patients.add(patient)
    return patient.id


def test_create_and_verify_consistent_backup(
    database_manager: DatabaseManager, tmp_path: Path
) -> None:
    add_patient(database_manager, "111111", "Original")
    manager = BackupManager(database_manager.database_path, tmp_path / "backups")

    backup = manager.create_backup()
    assert backup.exists()
    assert manager.verify_backup(backup)


def test_corrupt_backup_cannot_replace_active_database(
    database_manager: DatabaseManager, tmp_path: Path
) -> None:
    patient_id = add_patient(database_manager, "111111", "Protected")
    manager = BackupManager(database_manager.database_path, tmp_path / "backups")
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")

    with pytest.raises(RestoreError):
        manager.restore_backup(corrupt, prepare_for_replace=database_manager.dispose)
    with database_manager.unit_of_work() as unit_of_work:
        assert unit_of_work.patients.get(patient_id).name == "Protected"


def test_restore_valid_backup_and_preserve_pre_restore_database(
    database_manager: DatabaseManager, tmp_path: Path
) -> None:
    original_id = add_patient(database_manager, "111111", "In Backup")
    manager = BackupManager(database_manager.database_path, tmp_path / "backups")
    backup = manager.create_backup()
    later_id = add_patient(database_manager, "222222", "Added Later")

    pre_restore = manager.restore_backup(backup, prepare_for_replace=database_manager.dispose)
    restored = DatabaseManager(database_manager.database_path)
    restored.initialize()
    try:
        with restored.unit_of_work() as unit_of_work:
            assert unit_of_work.patients.exists(original_id)
            assert not unit_of_work.patients.exists(later_id)
    finally:
        restored.dispose()

    preserved = DatabaseManager(pre_restore)
    preserved.initialize()
    try:
        with preserved.unit_of_work() as unit_of_work:
            assert unit_of_work.patients.exists(original_id)
            assert unit_of_work.patients.exists(later_id)
    finally:
        preserved.dispose()


def test_backup_retention_keeps_configured_number(
    database_manager: DatabaseManager, tmp_path: Path
) -> None:
    add_patient(database_manager, "111111", "Patient")
    backup_directory = tmp_path / "backups"
    manager = BackupManager(
        database_manager.database_path,
        backup_directory,
        retention_count=2,
        now=AdvancingNow(),
    )

    manager.create_backup()
    manager.create_backup()
    manager.create_backup()
    assert len(list(backup_directory.glob("*.sqlite3"))) == 2


def test_reviewed_backup_content_change_blocks_restore(
    database_manager: DatabaseManager, tmp_path: Path
) -> None:
    patient_id = add_patient(database_manager, "111111", "Protected")
    manager = BackupManager(database_manager.database_path, tmp_path / "backups")
    service = BackupService(manager)
    backup = manager.create_backup()
    reviewed = service.inspect(backup)
    with backup.open("ab") as stream:
        stream.write(b"changed after review")

    with pytest.raises(BackupServiceError):
        service.restore(
            reviewed.path,
            prepare_for_replace=database_manager.dispose,
            expected_sha256=reviewed.sha256,
        )
    with database_manager.unit_of_work() as unit_of_work:
        assert unit_of_work.patients.exists(patient_id)


def test_restore_failure_reopens_preserved_active_database(
    database_manager: DatabaseManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient_id = add_patient(database_manager, "111111", "Protected")
    manager = BackupManager(database_manager.database_path, tmp_path / "backups")
    backup = manager.create_backup()
    service = BackupService(
        manager,
        prepare_for_replace=database_manager.dispose,
        reopen_after_replace=database_manager.initialize,
    )

    def fail_after_dispose() -> None:
        raise OSError("forced replacement failure")

    monkeypatch.setattr(manager, "_remove_active_sidecars", fail_after_dispose)
    with pytest.raises(BackupServiceError):
        service.restore(backup)

    with database_manager.unit_of_work() as unit_of_work:
        assert unit_of_work.patients.exists(patient_id)
