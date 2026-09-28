"""Parse the compact legacy task-entry grammar into structured values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

from icu_patient_tracker.domain.enums import ClinicalPriority, TaskBucket, TaskCategory


@dataclass(frozen=True, slots=True)
class TaskReminderInput:
    """One validated interval or fixed-time reminder specification."""

    interval_minutes: int | None = None
    fixed_time: time | None = None


@dataclass(frozen=True, slots=True)
class TaskInput:
    """Structured task values produced from one compact entry."""

    title: str
    category: TaskCategory
    priority: ClinicalPriority
    bucket: TaskBucket
    carry_forward: bool
    reminder: TaskReminderInput | None = None
    carry_explicit: bool = False


_PRIORITIES = {
    "crit": ClinicalPriority.CRITICAL,
    "critical": ClinicalPriority.CRITICAL,
    "stat": ClinicalPriority.CRITICAL,
    "urgent": ClinicalPriority.URGENT,
    "high": ClinicalPriority.URGENT,
    "low": ClinicalPriority.LOW,
    "routine": ClinicalPriority.ROUTINE,
}
_BUCKETS = {
    "today": TaskBucket.TODAY,
    "day": TaskBucket.TODAY,
    "am": TaskBucket.TODAY,
    "overnight": TaskBucket.OVERNIGHT,
    "night": TaskBucket.OVERNIGHT,
    "pm": TaskBucket.OVERNIGHT,
    "discharge": TaskBucket.DISCHARGE,
    "dc": TaskBucket.DISCHARGE,
    "followup": TaskBucket.FOLLOW_UP,
    "follow-up": TaskBucket.FOLLOW_UP,
    "f/u": TaskBucket.FOLLOW_UP,
    "recheck": TaskBucket.FOLLOW_UP,
    "diagnostic": TaskBucket.DIAGNOSTIC,
    "pending": TaskBucket.DIAGNOSTIC,
    "test": TaskBucket.DIAGNOSTIC,
}


def parse_task_input(
    value: str,
    category: TaskCategory = TaskCategory.CLINICAL,
    *,
    discard_invalid_reminder: bool = False,
) -> TaskInput:
    """Parse reference-compatible priority, bucket, reminder, and carry tokens."""
    body = re.sub(r"^\s*[-*+]\s+", "", value.strip())
    body = re.sub(r"^\[\s*[xX]?\s*\]\s*", "", body)
    parts = [part.strip() for part in body.split("|")]
    title = parts[0] if parts else ""
    priority = ClinicalPriority.ROUTINE
    bucket = TaskBucket.DIAGNOSTIC if category is TaskCategory.DIAGNOSTIC else TaskBucket.TODAY
    carry_forward = True
    carry_explicit = False
    reminder: TaskReminderInput | None = None
    if title.startswith("!!"):
        priority = ClinicalPriority.CRITICAL
        title = title[2:].strip()
    elif title.startswith("!"):
        priority = ClinicalPriority.URGENT
        title = title[1:].strip()
    if not title:
        raise ValueError("Task title must not be empty.")

    for raw_token in parts[1:]:
        token = raw_token.casefold().strip()
        if token in {"carry", "cf", "carry:yes", "carry:true"}:
            carry_forward = True
            carry_explicit = True
        elif token in {"nocarry", "no-carry", "carry:no", "carry:false"}:
            carry_forward = False
            carry_explicit = True
        elif match := re.fullmatch(r"(?:p|priority)\s*:\s*(.+)", token):
            priority = _PRIORITIES.get(match.group(1).strip(), ClinicalPriority.ROUTINE)
        elif match := re.fullmatch(r"(?:b|bucket)\s*:\s*(.+)", token):
            bucket = _BUCKETS.get(match.group(1).strip(), bucket)
        elif match := re.fullmatch(r"(?:r|remind|reminder)\s*:\s*(.+)", token):
            # Invalid reminder metadata is ignored while the task itself remains
            # valid, matching the tolerant multiline/checklist grammar.
            try:
                reminder = _parse_reminder(match.group(1))
            except ValueError:
                if not discard_invalid_reminder:
                    raise
                reminder = None
        elif token in _PRIORITIES:
            priority = _PRIORITIES[token]
        elif token in _BUCKETS:
            bucket = _BUCKETS[token]

    routed_category = category
    normalized_title = title.casefold()
    if category is TaskCategory.CLINICAL and (
        re.search(r"\bpocus\b", normalized_title)
        or re.search(r"point\s*[- ]?\s*of\s*[- ]?\s*care\s+ultra\s*sound", normalized_title)
        or re.search(r"point\s*[- ]?\s*of\s*[- ]?\s*care\s+us\b", normalized_title)
    ):
        routed_category = TaskCategory.POCUS
    return TaskInput(
        title, routed_category, priority, bucket, carry_forward, reminder, carry_explicit
    )


def _parse_reminder(value: str) -> TaskReminderInput:
    interval = re.fullmatch(r"(\d{1,3})\s*(?:m|min|mins|minute|minutes)?", value.strip())
    if interval:
        minutes = int(interval.group(1))
        if minutes < 1:
            raise ValueError("Reminder interval must be at least one minute.")
        return TaskReminderInput(interval_minutes=minutes)
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2))
        if hour <= 23 and minute <= 59:
            return TaskReminderInput(fixed_time=time(hour, minute))
    raise ValueError("Reminder must use minutes such as 60m or a 24-hour time such as 14:30.")
