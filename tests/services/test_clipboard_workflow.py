"""Slice 10 golden clipboard and EMR-state workflows."""

from datetime import UTC, datetime, timedelta

import pytest

from icu_patient_tracker.domain.enums import DeviceType
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.clipboard_service import ClipboardService
from icu_patient_tracker.services.exceptions import ClipboardServiceError
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.instrumentation_service import InstrumentationService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.soap_service import SOAPService

START = datetime(2026, 7, 22, 8, tzinfo=UTC)


class RecordingClipboard:
    def __init__(self, *, fail: bool = False) -> None:
        self.text = ""
        self.fail = fail

    def set_text(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("clipboard locked")
        self.text = text


def test_copy_chart_matches_golden_reference_order_and_crlf(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: START)
    days = HospitalDayService(factory)
    devices = InstrumentationService(factory)
    writer = RecordingClipboard()
    clipboard = ClipboardService(factory, writer)
    patient = patients.create(name="Bella", species="Canine")
    day = patient.hospital_days[0]
    days.update(
        patient.id,
        day.id,
        label="Post-op",
        treatment_changes="Fluids decreased\r\nAnalgesia continued",
        physical_examination="Bright and alert",
        assessment="Recovering well",
    )
    devices.add(
        patient.id,
        day.id,
        device_type=DeviceType.PERIPHERAL_IV_CATHETER,
        anatomical_location="Left cephalic",
        placed_at=START,
        size="20 g",
    )

    copied = clipboard.copy_chart(patient.id, day.id)

    assert copied == (
        "Bella | Jul 22, '26 | Post-op\r\n"
        "\r\nTreatment changes:\r\n"
        "Fluids decreased\r\nAnalgesia continued\r\n"
        "\r\nPhysical exam:\r\nBright and alert\r\n"
        "\r\nDevices/lines:\r\nPeripheral Iv Catheter: Left cephalic | 20 g"
    )
    assert writer.text == copied
    assert days.get(patient.id, day.id).emr_uploaded is False


def test_copy_mrn_writes_only_recorded_identifier(database_manager: DatabaseManager) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: START)
    writer = RecordingClipboard()
    clipboard = ClipboardService(factory, writer)
    patient = patients.create(mrn="123456", name="Bella", species="Canine")
    missing = patients.create(name="Milo", species="Feline")

    assert clipboard.copy_mrn(patient.id) == "123456"
    assert writer.text == "123456"
    with pytest.raises(ClipboardServiceError, match="does not have an MRN"):
        clipboard.copy_mrn(missing.id)


def test_copy_soap_marks_only_selected_day_after_success(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: START)
    days = HospitalDayService(factory)
    soap = SOAPService(factory)
    writer = RecordingClipboard()
    clipboard = ClipboardService(factory, writer)
    patient = patients.create(name="Milo", species="Feline")
    first = patient.hospital_days[0]
    second = days.create(patient.id, start_at=START + timedelta(days=1))
    document = soap.create(patient.id, first.id, author="Dr. Author")
    markdown = "# SOAP\n\nLine one\nLine two\n"
    soap.save_markdown(patient.id, first.id, document.id, markdown)

    assert clipboard.copy_soap(patient.id, first.id) == ("# SOAP\r\n\r\nLine one\r\nLine two\r\n")
    assert days.get(patient.id, first.id).emr_uploaded is True
    assert days.get(patient.id, second.id).emr_uploaded is False


def test_empty_or_failed_soap_copy_does_not_mark_uploaded(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: START)
    days = HospitalDayService(factory)
    soap = SOAPService(factory)
    patient = patients.create(name="Otis", species="Canine")
    day = patient.hospital_days[0]

    with pytest.raises(ClipboardServiceError, match="SOAP text is empty"):
        ClipboardService(factory, RecordingClipboard()).copy_soap(patient.id, day.id)
    document = soap.create(patient.id, day.id, author="Dr. Author")
    soap.save_markdown(patient.id, day.id, document.id, "Valid SOAP")
    with pytest.raises(ClipboardServiceError, match="could not be updated"):
        ClipboardService(factory, RecordingClipboard(fail=True)).copy_soap(patient.id, day.id)

    assert days.get(patient.id, day.id).emr_uploaded is False
