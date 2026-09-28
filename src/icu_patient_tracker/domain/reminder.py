"""Time-based notification state associated with a clinical task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import ReminderScheduleType, ReminderStatus
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
class Reminder:
    """A notification that draws attention to one task without representing the work itself."""

    task_id: UUID
    patient_id: UUID
    hospital_day_id: UUID
    trigger_at: datetime
    message: str
    schedule_type: ReminderScheduleType = ReminderScheduleType.ABSOLUTE
    interval_minutes: int | None = None
    fixed_time: time | None = None
    anchor_at: datetime | None = None
    status: ReminderStatus = ReminderStatus.PENDING
    snoozed_until: datetime | None = None
    dismissed_at: datetime | None = None
    completed_at: datetime | None = None
    last_shown_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.message = require_text(self.message, "message")
        self.task_id = require_uuid(self.task_id, "task_id")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.id = require_uuid(self.id, "id")
        self.status = require_enum(self.status, ReminderStatus, "status")
        self.schedule_type = require_enum(self.schedule_type, ReminderScheduleType, "schedule_type")
        require_aware_datetime(self.trigger_at, "trigger_at")
        if self.anchor_at is not None:
            require_aware_datetime(self.anchor_at, "anchor_at")
        for field_name, value in (
            ("snoozed_until", self.snoozed_until),
            ("dismissed_at", self.dismissed_at),
            ("completed_at", self.completed_at),
            ("last_shown_at", self.last_shown_at),
        ):
            if value is not None:
                require_aware_datetime(value, field_name)
        validate_audit_timestamps(self.created_at, self.updated_at)
        self._validate_status_timestamps()
        self._validate_schedule()

    def reschedule(
        self,
        *,
        trigger_at: datetime,
        schedule_type: ReminderScheduleType,
        interval_minutes: int | None = None,
        fixed_time: time | None = None,
        anchor_at: datetime | None = None,
    ) -> None:
        """Replace the notification rule while retaining reminder identity."""
        self._ensure_actionable("rescheduled")
        require_aware_datetime(trigger_at, "trigger_at")
        self.trigger_at = trigger_at
        self.schedule_type = require_enum(schedule_type, ReminderScheduleType, "schedule_type")
        self.interval_minutes = interval_minutes
        self.fixed_time = fixed_time
        self.anchor_at = anchor_at
        self.status = ReminderStatus.PENDING
        self.snoozed_until = None
        self._validate_schedule()
        self.updated_at = datetime.now(UTC)

    def update_message(self, message: str) -> None:
        """Edit notification wording without changing its schedule or identity."""
        self._ensure_actionable("updated")
        self.message = require_text(message, "message")
        self.updated_at = datetime.now(UTC)

    def snooze(self, until: datetime) -> None:
        """Delay a pending notification until a later trigger time."""
        if self.status not in {ReminderStatus.PENDING, ReminderStatus.SNOOZED}:
            raise InvalidStateTransitionError(f"A {self.status.value} reminder cannot be snoozed.")
        require_aware_datetime(until, "snoozed_until")
        if until <= self.trigger_at:
            raise DomainValidationError("snoozed_until must be later than the current trigger_at.")
        self.status = ReminderStatus.SNOOZED
        self.snoozed_until = until
        self.trigger_at = until
        self.updated_at = datetime.now(UTC)

    def dismiss(self, dismissed_at: datetime | None = None) -> None:
        """Acknowledge a notification without claiming its task was completed."""
        self._ensure_actionable("dismissed")
        timestamp = dismissed_at or datetime.now(UTC)
        require_aware_datetime(timestamp, "dismissed_at")
        self.status = ReminderStatus.DISMISSED
        self.dismissed_at = timestamp
        self.updated_at = datetime.now(UTC)

    def complete(self, completed_at: datetime | None = None) -> None:
        """Mark the reminder's intended notification outcome complete."""
        self._ensure_actionable("completed")
        timestamp = completed_at or datetime.now(UTC)
        require_aware_datetime(timestamp, "completed_at")
        self.status = ReminderStatus.COMPLETED
        self.completed_at = timestamp
        self.updated_at = datetime.now(UTC)

    def mark_shown(self, shown_at: datetime) -> None:
        """Record successful display and advance recurring rules past the shown time."""
        self._ensure_actionable("shown")
        require_aware_datetime(shown_at, "last_shown_at")
        if shown_at < self.trigger_at:
            raise DomainValidationError("A reminder cannot be shown before it is due.")
        self.last_shown_at = shown_at
        self.snoozed_until = None
        if self.schedule_type is ReminderScheduleType.INTERVAL:
            self.trigger_at = shown_at + timedelta(minutes=self.interval_minutes or 0)
            self.status = ReminderStatus.PENDING
        elif self.schedule_type is ReminderScheduleType.FIXED_TIME:
            next_date = shown_at.date()
            candidate = datetime.combine(
                next_date, self.fixed_time or time(), tzinfo=shown_at.tzinfo
            )
            if candidate <= shown_at:
                candidate += timedelta(days=1)
            self.trigger_at = candidate
            self.status = ReminderStatus.PENDING
        else:
            self.status = ReminderStatus.DISMISSED
            self.dismissed_at = shown_at
        self.updated_at = datetime.now(UTC)

    def cancel(self) -> None:
        """Cancel a pending notification while retaining its record."""
        self._ensure_actionable("cancelled")
        self.status = ReminderStatus.CANCELLED
        self.updated_at = datetime.now(UTC)

    def _ensure_actionable(self, action: str) -> None:
        if self.status not in {ReminderStatus.PENDING, ReminderStatus.SNOOZED}:
            raise InvalidStateTransitionError(f"A {self.status.value} reminder cannot be {action}.")

    def _validate_status_timestamps(self) -> None:
        expected_timestamp = {
            ReminderStatus.SNOOZED: self.snoozed_until,
            ReminderStatus.DISMISSED: self.dismissed_at,
            ReminderStatus.COMPLETED: self.completed_at,
        }.get(self.status)
        if (
            self.status
            in {
                ReminderStatus.SNOOZED,
                ReminderStatus.DISMISSED,
                ReminderStatus.COMPLETED,
            }
            and expected_timestamp is None
        ):
            raise DomainValidationError(
                f"A {self.status.value} reminder requires its matching timestamp."
            )

    def _validate_schedule(self) -> None:
        if self.schedule_type is ReminderScheduleType.ABSOLUTE:
            if any(
                value is not None
                for value in (self.interval_minutes, self.fixed_time, self.anchor_at)
            ):
                raise DomainValidationError("An absolute reminder accepts only trigger_at.")
        elif self.schedule_type is ReminderScheduleType.INTERVAL:
            if self.interval_minutes is None or self.interval_minutes < 1:
                raise DomainValidationError("An interval reminder requires positive minutes.")
            if self.anchor_at is None:
                raise DomainValidationError("An interval reminder requires anchor_at.")
            require_aware_datetime(self.anchor_at, "anchor_at")
            if self.fixed_time is not None:
                raise DomainValidationError("An interval reminder cannot use fixed_time.")
        elif self.fixed_time is None or any(
            value is not None for value in (self.interval_minutes, self.anchor_at)
        ):
            raise DomainValidationError("A fixed-time reminder requires only fixed_time.")

    def __repr__(self) -> str:
        return f"Reminder(id={self.id!r}, task_id={self.task_id!r}, status={self.status.value!r})"
