"""Ordered, relationship-safe collection of clinical problems."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import ProblemStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    EntityNotFoundError,
    RelationshipError,
)
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.validation import (
    require_uuid,
    validate_audit_timestamps,
)


@dataclass(slots=True)
class ProblemList:
    """The single deterministic problem collection owned by one hospital day."""

    patient_id: UUID
    hospital_day_id: UUID
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _problems: list[Problem] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.id = require_uuid(self.id, "id")
        validate_audit_timestamps(self.created_at, self.updated_at)
        initial_problems = list(self._problems)
        self._problems.clear()
        for problem in initial_problems:
            self.add(problem)

    @property
    def problems(self) -> tuple[Problem, ...]:
        """Return problems in their explicit deterministic order."""
        return tuple(sorted(self._problems, key=lambda problem: problem.ordering_position))

    @property
    def active_problems(self) -> tuple[Problem, ...]:
        """Return unresolved and non-archived problems."""
        return tuple(
            problem
            for problem in self.problems
            if problem.status not in {ProblemStatus.RESOLVED, ProblemStatus.INACTIVE}
        )

    @property
    def resolved_problems(self) -> tuple[Problem, ...]:
        """Return clinically resolved problems."""
        return tuple(
            problem for problem in self.problems if problem.status is ProblemStatus.RESOLVED
        )

    def add(self, problem: Problem) -> None:
        """Add a problem after enforcing identity and ownership invariants."""
        self._validate_relationship(problem)
        if any(existing.id == problem.id for existing in self._problems):
            raise DuplicateEntityError(f"Problem {problem.id} is already in this list.")
        if any(existing.lineage_id == problem.lineage_id for existing in self._problems):
            raise DuplicateEntityError(
                f"Problem lineage {problem.lineage_id} already has an occurrence in this list."
            )
        if any(
            existing.ordering_position == problem.ordering_position for existing in self._problems
        ):
            problem.ordering_position = len(self._problems)
        self._problems.append(problem)
        self._touch()

    def remove(self, problem_id: UUID) -> Problem:
        """Delete a problem record explicitly; archive should be preferred clinically."""
        problem = self.get(problem_id)
        self._problems.remove(problem)
        self._normalize_order()
        self._touch()
        return problem

    def archive(self, problem_id: UUID) -> None:
        """Retain a problem record while removing it from the active view."""
        self.get(problem_id).archive()
        self._touch()

    def reorder(self, ordered_ids: list[UUID]) -> None:
        """Apply a complete, duplicate-free ordering of current members."""
        current_ids = {problem.id for problem in self._problems}
        if len(ordered_ids) != len(set(ordered_ids)):
            raise DomainValidationError("Problem ordering must not contain duplicate IDs.")
        if set(ordered_ids) != current_ids:
            raise DomainValidationError(
                "Problem ordering must contain every current problem exactly once."
            )
        by_id = {problem.id: problem for problem in self._problems}
        self._problems = [by_id[problem_id] for problem_id in ordered_ids]
        self._normalize_order()
        self._touch()

    def get(self, problem_id: UUID) -> Problem:
        """Return one member by stable identifier."""
        for problem in self._problems:
            if problem.id == problem_id:
                return problem
        raise EntityNotFoundError(f"Problem {problem_id} is not in this list.")

    def _validate_relationship(self, problem: Problem) -> None:
        if problem.patient_id != self.patient_id:
            raise RelationshipError("Problem belongs to a different patient.")
        if problem.hospital_day_id != self.hospital_day_id:
            raise RelationshipError("Problem belongs to a different hospital day.")

    def _normalize_order(self) -> None:
        for position, problem in enumerate(self._problems):
            problem.ordering_position = position

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"ProblemList(id={self.id!r}, hospital_day_id={self.hospital_day_id!r}, "
            f"problems={len(self._problems)})"
        )
