"""Reference-compatible compact task grammar tests."""

from datetime import time

import pytest

from icu_patient_tracker.domain.enums import ClinicalPriority, TaskBucket, TaskCategory
from icu_patient_tracker.utils.task_input import parse_task_input


def test_compact_task_grammar_routes_pocus_and_structures_metadata() -> None:
    parsed = parse_task_input(
        "- [ ] !! POCUS lung scan | b:overnight | r:60m | nocarry",
        TaskCategory.CLINICAL,
    )

    assert parsed.title == "POCUS lung scan"
    assert parsed.category is TaskCategory.POCUS
    assert parsed.priority is ClinicalPriority.CRITICAL
    assert parsed.bucket is TaskBucket.OVERNIGHT
    assert not parsed.carry_forward
    assert parsed.reminder is not None
    assert parsed.reminder.interval_minutes == 60


def test_compact_task_tokens_preserve_reference_aliases_and_order() -> None:
    parsed = parse_task_input(
        "! Recheck culture | p:low | b:f/u | r:14:30",
        TaskCategory.DIAGNOSTIC,
    )

    assert parsed.priority is ClinicalPriority.LOW
    assert parsed.bucket is TaskBucket.FOLLOW_UP
    assert parsed.category is TaskCategory.DIAGNOSTIC
    assert parsed.reminder is not None
    assert parsed.reminder.fixed_time == time(14, 30)


@pytest.mark.parametrize("value", ["Task | r:0m", "Task | r:25:00", "Task | r:tomorrow"])
def test_compact_task_rejects_invalid_reminders(value: str) -> None:
    with pytest.raises(ValueError, match="Reminder"):
        parse_task_input(value)
