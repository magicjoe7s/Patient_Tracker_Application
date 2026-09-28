"""Task validation, state transition, and reminder ownership tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.enums import ReminderStatus, TaskStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
    RelationshipError,
)
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.task import Task


def make_task() -> Task:
    return Task(uuid4(), uuid4(), "Recheck blood pressure")


def make_reminder(task: Task) -> Reminder:
    return Reminder(
        task.id,
        task.patient_id,
        task.hospital_day_id,
        datetime(2026, 7, 20, 12, tzinfo=UTC),
        "Blood pressure recheck due",
    )


def test_task_defaults_and_supported_transitions() -> None:
    task = make_task()
    assert task.status is TaskStatus.PENDING
    assert task.occurrence_number == 1
    assert task.source_task_id is None
    assert task.carry_forward
    task.start()
    task.defer()
    task.start()
    task.complete()
    assert task.status is TaskStatus.COMPLETED
    assert task.completed_at is not None
    task.reopen()
    assert task.status is TaskStatus.PENDING
    assert task.completed_at is None


def test_task_rejects_invalid_values_and_terminal_transition() -> None:
    with pytest.raises(DomainValidationError, match="title"):
        Task(uuid4(), uuid4(), "")
    with pytest.raises(DomainValidationError, match="timezone"):
        Task(uuid4(), uuid4(), "Task", due_at=datetime(2026, 7, 20, 12))

    task = make_task()
    task.complete()
    with pytest.raises(InvalidStateTransitionError):
        task.complete()


def test_task_owns_at_most_one_matching_reminder() -> None:
    task = make_task()
    reminder = make_reminder(task)
    task.attach_reminder(reminder)

    assert task.reminder is reminder
    assert reminder.status is ReminderStatus.PENDING
    with pytest.raises(InvalidStateTransitionError):
        task.attach_reminder(make_reminder(task))

    other_task = make_task()
    with pytest.raises(RelationshipError):
        other_task.attach_reminder(reminder)


def test_carried_task_occurrence_preserves_lineage() -> None:
    original = make_task()
    carried = Task(
        original.patient_id,
        uuid4(),
        original.title,
        lineage_id=original.lineage_id,
        source_task_id=original.id,
        occurrence_number=2,
    )

    assert carried.id != original.id
    assert carried.lineage_id == original.lineage_id
    assert carried.source_task_id == original.id


def test_task_rejects_inconsistent_occurrence_metadata() -> None:
    with pytest.raises(DomainValidationError, match="initial task occurrence"):
        Task(uuid4(), uuid4(), "Task", occurrence_number=2)
