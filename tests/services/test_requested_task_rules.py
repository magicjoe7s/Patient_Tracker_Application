"""Regression coverage for the requested task-manager rules."""

from datetime import UTC, datetime, timedelta

from icu_patient_tracker.domain.enums import TaskBucket, TaskCategory, TaskStatus
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.sandbox_service import SandboxService
from icu_patient_tracker.services.task_service import TaskService

NOW = datetime(2026, 9, 8, 8, tzinfo=UTC)


def test_sandbox_tasks_default_to_no_carry_and_sync_the_source_check(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patient = PatientService(factory, now=lambda: NOW).create(name="Bella", species="Canine")
    day = patient.hospital_days[0]
    sandbox = SandboxService(factory, now=lambda: NOW)
    tasks = TaskService(factory)
    sandbox.save(patient.id, day.id, "- [ ] Recheck PCV")
    preview = sandbox.preview(patient.id, day.id)
    created = sandbox.extract(
        patient.id,
        day.id,
        expected_sandbox_text=preview.sandbox_text,
        line_numbers=(1,),
    )[0]

    assert created.carry_forward is False
    tasks.complete_from(patient.id, created.id)
    assert sandbox.get(patient.id, day.id) == "- [x] Recheck PCV"
    following = HospitalDayService(factory).create(
        patient.id, start_at=NOW + timedelta(days=1)
    )
    assert following.tasks == ()


def test_task_defaults_routing_and_housekeeping_carry_policy(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patient = PatientService(factory, now=lambda: NOW).create(name="Milo", species="Feline")
    day = patient.hospital_days[0]
    tasks = TaskService(factory)
    diagnostic = tasks.create(
        patient.id, day.id, title="Culture", category=TaskCategory.DIAGNOSTIC
    )
    pocus = tasks.create(patient.id, day.id, title="Point-of-care ultrasound abdomen")
    housekeeping = tasks.create(
        patient.id, day.id, title="Restock", category=TaskCategory.HOUSEKEEPING
    )

    assert diagnostic.bucket is TaskBucket.DIAGNOSTIC
    assert pocus.category is TaskCategory.POCUS
    assert housekeeping.carry_forward is False
    following = HospitalDayService(factory).create(
        patient.id, start_at=NOW + timedelta(days=1)
    )
    assert {task.title for task in following.tasks} == {
        "Culture",
        "Point-of-care ultrasound abdomen",
    }
    assert all(task.status is TaskStatus.PENDING for task in following.tasks)
