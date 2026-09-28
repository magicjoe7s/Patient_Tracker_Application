"""Reminder validation and notification lifecycle tests."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.enums import ReminderScheduleType, ReminderStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
)
from icu_patient_tracker.domain.reminder import Reminder


def make_reminder() -> Reminder:
    return Reminder(
        uuid4(),
        uuid4(),
        uuid4(),
        datetime(2026, 7, 20, 12, tzinfo=UTC),
        "Review culture result",
    )


def test_reminder_snooze_moves_trigger_forward() -> None:
    reminder = make_reminder()
    snoozed_until = reminder.trigger_at + timedelta(minutes=30)
    reminder.snooze(snoozed_until)

    assert reminder.status is ReminderStatus.SNOOZED
    assert reminder.trigger_at == snoozed_until
    assert reminder.snoozed_until == snoozed_until


def test_reminder_rejects_invalid_snooze_and_empty_message() -> None:
    reminder = make_reminder()
    with pytest.raises(DomainValidationError):
        reminder.snooze(reminder.trigger_at)
    with pytest.raises(DomainValidationError, match="message"):
        Reminder(uuid4(), uuid4(), uuid4(), reminder.trigger_at, " ")


@pytest.mark.parametrize("action", ["dismiss", "complete", "cancel"])
def test_reminder_terminal_actions_cannot_repeat(action: str) -> None:
    reminder = make_reminder()
    getattr(reminder, action)()
    with pytest.raises(InvalidStateTransitionError):
        getattr(reminder, action)()


def test_shown_interval_reminder_advances_from_actual_display_time() -> None:
    shown_at = datetime(2026, 7, 20, 12, 7, tzinfo=UTC)
    reminder = Reminder(
        uuid4(),
        uuid4(),
        uuid4(),
        datetime(2026, 7, 20, 12, tzinfo=UTC),
        "Recheck",
        schedule_type=ReminderScheduleType.INTERVAL,
        interval_minutes=30,
        anchor_at=datetime(2026, 7, 20, 11, 30, tzinfo=UTC),
    )

    reminder.mark_shown(shown_at)

    assert reminder.last_shown_at == shown_at
    assert reminder.trigger_at == shown_at + timedelta(minutes=30)
    assert reminder.status is ReminderStatus.PENDING


def test_shown_fixed_reminder_advances_to_next_fixed_occurrence() -> None:
    shown_at = datetime(2026, 7, 20, 9, 4, tzinfo=UTC)
    reminder = Reminder(
        uuid4(),
        uuid4(),
        uuid4(),
        datetime(2026, 7, 20, 9, tzinfo=UTC),
        "Review",
        schedule_type=ReminderScheduleType.FIXED_TIME,
        fixed_time=time(9),
    )

    reminder.mark_shown(shown_at)

    assert reminder.trigger_at == datetime(2026, 7, 21, 9, tzinfo=UTC)
    assert reminder.status is ReminderStatus.PENDING


def test_absolute_reminder_is_dismissed_after_display_and_cannot_show_early() -> None:
    reminder = make_reminder()
    with pytest.raises(DomainValidationError, match="before it is due"):
        reminder.mark_shown(reminder.trigger_at - timedelta(seconds=1))

    reminder.mark_shown(reminder.trigger_at)

    assert reminder.status is ReminderStatus.DISMISSED
    assert reminder.dismissed_at == reminder.trigger_at
