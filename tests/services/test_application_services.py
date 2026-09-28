"""End-to-end use-case tests through real unit-of-work boundaries."""

from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from icu_patient_tracker.app.config import ConfigManager
from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    ClinicalPriority,
    CodeStatus,
    DeviceStatus,
    DeviceType,
    ProblemStatus,
    ReminderScheduleType,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.persistence.autosave import AutosaveController
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.autosave_coordinator import AutosaveCoordinator
from icu_patient_tracker.services.events import RecordingEventPublisher
from icu_patient_tracker.services.exceptions import (
    DuplicateHospitalDayError,
    InvalidOperationError,
)
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.instrumentation_service import InstrumentationService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.problem_service import ProblemService
from icu_patient_tracker.services.reminder_service import ReminderService
from icu_patient_tracker.services.search_service import SearchFilters, SearchService, SearchSort
from icu_patient_tracker.services.settings_service import SettingsService
from icu_patient_tracker.services.soap_service import SOAPService
from icu_patient_tracker.services.task_service import TaskService

START = datetime(2026, 7, 20, 8, tzinfo=UTC)


def services(
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


def test_patient_lifecycle_and_events_are_persisted(database_manager: DatabaseManager) -> None:
    patients, _, _, publisher = services(database_manager)
    created = patients.create(mrn="A1", name="Bella", species="Canine", acuity=Acuity.CRITICAL)
    patients.update_summary(created.id, one_line_summary="Post-operative monitoring")
    patients.change_status(created.id, AdmissionStatus.DISCHARGED)

    loaded = patients.get(created.id)
    assert loaded.mrn == created.mrn
    assert loaded.one_line_summary == "Post-operative monitoring"
    assert loaded.admission_status is AdmissionStatus.DISCHARGED
    assert [event.operation for event in publisher.events] == [
        "created",
        "updated",
        "status:discharged",
    ]


def test_new_patient_receives_todays_first_hospital_day(
    database_manager: DatabaseManager,
) -> None:
    patients, _, _, _ = services(database_manager)

    patient = patients.create(name="Bella", species="Canine", acuity=Acuity.CRITICAL)

    assert len(patient.hospital_days) == 1
    assert patient.hospital_days[0].calendar_date == START.date()
    assert patient.hospital_days[0].day_number == 1
    assert patient.hospital_days[0].acuity is Acuity.CRITICAL


def test_purge_requires_explicit_archive(database_manager: DatabaseManager) -> None:
    patients, _, _, _ = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    with pytest.raises(InvalidOperationError):
        patients.purge(patient.id)
    patients.archive(patient.id)
    patients.purge(patient.id)
    assert patients.list() == ()


def test_failed_patient_create_does_not_publish_event(database_manager: DatabaseManager) -> None:
    patients, _, _, publisher = services(database_manager)
    patients.create(mrn="A1", name="Bella", species="Canine")
    publisher.events.clear()
    with pytest.raises(InvalidOperationError):
        patients.create(mrn="A1", name="Duplicate", species="Feline")
    assert publisher.events == []


def test_patient_details_are_correctable_without_changing_uuid(
    database_manager: DatabaseManager,
) -> None:
    patients, _, _, _ = services(database_manager)
    patient = patients.create(name="Bella", species="Unknown")
    other = patients.create(mrn="999999", name="Bella", species="Canine")

    corrected = patients.update_identity_details(patient.id, mrn="123456", species="Feline")

    assert corrected.id == patient.id
    assert corrected.mrn == "123456"
    assert corrected.species == "Feline"
    assert other.name == corrected.name
    with pytest.raises(InvalidOperationError, match="already assigned"):
        patients.update_identity_details(patient.id, mrn="999999", species="Must not persist")
    unchanged = patients.get(patient.id)
    assert unchanged.mrn == "123456"
    assert unchanged.species == "Feline"


def test_patient_summary_and_daily_charting_round_trip(
    database_manager: DatabaseManager,
) -> None:
    patients, days, _, _ = services(database_manager)
    patient = patients.create(name="Bella", species="Unknown", blood_type="DEA 1 positive")
    day = patient.hospital_days[0]

    patients.update_profile(
        patient.id,
        name="Bella Rose",
        species="Canine",
        mrn="123456",
        one_line_summary="Septic peritonitis after surgery",
        code_status=CodeStatus.FULL_CODE,
        blood_type=None,
        acuity=Acuity.CRITICAL,
    )
    days.update(
        patient.id,
        day.id,
        label="postop",
        acuity=Acuity.WATCHER,
        clinical_summary="Improving overnight",
        treatment_changes="Reduced fluids",
        physical_examination="Comfortable",
        assessment="Responding to treatment",
    )
    days.update(patient.id, day.id, label=None)

    loaded_patient = patients.get(patient.id)
    loaded_day = days.get(patient.id, day.id)
    assert loaded_patient.id == patient.id
    assert loaded_patient.name == "Bella Rose"
    assert loaded_patient.mrn == "123456"
    assert loaded_patient.blood_type is None
    assert loaded_patient.code_status is CodeStatus.FULL_CODE
    assert loaded_patient.one_line_summary == "Septic peritonitis after surgery"
    assert loaded_day.label is None
    assert loaded_day.acuity is Acuity.WATCHER
    assert loaded_day.clinical_summary == "Improving overnight"
    assert loaded_day.treatment_changes == "Reduced fluids"
    assert loaded_day.physical_examination == "Comfortable"
    assert loaded_day.assessment == "Responding to treatment"


def test_active_order_is_persisted_normalized_and_appended_on_readmission(
    database_manager: DatabaseManager,
) -> None:
    patients, _, _, _ = services(database_manager)
    first = patients.create(name="First", species="Canine")
    second = patients.create(name="Second", species="Canine")
    third = patients.create(name="Third", species="Canine")

    patients.reorder_active((third.id, first.id, second.id))
    patients.change_status(third.id, AdmissionStatus.DISCHARGED)
    assert [patient.id for patient in patients.list(status=AdmissionStatus.ADMITTED)] == [
        first.id,
        second.id,
    ]
    assert [patient.active_order for patient in patients.list(status=AdmissionStatus.ADMITTED)] == [
        0,
        1,
    ]

    patients.reactivate(third.id)
    database_path = database_manager.database_path
    database_manager.dispose()
    restarted_manager = DatabaseManager(database_path)
    restarted_manager.initialize()
    try:
        reloaded = PatientService(restarted_manager.unit_of_work)
        active = reloaded.list(status=AdmissionStatus.ADMITTED)
        assert [patient.id for patient in active] == [first.id, second.id, third.id]
        assert [patient.active_order for patient in active] == [0, 1, 2]
    finally:
        restarted_manager.dispose()


def test_new_day_carries_only_open_opted_in_tasks(database_manager: DatabaseManager) -> None:
    patients, days, tasks, _ = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    first = patient.hospital_days[0]
    carried = tasks.create(patient.id, first.id, title="Recheck PCV")
    tasks.create(patient.id, first.id, title="Do not carry", carry_forward=False)
    completed = tasks.create(patient.id, first.id, title="Call owner")
    tasks.complete(patient.id, completed.id)

    second = days.create(patient.id, start_at=START + timedelta(days=1))
    assert len(second.tasks) == 1
    assert second.tasks[0].lineage_id == carried.lineage_id
    assert second.tasks[0].source_task_id == carried.id
    assert second.tasks[0].occurrence_number == 2


def test_hospital_days_are_chronological_and_renumbered_after_backdated_insert(
    database_manager: DatabaseManager,
) -> None:
    patients, days, tasks, _ = services(database_manager)
    patient = patients.create(name="Bella", species="Canine")
    tasks.create(patient.id, patient.hospital_days[0].id, title="Recheck PCV")
    last = days.create(patient.id, start_at=START + timedelta(days=2), label="postop day two")
    middle = days.create(patient.id, start_at=START + timedelta(days=1), label="postop day one")

    ordered = days.list(patient.id)
    assert [day.id for day in ordered] == [patient.hospital_days[0].id, middle.id, last.id]
    assert [day.day_number for day in ordered] == [1, 2, 3]
    assert [day.label for day in ordered] == [None, "postop day one", "postop day two"]
    assert middle.tasks == ()
    assert len(last.tasks) == 1

    with pytest.raises(DuplicateHospitalDayError):
        days.create(patient.id, start_at=START + timedelta(days=1), label="duplicate")

    database_path = database_manager.database_path
    database_manager.dispose()
    restarted_manager = DatabaseManager(database_path)
    restarted_manager.initialize()
    try:
        reloaded = HospitalDayService(restarted_manager.unit_of_work).list(patient.id)
        assert [day.day_number for day in reloaded] == [1, 2, 3]
        assert [day.label for day in reloaded] == [None, "postop day one", "postop day two"]
    finally:
        restarted_manager.dispose()


def test_new_day_carries_only_current_supported_objects(
    database_manager: DatabaseManager,
) -> None:
    patients, days, tasks, publisher = services(database_manager)
    patient = patients.create(name="Bella", species="Canine")
    first = patient.hospital_days[0]
    problems = ProblemService(database_manager.unit_of_work, publisher)
    instrumentation = InstrumentationService(database_manager.unit_of_work, publisher)
    problem = problems.add(patient.id, first.id, title="Anemia")
    task = tasks.create(patient.id, first.id, title="Recheck PCV")
    device = instrumentation.add(
        patient.id,
        first.id,
        device_type=DeviceType.PERIPHERAL_IV_CATHETER,
        anatomical_location="Left cephalic",
        placed_at=START,
    )

    second = days.create(patient.id, start_at=START + timedelta(days=1))

    assert [carried.lineage_id for carried in second.tasks] == [task.lineage_id]
    assert [carried.device_type for carried in second.instrumentation.devices] == [
        device.device_type
    ]
    assert second.instrumentation.devices[0].id != device.id
    assert len(second.problem_list.problems) == 1
    assert second.problem_list.problems[0].lineage_id == problem.lineage_id
    assert second.problem_list.problems[0].source_problem_id == problem.id

    third = days.create(
        patient.id,
        start_at=START + timedelta(days=2),
        carry_tasks=False,
        carry_devices=False,
        carry_problems=False,
    )
    assert third.tasks == ()
    assert third.instrumentation.devices == ()
    assert third.problem_list.problems == ()


def test_task_lineage_delete_is_atomic(database_manager: DatabaseManager) -> None:
    patients, days, tasks, _ = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    first = patient.hospital_days[0]
    original = tasks.create(patient.id, first.id, title="Recheck PCV")
    days.create(patient.id, start_at=START + timedelta(days=1))
    assert tasks.delete_lineage(patient.id, original.lineage_id) == 2
    assert all(not day.tasks for day in days.list(patient.id))


def test_task_forward_edit_preserves_prior_history(database_manager: DatabaseManager) -> None:
    patients, days, tasks, _ = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    first = patient.hospital_days[0]
    original = tasks.create(patient.id, first.id, title="Old wording")
    second = days.create(patient.id, start_at=START + timedelta(days=1))
    days.create(patient.id, start_at=START + timedelta(days=2))

    changed = tasks.update_from(patient.id, second.tasks[0].id, title="New wording")
    loaded_days = days.list(patient.id)
    assert len(changed) == 2
    assert loaded_days[0].tasks[0].id == original.id
    assert loaded_days[0].tasks[0].title == "Old wording"
    assert [day.tasks[0].title for day in loaded_days[1:]] == ["New wording", "New wording"]


def test_task_category_changes_and_diagnostic_omissions_are_forward_only(
    database_manager: DatabaseManager,
) -> None:
    patients, days, tasks, _ = services(database_manager)
    patient = patients.create(name="Bella", species="Canine")
    first = patient.hospital_days[0]
    original = tasks.create(
        patient.id,
        first.id,
        title="Recheck culture",
        category=TaskCategory.DIAGNOSTIC,
        bucket=TaskBucket.DIAGNOSTIC,
    )
    second = days.create(patient.id, start_at=START + timedelta(days=1))
    third = days.create(patient.id, start_at=START + timedelta(days=2))

    changed = tasks.update_from(
        patient.id,
        second.tasks[0].id,
        title="POCUS recheck",
        category=TaskCategory.POCUS,
    )
    assert len(changed) == 2
    loaded = days.list(patient.id)
    assert loaded[0].tasks[0].id == original.id
    assert loaded[0].tasks[0].category is TaskCategory.DIAGNOSTIC
    assert [day.tasks[0].category for day in loaded[1:]] == [
        TaskCategory.POCUS,
        TaskCategory.POCUS,
    ]

    with pytest.raises(InvalidOperationError, match="pending diagnostics"):
        tasks.omit_diagnostic_from(patient.id, third.tasks[0].id)
    tasks.update_from(
        patient.id,
        second.tasks[0].id,
        title="Recheck culture",
        category=TaskCategory.DIAGNOSTIC,
    )
    omitted = tasks.omit_diagnostic_from(patient.id, second.tasks[0].id)
    assert len(omitted) == 2
    loaded = days.list(patient.id)
    assert loaded[0].tasks[0].status is TaskStatus.PENDING
    assert [day.tasks[0].status for day in loaded[1:]] == [
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
    ]

    database_path = database_manager.database_path
    database_manager.dispose()
    restarted_manager = DatabaseManager(database_path)
    restarted_manager.initialize()
    try:
        restarted_days = HospitalDayService(restarted_manager.unit_of_work).list(patient.id)
        assert [day.tasks[0].lineage_id for day in restarted_days] == [
            original.lineage_id,
            original.lineage_id,
            original.lineage_id,
        ]
        assert [day.tasks[0].occurrence_number for day in restarted_days] == [1, 2, 3]
        assert [day.tasks[0].status for day in restarted_days] == [
            TaskStatus.PENDING,
            TaskStatus.COMPLETED,
            TaskStatus.COMPLETED,
        ]
    finally:
        restarted_manager.dispose()


def test_reminder_specs_and_due_order(database_manager: DatabaseManager) -> None:
    patients, _, tasks, publisher = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    day = patient.hospital_days[0]
    first = tasks.create(patient.id, day.id, title="First")
    second = tasks.create(patient.id, day.id, title="Second")
    now = START + timedelta(hours=4)
    reminders = ReminderService(database_manager.unit_of_work, publisher, now=lambda: now)
    interval = reminders.add_interval(
        patient.id, first.id, interval_minutes=30, message="First due", anchor_at=START
    )
    fixed = reminders.add_fixed_time(
        patient.id, second.id, fixed_time=time(9), message="Second due"
    )

    assert interval.schedule_type is ReminderScheduleType.INTERVAL
    assert fixed.schedule_type is ReminderScheduleType.FIXED_TIME
    assert reminders.due() == (interval,)


def test_soap_refresh_preserves_unselected_sections(database_manager: DatabaseManager) -> None:
    patients, days, tasks, publisher = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    day = patient.hospital_days[0]
    days.update(patient.id, day.id, assessment="Stable", clinical_summary="Eating")
    tasks.create(patient.id, day.id, title="Remove catheter")
    problems = ProblemService(database_manager.unit_of_work, publisher)
    anemia = problems.add(patient.id, day.id, title="Anemia", assessment="Regenerative")
    appetite = problems.add(patient.id, day.id, title="Anorexia", assessment="Improving")
    resolved = problems.add(patient.id, day.id, title="Hypotension", assessment="Resolved")
    problems.change_status(patient.id, day.id, resolved.id, ProblemStatus.RESOLVED)
    problems.reorder(patient.id, day.id, [appetite.id, resolved.id, anemia.id])
    soap = SOAPService(database_manager.unit_of_work, publisher)
    document = soap.create(patient.id, day.id, author="Dr. Rivera")
    soap.update_sections(patient.id, day.id, document.id, subjective="Owner visited")
    refreshed = soap.refresh_from_day(patient.id, day.id, document.id)
    assert refreshed.subjective == "Owner visited"
    assert refreshed.assessment.splitlines() == [
        "- Anorexia: Improving",
        "- Anemia: Regenerative",
    ]
    assert refreshed.problem_ids == (appetite.id, anemia.id)
    assert "Hypotension" not in refreshed.assessment
    assert "Remove catheter" in refreshed.plan


def test_problem_service_mutates_ordered_problem_list(database_manager: DatabaseManager) -> None:
    patients, _, _, publisher = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    day = patient.hospital_days[0]
    problems = ProblemService(database_manager.unit_of_work, publisher)
    first = problems.add(patient.id, day.id, title="Anemia")
    second = problems.add(patient.id, day.id, title="Hypotension")

    problems.update(patient.id, day.id, first.id, title="Regenerative anemia")
    problems.change_status(patient.id, day.id, second.id, ProblemStatus.RESOLVED)
    problems.reorder(patient.id, day.id, [second.id, first.id])

    loaded = problems.list(patient.id, day.id)
    assert [problem.id for problem in loaded] == [second.id, first.id]
    assert loaded[0].status is ProblemStatus.RESOLVED
    assert loaded[1].title == "Regenerative anemia"


def test_problem_carry_and_forward_mutations_preserve_daily_history(
    database_manager: DatabaseManager,
) -> None:
    patients, days, _, publisher = services(database_manager)
    patient = patients.create(name="Bella", species="Canine")
    first_day = patient.hospital_days[0]
    problems = ProblemService(database_manager.unit_of_work, publisher)
    anemia = problems.add(
        patient.id,
        first_day.id,
        title="Anemia",
        assessment="Regenerative",
        priority=ClinicalPriority.URGENT,
    )
    hypotension = problems.add(patient.id, first_day.id, title="Hypotension")
    problems.reorder(patient.id, first_day.id, [hypotension.id, anemia.id])
    problems.change_status(patient.id, first_day.id, hypotension.id, ProblemStatus.RESOLVED)

    second_day = days.create(patient.id, start_at=START + timedelta(days=1))
    third_day = days.create(patient.id, start_at=START + timedelta(days=2))
    assert [problem.title for problem in second_day.problem_list.problems] == ["Anemia"]
    assert [problem.title for problem in third_day.problem_list.problems] == ["Anemia"]
    second_anemia = second_day.problem_list.problems[0]
    assert second_anemia.lineage_id == anemia.lineage_id
    assert second_anemia.source_problem_id == anemia.id
    assert third_day.problem_list.problems[0].occurrence_number == 3

    changed = problems.update_from(
        patient.id,
        second_day.id,
        second_anemia.id,
        title="Regenerative anemia",
        assessment="Improving",
    )
    assert len(changed) == 2
    resolved = problems.change_status_from(
        patient.id,
        second_day.id,
        second_anemia.id,
        ProblemStatus.RESOLVED,
    )
    assert len(resolved) == 2
    loaded = days.list(patient.id)
    assert loaded[0].problem_list.problems[1].title == "Anemia"
    assert loaded[0].problem_list.problems[1].status is ProblemStatus.ACTIVE
    assert [day.problem_list.problems[0].title for day in loaded[1:]] == [
        "Regenerative anemia",
        "Regenerative anemia",
    ]
    assert [day.problem_list.problems[0].status for day in loaded[1:]] == [
        ProblemStatus.RESOLVED,
        ProblemStatus.RESOLVED,
    ]

    fourth_day = days.create(patient.id, start_at=START + timedelta(days=3))
    assert fourth_day.problem_list.problems == ()

    database_path = database_manager.database_path
    database_manager.dispose()
    restarted_manager = DatabaseManager(database_path)
    restarted_manager.initialize()
    try:
        restarted = HospitalDayService(restarted_manager.unit_of_work).list(patient.id)
        occurrences = [
            problem
            for day in restarted
            for problem in day.problem_list.problems
            if problem.lineage_id == anemia.lineage_id
        ]
        assert [problem.occurrence_number for problem in occurrences] == [1, 2, 3]
        assert [problem.status for problem in occurrences] == [
            ProblemStatus.ACTIVE,
            ProblemStatus.RESOLVED,
            ProblemStatus.RESOLVED,
        ]
    finally:
        restarted_manager.dispose()


def test_problem_remove_from_retains_earlier_occurrence(database_manager: DatabaseManager) -> None:
    patients, days, _, publisher = services(database_manager)
    patient = patients.create(name="Bella", species="Canine")
    first_day = patient.hospital_days[0]
    problems = ProblemService(database_manager.unit_of_work, publisher)
    original = problems.add(patient.id, first_day.id, title="Anemia")
    second_day = days.create(patient.id, start_at=START + timedelta(days=1))
    days.create(patient.id, start_at=START + timedelta(days=2))

    removed = problems.remove_from(
        patient.id, second_day.id, second_day.problem_list.problems[0].id
    )

    assert len(removed) == 2
    loaded = days.list(patient.id)
    assert loaded[0].problem_list.problems[0].id == original.id
    assert loaded[1].problem_list.problems == ()
    assert loaded[2].problem_list.problems == ()


def test_problem_text_replacement_updates_and_carries_forward(
    database_manager: DatabaseManager,
) -> None:
    patients, days, _, publisher = services(database_manager)
    patient = patients.create(name="Bella", species="Canine")
    first_day = patient.hospital_days[0]
    problems = ProblemService(database_manager.unit_of_work, publisher)
    anemia = problems.add(patient.id, first_day.id, title="Anemia")
    second_day = days.create(patient.id, start_at=START + timedelta(days=1))
    third_day = days.create(patient.id, start_at=START + timedelta(days=2))

    selected = problems.replace_titles_from(
        patient.id,
        second_day.id,
        ("Regenerative anemia", "Hypoglycemia"),
    )

    assert len(selected) == 2
    loaded = days.list(patient.id)
    assert loaded[0].problem_list.problems[0].id == anemia.id
    assert loaded[0].problem_list.problems[0].title == "Anemia"
    assert [problem.title for problem in loaded[1].problem_list.problems] == [
        "Regenerative anemia",
        "Hypoglycemia",
    ]
    assert [problem.title for problem in loaded[2].problem_list.problems] == [
        "Regenerative anemia",
        "Hypoglycemia",
    ]
    added_second = loaded[1].problem_list.problems[1]
    added_third = loaded[2].problem_list.problems[1]
    assert added_third.lineage_id == added_second.lineage_id
    assert added_third.source_problem_id == added_second.id
    assert added_third.occurrence_number == 2
    assert second_day.id == loaded[1].id
    assert third_day.id == loaded[2].id


def test_instrumentation_service_mutates_device_lifecycle(
    database_manager: DatabaseManager,
) -> None:
    patients, _, _, publisher = services(database_manager)
    patient = patients.create(mrn="A1", name="Bella", species="Canine")
    day = patient.hospital_days[0]
    instrumentation = InstrumentationService(database_manager.unit_of_work, publisher)
    device = instrumentation.add(
        patient.id,
        day.id,
        device_type=DeviceType.CENTRAL_VENOUS_CATHETER,
        anatomical_location="Right jugular",
        placed_at=START,
    )

    instrumentation.update(patient.id, day.id, device.id, size="7 Fr")
    instrumentation.discontinue(patient.id, day.id, device.id, START + timedelta(hours=3))
    loaded = instrumentation.list(patient.id, day.id)[0]
    assert loaded.size == "7 Fr"
    assert loaded.status is DeviceStatus.REMOVED


def test_search_combines_text_filters_and_stable_sort(database_manager: DatabaseManager) -> None:
    patients, _, tasks, _ = services(database_manager)
    zoe = patients.create(mrn="B2", name="Zoe", species="Canine", acuity=Acuity.CRITICAL)
    patients.create(mrn="A1", name="Alfie", species="Feline", acuity=Acuity.STABLE)
    day = zoe.hospital_days[0]
    tasks.create(zoe.id, day.id, title="Review radiographs", category=TaskCategory.DIAGNOSTIC)
    search = SearchService(database_manager.unit_of_work)

    results = search.search(
        "radiograph",
        filters=SearchFilters(pending_diagnostic=True),
        sort=SearchSort.ACUITY,
    )
    assert [result.mrn for result in results] == ["B2"]


def test_settings_update_and_reset(tmp_path: Path) -> None:
    publisher = RecordingEventPublisher()
    settings = SettingsService(ConfigManager(tmp_path / "config.json"), publisher)
    updated = settings.update(theme="light", backup_retention_count=4)
    assert updated.theme == "light"
    assert settings.get().backup_retention_count == 4
    assert settings.reset().theme == "dark"
    assert [event.operation for event in publisher.events] == ["updated", "reset"]


def test_autosave_coordinator_publishes_lifecycle_events() -> None:
    saved: list[bool] = []
    publisher = RecordingEventPublisher()
    controller = AutosaveController(lambda: saved.append(True), debounce_seconds=0)
    coordinator = AutosaveCoordinator(controller, publisher)

    coordinator.mark_dirty()
    assert coordinator.poll() is True
    assert saved == [True]
    assert [event.operation for event in publisher.events] == ["scheduled", "completed"]
