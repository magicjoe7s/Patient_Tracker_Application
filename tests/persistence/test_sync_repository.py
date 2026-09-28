"""Local sync identity, outbox, conflict, and transaction-safety tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.database import DatabaseManager


def test_sync_foundation_migration_adds_tables_and_tracking_columns(
    database_manager: DatabaseManager,
) -> None:
    with sqlite3.connect(database_manager.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        patient_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(patients)").fetchall()
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()

    assert {"sync_devices", "sync_outbox", "sync_conflicts", "sync_state"} <= tables
    assert {"server_version", "deleted_at"} <= patient_columns
    assert revision == ("0014_clinical_sync",)


def test_device_identity_is_created_once_and_cursor_only_moves_forward(
    database_manager: DatabaseManager,
) -> None:
    device_id = uuid4()
    with database_manager.unit_of_work() as unit_of_work:
        created = unit_of_work.sync.ensure_device("ICU Workstation A", device_id=device_id)
        state = unit_of_work.sync.state()

    with database_manager.unit_of_work() as unit_of_work:
        loaded = unit_of_work.sync.ensure_device("ICU Workstation A", device_id=uuid4())
        advanced = unit_of_work.sync.advance_pull_cursor(device_id, 42)
        with pytest.raises(ValueError, match="backwards"):
            unit_of_work.sync.advance_pull_cursor(device_id, 41)

    assert created.id == device_id
    assert loaded.id == device_id
    assert advanced.last_pull_sequence == 42
    assert state is not None
    assert state.device_id == device_id
    assert state.status == "disabled"


def test_outbox_round_trips_json_and_honors_retry_time(
    database_manager: DatabaseManager,
) -> None:
    now = datetime(2026, 8, 23, 12, tzinfo=UTC)
    entity_id = uuid4()
    with database_manager.unit_of_work() as unit_of_work:
        operation = unit_of_work.sync.queue(
            entity_type="Patient",
            entity_id=entity_id,
            operation="upsert",
            base_server_version=3,
            payload={"id": entity_id.hex, "name": "Synthetic Patient"},
            created_at=now,
        )

    with database_manager.unit_of_work() as unit_of_work:
        pending = unit_of_work.sync.pending(now=now)
        failed = unit_of_work.sync.mark_failed(
            operation.operation_id,
            error="temporary network failure",
            retry_at=now + timedelta(minutes=2),
        )

    with database_manager.unit_of_work() as unit_of_work:
        not_due = unit_of_work.sync.pending(now=now + timedelta(minutes=1))
        due = unit_of_work.sync.pending(now=now + timedelta(minutes=2))

    assert len(pending) == 1
    assert pending[0].entity_type == "patient"
    assert pending[0].payload["name"] == "Synthetic Patient"
    assert failed.attempt_count == 1
    assert not_due == ()
    assert due == (failed,)


def test_patient_and_outbox_operation_commit_and_roll_back_together(
    database_manager: DatabaseManager,
) -> None:
    committed = Patient("Committed Synthetic", "Canine")
    with database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(committed)
        committed_operation = unit_of_work.sync.queue(
            entity_type="patient",
            entity_id=committed.id,
            operation="upsert",
            base_server_version=0,
            payload={"id": committed.id.hex, "name": committed.name},
        )

    rolled_back = Patient("Rolled Back Synthetic", "Feline")
    with (
        pytest.raises(RuntimeError, match="force rollback"),
        database_manager.unit_of_work() as unit_of_work,
    ):
        unit_of_work.patients.add(rolled_back)
        rolled_back_operation = unit_of_work.sync.queue(
            entity_type="patient",
            entity_id=rolled_back.id,
            operation="upsert",
            base_server_version=0,
            payload={"id": rolled_back.id.hex, "name": rolled_back.name},
        )
        raise RuntimeError("force rollback")

    with database_manager.unit_of_work() as unit_of_work:
        pending_ids = {item.operation_id for item in unit_of_work.sync.pending()}
        assert unit_of_work.patients.exists(committed.id)
        assert not unit_of_work.patients.exists(rolled_back.id)

    assert committed_operation.operation_id in pending_ids
    assert rolled_back_operation.operation_id not in pending_ids


def test_conflict_preserves_both_versions_until_explicit_resolution(
    database_manager: DatabaseManager,
) -> None:
    now = datetime(2026, 8, 23, 13, tzinfo=UTC)
    entity_id = uuid4()
    with database_manager.unit_of_work() as unit_of_work:
        operation = unit_of_work.sync.queue(
            entity_type="patient",
            entity_id=entity_id,
            operation="upsert",
            base_server_version=4,
            payload={"name": "Local Name"},
            created_at=now,
        )
        conflict = unit_of_work.sync.record_conflict(
            operation.operation_id,
            server_payload={"name": "Server Name"},
            server_version=5,
            detected_at=now,
        )

    with database_manager.unit_of_work() as unit_of_work:
        unresolved = unit_of_work.sync.unresolved_conflicts()
        resolved = unit_of_work.sync.resolve_conflict(
            conflict.id,
            resolution="keep_server",
            resolved_at=now + timedelta(minutes=1),
        )

    assert unresolved == (conflict,)
    assert conflict.local_payload == {"name": "Local Name"}
    assert conflict.server_payload == {"name": "Server Name"}
    assert resolved.resolution == "keep_server"
    assert resolved.resolved_at == now + timedelta(minutes=1)
