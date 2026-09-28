"""Safe, framework-independent clipboard exports for EMR handoff."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.events import EventPublisher, HospitalDayChanged
from icu_patient_tracker.services.exceptions import ClipboardServiceError

_MONTHS = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class ClipboardWriter(Protocol):
    """Minimal output port implemented by the desktop clipboard adapter."""

    def set_text(self, text: str) -> None: ...


class ClipboardService(ServiceBase):
    """Format canonical data and copy it without automating an external EMR."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        writer: ClipboardWriter,
        publisher: EventPublisher | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory, publisher)
        self._writer = writer

    def copy_chart(self, patient_id: UUID, day_id: UUID) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            patient = self._patient(unit_of_work, patient_id)
            day = self._day(patient, day_id)
            text = format_chart_export(patient, day)
        self._write(text)
        return text

    def copy_mrn(self, patient_id: UUID) -> str:
        """Copy one explicitly recorded MRN without adding labels or clinical content."""
        with self._unit_of_work_factory() as unit_of_work:
            patient = self._patient(unit_of_work, patient_id)
            mrn = patient.mrn or ""
        if not mrn:
            raise ClipboardServiceError("This patient does not have an MRN to copy.")
        self._write(mrn)
        return mrn

    def copy_patient_name(self, patient_id: UUID) -> str:
        """Copy the canonical patient name without labels."""
        with self._unit_of_work_factory() as unit_of_work:
            name = self._patient(unit_of_work, patient_id).name
        self._write(name)
        return name

    def copy_soap(self, patient_id: UUID, day_id: UUID) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            patient = self._patient(unit_of_work, patient_id)
            day = self._day(patient, day_id)
            document = day.soap_documents[-1] if day.soap_documents else None
            text = document.markdown_text if document is not None else ""
        if not text.strip():
            raise ClipboardServiceError("SOAP text is empty. Save the SOAP before copying it.")
        exported = normalize_clipboard_newlines(text)
        self._write(exported)
        self.set_emr_uploaded(patient_id, day_id, True)
        return exported

    def set_emr_uploaded(self, patient_id: UUID, day_id: UUID, uploaded: bool) -> HospitalDay:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                day.set_emr_uploaded(uploaded)
                unit_of_work.patients.save(patient)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(HospitalDayChanged(str(day_id), "emr_upload_state_changed"))
        return day

    def _write(self, text: str) -> None:
        if not text.strip():
            raise ClipboardServiceError("There is no content to copy.")
        try:
            self._writer.set_text(text)
        except Exception as error:
            raise ClipboardServiceError(
                "The clipboard could not be updated. Please try again."
            ) from error


def format_chart_export(patient: Patient, day: HospitalDay) -> str:
    """Reproduce the reference Copy Chart section order from canonical values."""
    label = (
        f"{_MONTHS[day.calendar_date.month]} {day.calendar_date.day:02d}, '{day.calendar_date:%y}"
    )
    if day.label:
        label = f"{label} | {day.label}"
    devices = "\n".join(_format_device(device) for device in day.instrumentation.active_devices)
    lines = (
        f"{patient.name} | {label}",
        "",
        "Treatment changes:",
        normalize_newlines(day.treatment_changes),
        "",
        "Physical exam:",
        normalize_newlines(day.physical_examination),
        "",
        "Devices/lines:",
        devices,
    )
    return normalize_clipboard_newlines("\n".join(lines))


def normalize_newlines(text: str) -> str:
    """Return LF-only text before composing an export."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_clipboard_newlines(text: str) -> str:
    """Use CRLF because some external record editors collapse LF-only blocks."""
    return normalize_newlines(text).replace("\n", "\r\n")


def _format_device(device: Device) -> str:
    label = device.device_type.value.replace("_", " ").title()
    details = [device.anatomical_location]
    if device.size:
        details.append(device.size)
    if device.notes:
        details.append(normalize_newlines(device.notes).replace("\n", " "))
    return f"{label}: {' | '.join(details)}"
