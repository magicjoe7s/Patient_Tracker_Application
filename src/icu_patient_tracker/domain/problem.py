"""Clinical problem state and supported lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import ClinicalPriority, ProblemStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
)
from icu_patient_tracker.domain.validation import (
    require_aware_datetime,
    require_enum,
    require_text,
    require_uuid,
    validate_audit_timestamps,
)


@dataclass(slots=True)
class Problem:
    """One ordered clinical concern within a single hospital-day problem list."""

    patient_id: UUID
    hospital_day_id: UUID
    title: str
    description: str = ""
    status: ProblemStatus = ProblemStatus.ACTIVE
    priority: ClinicalPriority = ClinicalPriority.ROUTINE
    identified_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    assessment: str = ""
    plan: str = ""
    notes: str = ""
    ordering_position: int = 0
    lineage_id: UUID = field(default_factory=uuid4)
    source_problem_id: UUID | None = None
    occurrence_number: int = 1
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.title = require_text(self.title, "title")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.lineage_id = require_uuid(self.lineage_id, "lineage_id")
        if self.source_problem_id is not None:
            self.source_problem_id = require_uuid(self.source_problem_id, "source_problem_id")
        self.id = require_uuid(self.id, "id")
        self.status = require_enum(self.status, ProblemStatus, "status")
        self.priority = require_enum(self.priority, ClinicalPriority, "priority")
        require_aware_datetime(self.identified_at, "identified_at")
        if self.ordering_position < 0:
            raise DomainValidationError("ordering_position must not be negative.")
        if self.source_problem_id == self.id:
            raise DomainValidationError("source_problem_id cannot reference the problem itself.")
        if self.occurrence_number < 1:
            raise DomainValidationError("occurrence_number must be at least 1.")
        if self.source_problem_id is None and self.occurrence_number != 1:
            raise DomainValidationError(
                "An initial problem occurrence must have occurrence_number 1."
            )
        if self.source_problem_id is not None and self.occurrence_number == 1:
            raise DomainValidationError(
                "A carried problem occurrence must have occurrence_number greater than 1."
            )
        validate_audit_timestamps(self.created_at, self.updated_at)
        if self.resolved_at is not None:
            if self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None:
                raise DomainValidationError("resolved_at must include timezone information.")
            if self.resolved_at < self.identified_at:
                raise DomainValidationError("resolved_at must not precede identified_at.")
        if self.status is ProblemStatus.RESOLVED and self.resolved_at is None:
            raise DomainValidationError("A resolved problem requires resolved_at.")
        if self.status is not ProblemStatus.RESOLVED and self.resolved_at is not None:
            raise DomainValidationError("Only a resolved problem may have resolved_at.")

    def change_status(self, status: ProblemStatus, changed_at: datetime | None = None) -> None:
        """Apply an explicit supported problem-state transition."""
        status = require_enum(status, ProblemStatus, "status")
        if status is self.status:
            raise InvalidStateTransitionError(f"Problem is already {status.value}.")
        allowed = {
            ProblemStatus.ACTIVE: {
                ProblemStatus.IMPROVING,
                ProblemStatus.WORSENING,
                ProblemStatus.STATIC,
                ProblemStatus.RESOLVED,
                ProblemStatus.INACTIVE,
            },
            ProblemStatus.IMPROVING: {
                ProblemStatus.ACTIVE,
                ProblemStatus.WORSENING,
                ProblemStatus.STATIC,
                ProblemStatus.RESOLVED,
                ProblemStatus.INACTIVE,
            },
            ProblemStatus.WORSENING: {
                ProblemStatus.ACTIVE,
                ProblemStatus.IMPROVING,
                ProblemStatus.STATIC,
                ProblemStatus.RESOLVED,
                ProblemStatus.INACTIVE,
            },
            ProblemStatus.STATIC: {
                ProblemStatus.ACTIVE,
                ProblemStatus.IMPROVING,
                ProblemStatus.WORSENING,
                ProblemStatus.RESOLVED,
                ProblemStatus.INACTIVE,
            },
            ProblemStatus.RESOLVED: {ProblemStatus.ACTIVE},
            ProblemStatus.INACTIVE: {ProblemStatus.ACTIVE},
        }
        if status not in allowed[self.status]:
            raise InvalidStateTransitionError(
                f"Problem cannot transition from {self.status.value} to {status.value}."
            )
        transition_time = changed_at or datetime.now(UTC)
        if transition_time.tzinfo is None or transition_time.utcoffset() is None:
            raise DomainValidationError("changed_at must include timezone information.")
        if transition_time < self.identified_at:
            raise DomainValidationError("changed_at must not precede identified_at.")
        self.status = status
        self.resolved_at = transition_time if status is ProblemStatus.RESOLVED else None
        self.updated_at = datetime.now(UTC)

    def update_details(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: ClinicalPriority | None = None,
        assessment: str | None = None,
        plan: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Edit supported content without changing problem identity or lifecycle."""
        if title is not None:
            self.title = require_text(title, "title")
        if description is not None:
            self.description = description
        if priority is not None:
            self.priority = require_enum(priority, ClinicalPriority, "priority")
        if assessment is not None:
            self.assessment = assessment
        if plan is not None:
            self.plan = plan
        if notes is not None:
            self.notes = notes
        self.updated_at = datetime.now(UTC)

    def resolve(self, resolved_at: datetime | None = None) -> None:
        """Resolve an active problem exactly once."""
        if self.status in {ProblemStatus.RESOLVED, ProblemStatus.INACTIVE}:
            raise InvalidStateTransitionError(f"A {self.status.value} problem cannot be resolved.")
        self.change_status(ProblemStatus.RESOLVED, resolved_at)

    def archive(self) -> None:
        """Mark a non-resolved problem inactive while retaining its record."""
        if self.status in {ProblemStatus.RESOLVED, ProblemStatus.INACTIVE}:
            raise InvalidStateTransitionError(f"A {self.status.value} problem cannot be archived.")
        self.change_status(ProblemStatus.INACTIVE)

    def __repr__(self) -> str:
        return f"Problem(id={self.id!r}, title={self.title!r}, status={self.status.value!r})"
