"""Reminder scheduling, authoritative occurrence selection, and digest use cases."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from icu_patient_tracker.domain.enums import (
    AdmissionStatus,
    ClinicalPriority,
    ReminderScheduleType,
    ReminderStatus,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.domain.exceptions import DomainError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.events import EventPublisher, ReminderChanged
from icu_patient_tracker.services.exceptions import InvalidOperationError, ResourceNotFoundError

_TERMINAL_TASK_STATUSES = {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
_ACTIONABLE_REMINDER_STATUSES = {ReminderStatus.PENDING, ReminderStatus.SNOOZED}
_TIMED_REMINDER_CATEGORIES = {TaskCategory.CLINICAL, TaskCategory.POCUS}
_INACTIVE_PATIENT_STATUSES = {AdmissionStatus.ARCHIVED, AdmissionStatus.DECEASED}


@dataclass(frozen=True, slots=True)
class DigestEntry:
    """One in-application digest row; never passed to an OS notification."""

    patient_id: UUID
    patient_name: str
    day_number: int
    task_id: UUID
    title: str
    category: TaskCategory
    priority: ClinicalPriority


@dataclass(frozen=True, slots=True)
class HourlyDigest:
    """Deterministic reminder and task summary calculated at one instant."""

    generated_at: datetime
    due: tuple[DigestEntry, ...]
    pending_diagnostics: tuple[DigestEntry, ...]
    follow_up: tuple[DigestEntry, ...]
    urgent: tuple[DigestEntry, ...]
    open_todo_count: int
    open_diagnostic_count: int
    open_todos: tuple[DigestEntry, ...] = ()
    housekeeping: tuple[DigestEntry, ...] = ()

    @property
    def has_content(self) -> bool:
        """Return whether the digest contains any actionable work."""
        return bool(
            self.due
            or self.pending_diagnostics
            or self.follow_up
            or self.urgent
            or self.open_todo_count
            or self.open_diagnostic_count
            or self.housekeeping
        )


class ReminderService(ServiceBase):
    """Manage reminder specifications with an injectable wall clock."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        publisher: EventPublisher | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory, publisher)
        self._now = now or (lambda: datetime.now(UTC))

    def add_absolute(
        self, patient_id: UUID, task_id: UUID, *, trigger_at: datetime, message: str
    ) -> Reminder:
        return self._add(patient_id, task_id, ReminderScheduleType.ABSOLUTE, trigger_at, message)

    def add_interval(
        self,
        patient_id: UUID,
        task_id: UUID,
        *,
        interval_minutes: int,
        message: str,
        anchor_at: datetime | None = None,
    ) -> Reminder:
        anchor = anchor_at or self._now()
        trigger = anchor + timedelta(minutes=interval_minutes)
        return self._add(
            patient_id,
            task_id,
            ReminderScheduleType.INTERVAL,
            trigger,
            message,
            interval_minutes=interval_minutes,
            anchor_at=anchor,
        )

    def add_fixed_time(
        self, patient_id: UUID, task_id: UUID, *, fixed_time: time, message: str
    ) -> Reminder:
        now = self._now()
        trigger = datetime.combine(now.date(), fixed_time, tzinfo=now.tzinfo)
        if trigger <= now:
            trigger += timedelta(days=1)
        return self._add(
            patient_id,
            task_id,
            ReminderScheduleType.FIXED_TIME,
            trigger,
            message,
            fixed_time=fixed_time,
        )

    def update_absolute(
        self,
        patient_id: UUID,
        reminder_id: UUID,
        *,
        trigger_at: datetime,
        message: str | None = None,
    ) -> Reminder:
        def update(reminder: Reminder) -> None:
            reminder.reschedule(
                trigger_at=trigger_at,
                schedule_type=ReminderScheduleType.ABSOLUTE,
            )
            if message is not None:
                reminder.update_message(message)

        return self._mutate(patient_id, reminder_id, "updated", update)

    def due(self) -> tuple[Reminder, ...]:
        """Return due reminders only for each lineage's newest task occurrence."""
        now = self._now()
        with self._unit_of_work_factory() as unit_of_work:
            patients = unit_of_work.patients.list()
        due = [
            task.reminder
            for patient, _day, task in self._authoritative_occurrences(patients)
            if patient.admission_status not in _INACTIVE_PATIENT_STATUSES
            and task.category in _TIMED_REMINDER_CATEGORIES
            and task.status not in _TERMINAL_TASK_STATUSES
            and task.reminder is not None
            and task.reminder.status in _ACTIONABLE_REMINDER_STATUSES
            and task.reminder.trigger_at <= now
        ]
        return tuple(sorted(due, key=lambda reminder: (reminder.trigger_at, str(reminder.id))))

    def mark_shown(self, reminder_ids: Iterable[UUID]) -> tuple[Reminder, ...]:
        """Persist successful presentation and advance recurring schedules."""
        requested = tuple(dict.fromkeys(reminder_ids))
        if not requested:
            return ()
        requested_set = set(requested)
        shown_at = self._now()
        changed: dict[UUID, Reminder] = {}
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patients = unit_of_work.patients.list()
                authoritative = {
                    task.reminder.id: (patient, task.reminder)
                    for patient, _day, task in self._authoritative_occurrences(patients)
                    if task.reminder is not None
                }
                missing = requested_set.difference(authoritative)
                if missing:
                    missing_id = sorted(missing, key=str)[0]
                    raise ResourceNotFoundError(
                        f"Authoritative reminder {missing_id} was not found."
                    )
                affected: dict[UUID, Patient] = {}
                for reminder_id in requested:
                    patient, reminder = authoritative[reminder_id]
                    reminder.mark_shown(shown_at)
                    changed[reminder_id] = reminder
                    affected[patient.id] = patient
                for patient in affected.values():
                    unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        for reminder_id in requested:
            self._publisher.publish(ReminderChanged(str(reminder_id), "shown"))
        return tuple(changed[reminder_id] for reminder_id in requested)

    def hourly_digest(self) -> HourlyDigest:
        """Calculate an in-app hourly digest without relying on a Qt timer."""
        now = self._now()
        with self._unit_of_work_factory() as unit_of_work:
            patients = unit_of_work.patients.list()

        due: list[DigestEntry] = []
        diagnostics: list[DigestEntry] = []
        follow_up: list[DigestEntry] = []
        urgent: list[DigestEntry] = []
        open_todos: list[DigestEntry] = []
        housekeeping: list[DigestEntry] = []
        open_todo_count = 0
        open_diagnostic_count = 0
        for patient, day, task in self._authoritative_occurrences(patients):
            if patient.admission_status in _INACTIVE_PATIENT_STATUSES:
                continue
            if task.status in _TERMINAL_TASK_STATUSES:
                continue
            entry = self._digest_entry(patient, day, task)
            if task.category in _TIMED_REMINDER_CATEGORIES:
                open_todo_count += 1
                if patient.admission_status is AdmissionStatus.ADMITTED:
                    open_todos.append(entry)
            if (
                now.astimezone().hour == 21
                and task.category is TaskCategory.HOUSEKEEPING
                and patient.admission_status is AdmissionStatus.ADMITTED
            ):
                housekeeping.append(entry)
            if task.category is TaskCategory.DIAGNOSTIC:
                open_diagnostic_count += 1
                if task.bucket is TaskBucket.FOLLOW_UP:
                    follow_up.append(entry)
                elif patient.admission_status is AdmissionStatus.ADMITTED:
                    diagnostics.append(entry)
            if (
                patient.admission_status is AdmissionStatus.ADMITTED
                and task.category in _TIMED_REMINDER_CATEGORIES
                and task.priority in {ClinicalPriority.URGENT, ClinicalPriority.CRITICAL}
            ):
                urgent.append(entry)
            reminder = task.reminder
            if (
                reminder is not None
                and task.category in _TIMED_REMINDER_CATEGORIES
                and reminder.status in _ACTIONABLE_REMINDER_STATUSES
                and reminder.trigger_at <= now
            ):
                due.append(entry)

        def sort_key(entry: DigestEntry) -> tuple[str, int, str]:
            return entry.patient_name.casefold(), entry.day_number, entry.title.casefold()

        return HourlyDigest(
            generated_at=now,
            due=tuple(sorted(due, key=sort_key)),
            pending_diagnostics=tuple(sorted(diagnostics, key=sort_key)),
            follow_up=tuple(sorted(follow_up, key=sort_key)),
            urgent=tuple(sorted(urgent, key=sort_key)),
            open_todo_count=open_todo_count,
            open_diagnostic_count=open_diagnostic_count,
            open_todos=tuple(sorted(open_todos, key=sort_key)),
            housekeeping=tuple(sorted(housekeeping, key=sort_key)),
        )

    def snooze(self, patient_id: UUID, reminder_id: UUID, until: datetime) -> Reminder:
        return self._mutate(
            patient_id, reminder_id, "snoozed", lambda reminder: reminder.snooze(until)
        )

    def snooze_five_minutes(self, patient_id: UUID, reminder_id: UUID) -> Reminder:
        """Apply the standard five-minute reminder snooze policy."""
        return self.snooze(patient_id, reminder_id, self._now() + timedelta(minutes=5))

    def dismiss(self, patient_id: UUID, reminder_id: UUID) -> Reminder:
        return self._mutate(
            patient_id,
            reminder_id,
            "dismissed",
            lambda reminder: reminder.dismiss(self._now()),
        )

    def complete(self, patient_id: UUID, reminder_id: UUID) -> Reminder:
        return self._mutate(
            patient_id,
            reminder_id,
            "completed",
            lambda reminder: reminder.complete(self._now()),
        )

    def remove(self, patient_id: UUID, reminder_id: UUID) -> Reminder:
        with self._unit_of_work_factory() as unit_of_work:
            patient = self._patient(unit_of_work, patient_id)
            _, task, reminder = self._find(patient, reminder_id)
            task.remove_reminder()
            unit_of_work.patients.save(patient)
        self._publisher.publish(ReminderChanged(str(reminder_id), "removed"))
        return reminder

    def _add(
        self,
        patient_id: UUID,
        task_id: UUID,
        schedule_type: ReminderScheduleType,
        trigger_at: datetime,
        message: str,
        *,
        interval_minutes: int | None = None,
        fixed_time: time | None = None,
        anchor_at: datetime | None = None,
    ) -> Reminder:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day, task = self._task(patient, task_id)
                if task.status in _TERMINAL_TASK_STATUSES:
                    raise InvalidOperationError("A terminal task cannot receive a reminder.")
                if task.category not in _TIMED_REMINDER_CATEGORIES:
                    raise InvalidOperationError(
                        "Only To Do and POCUS tasks support timed reminders."
                    )
                reminder = Reminder(
                    task.id,
                    patient_id,
                    day.id,
                    trigger_at,
                    message,
                    schedule_type=schedule_type,
                    interval_minutes=interval_minutes,
                    fixed_time=fixed_time,
                    anchor_at=anchor_at,
                )
                task.attach_reminder(reminder)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ReminderChanged(str(reminder.id), "created"))
        return reminder

    def _mutate(
        self,
        patient_id: UUID,
        reminder_id: UUID,
        operation: str,
        action: Callable[[Reminder], None],
    ) -> Reminder:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                _, _, reminder = self._find(patient, reminder_id)
                action(reminder)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(ReminderChanged(str(reminder_id), operation))
        return reminder

    @staticmethod
    def _authoritative_occurrences(
        patients: Iterable[Patient],
    ) -> tuple[tuple[Patient, HospitalDay, Task], ...]:
        authoritative: list[tuple[Patient, HospitalDay, Task]] = []
        for patient in patients:
            latest: dict[UUID, tuple[Patient, HospitalDay, Task]] = {}
            for day in patient.hospital_days:
                for task in day.tasks:
                    latest[task.lineage_id] = (patient, day, task)
            authoritative.extend(latest.values())
        return tuple(authoritative)

    @staticmethod
    def _digest_entry(patient: Patient, day: HospitalDay, task: Task) -> DigestEntry:
        return DigestEntry(
            patient_id=patient.id,
            patient_name=patient.name,
            day_number=day.day_number,
            task_id=task.id,
            title=task.title,
            category=task.category,
            priority=task.priority,
        )

    @staticmethod
    def _find(patient: Patient, reminder_id: UUID) -> tuple[HospitalDay, Task, Reminder]:
        for day in patient.hospital_days:
            for task in day.tasks:
                if task.reminder is not None and task.reminder.id == reminder_id:
                    return day, task, task.reminder
        raise ResourceNotFoundError(f"Reminder {reminder_id} was not found.")
