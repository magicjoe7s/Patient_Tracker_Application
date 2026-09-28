"""Recognition of free-text instrumentation that contributes to Ins/Out."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceType
from icu_patient_tracker.services.instrumentation_service import device_output_label


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
