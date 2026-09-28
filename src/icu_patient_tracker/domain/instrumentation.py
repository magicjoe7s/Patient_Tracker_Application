"""Relationship-safe collection of current and historical medical devices."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceStatus, DeviceType
from icu_patient_tracker.domain.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    RelationshipError,
)
from icu_patient_tracker.domain.validation import (
    require_uuid,
    validate_audit_timestamps,
)


@dataclass(slots=True)
class Instrumentation:
    """The device collection owned by exactly one patient hospital day."""

    patient_id: UUID
    hospital_day_id: UUID
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _devices: list[Device] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.id = require_uuid(self.id, "id")
        validate_audit_timestamps(self.created_at, self.updated_at)
        initial_devices = list(self._devices)
        self._devices.clear()
        for device in initial_devices:
            self.add(device)

    @property
    def devices(self) -> tuple[Device, ...]:
        """Return all devices in insertion order."""
        return tuple(self._devices)

    @property
    def active_devices(self) -> tuple[Device, ...]:
        """Return devices that remain in place."""
        return tuple(device for device in self._devices if device.status is DeviceStatus.ACTIVE)

    @property
    def historical_devices(self) -> tuple[Device, ...]:
        """Return removed devices retained for clinical history."""
        return tuple(device for device in self._devices if device.status is DeviceStatus.REMOVED)

    def add(self, device: Device) -> None:
        """Add a device after verifying its patient and hospital-day owners."""
        self._validate_relationship(device)
        if any(existing.id == device.id for existing in self._devices):
            raise DuplicateEntityError(f"Device {device.id} is already recorded.")
        self._devices.append(device)
        self._touch()

    def mark_removed(self, device_id: UUID, removed_at: datetime | None = None) -> None:
        """Clinically remove a device without deleting its historical record."""
        self.get(device_id).mark_removed(removed_at)
        self._touch()

    def delete_record(self, device_id: UUID) -> Device:
        """Delete an erroneous record; this is distinct from clinical removal."""
        device = self.get(device_id)
        self._devices.remove(device)
        self._touch()
        return device

    def group_by_type(self) -> dict[DeviceType, tuple[Device, ...]]:
        """Group all current and historical devices by controlled type."""
        grouped: defaultdict[DeviceType, list[Device]] = defaultdict(list)
        for device in self._devices:
            grouped[device.device_type].append(device)
        return {device_type: tuple(devices) for device_type, devices in grouped.items()}

    def group_by_status(self) -> dict[DeviceStatus, tuple[Device, ...]]:
        """Group devices by placement lifecycle state."""
        grouped: defaultdict[DeviceStatus, list[Device]] = defaultdict(list)
        for device in self._devices:
            grouped[device.status].append(device)
        return {status: tuple(devices) for status, devices in grouped.items()}

    def get(self, device_id: UUID) -> Device:
        """Return one member by stable identifier."""
        for device in self._devices:
            if device.id == device_id:
                return device
        raise EntityNotFoundError(f"Device {device_id} is not in this instrumentation record.")

    def _validate_relationship(self, device: Device) -> None:
        if device.patient_id != self.patient_id:
            raise RelationshipError("Device belongs to a different patient.")
        if device.hospital_day_id != self.hospital_day_id:
            raise RelationshipError("Device belongs to a different hospital day.")

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"Instrumentation(id={self.id!r}, hospital_day_id={self.hospital_day_id!r}, "
            f"devices={len(self._devices)})"
        )
