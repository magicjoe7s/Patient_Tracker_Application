"""Derived task-board projection and mutation workflow tests."""

from datetime import UTC, datetime, timedelta

from icu_patient_tracker.domain.enums import AdmissionStatus, TaskCategory, TaskStatus
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.events import RecordingEventPublisher
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.task_service import TaskService

START = datetime(2026, 7, 20, 8, tzinfo=UTC)


def _services(
    database_manager: DatabaseManager,
) -> tuple[PatientService, HospitalDayService, TaskService, RecordingEventPublisher]:
    publisher = RecordingEventPublisher()
    factory = database_manager.unit_of_work
    return (
        PatientService(factory, publisher, now=lambda: START),
        HospitalDayService(factory, publisher),
        TaskService(factory, publisher),
        publisher,
    )


def test_board_uses_only_newest_occurrence_and_never_reveals_stale_open_copy(
    database_manager: DatabaseManager,
) -> None:
    patients, days, tasks, publisher = _services(database_manager)
    patient = patients.create(name="Bella", species="Canine")
    first_day = patient.hospital_days[0]
    original = tasks.create(
        patient.id,
        first_day.id,
        title="Recheck PCV",
        category=TaskCategory.CLINICAL,
    )
    second_day = days.create(patient.id, start_at=START + timedelta(days=1))

    rows = tasks.board(category=TaskCategory.CLINICAL)

    assert len(rows) == 1
    assert rows[0].patient_id == patient.id
    assert rows[0].hospital_day_id == second_day.id
    assert rows[0].task.lineage_id == original.lineage_id
    assert rows[0].task.occurrence_number == 2

    publisher.events.clear()
    tasks.complete_from(patient.id, rows[0].task.id)

    assert tasks.board(category=TaskCategory.CLINICAL) == ()
    completed = tasks.board(category=TaskCategory.CLINICAL, include_completed=True)
    assert len(completed) == 1
    assert completed[0].task.id == rows[0].task.id
    assert completed[0].task.status is TaskStatus.COMPLETED
    assert [event.operation for event in publisher.events] == ["completed_forward"]


def test_board_applies_category_specific_patient_eligibility(
    database_manager: DatabaseManager,
) -> None:
    patients, _, tasks, _ = _services(database_manager)
    statuses = (
        AdmissionStatus.ADMITTED,
        AdmissionStatus.DISCHARGED,
        AdmissionStatus.TRANSFERRED,
        AdmissionStatus.DECEASED,
        AdmissionStatus.ARCHIVED,
    )
    created = []
    for status in statuses:
        patient = patients.create(name=status.value.title(), species="Unknown")
        day = patient.hospital_days[0]
        for category in (
            TaskCategory.CLINICAL,
            TaskCategory.POCUS,
            TaskCategory.DIAGNOSTIC,
            TaskCategory.HOUSEKEEPING,
        ):
            tasks.create(
                patient.id,
                day.id,
                title=f"{status.value}-{category.value}",
                category=category,
            )
        if status is not AdmissionStatus.ADMITTED:
            patients.change_status(patient.id, status)
        created.append(patient.id)

    assert {row.patient_status for row in tasks.board(category=TaskCategory.CLINICAL)} == {
        AdmissionStatus.ADMITTED
    }
    assert {row.patient_status for row in tasks.board(category=TaskCategory.POCUS)} == {
        AdmissionStatus.ADMITTED
    }
    assert {row.patient_status for row in tasks.board(category=TaskCategory.DIAGNOSTIC)} == {
        AdmissionStatus.ADMITTED,
        AdmissionStatus.DISCHARGED,
        AdmissionStatus.TRANSFERRED,
    }
    housekeeping = tasks.board(category=TaskCategory.HOUSEKEEPING)
    assert {row.patient_id for row in housekeeping} == set(created)


def test_board_is_rederived_from_canonical_task_mutations(
    database_manager: DatabaseManager,
) -> None:
    patients, _, tasks, _ = _services(database_manager)
    patient = patients.create(name="Milo", species="Feline")
    day = patient.hospital_days[0]
    task = tasks.create(
        patient.id,
        day.id,
        title="Original",
        category=TaskCategory.DIAGNOSTIC,
    )

    first_projection = tasks.board(category=TaskCategory.DIAGNOSTIC)
    tasks.update_from(patient.id, task.id, title="Updated")
    second_projection = tasks.board(category=TaskCategory.DIAGNOSTIC)

    assert first_projection[0].task.title == "Original"
    assert second_projection[0].task.title == "Updated"
    assert first_projection[0].task is not second_projection[0].task
