"""Problem validation and clinical trajectory tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.enums import ProblemStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
)
from icu_patient_tracker.domain.problem import Problem


def make_problem(**changes: object) -> Problem:
    values: dict[str, object] = {
        "patient_id": uuid4(),
        "hospital_day_id": uuid4(),
        "title": "Hypotension",
    }
    values.update(changes)
    return Problem(**values)  # type: ignore[arg-type]


def test_problem_creation_has_stable_defaults() -> None:
    problem = make_problem()
    other = make_problem()

    assert problem.status is ProblemStatus.ACTIVE
    assert problem.ordering_position == 0
    assert problem.lineage_id != other.lineage_id
    assert problem.source_problem_id is None
    assert problem.occurrence_number == 1
    assert "Hypotension" in repr(problem)


def test_problem_rejects_empty_title_and_negative_order() -> None:
    with pytest.raises(DomainValidationError, match="title"):
        make_problem(title=" ")
    with pytest.raises(DomainValidationError, match="ordering_position"):
        make_problem(ordering_position=-1)


def test_problem_resolves_and_can_be_reopened() -> None:
    problem = make_problem()
    resolved_at = datetime.now(UTC) + timedelta(seconds=1)
    problem.resolve(resolved_at)

    assert problem.status is ProblemStatus.RESOLVED
    assert problem.resolved_at == resolved_at
    problem.change_status(ProblemStatus.ACTIVE)
    assert problem.resolved_at is None


def test_problem_rejects_repeated_or_inactive_resolution() -> None:
    problem = make_problem()
    problem.resolve()
    with pytest.raises(InvalidStateTransitionError):
        problem.resolve()

    inactive = make_problem()
    inactive.archive()
    with pytest.raises(InvalidStateTransitionError):
        inactive.resolve()


def test_carried_problem_preserves_lineage_with_independent_identity() -> None:
    original = make_problem()
    carried = make_problem(
        hospital_day_id=uuid4(),
        lineage_id=original.lineage_id,
        source_problem_id=original.id,
        occurrence_number=2,
    )

    assert carried.id != original.id
    assert carried.lineage_id == original.lineage_id
    assert carried.source_problem_id == original.id


def test_problem_rejects_inconsistent_occurrence_metadata() -> None:
    with pytest.raises(DomainValidationError, match="initial problem occurrence"):
        make_problem(occurrence_number=2)
    with pytest.raises(DomainValidationError, match="carried problem occurrence"):
        make_problem(source_problem_id=uuid4(), occurrence_number=1)
