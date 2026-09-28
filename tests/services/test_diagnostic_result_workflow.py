"""Structured diagnostic-result workflow tests."""

from icu_patient_tracker.domain.enums import TaskCategory, TaskStatus
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.diagnostic_result_service import DiagnosticResultService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.task_service import TaskService


def test_result_is_saved_in_place_and_completion_is_optional(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patient = PatientService(factory).create(name="Bella", species="Canine")
    day = patient.hospital_days[0]
    task = TaskService(factory).create(
        patient.id,
        day.id,
        title="CBC",
        category=TaskCategory.DIAGNOSTIC,
    )
    service = DiagnosticResultService(factory)

    preliminary = service.record(patient.id, day.id, task.id, "Preliminary result", complete=False)
    result_id = preliminary.diagnostic_result.id if preliminary.diagnostic_result else None
    assert preliminary.status is TaskStatus.PENDING
    assert preliminary.diagnostic_result is not None
    assert preliminary.diagnostic_result.result_text == "Preliminary result"

    completed = service.record(
        patient.id,
        day.id,
        task.id,
        "Mild nonregenerative anemia; platelets adequate",
        complete=True,
    )
    assert completed.status is TaskStatus.COMPLETED
    assert completed.diagnostic_result is not None
    assert completed.diagnostic_result.id == result_id

    with database_manager.unit_of_work() as unit_of_work:
        reloaded = unit_of_work.patients.get(patient.id)
    stored = reloaded.hospital_days[0].tasks[0]
    assert stored.diagnostic_result is not None
    assert stored.diagnostic_result.result_text == (
        "Mild nonregenerative anemia; platelets adequate"
    )
