"""Task occurrence lifecycle and explicit cross-day carry-forward policy."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from icu_patient_tracker.domain.diagnostic_result import DiagnosticResult
from icu_patient_tracker.domain.enums import (
    AdmissionStatus,
    ClinicalPriority,
    ReminderStatus,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.domain.exceptions import DomainError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase
from icu_patient_tracker.services.events import TaskChanged
from icu_patient_tracker.services.exceptions import InvalidOperationError
from icu_patient_tracker.utils.diagnostic_text import DiagnosticTextEntry
from icu_patient_tracker.utils.task_input import parse_task_input


@dataclass(frozen=True, slots=True)
class TaskCarryForwardPolicy:
    """Copy only unfinished, opted-in occurrences and preserve lineage."""

    def create_occurrences(self, source: HospitalDay, target: HospitalDay) -> tuple[Task, ...]:
        existing_lineages = {task.lineage_id for task in target.tasks}
        created: list[Task] = []
        for task in source.tasks:
            if (
                task.carry_forward
                and task.category is not TaskCategory.HOUSEKEEPING
                and task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
                and task.lineage_id not in existing_lineages
            ):
                occurrence = Task(
                    patient_id=target.patient_id,
                    hospital_day_id=target.id,
                    title=task.title,
                    description=task.description,
                    priority=task.priority,
                    assigned_to=task.assigned_to,
                    category=task.category,
                    bucket=task.bucket,
                    source=task.source,
                    lineage_id=task.lineage_id,
                    source_task_id=task.id,
                    occurrence_number=task.occurrence_number + 1,
                    carry_forward=task.carry_forward,
                )
                if task.reminder is not None and task.reminder.status in {
                    ReminderStatus.PENDING,
                    ReminderStatus.SNOOZED,
                }:
                    source_reminder = task.reminder
                    occurrence.attach_reminder(
                        Reminder(
                            task_id=occurrence.id,
                            patient_id=target.patient_id,
                            hospital_day_id=target.id,
                            trigger_at=source_reminder.trigger_at,
                            message=occurrence.title,
                            schedule_type=source_reminder.schedule_type,
                            interval_minutes=source_reminder.interval_minutes,
                            fixed_time=source_reminder.fixed_time,
                            anchor_at=source_reminder.anchor_at,
                            status=source_reminder.status,
                            snoozed_until=source_reminder.snoozed_until,
                            last_shown_at=source_reminder.last_shown_at,
                        )
                    )
                target.add_task(occurrence)
                existing_lineages.add(task.lineage_id)
                created.append(occurrence)
        return tuple(created)


@dataclass(frozen=True, slots=True)
class TaskBoardRow:
    """One immutable display projection pointing back to canonical task state."""

    patient_id: UUID
    patient_name: str
    patient_status: AdmissionStatus
    hospital_day_id: UUID
    day_number: int
    day_label: str
    task: Task


class TaskService(ServiceBase):
    """Coordinate task CRUD, state changes, boards, and lineage deletion."""

    def create(
        self,
        patient_id: UUID,
        day_id: UUID,
        *,
        title: str,
        description: str = "",
        priority: ClinicalPriority = ClinicalPriority.ROUTINE,
        category: TaskCategory = TaskCategory.CLINICAL,
        bucket: TaskBucket | None = None,
        due_at: datetime | None = None,
        assigned_to: str | None = None,
        carry_forward: bool = True,
    ) -> Task:
        if category is TaskCategory.CLINICAL:
            category = parse_task_input(title, category).category
        if bucket is None:
            bucket = (
                TaskBucket.DIAGNOSTIC
                if category is TaskCategory.DIAGNOSTIC
                else TaskBucket.TODAY
            )
        if category is TaskCategory.HOUSEKEEPING:
            carry_forward = False
        task: Task
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                task = Task(
                    patient_id,
                    day.id,
                    title,
                    description=description,
                    priority=priority,
                    category=category,
                    bucket=bucket,
                    due_at=due_at,
                    assigned_to=assigned_to,
                    carry_forward=carry_forward,
                )
                day.add_task(task)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(TaskChanged(str(task.id), "created"))
        return task

    def replace_diagnostics_from(
        self,
        patient_id: UUID,
        day_id: UUID,
        entries: tuple[DiagnosticTextEntry, ...],
    ) -> tuple[Task, ...]:
        """Reconcile one free-form diagnostic block in a single transaction."""
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                selected_day = self._day(patient, day_id)
                existing = {
                    task.title.strip().casefold(): task
                    for task in selected_day.tasks
                    if task.category is TaskCategory.DIAGNOSTIC
                    and task.status is not TaskStatus.CANCELLED
                }
                retained_lineages: set[UUID] = set()
                for entry in entries:
                    task = existing.get(entry.title.casefold())
                    if task is None:
                        task = Task(
                            patient_id,
                            selected_day.id,
                            entry.title,
                            category=TaskCategory.DIAGNOSTIC,
                            bucket=TaskBucket.DIAGNOSTIC,
                        )
                        selected_day.add_task(task)
                    retained_lineages.add(task.lineage_id)
                    occurrences = tuple(
                        occurrence
                        for day in patient.hospital_days
                        if day.day_number >= selected_day.day_number
                        for occurrence in day.tasks
                        if occurrence.lineage_id == task.lineage_id
                    )
                    for occurrence in occurrences:
                        if entry.result:
                            if occurrence.diagnostic_result is None:
                                occurrence.attach_diagnostic_result(
                                    DiagnosticResult(
                                        patient_id,
                                        occurrence.hospital_day_id,
                                        occurrence.id,
                                        entry.result,
                                    )
                                )
                            else:
                                occurrence.diagnostic_result.update(entry.result)
                        if entry.completed and occurrence.status in {
                            TaskStatus.PENDING,
                            TaskStatus.IN_PROGRESS,
                            TaskStatus.DEFERRED,
                        }:
                            occurrence.complete()
                        elif not entry.completed and occurrence.status in {
                            TaskStatus.COMPLETED,
                            TaskStatus.CANCELLED,
                            TaskStatus.DEFERRED,
                        }:
                            occurrence.reopen()
                removed_lineages = {
                    task.lineage_id
                    for task in existing.values()
                    if task.lineage_id not in retained_lineages
                }
                for day in patient.hospital_days:
                    if day.day_number < selected_day.day_number:
                        continue
                    for task in tuple(day.tasks):
                        if task.lineage_id in removed_lineages:
                            day.remove_task(task.id)
                unit_of_work.patients.save(patient)
                result = tuple(
                    task
                    for task in selected_day.tasks
                    if task.category is TaskCategory.DIAGNOSTIC
                    and task.status is not TaskStatus.CANCELLED
                )
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(TaskChanged(str(day_id), "diagnostics_reconciled"))
        return result

    def list_for_day(
        self,
        patient_id: UUID,
        day_id: UUID,
        *,
        status: TaskStatus | None = None,
        bucket: TaskBucket | None = None,
    ) -> tuple[Task, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            tasks = self._day(self._patient(unit_of_work, patient_id), day_id).tasks
        return tuple(
            task
            for task in tasks
            if (status is None or task.status is status)
            and (bucket is None or task.bucket is bucket)
        )

    def current_board(self, patient_id: UUID | None = None) -> tuple[Task, ...]:
        """Compatibility projection of open tasks from the richer board rows."""
        return tuple(
            row.task
            for row in self.board(patient_id=patient_id)
            if row.task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
        )

    def board(
        self,
        *,
        category: TaskCategory | None = None,
        include_completed: bool = False,
        patient_id: UUID | None = None,
    ) -> tuple[TaskBoardRow, ...]:
        """Derive newest lineage occurrences across eligible patient dispositions."""
        with self._unit_of_work_factory() as unit_of_work:
            patients = (
                (self._patient(unit_of_work, patient_id),)
                if patient_id
                else unit_of_work.patients.list()
            )
        board: list[TaskBoardRow] = []
        for patient in patients:
            newest: dict[UUID, tuple[HospitalDay, Task]] = {}
            for day in patient.hospital_days:
                for task in day.tasks:
                    current = newest.get(task.lineage_id)
                    if current is None or task.occurrence_number > current[1].occurrence_number:
                        newest[task.lineage_id] = (day, task)
            for day, task in newest.values():
                if category is not None and task.category is not category:
                    continue
                if not self._eligible_for_board(patient.admission_status, task.category):
                    continue
                if not include_completed and task.status in {
                    TaskStatus.COMPLETED,
                    TaskStatus.CANCELLED,
                }:
                    continue
                label = day.calendar_date.isoformat()
                if day.label:
                    label = f"{label} | {day.label}"
                board.append(
                    TaskBoardRow(
                        patient.id,
                        patient.name,
                        patient.admission_status,
                        day.id,
                        day.day_number,
                        label,
                        task,
                    )
                )
        return tuple(
            sorted(
                board,
                key=lambda row: (
                    row.task.category.value,
                    row.patient_status.value,
                    row.patient_name.casefold(),
                    row.day_number,
                    row.task.bucket.value,
                    row.task.title.casefold(),
                    str(row.task.id),
                ),
            )
        )

    @staticmethod
    def _eligible_for_board(status: AdmissionStatus, category: TaskCategory) -> bool:
        if category is TaskCategory.DIAGNOSTIC:
            return status in {
                AdmissionStatus.ADMITTED,
                AdmissionStatus.DISCHARGED,
                AdmissionStatus.TRANSFERRED,
            }
        if category is TaskCategory.HOUSEKEEPING:
            return True
        return status is AdmissionStatus.ADMITTED

    def update(
        self,
        patient_id: UUID,
        task_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: ClinicalPriority | None = None,
        category: TaskCategory | None = None,
        bucket: TaskBucket | None = None,
        assigned_to: str | None = None,
        carry_forward: bool | None = None,
    ) -> Task:
        return self._mutate(
            patient_id,
            task_id,
            "updated",
            lambda task: task.update_details(
                title=title,
                description=description,
                priority=priority,
                category=category,
                bucket=bucket,
                assigned_to=assigned_to,
                carry_forward=carry_forward,
            ),
        )

    def complete(self, patient_id: UUID, task_id: UUID, at: datetime | None = None) -> Task:
        return self._mutate(patient_id, task_id, "completed", lambda task: task.complete(at))

    def update_from(
        self,
        patient_id: UUID,
        task_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: ClinicalPriority | None = None,
        category: TaskCategory | None = None,
        bucket: TaskBucket | None = None,
        assigned_to: str | None = None,
        carry_forward: bool | None = None,
    ) -> tuple[Task, ...]:
        """Edit matching lineage occurrences from the selected day forward."""
        if title is not None and category is TaskCategory.CLINICAL:
            category = parse_task_input(title, category).category
        return self._mutate_forward(
            patient_id,
            task_id,
            "updated_forward",
            lambda task: task.update_details(
                title=title,
                description=description,
                priority=priority,
                category=category,
                bucket=bucket,
                assigned_to=assigned_to,
                carry_forward=carry_forward,
            ),
            set(TaskStatus),
        )

    def reopen(self, patient_id: UUID, task_id: UUID) -> Task:
        return self._mutate(patient_id, task_id, "reopened", lambda task: task.reopen())

    def complete_from(
        self, patient_id: UUID, task_id: UUID, at: datetime | None = None
    ) -> tuple[Task, ...]:
        """Complete actionable occurrences from the selected day forward."""
        return self._mutate_forward(
            patient_id,
            task_id,
            "completed_forward",
            lambda task: task.complete(at),
            {TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.DEFERRED},
        )

    def reopen_from(self, patient_id: UUID, task_id: UUID) -> tuple[Task, ...]:
        """Reopen terminal/deferred occurrences from the selected day forward."""
        return self._mutate_forward(
            patient_id,
            task_id,
            "reopened_forward",
            lambda task: task.reopen(),
            {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.DEFERRED},
        )

    def omit_diagnostic_from(self, patient_id: UUID, task_id: UUID) -> tuple[Task, ...]:
        """Record a carried diagnostic omission as completed occurrences, never deletion."""
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                _, selected = self._task(patient, task_id)
        except PersistenceError as error:
            raise self._translate(error) from error
        if selected.category is not TaskCategory.DIAGNOSTIC:
            raise InvalidOperationError("Only pending diagnostics can be omitted this way.")
        return self.complete_from(patient_id, task_id)

    def delete_occurrence(self, patient_id: UUID, task_id: UUID) -> Task:
        removed: Task
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day, _ = self._task(patient, task_id)
                removed = day.remove_task(task_id)
                unit_of_work.patients.save(patient)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(TaskChanged(str(task_id), "deleted"))
        return removed

    def delete_from(self, patient_id: UUID, task_id: UUID) -> tuple[Task, ...]:
        """Delete matching lineage occurrences from the selected day forward."""
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                selected_day, selected = self._task(patient, task_id)
                affected = tuple(
                    task
                    for day in patient.hospital_days
                    if day.day_number >= selected_day.day_number
                    for task in tuple(day.tasks)
                    if task.lineage_id == selected.lineage_id
                )
                for day in patient.hospital_days:
                    for task in affected:
                        if task.hospital_day_id == day.id:
                            day.remove_task(task.id)
                unit_of_work.patients.save(patient)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(TaskChanged(str(selected.lineage_id), "deleted_forward"))
        return affected

    def delete_lineage(self, patient_id: UUID, lineage_id: UUID) -> int:
        removed = 0
        with self._unit_of_work_factory() as unit_of_work:
            patient = self._patient(unit_of_work, patient_id)
            for day in patient.hospital_days:
                for task in tuple(day.tasks):
                    if task.lineage_id == lineage_id:
                        day.remove_task(task.id)
                        removed += 1
            if not removed:
                raise InvalidOperationError(f"Task lineage {lineage_id} was not found.")
            unit_of_work.patients.save(patient)
        self._publisher.publish(TaskChanged(str(lineage_id), "lineage_deleted"))
        return removed

    def _mutate(
        self, patient_id: UUID, task_id: UUID, operation: str, action: Callable[[Task], None]
    ) -> Task:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                _, task = self._task(patient, task_id)
                try:
                    action(task)
                except DomainError as error:
                    raise InvalidOperationError(str(error)) from error
                unit_of_work.patients.save(patient)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(TaskChanged(str(task_id), operation))
        return task

    def _mutate_forward(
        self,
        patient_id: UUID,
        task_id: UUID,
        operation: str,
        action: Callable[[Task], None],
        eligible_statuses: set[TaskStatus],
    ) -> tuple[Task, ...]:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                selected_day, selected = self._task(patient, task_id)
                affected = tuple(
                    task
                    for day in patient.hospital_days
                    if day.day_number >= selected_day.day_number
                    for task in day.tasks
                    if task.lineage_id == selected.lineage_id and task.status in eligible_statuses
                )
                if not affected:
                    raise InvalidOperationError("No eligible task occurrences were found.")
                for task in affected:
                    action(task)
                if (
                    selected.source == "sandbox"
                    and selected.occurrence_number == 1
                    and operation in {"completed_forward", "reopened_forward"}
                ):
                    self._sync_sandbox_check(
                        selected_day,
                        selected,
                        completed=operation == "completed_forward",
                    )
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(TaskChanged(str(selected.lineage_id), operation))
        return affected

    @staticmethod
    def _sync_sandbox_check(day: HospitalDay, task: Task, *, completed: bool) -> None:
        """Mirror a source-day Sandbox task check without changing other scratch text."""
        rebuilt: list[str] = []
        changed = False
        for line in day.sandbox_text.splitlines(keepends=True):
            match = re.match(r"^(\s*-\s*\[)([ xX])(\]\s*)(.*?)(\r?\n)?$", line)
            if match is None or changed:
                rebuilt.append(line)
                continue
            try:
                parsed = parse_task_input(
                    match.group(4),
                    TaskCategory.CLINICAL,
                    discard_invalid_reminder=True,
                )
            except ValueError:
                rebuilt.append(line)
                continue
            if " ".join(parsed.title.casefold().split()) != " ".join(
                task.title.casefold().split()
            ):
                rebuilt.append(line)
                continue
            marker = "x" if completed else " "
            rebuilt.append(
                f"{match.group(1)}{marker}{match.group(3)}{match.group(4)}{match.group(5) or ''}"
            )
            changed = True
        if changed:
            day.update_sandbox("".join(rebuilt))
