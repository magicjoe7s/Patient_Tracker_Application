"""Slice 7 reminder authority, recurrence, snooze, digest, and restart tests."""

from datetime import UTC, datetime, timedelta

from icu_patient_tracker.domain.enums import ClinicalPriority, TaskBucket, TaskCategory
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.events import RecordingEventPublisher
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.reminder_service import ReminderService
from icu_patient_tracker.services.task_service import TaskService

START = datetime(2026, 7, 20, 8, tzinfo=UTC)


def _services(
    manager: DatabaseManager, clock: list[datetime]
) -> tuple[PatientService, HospitalDayService, TaskService, ReminderService]:
    publisher = RecordingEventPublisher()
    factory = manager.unit_of_work
    return (
        PatientService(factory, publisher, now=lambda: START),
        HospitalDayService(factory, publisher),
        TaskService(factory, publisher),
        ReminderService(factory, publisher, now=lambda: clock[0]),
    )


def test_newest_occurrence_is_authoritative_and_completion_suppresses_history(
    database_manager: DatabaseManager,
) -> None:
    clock = [START + timedelta(hours=2)]
    patients, days, tasks, reminders = _services(database_manager, clock)
    patient = patients.create(name="Bella", species="Canine")
    first_day = patient.hospital_days[0]
    first = tasks.create(patient.id, first_day.id, title="Recheck perfusion")
    original = reminders.add_interval(
        patient.id,
        first.id,
        interval_minutes=30,
        message="Recheck perfusion",
        anchor_at=START,
    )

    second_day = days.create(patient.id, start_at=START + timedelta(days=1))
    latest = second_day.tasks[0]

    assert latest.reminder is not None
    assert latest.reminder.id != original.id
    assert reminders.due() == (latest.reminder,)
    tasks.complete(patient.id, latest.id, at=clock[0])
    assert reminders.due() == ()


def test_snooze_show_and_recurring_state_survive_service_restart(
    database_manager: DatabaseManager,
) -> None:
    clock = [START + timedelta(hours=1)]
    patients, _days, tasks, reminders = _services(database_manager, clock)
    patient = patients.create(name="Milo", species="Feline")
    day = patient.hospital_days[0]
    task = tasks.create(patient.id, day.id, title="Repeat POCUS", category=TaskCategory.POCUS)
    reminder = reminders.add_interval(
        patient.id,
        task.id,
        interval_minutes=30,
        message="Repeat POCUS",
        anchor_at=START,
    )

    snoozed = reminders.snooze_five_minutes(patient.id, reminder.id)
    assert snoozed.trigger_at == clock[0] + timedelta(minutes=5)
    assert reminders.due() == ()
    clock[0] += timedelta(minutes=5)
    assert reminders.due()[0].id == reminder.id

    shown = reminders.mark_shown((reminder.id,))[0]
    assert shown.last_shown_at == clock[0]
    assert shown.trigger_at == clock[0] + timedelta(minutes=30)
    restarted = ReminderService(database_manager.unit_of_work, now=lambda: clock[0])
    assert restarted.due() == ()
    clock[0] += timedelta(minutes=30)
    reloaded_due = restarted.due()
    assert reloaded_due[0].id == reminder.id
    assert reloaded_due[0].last_shown_at == START + timedelta(hours=1, minutes=5)


def test_hourly_digest_excludes_future_shown_snoozed_and_completed_items(
    database_manager: DatabaseManager,
) -> None:
    clock = [START + timedelta(hours=2)]
    patients, _days, tasks, reminders = _services(database_manager, clock)
    patient = patients.create(name="Nori", species="Canine")
    day = patient.hospital_days[0]
    due_task = tasks.create(
        patient.id,
        day.id,
        title="Due",
        priority=ClinicalPriority.URGENT,
    )
    future_task = tasks.create(patient.id, day.id, title="Future")
    snoozed_task = tasks.create(patient.id, day.id, title="Snoozed")
    completed_task = tasks.create(patient.id, day.id, title="Completed")
    tasks.create(
        patient.id,
        day.id,
        title="Culture",
        category=TaskCategory.DIAGNOSTIC,
        bucket=TaskBucket.DIAGNOSTIC,
    )
    reminders.add_absolute(
        patient.id, due_task.id, trigger_at=clock[0] - timedelta(minutes=1), message="Due"
    )
    reminders.add_absolute(
        patient.id, future_task.id, trigger_at=clock[0] + timedelta(hours=1), message="Future"
    )
    snoozed = reminders.add_absolute(
        patient.id,
        snoozed_task.id,
        trigger_at=clock[0] - timedelta(minutes=2),
        message="Snoozed",
    )
    reminders.snooze_five_minutes(patient.id, snoozed.id)
    tasks.complete(patient.id, completed_task.id, at=clock[0])

    digest = reminders.hourly_digest()

    assert [entry.title for entry in digest.due] == ["Due"]
    assert [entry.title for entry in digest.urgent] == ["Due"]
    assert [entry.title for entry in digest.pending_diagnostics] == ["Culture"]
    assert digest.open_todo_count == 3
    assert digest.open_diagnostic_count == 1


def test_hourly_digest_lists_open_work_and_limits_housekeeping_to_local_9_pm(
    database_manager: DatabaseManager,
) -> None:
    local_zone = datetime.now().astimezone().tzinfo
    assert local_zone is not None
    clock = [datetime(2026, 7, 20, 20, tzinfo=local_zone)]
    patients, _days, tasks, reminders = _services(database_manager, clock)
    patient = patients.create(name="Nori", species="Canine")
    day = patient.hospital_days[0]
    tasks.create(patient.id, day.id, title="Recheck perfusion")
    tasks.create(
        patient.id,
        day.id,
        title="Round off patient",
        category=TaskCategory.HOUSEKEEPING,
    )

    digest = reminders.hourly_digest()
    assert [entry.title for entry in digest.open_todos] == ["Recheck perfusion"]
    assert digest.housekeeping == ()

    clock[0] = clock[0].replace(hour=21)
    digest = reminders.hourly_digest()
    assert [entry.title for entry in digest.housekeeping] == ["Round off patient"]
