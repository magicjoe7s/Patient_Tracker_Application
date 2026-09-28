"""Hospital-day navigation, creation, and structured-content use cases."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import Acuity
from icu_patient_tracker.domain.exceptions import DomainError, DuplicateEntityError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.persistence.exceptions import PersistenceError
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.events import EventPublisher, HospitalDayChanged
from icu_patient_tracker.services.exceptions import (
    DuplicateHospitalDayError,
    HospitalDayNotFoundError,
    InvalidOperationError,
)
from icu_patient_tracker.services.problem_service import ProblemCarryForwardPolicy
from icu_patient_tracker.services.task_service import TaskCarryForwardPolicy


class HospitalDayService(ServiceBase):
    """Coordinate one atomic change to a patient-owned hospital day."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        publisher: EventPublisher | None = None,
        *,
        carry_policy: TaskCarryForwardPolicy | None = None,
        problem_carry_policy: ProblemCarryForwardPolicy | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory, publisher)
        self._carry_policy = carry_policy or TaskCarryForwardPolicy()
        self._problem_carry_policy = problem_carry_policy or ProblemCarryForwardPolicy()

    def create(
        self,
        patient_id: UUID,
        *,
        start_at: datetime,
        label: str | None = None,
        carry_tasks: bool = True,
        carry_devices: bool = True,
        carry_problems: bool = True,
    ) -> HospitalDay:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                existing_days = patient.hospital_days
                previous = next(
                    (day for day in reversed(existing_days) if day.calendar_date < start_at.date()),
                    None,
                )
                carry_source = (
                    previous
                    if existing_days and start_at.date() > existing_days[-1].calendar_date
                    else None
                )
                day = HospitalDay(
                    patient_id=patient_id,
                    calendar_date=start_at.date(),
                    day_number=max((existing.day_number for existing in existing_days), default=0)
                    + 1,
                    start_at=start_at,
                    label=label,
                    # Daily acuity is reassessed rather than carried from the prior day.
                    acuity=Acuity.UNKNOWN,
                    overnight_resident=(carry_source.overnight_resident if carry_source else ""),
                    faculty=(carry_source.faculty if carry_source else ""),
                )
                if carry_source is not None and carry_tasks:
                    self._carry_policy.create_occurrences(carry_source, day)
                if carry_source is not None and carry_problems:
                    self._problem_carry_policy.create_occurrences(carry_source, day)
                if carry_source is not None and carry_devices:
                    for source in carry_source.instrumentation.active_devices:
                        day.instrumentation.add(
                            Device(
                                patient_id=patient_id,
                                hospital_day_id=day.id,
                                device_type=source.device_type,
                                anatomical_location=source.anatomical_location,
                                placed_at=source.placed_at,
                                size=source.size,
                                notes=source.notes,
                                complications=source.complications,
                            )
                        )
                patient.add_hospital_day(day)
                unit_of_work.patients.save(patient)
        except DuplicateEntityError as error:
            raise DuplicateHospitalDayError(str(error)) from error
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(HospitalDayChanged(str(day.id), "created"))
        return day

    def get(self, patient_id: UUID, day_id: UUID) -> HospitalDay:
        with self._unit_of_work_factory() as unit_of_work:
            return self._day(self._patient(unit_of_work, patient_id), day_id)

    def list(self, patient_id: UUID) -> tuple[HospitalDay, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return self._patient(unit_of_work, patient_id).hospital_days

    def update(self, patient_id: UUID, day_id: UUID, **changes: object) -> HospitalDay:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                day = self._day(patient, day_id)
                if "label" in changes:
                    label = changes.pop("label")
                    if label is not None and not isinstance(label, str):
                        raise InvalidOperationError("label must be text or None.")
                    day.replace_label(label)
                day.update_clinical_content(**changes)  # type: ignore[arg-type]
                unit_of_work.patients.save(patient)
        except DomainError as error:
            raise InvalidOperationError(str(error)) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(HospitalDayChanged(str(day_id), "updated"))
        return day

    def adjacent(
        self, patient_id: UUID, day_id: UUID
    ) -> tuple[HospitalDay | None, HospitalDay | None]:
        days = self.list(patient_id)
        for index, day in enumerate(days):
            if day.id == day_id:
                previous = days[index - 1] if index else None
                following = days[index + 1] if index + 1 < len(days) else None
                return previous, following
        raise HospitalDayNotFoundError(f"Hospital day {day_id} was not found.")
