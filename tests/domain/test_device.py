"""Device placement, removal, and complication tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceStatus, DeviceType
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
)


def make_device(**changes: object) -> Device:
    values: dict[str, object] = {
        "patient_id": uuid4(),
        "hospital_day_id": uuid4(),
        "device_type": DeviceType.PERIPHERAL_IV_CATHETER,
        "anatomical_location": "Left cephalic",
        "placed_at": datetime(2026, 7, 20, 8, tzinfo=UTC),
    }
    values.update(changes)
    return Device(**values)  # type: ignore[arg-type]


def test_device_creation_and_removal_preserve_history() -> None:
    device = make_device()
    removal = device.placed_at + timedelta(hours=4)
    device.mark_removed(removal)

    assert device.status is DeviceStatus.REMOVED
    assert device.removed_at == removal
    assert "peripheral_iv_catheter" in repr(device)
    with pytest.raises(InvalidStateTransitionError):
        device.mark_removed(removal)


def test_device_rejects_invalid_timestamp_order() -> None:
    placed = datetime(2026, 7, 20, 8, tzinfo=UTC)
    with pytest.raises(DomainValidationError, match="removed_at"):
        make_device(
            status=DeviceStatus.REMOVED,
            removed_at=placed - timedelta(minutes=1),
        )
    assert make_device(anatomical_location="").anatomical_location == ""


def test_unknown_placement_can_be_removed_without_inventing_a_date() -> None:
    device = make_device(placed_at=None, anatomical_location="")
    removed = datetime(2026, 7, 20, 8, tzinfo=UTC)
    device.mark_removed(removed)
    assert device.placed_at is None
    assert device.removed_at == removed
    with pytest.raises(DomainValidationError, match="timezone"):
        make_device(placed_at=None, removed_at=datetime(2026, 7, 20), status=DeviceStatus.REMOVED)


def test_device_records_nonempty_complications() -> None:
    device = make_device()
    device.add_complication("Swelling")
    assert device.complications == ("Swelling",)
    with pytest.raises(DomainValidationError):
        device.add_complication(" ")
