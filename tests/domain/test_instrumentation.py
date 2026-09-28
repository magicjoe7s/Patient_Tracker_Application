"""Instrumentation ownership, history, and grouping tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceType
from icu_patient_tracker.domain.exceptions import DuplicateEntityError, RelationshipError
from icu_patient_tracker.domain.instrumentation import Instrumentation


def make_device(day_id: UUID, patient_id: UUID) -> Device:
    return Device(
        patient_id,
        day_id,
        DeviceType.URINARY_CATHETER,
        "Urinary bladder",
        datetime(2026, 7, 20, 8, tzinfo=UTC),
    )


def test_instrumentation_tracks_active_and_historical_devices() -> None:
    day_id = uuid4()
    patient_id = uuid4()
    instrumentation = Instrumentation(patient_id, day_id)
    device = make_device(day_id, patient_id)
    instrumentation.add(device)
    instrumentation.mark_removed(device.id, device.placed_at + timedelta(hours=1))

    assert instrumentation.active_devices == ()
    assert instrumentation.historical_devices == (device,)
    assert instrumentation.group_by_type()[DeviceType.URINARY_CATHETER] == (device,)


def test_instrumentation_enforces_identity_and_ownership() -> None:
    day_id = uuid4()
    patient_id = uuid4()
    instrumentation = Instrumentation(patient_id, day_id)
    device = make_device(day_id, patient_id)
    instrumentation.add(device)
    with pytest.raises(DuplicateEntityError):
        instrumentation.add(device)
    with pytest.raises(RelationshipError):
        instrumentation.add(make_device(day_id, uuid4()))


def test_delete_record_is_distinct_from_clinical_removal() -> None:
    day_id = uuid4()
    patient_id = uuid4()
    instrumentation = Instrumentation(patient_id, day_id)
    device = make_device(day_id, patient_id)
    instrumentation.add(device)

    assert instrumentation.delete_record(device.id) is device
    assert instrumentation.devices == ()
