"""Patient aggregate application use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    CodeStatus,
    ReproductiveStatus,
    Sex,
)
from icu_patient_tracker.domain.exceptions import DomainError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.exceptions import (
    DuplicateIdentityError,
    PersistenceError,
    RecordNotFoundError,
)
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.events import EventPublisher, PatientChanged
from icu_patient_tracker.services.exceptions import InvalidOperationError, PatientNotFoundError


@dataclass(frozen=True, slots=True)
class PatientSummary:
    """Read model for census-like patient lists."""

    id: UUID
    mrn: str | None
    name: str
    species: str
    status: AdmissionStatus
    acuity: Acuity
    one_line_summary: str
    active_order: int


class PatientService(ServiceBase):
    """Coordinate patient lifecycle operations in one transaction each."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        publisher: EventPublisher | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory, publisher)
        self._now = now or (lambda: datetime.now().astimezone())

    def create(
        self,
        *,
        name: str,
        species: str,
        mrn: str | None = None,
        breed: str | None = None,
        sex: Sex = Sex.UNKNOWN,
        reproductive_status: ReproductiveStatus = ReproductiveStatus.UNKNOWN,
        date_of_birth: date | None = None,
        estimated_age_years: float | None = None,
        body_weight_kg: float | None = None,
        one_line_summary: str = "",
        code_status: CodeStatus = CodeStatus.FULL_CODE,
        blood_type: str | None = None,
        acuity: Acuity = Acuity.UNKNOWN,
    ) -> Patient:
        try:
            patient = Patient(
                name=name,
                species=species,
                mrn=mrn,
                breed=breed,
                sex=sex,
                reproductive_status=reproductive_status,
                date_of_birth=date_of_birth,
                estimated_age_years=estimated_age_years,
                body_weight_kg=body_weight_kg,
                one_line_summary=one_line_summary,
                code_status=code_status,
                blood_type=blood_type,
                acuity=acuity,
            )
            current_time = self._now()
            initial_start = datetime.combine(
                current_time.date(), time(hour=8), tzinfo=current_time.tzinfo
            )
            patient.add_hospital_day(
                HospitalDay(
                    patient_id=patient.id,
                    calendar_date=initial_start.date(),
                    day_number=1,
                    start_at=initial_start,
                    acuity=acuity,
                )
            )
            with self._unit_of_work_factory() as unit_of_work:
                active = (
                    existing.active_order
                    for existing in unit_of_work.patients.list()
                    if existing.admission_status is AdmissionStatus.ADMITTED
                )
                patient.set_active_order(max(active, default=-1) + 1)
                unit_of_work.patients.add(patient)
        except DuplicateIdentityError as error:
            raise InvalidOperationError(
                f"Patient MRN {mrn!r} already exists."
                if mrn is not None
                else "The generated patient identity already exists."
            ) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(PatientChanged(str(patient.id), "created"))
        return patient

    def get(self, patient_id: UUID) -> Patient:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                return self._patient(unit_of_work, patient_id)
        except PersistenceError as error:
            raise self._translate(error) from error

    def get_by_mrn(self, mrn: str) -> Patient:
        """Look up a patient by a recorded MRN without treating it as identity."""
        try:
            with self._unit_of_work_factory() as unit_of_work:
                return unit_of_work.patients.get_by_mrn(mrn)
        except RecordNotFoundError as error:
            raise PatientNotFoundError(f"Patient MRN {mrn!r} was not found.") from error
        except PersistenceError as error:
            raise self._translate(error) from error

    def list(self, *, status: AdmissionStatus | None = None) -> tuple[Patient, ...]:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patients = unit_of_work.patients.list()
        except PersistenceError as error:
            raise self._translate(error) from error
        selected = (
            patients
            if status is None
            else tuple(p for p in patients if p.admission_status is status)
        )
        return tuple(sorted(selected, key=lambda p: (p.active_order, p.name.casefold(), str(p.id))))

    def summaries(self, *, status: AdmissionStatus | None = None) -> tuple[PatientSummary, ...]:
        return tuple(
            PatientSummary(
                patient.id,
                patient.mrn,
                patient.name,
                patient.species,
                patient.admission_status,
                patient.acuity,
                patient.one_line_summary,
                patient.active_order,
            )
            for patient in self.list(status=status)
        )

    def update_summary(
        self,
        patient_id: UUID,
        *,
        name: str | None = None,
        one_line_summary: str | None = None,
        code_status: CodeStatus | None = None,
        blood_type: str | None = None,
        acuity: Acuity | None = None,
    ) -> Patient:
        def change(patient: Patient) -> None:
            if name is not None:
                patient.rename(name)
            patient.update_summary(
                one_line_summary=one_line_summary,
                code_status=code_status,
                blood_type=blood_type,
                acuity=acuity,
            )

        return self._change(patient_id, "updated", change)

    def update_mrn(self, patient_id: UUID, mrn: str | None) -> Patient:
        """Correct or clear an MRN while retaining immutable patient identity."""
        return self._change(patient_id, "mrn", lambda patient: patient.update_mrn(mrn))

    def update_species(self, patient_id: UUID, species: str) -> Patient:
        """Correct species, including an imported Unknown value."""
        return self._change(patient_id, "species", lambda patient: patient.update_species(species))

    def update_identity_details(
        self, patient_id: UUID, *, mrn: str | None, species: str
    ) -> Patient:
        """Correct MRN and species atomically without changing patient identity."""

        def change(patient: Patient) -> None:
            patient.update_mrn(mrn)
            patient.update_species(species)

        return self._change(patient_id, "identity-details", change)

    def update_profile(
        self,
        patient_id: UUID,
        *,
        name: str,
        species: str,
        mrn: str | None,
        one_line_summary: str,
        code_status: CodeStatus,
        blood_type: str | None,
        acuity: Acuity,
    ) -> Patient:
        """Persist all editable patient-summary fields in one transaction."""
        return self._change(
            patient_id,
            "profile",
            lambda patient: patient.update_profile(
                name=name,
                species=species,
                mrn=mrn,
                one_line_summary=one_line_summary,
                code_status=code_status,
                blood_type=blood_type,
                acuity=acuity,
            ),
        )

    def change_status(self, patient_id: UUID, status: AdmissionStatus) -> Patient:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                was_active = patient.admission_status is AdmissionStatus.ADMITTED
                try:
                    patient.change_admission_status(status)
                except DomainError as error:
                    raise InvalidOperationError(str(error)) from error
                if status is AdmissionStatus.ADMITTED:
                    active_orders = (
                        existing.active_order
                        for existing in unit_of_work.patients.list()
                        if existing.admission_status is AdmissionStatus.ADMITTED
                        and existing.id != patient_id
                    )
                    patient.set_active_order(max(active_orders, default=-1) + 1)
                unit_of_work.patients.save(patient)
                if was_active and status is not AdmissionStatus.ADMITTED:
                    active = sorted(
                        (
                            existing
                            for existing in unit_of_work.patients.list()
                            if existing.admission_status is AdmissionStatus.ADMITTED
                        ),
                        key=lambda existing: (
                            existing.active_order,
                            existing.name.casefold(),
                            str(existing.id),
                        ),
                    )
                    for position, existing in enumerate(active):
                        if existing.active_order != position:
                            existing.set_active_order(position)
                            unit_of_work.patients.save(existing)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(PatientChanged(str(patient_id), f"status:{status.value}"))
        return patient

    def archive(self, patient_id: UUID) -> Patient:
        return self.change_status(patient_id, AdmissionStatus.ARCHIVED)

    def reactivate(self, patient_id: UUID) -> Patient:
        return self.change_status(patient_id, AdmissionStatus.ADMITTED)

    def purge(self, patient_id: UUID) -> None:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                if patient.admission_status is not AdmissionStatus.ARCHIVED:
                    raise InvalidOperationError(
                        "Only an archived patient may be permanently deleted."
                    )
                unit_of_work.patients.delete(patient_id)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(PatientChanged(str(patient_id), "purged"))

    def reorder_active(self, ordered_ids: tuple[UUID, ...]) -> tuple[Patient, ...]:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                active = tuple(
                    p
                    for p in unit_of_work.patients.list()
                    if p.admission_status is AdmissionStatus.ADMITTED
                )
                if set(ordered_ids) != {p.id for p in active} or len(ordered_ids) != len(active):
                    raise InvalidOperationError(
                        "Active ordering must contain every admitted patient once."
                    )
                by_id = {patient.id: patient for patient in active}
                for position, patient_id in enumerate(ordered_ids):
                    by_id[patient_id].set_active_order(position)
                    unit_of_work.patients.save(by_id[patient_id])
                result = tuple(by_id[patient_id] for patient_id in ordered_ids)
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(PatientChanged("active-census", "reordered"))
        return result

    def _change(
        self, patient_id: UUID, operation: str, change: Callable[[Patient], None]
    ) -> Patient:
        try:
            with self._unit_of_work_factory() as unit_of_work:
                patient = self._patient(unit_of_work, patient_id)
                try:
                    change(patient)
                except DomainError as error:
                    raise InvalidOperationError(str(error)) from error
                unit_of_work.patients.save(patient)
        except DuplicateIdentityError as error:
            raise InvalidOperationError(
                "That MRN is already assigned to another patient."
            ) from error
        except PersistenceError as error:
            raise self._translate(error) from error
        self._publisher.publish(PatientChanged(str(patient_id), operation))
        return patient
