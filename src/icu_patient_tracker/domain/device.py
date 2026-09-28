"""Medical device placement and removal lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import DeviceStatus, DeviceType
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
)
from icu_patient_tracker.domain.validation import (
    require_enum,
    require_text,
    require_uuid,
    validate_audit_timestamps,
    validate_timestamp_order,
)


@dataclass(slots=True)
class Device:
    """One medical device owned by a hospital day's instrumentation record."""

    patient_id: UUID
    hospital_day_id: UUID
    device_type: DeviceType
    anatomical_location: str
    placed_at: datetime
    status: DeviceStatus = DeviceStatus.ACTIVE
    removed_at: datetime | None = None
    size: str | None = None
    notes: str = ""
    complications: tuple[str, ...] = ()
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.id = require_uuid(self.id, "id")
        self.device_type = require_enum(self.device_type, DeviceType, "device_type")
        self.status = require_enum(self.status, DeviceStatus, "status")
        self.anatomical_location = require_text(self.anatomical_location, "anatomical_location")
        if self.size is not None:
            self.size = require_text(self.size, "size")
        validate_timestamp_order(self.placed_at, self.removed_at, "placed_at", "removed_at")
        validate_audit_timestamps(self.created_at, self.updated_at)
        if self.status is DeviceStatus.REMOVED and self.removed_at is None:
            raise DomainValidationError("A removed device requires removed_at.")
        if self.status is DeviceStatus.ACTIVE and self.removed_at is not None:
            raise DomainValidationError("An active device cannot have removed_at.")
        normalized_complications = tuple(
            require_text(complication, "complication") for complication in self.complications
        )
        self.complications = normalized_complications

    def mark_removed(self, removed_at: datetime | None = None) -> None:
        """Record clinical removal while preserving the device history."""
        if self.status is DeviceStatus.REMOVED:
            raise InvalidStateTransitionError("Device is already removed.")
        removal_time = removed_at or datetime.now(UTC)
        validate_timestamp_order(self.placed_at, removal_time, "placed_at", "removed_at")
        self.status = DeviceStatus.REMOVED
        self.removed_at = removal_time
        self.updated_at = datetime.now(UTC)

    def update_details(
        self,
        *,
        anatomical_location: str | None = None,
        size: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Edit supported placement metadata without changing device identity."""
        if anatomical_location is not None:
            self.anatomical_location = require_text(anatomical_location, "anatomical_location")
        if size is not None:
            self.size = require_text(size, "size")
        if notes is not None:
            self.notes = notes
        self.updated_at = datetime.now(UTC)

    def add_complication(self, complication: str) -> None:
        """Append a non-empty observed device complication."""
        normalized = require_text(complication, "complication")
        self.complications = (*self.complications, normalized)
        self.updated_at = datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"Device(id={self.id!r}, type={self.device_type.value!r}, status={self.status.value!r})"
        )
