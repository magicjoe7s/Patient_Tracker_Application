"""Formal schema initialization, upgrade, downgrade, and future-version tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from icu_patient_tracker.persistence.exceptions import UnsupportedSchemaVersionError
from icu_patient_tracker.persistence.migration_manager import (
    CURRENT_SCHEMA_REVISION,
    MigrationManager,
)


def test_earlier_schema_upgrades_and_preserves_task_data(tmp_path: Path) -> None:
    database_path = tmp_path / "earlier.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade("0001_initial_domain")
    task_id = uuid4().hex
    day_id = uuid4().hex
    timestamp = datetime(2026, 7, 20, 8, tzinfo=UTC).isoformat()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO patients "
                "(mrn, name, species, sex, reproductive_status, admission_status, "
                "created_at, updated_at) "
                "VALUES ('123456', 'Bella', 'Canine', 'unknown', 'unknown', "
                "'admitted', :timestamp, :timestamp)"
            ),
            {"timestamp": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO hospital_days "
                "(id, patient_mrn, calendar_date, day_number, start_at, status, "
                "created_at, updated_at) VALUES "
                "(:id, '123456', '2026-07-20', 1, :timestamp, 'open', "
                ":timestamp, :timestamp)"
            ),
            {"id": day_id, "timestamp": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO tasks "
                "(id, hospital_day_id, title, description, status, priority, category, "
                "created_at, updated_at) VALUES "
                "(:id, :day_id, 'Recheck', '', 'pending', 'routine', 'clinical', "
                ":timestamp, :timestamp)"
            ),
            {"id": task_id, "day_id": day_id, "timestamp": timestamp},
        )
    engine.dispose()

    manager.upgrade()
    assert manager.current_revision() == CURRENT_SCHEMA_REVISION
    upgraded_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with upgraded_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, lineage_id, occurrence_number, carry_forward FROM tasks WHERE id = :id"
            ),
            {"id": task_id},
        ).one()
        patient_row = connection.execute(
            text("SELECT id, mrn FROM patients WHERE mrn = '123456'")
        ).one()
        day_owner = connection.scalar(
            text("SELECT patient_id FROM hospital_days WHERE id = :id"), {"id": day_id}
        )
    upgraded_engine.dispose()
    assert row == (task_id, task_id, 1, 1)
    assert len(patient_row.id) == 32
    assert patient_row.mrn == "123456"
    assert day_owner == patient_row.id


def test_current_schema_can_downgrade_to_supported_previous_revision(tmp_path: Path) -> None:
    manager = MigrationManager(tmp_path / "downgrade.sqlite3")
    manager.upgrade()
    manager.downgrade("0001_initial_domain")
    assert manager.current_revision() == "0001_initial_domain"


def test_chronological_day_migration_renumbers_existing_backdated_days(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "chronological.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade("0004_patient_uuid_identity")
    patient_id = uuid4().hex
    later_day_id = uuid4().hex
    earlier_day_id = uuid4().hex
    timestamp = datetime(2026, 7, 22, 8, tzinfo=UTC).isoformat()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO patients "
                "(id, mrn, name, species, sex, reproductive_status, admission_status, "
                "created_at, updated_at, one_line_summary, code_status, acuity, active_order) "
                "VALUES (:id, NULL, 'Bella', 'Canine', 'unknown', 'unknown', 'admitted', "
                ":timestamp, :timestamp, '', 'full_code', 'stable', 0)"
            ),
            {"id": patient_id, "timestamp": timestamp},
        )
        for day_id, calendar_date, day_number in (
            (later_day_id, "2026-07-22", 1),
            (earlier_day_id, "2026-07-20", 2),
        ):
            connection.execute(
                text(
                    "INSERT INTO hospital_days "
                    "(id, patient_id, calendar_date, day_number, start_at, status, acuity, "
                    "treatment_changes, physical_examination, assessment, clinical_summary, "
                    "created_at, updated_at) VALUES "
                    "(:id, :patient_id, :calendar_date, :day_number, :start_at, 'open', "
                    "'stable', '', '', '', '', :timestamp, :timestamp)"
                ),
                {
                    "id": day_id,
                    "patient_id": patient_id,
                    "calendar_date": calendar_date,
                    "day_number": day_number,
                    "start_at": f"{calendar_date}T08:00:00+00:00",
                    "timestamp": timestamp,
                },
            )
    engine.dispose()

    manager.upgrade()

    upgraded_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with upgraded_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT calendar_date, day_number FROM hospital_days "
                "WHERE patient_id = :patient_id ORDER BY calendar_date"
            ),
            {"patient_id": patient_id},
        ).all()
    upgraded_engine.dispose()
    assert rows == [("2026-07-20", 1), ("2026-07-22", 2)]


def test_problem_lineage_migration_preserves_existing_problem(tmp_path: Path) -> None:
    database_path = tmp_path / "problem-lineage.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade("0005_chronological_day_numbers")
    patient_id = uuid4().hex
    day_id = uuid4().hex
    problem_list_id = uuid4().hex
    problem_id = uuid4().hex
    timestamp = datetime(2026, 7, 22, 8, tzinfo=UTC).isoformat()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO patients "
                "(id, mrn, name, species, sex, reproductive_status, admission_status, "
                "created_at, updated_at, one_line_summary, code_status, acuity, active_order) "
                "VALUES (:id, NULL, 'Bella', 'Canine', 'unknown', 'unknown', 'admitted', "
                ":timestamp, :timestamp, '', 'full_code', 'stable', 0)"
            ),
            {"id": patient_id, "timestamp": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO hospital_days "
                "(id, patient_id, calendar_date, day_number, start_at, status, acuity, "
                "treatment_changes, physical_examination, assessment, clinical_summary, "
                "created_at, updated_at) VALUES "
                "(:id, :patient_id, '2026-07-22', 1, :timestamp, 'open', 'stable', "
                "'', '', '', '', :timestamp, :timestamp)"
            ),
            {"id": day_id, "patient_id": patient_id, "timestamp": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO problem_lists (id, hospital_day_id, created_at, updated_at) "
                "VALUES (:id, :day_id, :timestamp, :timestamp)"
            ),
            {"id": problem_list_id, "day_id": day_id, "timestamp": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO problems "
                "(id, problem_list_id, title, description, status, priority, identified_at, "
                "assessment, plan, notes, ordering_position, created_at, updated_at) VALUES "
                "(:id, :list_id, 'Anemia', '', 'active', 'routine', :timestamp, '', '', '', "
                "0, :timestamp, :timestamp)"
            ),
            {"id": problem_id, "list_id": problem_list_id, "timestamp": timestamp},
        )
    engine.dispose()

    manager.upgrade()

    upgraded_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with upgraded_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, lineage_id, source_problem_id, occurrence_number "
                "FROM problems WHERE id = :id"
            ),
            {"id": problem_id},
        ).one()
    upgraded_engine.dispose()
    assert row == (problem_id, problem_id, None, 1)


def test_reminder_shown_state_migration_adds_nullable_timestamp(tmp_path: Path) -> None:
    database_path = tmp_path / "reminder-shown.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade("0006_problem_lineage")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        before = {row.name for row in connection.execute(text("PRAGMA table_info(reminders)"))}
    assert "last_shown_at" not in before

    manager.upgrade()

    with engine.connect() as connection:
        columns = {
            row.name: row for row in connection.execute(text("PRAGMA table_info(reminders)"))
        }
    engine.dispose()
    assert columns["last_shown_at"].notnull == 0


def test_canonical_soap_migration_adds_lossless_text_and_staff_fields(tmp_path: Path) -> None:
    database_path = tmp_path / "canonical-soap.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade("0007_reminder_shown_state")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        soap_before = {
            row.name for row in connection.execute(text("PRAGMA table_info(soap_documents)"))
        }
    assert "markdown_text" not in soap_before

    manager.upgrade()

    with engine.connect() as connection:
        soap_columns = {
            row.name: row for row in connection.execute(text("PRAGMA table_info(soap_documents)"))
        }
        day_columns = {
            row.name: row for row in connection.execute(text("PRAGMA table_info(hospital_days)"))
        }
    engine.dispose()
    assert soap_columns["markdown_text"].notnull == 1
    assert day_columns["overnight_resident"].notnull == 1
    assert day_columns["faculty"].notnull == 1


def test_day_sandbox_migration_adds_non_null_lossless_text(tmp_path: Path) -> None:
    database_path = tmp_path / "day-sandbox.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade("0008_canonical_soap")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        before = {row.name for row in connection.execute(text("PRAGMA table_info(hospital_days)"))}
    assert "sandbox_text" not in before

    manager.upgrade()

    with engine.connect() as connection:
        columns = {
            row.name: row for row in connection.execute(text("PRAGMA table_info(hospital_days)"))
        }
    engine.dispose()
    assert columns["sandbox_text"].notnull == 1
    assert columns["sandbox_text"].dflt_value == "''"


def test_emr_upload_migration_adds_false_day_owned_state(tmp_path: Path) -> None:
    database_path = tmp_path / "emr-state.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade("0009_day_sandbox")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        before = {row.name for row in connection.execute(text("PRAGMA table_info(hospital_days)"))}
    assert "emr_uploaded" not in before

    manager.upgrade()

    with engine.connect() as connection:
        columns = {
            row.name: row for row in connection.execute(text("PRAGMA table_info(hospital_days)"))
        }
    engine.dispose()
    assert columns["emr_uploaded"].notnull == 1
    assert columns["emr_uploaded"].dflt_value in {"0", "false"}


def test_unknown_future_schema_is_rejected_before_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "future.sqlite3"
    manager = MigrationManager(database_path)
    manager.upgrade()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999_future'"))
    engine.dispose()

    with pytest.raises(UnsupportedSchemaVersionError, match="9999_future"):
        manager.upgrade()
