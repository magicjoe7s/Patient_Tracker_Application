"""SQLite initialization, safety setting, transaction, and cleanup tests."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.persistence.exceptions import TransactionError


def test_new_database_initializes_current_schema(database_manager: DatabaseManager) -> None:
    settings = database_manager.sqlite_settings()

    assert database_manager.database_path.exists()
    assert settings["foreign_keys"] == 1
    assert settings["journal_mode"] == "wal"
    assert settings["busy_timeout"] == 5000


def test_transaction_commits_and_rollback_discards_all_changes(
    database_manager: DatabaseManager,
) -> None:
    committed = Patient("Committed", "Canine", mrn="111111")
    with database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(committed)

    with (
        pytest.raises(RuntimeError, match="force rollback"),
        database_manager.unit_of_work() as unit_of_work,
    ):
        rolled_back = Patient("Rolled Back", "Feline", mrn="222222")
        unit_of_work.patients.add(rolled_back)
        raise RuntimeError("force rollback")

    with database_manager.unit_of_work() as unit_of_work:
        assert unit_of_work.patients.exists(committed.id)
        assert not unit_of_work.patients.exists(rolled_back.id)


def test_session_resources_close_after_unit_of_work(tmp_path: Path) -> None:
    database_path = tmp_path / "tracker.sqlite3"
    manager = DatabaseManager(database_path)
    manager.initialize()
    with manager.unit_of_work() as unit_of_work:
        assert unit_of_work.patients.list() == ()
    manager.dispose()

    moved_path = tmp_path / "moved.sqlite3"
    database_path.replace(moved_path)
    assert moved_path.exists()


def test_foreign_keys_prevent_orphan_records(database_manager: DatabaseManager) -> None:
    with sqlite3.connect(database_manager.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO problems "
                "(id, problem_list_id, title, description, status, priority, identified_at, "
                "assessment, plan, notes, ordering_position, created_at, updated_at) "
                "VALUES (?, ?, 'Orphan', '', 'active', 'routine', ?, '', '', '', 0, ?, ?)",
                (
                    uuid4().hex,
                    uuid4().hex,
                    "2026-07-20T08:00:00+00:00",
                    "2026-07-20T08:00:00+00:00",
                    "2026-07-20T08:00:00+00:00",
                ),
            )


def test_competing_nested_use_of_same_unit_is_rejected(
    database_manager: DatabaseManager,
) -> None:
    unit_of_work = database_manager.unit_of_work()
    with unit_of_work, pytest.raises(TransactionError, match="nested transaction"):
        unit_of_work.__enter__()
