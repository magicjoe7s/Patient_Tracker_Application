"""Clinical and administrative work item lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import (
    ClinicalPriority,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
    RelationshipError,
)
from icu_patient_tracker.domain.validation import (
    require_aware_datetime,
    require_enum,
    require_text,
    require_uuid,
    validate_audit_timestamps,
)

if TYPE_CHECKING:
    from icu_patient_tracker.domain.diagnostic_result import DiagnosticResult
    from icu_patient_tracker.domain.reminder import Reminder


@dataclass(slots=True)
class Task:
    """One required action owned by a patient hospital day."""

    patient_id: UUID
    hospital_day_id: UUID
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: ClinicalPriority = ClinicalPriority.ROUTINE
    due_at: datetime | None = None
    completed_at: datetime | None = None
    assigned_to: str | None = None
    category: TaskCategory = TaskCategory.CLINICAL
    bucket: TaskBucket = TaskBucket.TODAY
    source: str | None = None
    lineage_id: UUID = field(default_factory=uuid4)
    source_task_id: UUID | None = None
    occurrence_number: int = 1
    carry_forward: bool = True
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _reminder: Reminder | None = field(default=None, repr=False)
    _diagnostic_result: DiagnosticResult | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.title = require_text(self.title, "title")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.lineage_id = require_uuid(self.lineage_id, "lineage_id")
        if self.source_task_id is not None:
            self.source_task_id = require_uuid(self.source_task_id, "source_task_id")
        self.id = require_uuid(self.id, "id")
        self.status = require_enum(self.status, TaskStatus, "status")
        self.priority = require_enum(self.priority, ClinicalPriority, "priority")
        self.category = require_enum(self.category, TaskCategory, "category")
        self.bucket = require_enum(self.bucket, TaskBucket, "bucket")
        if self.source_task_id == self.id:
            raise DomainValidationError("source_task_id cannot reference the task itself.")
        if self.occurrence_number < 1:
            raise DomainValidationError("occurrence_number must be at least 1.")
        if self.source_task_id is None and self.occurrence_number != 1:
            raise DomainValidationError("An initial task occurrence must have occurrence_number 1.")
        if self.source_task_id is not None and self.occurrence_number == 1:
            raise DomainValidationError(
                "A carried task occurrence must have occurrence_number greater than 1."
            )
        if self.assigned_to is not None:
            self.assigned_to = require_text(self.assigned_to, "assigned_to")
        if self.source is not None:
            self.source = require_text(self.source, "source")
        if self.due_at is not None:
            require_aware_datetime(self.due_at, "due_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
        validate_audit_timestamps(self.created_at, self.updated_at)
        if self.status is TaskStatus.COMPLETED and self.completed_at is None:
            raise DomainValidationError("A completed task requires completed_at.")
        if self.status is not TaskStatus.COMPLETED and self.completed_at is not None:
            raise DomainValidationError("Only a completed task may have completed_at.")

    @property
    def reminder(self) -> Reminder | None:
        """Return the task's optional owned notification."""
        return self._reminder

    @property
    def diagnostic_result(self) -> DiagnosticResult | None:
        """Return the optional result owned by this diagnostic occurrence."""
        return self._diagnostic_result

    def attach_diagnostic_result(self, result: DiagnosticResult) -> None:
        """Attach one result whose ownership matches this diagnostic task."""
        if self.category is not TaskCategory.DIAGNOSTIC:
            raise InvalidStateTransitionError("Only a diagnostic task may own a result.")
        if result.task_id != self.id:
            raise RelationshipError("Diagnostic result references a different task.")
        if result.patient_id != self.patient_id:
            raise RelationshipError("Diagnostic result belongs to a different patient.")
        if result.hospital_day_id != self.hospital_day_id:
            raise RelationshipError("Diagnostic result belongs to a different hospital day.")
        if self._diagnostic_result is not None:
            raise InvalidStateTransitionError("Diagnostic task already has a result.")
        self._diagnostic_result = result
        self.updated_at = datetime.now(UTC)

    def attach_reminder(self, reminder: Reminder) -> None:
        """Attach at most one notification with the same clinical context."""
        if reminder.task_id != self.id:
            raise RelationshipError("Reminder references a different task.")
        if reminder.patient_id != self.patient_id:
            raise RelationshipError("Reminder belongs to a different patient.")
        if reminder.hospital_day_id != self.hospital_day_id:
            raise RelationshipError("Reminder belongs to a different hospital day.")
        if self._reminder is not None:
            raise InvalidStateTransitionError("Task already has a reminder.")
        self._reminder = reminder
        self.updated_at = datetime.now(UTC)

    def start(self) -> None:
        """Move pending or deferred work into progress."""
        self._transition(TaskStatus.IN_PROGRESS, {TaskStatus.PENDING, TaskStatus.DEFERRED})

    def defer(self) -> None:
        """Defer pending or in-progress work without completing it."""
        self._transition(TaskStatus.DEFERRED, {TaskStatus.PENDING, TaskStatus.IN_PROGRESS})

    def complete(self, completed_at: datetime | None = None) -> None:
        """Complete actionable work exactly once."""
        if self.status not in {
            TaskStatus.PENDING,
            TaskStatus.IN_PROGRESS,
            TaskStatus.DEFERRED,
        }:
            raise InvalidStateTransitionError(f"A {self.status.value} task cannot be completed.")
        completion_time = completed_at or datetime.now(UTC)
        require_aware_datetime(completion_time, "completed_at")
        self.status = TaskStatus.COMPLETED
        self.completed_at = completion_time
        self.updated_at = datetime.now(UTC)

    def cancel(self) -> None:
        """Cancel unfinished work while retaining its record."""
        if self.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            raise InvalidStateTransitionError(f"A {self.status.value} task cannot be cancelled.")
        self.status = TaskStatus.CANCELLED
        self.updated_at = datetime.now(UTC)

    def reopen(self) -> None:
        """Return completed, cancelled, or deferred work to pending."""
        if self.status not in {
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.DEFERRED,
        }:
            raise InvalidStateTransitionError(f"A {self.status.value} task cannot be reopened.")
        self.status = TaskStatus.PENDING
        self.completed_at = None
        self.updated_at = datetime.now(UTC)

    def update_details(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: ClinicalPriority | None = None,
        category: TaskCategory | None = None,
        bucket: TaskBucket | None = None,
        assigned_to: str | None = None,
        carry_forward: bool | None = None,
    ) -> None:
        """Edit task metadata without changing occurrence or lineage identity."""
        if title is not None:
            self.title = require_text(title, "title")
        if description is not None:
            self.description = description
        if priority is not None:
            self.priority = require_enum(priority, ClinicalPriority, "priority")
        if category is not None:
            if self._diagnostic_result is not None and category is not TaskCategory.DIAGNOSTIC:
                raise InvalidStateTransitionError(
                    "A task with a diagnostic result must remain a diagnostic task."
                )
            self.category = require_enum(category, TaskCategory, "category")
        if bucket is not None:
            self.bucket = require_enum(bucket, TaskBucket, "bucket")
        if assigned_to is not None:
            self.assigned_to = require_text(assigned_to, "assigned_to")
        if carry_forward is not None:
            self.carry_forward = carry_forward
        self.updated_at = datetime.now(UTC)

    def remove_reminder(self) -> Reminder | None:
        """Detach and return the owned reminder specification."""
        reminder = self._reminder
        self._reminder = None
        self.updated_at = datetime.now(UTC)
        return reminder

    def _transition(self, target: TaskStatus, allowed_sources: set[TaskStatus]) -> None:
        if self.status not in allowed_sources:
            raise InvalidStateTransitionError(
                f"Task cannot transition from {self.status.value} to {target.value}."
            )
        self.status = target
        self.updated_at = datetime.now(UTC)

    def __repr__(self) -> str:
        return f"Task(id={self.id!r}, title={self.title!r}, status={self.status.value!r})"
