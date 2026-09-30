"""Configured deployment identifiers remain unique and release-ready."""

from uuid import UUID

from icu_patient_tracker.sync.project import DEVICES


def test_er_has_a_distinct_valid_device_identity() -> None:
    assert DEVICES["ER"] == "6f74d87e-1d08-48e6-bd79-ded8356b2ac1"
    assert len(DEVICES) == 4
    assert len(set(DEVICES.values())) == len(DEVICES)
    assert all(UUID(device_id) for device_id in DEVICES.values())
