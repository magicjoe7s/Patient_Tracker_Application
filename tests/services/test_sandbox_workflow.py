"""Database-backed Slice 9 Sandbox workflow tests."""

from datetime import UTC, datetime

import pytest

from icu_patient_tracker.domain.enums import (
    ClinicalPriority,
    ReminderScheduleType,
    TaskBucket,
    TaskCategory,
)
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.events import RecordingEventPublisher
from icu_patient_tracker.services.exceptions import InvalidOperationError
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.sandbox_service import SandboxService
from icu_patient_tracker.services.task_service import TaskService

NOW = datetime(2026, 7, 22, 10, tzinfo=UTC)


def test_preview_extract_and_restart_are_lossless_and_idempotent(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    publisher = RecordingEventPublisher()
    patients = PatientService(factory, publisher, now=lambda: NOW)
    tasks = TaskService(factory, publisher)
    sandbox = SandboxService(factory, publisher, now=lambda: NOW)
    patient = patients.create(name="Bella", species="Canine")
    day = patient.hospital_days[0]
    tasks.create(patient.id, day.id, title="Existing task")
    tasks.create(patient.id, day.id, title="Existing POCUS", category=TaskCategory.POCUS)
    text = (
        "## Scratch\n"
        "Free text is preserved.\n"
        "- [x] Already complete\n"
        "- [ ] !! CBC | overnight | nocarry | reminder:60m\n"
        "- [ ] POCUS abdomen | urgent\n"
        "- [ ]   existing TASK\n"
        "- [ ] Existing POCUS\n"
        "- [ ] #INPUT#\n"
    )

    assert sandbox.save(patient.id, day.id, text) == text
    assert tasks.list_for_day(patient.id, day.id)[0].title == "Existing task"
    preview = sandbox.preview(patient.id, day.id)

    assert [candidate.line_number for candidate in preview.candidates] == [4, 5]
    assert [candidate.task.category for candidate in preview.candidates] == [
        TaskCategory.CLINICAL,
        TaskCategory.POCUS,
    ]
    assert {ignored.reason for ignored in preview.ignored} == {
        "duplicate task",
        "placeholder or empty task",
    }

    created = sandbox.extract(
        patient.id,
        day.id,
        expected_sandbox_text=preview.sandbox_text,
        line_numbers=(4, 5),
    )
    assert len(created) == 2
    clinical = created[0]
    assert clinical.title == "CBC"
    assert clinical.priority is ClinicalPriority.CRITICAL
    assert clinical.bucket is TaskBucket.OVERNIGHT
    assert clinical.carry_forward is False
    assert clinical.source == "sandbox"
    assert clinical.reminder is not None
    assert clinical.reminder.schedule_type is ReminderScheduleType.INTERVAL
    assert clinical.reminder.interval_minutes == 60
    assert created[1].category is TaskCategory.POCUS
    assert sandbox.get(patient.id, day.id) == text
    assert sandbox.preview(patient.id, day.id).candidates == ()

    restarted = SandboxService(factory, now=lambda: NOW)
    assert restarted.get(patient.id, day.id) == text
    loaded_titles = {task.title for task in tasks.list_for_day(patient.id, day.id)}
    assert loaded_titles == {"Existing task", "Existing POCUS", "CBC", "POCUS abdomen"}


def test_changed_sandbox_invalidates_preview_without_creating_tasks(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: NOW)
    sandbox = SandboxService(factory, now=lambda: NOW)
    tasks = TaskService(factory)
    patient = patients.create(name="Milo", species="Feline")
    day = patient.hospital_days[0]
    sandbox.save(patient.id, day.id, "- [ ] CBC")
    preview = sandbox.preview(patient.id, day.id)
    sandbox.save(patient.id, day.id, "- [ ] Chemistry")

    with pytest.raises(InvalidOperationError, match="changed after preview"):
        sandbox.extract(
            patient.id,
            day.id,
            expected_sandbox_text=preview.sandbox_text,
            line_numbers=(1,),
        )

    assert tasks.list_for_day(patient.id, day.id) == ()
