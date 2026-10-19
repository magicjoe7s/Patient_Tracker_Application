"""Optional placement persistence, migration and sync compatibility."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text

from icu_patient_tracker.persistence.backup import BackupManager
from icu_patient_tracker.persistence.clinical_payload import decode_patient, encode_patient
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.persistence.migration_manager import MigrationManager
from tests.persistence.factories import make_representative_patient


def test_unknown_placement_roundtrips_restart_backup_and_sync(database_manager, tmp_path):
    patient = make_representative_patient()
    device = patient.hospital_days[0].instrumentation.active_devices[0]
    device.placed_at = None
    device.anatomical_location = ""
    device.size = None
    with database_manager.unit_of_work() as unit:
        unit.patients.add(patient)
        outgoing = unit.clinical_sync.prepare()[0]
    assert outgoing.payload["schema_version"] == 4
    remote = decode_patient(outgoing.payload, patient.id)
    assert remote.hospital_days[0].instrumentation.active_devices[0].placed_at is None
    backup_manager = BackupManager(database_manager.database_path, tmp_path / "backups")
    backup = backup_manager.create_backup()
    backup_manager.restore_backup(backup, prepare_for_replace=database_manager.dispose)
    reopened = DatabaseManager(database_manager.database_path)
    reopened.initialize()
    try:
        with reopened.unit_of_work() as unit:
            restored = unit.patients.get(patient.id)
            actual = restored.hospital_days[0].instrumentation.active_devices[0]
            assert actual.placed_at is None
            assert actual.anatomical_location == ""
            assert actual.created_at == device.created_at
            assert encode_patient(restored) == encode_patient(patient)
    finally:
        reopened.dispose()


def test_existing_format_remains_readable():
    patient = make_representative_patient()
    payload = encode_patient(patient)
    payload["schema_version"] = 1
    assert encode_patient(decode_patient(payload, patient.id)) == encode_patient(patient)
    with pytest.raises(ValueError, match="Update ICU Patient Tracker on both Mac and Windows"):
        decode_patient({"schema_version": 99, "patient": None}, uuid4())


def test_device_migration_preserves_records_and_refuses_lossy_downgrade(tmp_path):
    path = tmp_path / "migration.sqlite3"
    migration = MigrationManager(path)
    migration.upgrade("0014_clinical_sync")
    # Build the representative graph using the old, non-null placement schema.
    database = DatabaseManager(path)
    patient = make_representative_patient()
    with database.unit_of_work() as unit:
        unit.patients.add(patient)
    database.dispose()
    migration.upgrade()
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        columns = {column["name"]: column for column in inspect(connection).get_columns("devices")}
        assert columns["placed_at"]["nullable"]
        assert connection.scalar(text("SELECT count(*) FROM devices")) == 2
        assert connection.scalar(text("SELECT placed_at FROM devices LIMIT 1")) is not None
        connection.execute(text("UPDATE devices SET placed_at = NULL"))
    with pytest.raises(ValueError, match="Cannot downgrade"):
        migration.downgrade("0014_clinical_sync")
    with engine.begin() as connection:
        connection.execute(text("UPDATE devices SET placed_at = :placed"),
                           {"placed": datetime(2026, 7, 20, 8, tzinfo=UTC).isoformat()})
    engine.dispose()
    migration.downgrade("0014_clinical_sync")
    assert migration.current_revision() == "0014_clinical_sync"
