"""Instrumentation application use cases."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceStatus, DeviceType
from icu_patient_tracker.domain.exceptions import DomainError, EntityNotFoundError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase
from icu_patient_tracker.services.events import InstrumentationChanged
from icu_patient_tracker.services.exceptions import InvalidOperationError, ResourceNotFoundError


class InstrumentationService(ServiceBase):
    """Coordinate device placement, edits, discontinuation, and record correction."""

    def list(self, patient_id: UUID, day_id: UUID) -> tuple[Device, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            day = self._day(self._patient(unit_of_work, patient_id), day_id)
            return day.instrumentation.devices

    def replace_active_lines(
        self, patient_id: UUID, day_id: UUID, lines: tuple[str, ...]
    ) -> tuple[Device, ...]:
        """Replace active instrumentation from directly editable, one-per-line text."""
        normalized = tuple(line.strip() for line in lines if line.strip())
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                reconcile_instrumentation_lines(day, normalized)
                unit_of_work.patients.save(patient)
                active = day.instrumentation.active_devices
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(InstrumentationChanged(str(day_id), "lines_replaced"))
        return active

    def add(
        self,
        patient_id: UUID,
        day_id: UUID,
        *,
        device_type: DeviceType,
        anatomical_location: str,
        placed_at: datetime,
        size: str | None = None,
        notes: str = "",
    ) -> Device:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                device = Device(
                    patient_id,
                    day_id,
                    device_type,
                    anatomical_location,
                    placed_at,
                    size=size,
                    notes=notes,
                )
                day.instrumentation.add(device)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(InstrumentationChanged(str(device.id), "created"))
        return device

    def update(
        self,
        patient_id: UUID,
        day_id: UUID,
        device_id: UUID,
        *,
        anatomical_location: str | None = None,
        size: str | None = None,
        notes: str | None = None,
    ) -> Device:
        return self._mutate(
            patient_id,
            day_id,
            device_id,
            "updated",
            lambda device: device.update_details(
                anatomical_location=anatomical_location, size=size, notes=notes
            ),
        )

    def discontinue(
        self,
        patient_id: UUID,
        day_id: UUID,
        device_id: UUID,
        removed_at: datetime | None = None,
    ) -> Device:
        return self._mutate(
            patient_id,
            day_id,
            device_id,
            "discontinued",
            lambda device: device.mark_removed(removed_at),
        )

    def delete_record(self, patient_id: UUID, day_id: UUID, device_id: UUID) -> Device:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                device = self._day(patient, day_id).instrumentation.delete_record(device_id)
                unit_of_work.patients.save(patient)
        except EntityNotFoundError as error:
            raise ResourceNotFoundError(f"Device {device_id} was not found.") from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(InstrumentationChanged(str(device_id), "deleted"))
        return device

    def _mutate(
        self,
        patient_id: UUID,
        day_id: UUID,
        device_id: UUID,
        operation: str,
        action: Callable[[Device], None],
    ) -> Device:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                try:
                    device = self._day(patient, day_id).instrumentation.get(device_id)
                except EntityNotFoundError as error:
                    raise ResourceNotFoundError(f"Device {device_id} was not found.") from error
                action(device)
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(InstrumentationChanged(str(device_id), operation))
        return device


def device_line(device: Device) -> str:
    """Render one active device as the text clinicians edit and SOAP displays."""
    if device.device_type is DeviceType.OTHER:
        return device.anatomical_location.strip()
    label = {
        DeviceType.PERIPHERAL_IV_CATHETER: "Peripheral IVC",
        DeviceType.CENTRAL_VENOUS_CATHETER: "Central line",
        DeviceType.CHEST_TUBE: "Chest tube",
        DeviceType.URINARY_CATHETER: "Urinary catheter",
        DeviceType.ABDOMINAL_DRAIN: "Drain",
        DeviceType.FECAL_FOLEY: "Fecal foley",
    }.get(device.device_type, device.device_type.value.replace("_", " ").title())
    details = [device.anatomical_location.strip()]
    if device.size:
        details.append(f"size {device.size}")
    details.append(f"placed {device.placed_at.date().isoformat()}")
    return f"{label}: " + " | ".join(details)


_FREE_TEXT_OUTPUT_DEVICES: tuple[tuple[DeviceType, re.Pattern[str]], ...] = (
    (
        DeviceType.URINARY_CATHETER,
        re.compile(r"\b(?:urinary\s+catheter|foley(?:\s+catheter)?|u[\s-]?cath)\b", re.I),
    ),
    (
        DeviceType.CHEST_TUBE,
        re.compile(r"\b(?:chest\s+tube|thoracostomy\s+tube)\b", re.I),
    ),
    (
        DeviceType.ABDOMINAL_DRAIN,
        re.compile(r"\b(?:abdominal\s+(?:jp\s+)?drain|abdominal\s+jp)\b", re.I),
    ),
    (
        DeviceType.SUBCUTANEOUS_DRAIN,
        re.compile(r"\b(?:subcutaneous|subcut|sq)\s+drain\b", re.I),
    ),
)


def device_output_label(device: Device) -> str | None:
    """Return the Ins/Out row label for a qualifying active device."""
    line = device_line(device)
    device_type = device.device_type
    structured = device_type is not DeviceType.OTHER
    if device_type is DeviceType.OTHER:
        device_type = next(
            (candidate for candidate, pattern in _FREE_TEXT_OUTPUT_DEVICES if pattern.search(line)),
            DeviceType.OTHER,
        )
    if device_type is DeviceType.URINARY_CATHETER:
        return "Urinary catheter output" if structured else "UOP"
    if device_type is DeviceType.FECAL_FOLEY:
        return "Fecal foley output"
    if structured:
        return {
            DeviceType.CHEST_TUBE: "Chest tube output",
            DeviceType.ABDOMINAL_DRAIN: "Drain output",
            DeviceType.SUBCUTANEOUS_DRAIN: "Drain output",
        }.get(device_type)
    base = {
        DeviceType.CHEST_TUBE: "chest tube",
        DeviceType.ABDOMINAL_DRAIN: "abdominal drain",
        DeviceType.SUBCUTANEOUS_DRAIN: "subcutaneous drain",
    }.get(device_type)
    if base is None:
        return None
    qualifier = re.search(r"\b(left|right|bilateral)\b", line, re.I)
    number = re.search(r"(?:#|no\.?\s*)(\d+)\b", line, re.I)
    parts = [qualifier.group(1).title()] if qualifier else []
    parts.append(base)
    if number:
        parts.append(f"#{number.group(1)}")
    return " ".join(parts) + " output"


def reconcile_instrumentation_lines(day: HospitalDay, lines: tuple[str, ...]) -> None:
    """Reconcile free-text active lines while retaining untouched device identities."""
    instrumentation = day.instrumentation
    unused = list(instrumentation.active_devices)
    retained: list[Device] = []
    for line in lines:
        selected = next((device for device in unused if device_line(device) == line), None)
        if selected is not None:
            unused.remove(selected)
            retained.append(selected)
            continue
        if unused:
            selected = unused.pop(0)
            selected.device_type = DeviceType.OTHER
            selected.update_details(anatomical_location=line)
        else:
            selected = Device(
                instrumentation.patient_id,
                instrumentation.hospital_day_id,
                DeviceType.OTHER,
                line,
                datetime.now(UTC),
            )
            instrumentation.add(selected)
        retained.append(selected)
    for omitted in unused:
        instrumentation.delete_record(omitted.id)
    historical = [
        device for device in instrumentation.devices if device.status is DeviceStatus.REMOVED
    ]
    instrumentation._devices = [*retained, *historical]
