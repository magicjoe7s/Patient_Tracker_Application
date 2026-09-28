"""Shared transaction and aggregate lookup helpers for services."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.exceptions import PersistenceError, RecordNotFoundError
from icu_patient_tracker.repositories.unit_of_work import UnitOfWork
from icu_patient_tracker.services.events import EventPublisher, NullEventPublisher
from icu_patient_tracker.services.exceptions import (
    ApplicationPersistenceError,
    HospitalDayNotFoundError,
    PatientNotFoundError,
    TaskNotFoundError,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]


class ServiceBase:
    """Provide dependency injection and stable persistence-error translation."""

    def __init__(
        self, unit_of_work_factory: UnitOfWorkFactory, publisher: EventPublisher | None = None
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._publisher = publisher or NullEventPublisher()

    @staticmethod
    def _patient(unit_of_work: UnitOfWork, patient_id: UUID) -> Patient:
        try:
            return unit_of_work.patients.get(patient_id)
        except RecordNotFoundError as error:
            raise PatientNotFoundError(f"Patient {patient_id!s} was not found.") from error

    @staticmethod
    def _day(patient: Patient, day_id: UUID) -> HospitalDay:
        for day in patient.hospital_days:
            if day.id == day_id:
                return day
        raise HospitalDayNotFoundError(f"Hospital day {day_id} was not found.")

    @classmethod
    def _task(cls, patient: Patient, task_id: UUID) -> tuple[HospitalDay, Task]:
        for day in patient.hospital_days:
            for task in day.tasks:
                if task.id == task_id:
                    return day, task
        raise TaskNotFoundError(f"Task {task_id} was not found.")

    @staticmethod
    def _translate(error: PersistenceError) -> ApplicationPersistenceError:
        return ApplicationPersistenceError("The requested change could not be saved.")
