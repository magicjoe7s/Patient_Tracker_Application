"""Problem-list relationship, filtering, and ordering tests."""

from uuid import UUID, uuid4

import pytest

from icu_patient_tracker.domain.enums import ProblemStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    RelationshipError,
)
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.problem_list import ProblemList


def make_problem(day_id: UUID, patient_id: UUID, title: str) -> Problem:
    return Problem(patient_id, day_id, title)


def test_problem_list_adds_filters_and_removes_members() -> None:
    day_id = uuid4()
    patient_id = uuid4()
    problem_list = ProblemList(patient_id, day_id)
    active = make_problem(day_id, patient_id, "Hypotension")
    resolved = make_problem(day_id, patient_id, "Hypoglycemia")
    resolved.resolve()
    problem_list.add(active)
    problem_list.add(resolved)

    assert problem_list.active_problems == (active,)
    assert problem_list.resolved_problems == (resolved,)
    assert problem_list.remove(active.id) is active


def test_problem_list_prevents_duplicates_and_wrong_owners() -> None:
    day_id = uuid4()
    patient_id = uuid4()
    problem_list = ProblemList(patient_id, day_id)
    problem = make_problem(day_id, patient_id, "Hypotension")
    problem_list.add(problem)
    with pytest.raises(DuplicateEntityError):
        problem_list.add(problem)
    with pytest.raises(RelationshipError):
        problem_list.add(make_problem(day_id, uuid4(), "Anemia"))


def test_problem_list_reorders_every_member_deterministically() -> None:
    day_id = uuid4()
    patient_id = uuid4()
    problem_list = ProblemList(patient_id, day_id)
    first = make_problem(day_id, patient_id, "First")
    second = make_problem(day_id, patient_id, "Second")
    problem_list.add(first)
    problem_list.add(second)

    problem_list.reorder([second.id, first.id])
    assert problem_list.problems == (second, first)
    assert [problem.ordering_position for problem in problem_list.problems] == [0, 1]
    with pytest.raises(DomainValidationError):
        problem_list.reorder([first.id, first.id])


def test_problem_list_archives_without_deleting() -> None:
    day_id = uuid4()
    patient_id = uuid4()
    problem_list = ProblemList(patient_id, day_id)
    problem = make_problem(day_id, patient_id, "Historical concern")
    problem_list.add(problem)
    problem_list.archive(problem.id)

    assert problem.status is ProblemStatus.INACTIVE
    assert problem_list.problems == (problem,)
