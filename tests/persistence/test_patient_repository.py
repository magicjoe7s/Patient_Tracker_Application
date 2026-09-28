"""Patient aggregate CRUD and full clinical-graph round-trip tests."""

import pytest

from icu_patient_tracker.domain.enums import (
    AdmissionStatus,
    DeviceStatus,
    DocumentStatus,
    TaskStatus,
)
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.persistence.exceptions import (
    DuplicateIdentityError,
    RecordNotFoundError,
)
from tests.persistence.factories import make_representative_patient


def test_create_and_reload_complete_representative_graph(
    database_manager: DatabaseManager,
) -> None:
    patient = make_representative_patient()
    with database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(patient)

    database_manager.dispose()
    reopened = DatabaseManager(database_manager.database_path)
    reopened.initialize()
    try:
        with reopened.unit_of_work() as unit_of_work:
            loaded = unit_of_work.patients.get(patient.id)
    finally:
        reopened.dispose()

    assert loaded.mrn == patient.mrn
    assert [day.id for day in loaded.hospital_days] == [day.id for day in patient.hospital_days]
    first_day, second_day = loaded.hospital_days
    assert [problem.title for problem in first_day.problem_list.problems] == [
        "Anemia",
        "Hypotension",
    ]
    assert [device.status for device in first_day.instrumentation.devices] == [
        DeviceStatus.ACTIVE,
        DeviceStatus.REMOVED,
    ]
    original_task = first_day.tasks[0]
    carried_task = second_day.tasks[0]
    assert original_task.status is TaskStatus.COMPLETED
    assert original_task.reminder is not None
    assert carried_task.lineage_id == original_task.lineage_id
    assert carried_task.source_task_id == original_task.id
    assert carried_task.occurrence_number == 2
    assert first_day.soap_documents[0].status is DocumentStatus.FINALIZED
    assert first_day.soap_documents[0].problem_ids == tuple(
        problem.id for problem in first_day.problem_list.problems
    )
    assert first_day.soap_documents[1].status is DocumentStatus.AMENDED
    assert first_day.soap_documents[1].amends_document_id == first_day.soap_documents[0].id


def test_update_and_reload_patient_aggregate(database_manager: DatabaseManager) -> None:
    patient = make_representative_patient()
    with database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(patient)

    patient.update_body_weight(13.1)
    patient.change_admission_status(AdmissionStatus.DISCHARGED)
    patient.hospital_days[1].tasks[0].complete()
    with database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.save(patient)
    with database_manager.unit_of_work() as unit_of_work:
        reloaded = unit_of_work.patients.get(patient.id)

    assert reloaded.body_weight_kg == 13.1
    assert reloaded.admission_status is AdmissionStatus.DISCHARGED
    assert reloaded.hospital_days[1].tasks[0].status is TaskStatus.COMPLETED


def test_duplicate_missing_list_and_delete_behavior(database_manager: DatabaseManager) -> None:
    patient = make_representative_patient()
    with database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(patient)

    with pytest.raises(DuplicateIdentityError), database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(patient)
    with database_manager.unit_of_work() as unit_of_work:
        assert [listed.mrn for listed in unit_of_work.patients.list()] == [patient.mrn]
        unit_of_work.patients.delete(patient.id)
    with pytest.raises(RecordNotFoundError), database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.get(patient.id)


def test_optional_mrn_is_unique_and_supports_secondary_lookup(
    database_manager: DatabaseManager,
) -> None:
    without_mrn = make_representative_patient(None)
    with_mrn = make_representative_patient("123456")
    with database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(without_mrn)
        unit_of_work.patients.add(with_mrn)

    with database_manager.unit_of_work() as unit_of_work:
        assert unit_of_work.patients.get_by_mrn("123456").id == with_mrn.id

    duplicate = make_representative_patient("123456")
    with pytest.raises(DuplicateIdentityError), database_manager.unit_of_work() as unit_of_work:
        unit_of_work.patients.add(duplicate)
