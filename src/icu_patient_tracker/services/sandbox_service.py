"""Day-owned Sandbox Markdown and explicit checklist extraction use cases."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from icu_patient_tracker.domain.enums import ReminderScheduleType, TaskCategory
from icu_patient_tracker.domain.exceptions import DomainError
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.events import EventPublisher, HospitalDayChanged, TaskChanged
from icu_patient_tracker.services.exceptions import InvalidOperationError
from icu_patient_tracker.utils.task_input import TaskInput, parse_task_input

_UNCHECKED = re.compile(r"^\s*-\s*\[\s*\]\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SandboxTaskCandidate:
    """One validated, not-yet-persisted checklist extraction choice."""

    line_number: int
    source_text: str
    task: TaskInput


@dataclass(frozen=True, slots=True)
class SandboxIgnoredLine:
    """A checklist-looking row excluded from extraction with a safe reason."""

    line_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class SandboxExtractionPreview:
    """Immutable preview tied to the exact Sandbox text that was inspected."""

    sandbox_text: str
    candidates: tuple[SandboxTaskCandidate, ...]
    ignored: tuple[SandboxIgnoredLine, ...]


class SandboxService(ServiceBase):
    """Persist scratch Markdown and atomically create confirmed To Do/POCUS tasks."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        publisher: EventPublisher | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory, publisher)
        self._now = now or (lambda: datetime.now(UTC))

    def get(self, patient_id: UUID, day_id: UUID) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            return self._day(self._patient(unit_of_work, patient_id), day_id).sandbox_text

    def save(self, patient_id: UUID, day_id: UUID, sandbox_text: str) -> str:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                day.update_sandbox(sandbox_text)
                unit_of_work.patients.save(patient)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(HospitalDayChanged(str(day_id), "sandbox_saved"))
        return sandbox_text

    def preview(self, patient_id: UUID, day_id: UUID) -> SandboxExtractionPreview:
        with self._unit_of_work_factory() as unit_of_work:
            day = self._day(self._patient(unit_of_work, patient_id), day_id)
            sandbox_text = day.sandbox_text
            existing = {
                self._identity(task.title)
                for task in day.tasks
                if task.category in {TaskCategory.CLINICAL, TaskCategory.POCUS}
            }
        return self._preview_text(sandbox_text, existing)

    def extract(
        self,
        patient_id: UUID,
        day_id: UUID,
        *,
        expected_sandbox_text: str,
        line_numbers: Iterable[int],
    ) -> tuple[Task, ...]:
        """Create confirmed candidates only if the previewed Sandbox has not changed."""
        selected = set(line_numbers)
        if not selected:
            return ()
        created: list[Task] = []
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                if day.sandbox_text != expected_sandbox_text:
                    raise InvalidOperationError(
                        "Sandbox changed after preview. Review the extraction again."
                    )
                existing = {
                    self._identity(task.title)
                    for task in day.tasks
                    if task.category in {TaskCategory.CLINICAL, TaskCategory.POCUS}
                }
                preview = self._preview_text(day.sandbox_text, existing)
                available = {candidate.line_number: candidate for candidate in preview.candidates}
                if selected - set(available):
                    raise InvalidOperationError(
                        "One or more selected Sandbox tasks are no longer available."
                    )
                now = self._now()
                for line_number in sorted(selected):
                    values = available[line_number].task
                    task = Task(
                        patient_id=patient_id,
                        hospital_day_id=day_id,
                        title=values.title,
                        priority=values.priority,
                        category=values.category,
                        bucket=values.bucket,
                        carry_forward=(values.carry_forward if values.carry_explicit else False),
                        source="sandbox",
                    )
                    if values.reminder is not None:
                        task.attach_reminder(self._reminder(task, values, now))
                    day.add_task(task)
                    created.append(task)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        for task in created:
            self._publisher.publish(TaskChanged(str(task.id), "created_from_sandbox"))
        return tuple(created)

    @classmethod
    def _preview_text(cls, sandbox_text: str, existing: set[str]) -> SandboxExtractionPreview:
        candidates: list[SandboxTaskCandidate] = []
        ignored: list[SandboxIgnoredLine] = []
        seen = set(existing)
        for line_number, line in enumerate(sandbox_text.splitlines(), start=1):
            match = _UNCHECKED.match(line)
            if match is None:
                continue
            raw_task = match.group(1).strip()
            if not raw_task or "#INPUT#" in raw_task:
                ignored.append(SandboxIgnoredLine(line_number, "placeholder or empty task"))
                continue
            try:
                values = parse_task_input(
                    raw_task,
                    TaskCategory.CLINICAL,
                    discard_invalid_reminder=True,
                )
            except ValueError:
                ignored.append(SandboxIgnoredLine(line_number, "invalid task metadata"))
                continue
            identity = cls._identity(values.title)
            if identity in seen:
                ignored.append(SandboxIgnoredLine(line_number, "duplicate task"))
                continue
            seen.add(identity)
            candidates.append(SandboxTaskCandidate(line_number, line, values))
        return SandboxExtractionPreview(sandbox_text, tuple(candidates), tuple(ignored))

    @staticmethod
    def _identity(title: str) -> str:
        return " ".join(title.casefold().split())

    @staticmethod
    def _reminder(task: Task, values: TaskInput, now: datetime) -> Reminder:
        specification = values.reminder
        if specification is None:
            raise InvalidOperationError("Reminder specification is missing.")
        if specification.interval_minutes is not None:
            trigger = now + timedelta(minutes=specification.interval_minutes)
            return Reminder(
                task.id,
                task.patient_id,
                task.hospital_day_id,
                trigger,
                task.title,
                schedule_type=ReminderScheduleType.INTERVAL,
                interval_minutes=specification.interval_minutes,
                anchor_at=now,
            )
        fixed_time = specification.fixed_time
        if fixed_time is None:
            raise InvalidOperationError("Reminder fixed time is missing.")
        trigger = datetime.combine(now.date(), fixed_time, tzinfo=now.tzinfo)
        if trigger <= now:
            trigger += timedelta(days=1)
        return Reminder(
            task.id,
            task.patient_id,
            task.hospital_day_id,
            trigger,
            task.title,
            schedule_type=ReminderScheduleType.FIXED_TIME,
            fixed_time=fixed_time,
        )
