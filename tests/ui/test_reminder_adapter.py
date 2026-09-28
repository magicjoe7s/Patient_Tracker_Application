"""Headless Qt adapter tests for privacy, polling, and digest cadence."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from icu_patient_tracker.domain.enums import ClinicalPriority, TaskCategory
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.services.reminder_service import DigestEntry, HourlyDigest
from icu_patient_tracker.ui.reminder_adapter import QtReminderAdapter


class FakeSink:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def show(self, title: str, message: str) -> bool:
        self.messages.append((title, message))
        return True


class FakeReminderService:
    def __init__(self, due: tuple[Reminder, ...], digest: HourlyDigest) -> None:
        self._due = due
        self._digest = digest
        self.shown: list[tuple[object, ...]] = []

    def due(self) -> tuple[Reminder, ...]:
        due, self._due = self._due, ()
        return due

    def mark_shown(self, reminder_ids) -> None:
        self.shown.append(tuple(reminder_ids))

    def hourly_digest(self) -> HourlyDigest:
        return self._digest


def test_adapter_limits_privacy_safe_alert_and_marks_displayed_reminders() -> None:
    now = datetime(2026, 7, 20, 10, tzinfo=UTC)
    patient_id = uuid4()
    reminders = tuple(
        Reminder(uuid4(), patient_id, uuid4(), now, f"Sensitive task {index}") for index in range(5)
    )
    digest = HourlyDigest(now, (), (), (), (), 0, 0)
    service = FakeReminderService(reminders, digest)
    sink = FakeSink()
    adapter = QtReminderAdapter(service, notification_sink=sink, now=lambda: now)  # type: ignore[arg-type]

    adapter.poll()

    assert service.shown == [tuple(reminder.id for reminder in reminders)]
    body = sink.messages[0][1]
    assert body.count("A scheduled reminder is due.") == 3
    assert "+2 more" in body
    assert "Sensitive" not in body


def test_hourly_digest_emits_once_and_reappears_after_five_minute_snooze() -> None:
    clock = [datetime(2026, 7, 20, 10, tzinfo=UTC)]
    entry = DigestEntry(
        patient_id=uuid4(),
        patient_name="Bella",
        day_number=2,
        task_id=uuid4(),
        title="Recheck",
        category=TaskCategory.CLINICAL,
        priority=ClinicalPriority.URGENT,
    )
    digest = HourlyDigest(clock[0], (entry,), (), (), (entry,), 1, 0)
    service = FakeReminderService((), digest)
    adapter = QtReminderAdapter(
        service,
        notification_sink=FakeSink(),
        now=lambda: clock[0],  # type: ignore[arg-type]
    )
    received: list[HourlyDigest] = []
    adapter.digest_ready.connect(received.append)

    adapter.poll()
    adapter.poll()
    assert received == [digest]

    adapter.snooze_digest()
    clock[0] += timedelta(minutes=4)
    adapter.poll()
    assert received == [digest]
    clock[0] += timedelta(minutes=1)
    adapter.poll()
    assert received == [digest, digest]
