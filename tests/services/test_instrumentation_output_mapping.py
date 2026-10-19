"""Recognition of free-text instrumentation that contributes to Ins/Out."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceType
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.services.instrumentation_service import (
    device_output_label,
    reconcile_instrumentation_lines,
)


def free_text_device(line: str) -> Device:
    return Device(uuid4(), uuid4(), DeviceType.OTHER, line, datetime.now(UTC))


@pytest.mark.parametrize(
    ("line", "expected"),
    (
        ("U-cath — placed today", "UOP"),
        ("u cath", "UOP"),
        ("Foley catheter", "UOP"),
        ("Urinary catheter", "UOP"),
        ("Left chest tube", "Left chest tube output"),
        ("Right thoracostomy tube #2", "Right chest tube #2 output"),
        ("Right abdominal JP drain", "Right abdominal drain output"),
        ("SQ drain — left", "Left subcutaneous drain output"),
    ),
)
def test_free_text_output_device_aliases(line: str, expected: str) -> None:
    assert device_output_label(free_text_device(line)) == expected


def test_unrelated_instrumentation_does_not_add_output() -> None:
    assert device_output_label(free_text_device("PIV — left cephalic")) is None


def test_free_text_does_not_invent_placement_time() -> None:
    start = datetime(2026, 10, 19, 8, tzinfo=UTC)
    day = HospitalDay(uuid4(), start.date(), 1, start)
    reconcile_instrumentation_lines(day, ("Peripheral catheter, details unknown",))
    device = day.instrumentation.active_devices[0]
    assert device.placed_at is None
    assert device.created_at is not None
