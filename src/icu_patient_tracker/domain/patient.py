"""Patient aggregate root and patient-level validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    CodeStatus,
    ReproductiveStatus,
    Sex,
)
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    InvalidStateTransitionError,
    RelationshipError,
)
from icu_patient_tracker.domain.validation import (
    require_enum,
    require_text,
    validate_audit_timestamps,
)

if TYPE_CHECKING:
    from icu_patient_tracker.domain.hospital_day import HospitalDay


@dataclass(slots=True)
class Patient:
    """A veterinary patient with immutable internal identity and optional MRN."""

    name: str
    species: str
    id: UUID = field(default_factory=uuid4)
    mrn: str | None = None
    breed: str | None = None
    sex: Sex = Sex.UNKNOWN
    reproductive_status: ReproductiveStatus = ReproductiveStatus.UNKNOWN
    date_of_birth: date | None = None
    estimated_age_years: float | None = None
    body_weight_kg: float | None = None
    one_line_summary: str = ""
    code_status: CodeStatus = CodeStatus.FULL_CODE
    blood_type: str | None = None
    acuity: Acuity = Acuity.UNKNOWN
    admission_status: AdmissionStatus = AdmissionStatus.ADMITTED
    active_order: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _hospital_days: list[HospitalDay] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("id must be a UUID.")
        if self.mrn is not None:
            self.mrn = require_text(self.mrn, "mrn")
        self.name = require_text(self.name, "name")
        self.species = require_text(self.species, "species")
        self.sex = require_enum(self.sex, Sex, "sex")
        self.reproductive_status = require_enum(
            self.reproductive_status, ReproductiveStatus, "reproductive_status"
        )
        self.admission_status = require_enum(
            self.admission_status, AdmissionStatus, "admission_status"
        )
        self.code_status = require_enum(self.code_status, CodeStatus, "code_status")
        self.acuity = require_enum(self.acuity, Acuity, "acuity")
        if self.blood_type is not None:
            self.blood_type = require_text(self.blood_type, "blood_type")
        if self.active_order < 0:
            raise DomainValidationError("active_order must not be negative.")
        if self.breed is not None:
            self.breed = require_text(self.breed, "breed")
        if self.date_of_birth is not None and self.date_of_birth > date.today():
            raise DomainValidationError("date_of_birth must not be in the future.")
        if self.date_of_birth is not None and self.estimated_age_years is not None:
            raise DomainValidationError("Provide date_of_birth or estimated_age_years, not both.")
        if self.estimated_age_years is not None and self.estimated_age_years < 0:
            raise DomainValidationError("estimated_age_years must not be negative.")
        self._validate_weight(self.body_weight_kg)
        validate_audit_timestamps(self.created_at, self.updated_at)

    @property
    def hospital_days(self) -> tuple[HospitalDay, ...]:
        """Return hospitalization contexts in chronological ICU order."""
        return tuple(
            sorted(
                self._hospital_days,
                key=lambda day: (day.calendar_date, day.start_at, str(day.id)),
            )
        )

    def add_hospital_day(self, hospital_day: HospitalDay) -> None:
        """Attach a uniquely numbered hospital day owned by this patient."""
        if hospital_day.patient_id != self.id:
            raise RelationshipError("Hospital day belongs to a different patient.")
        if any(day.id == hospital_day.id for day in self._hospital_days):
            raise DuplicateEntityError(f"Hospital day {hospital_day.id} is already attached.")
        if any(day.day_number == hospital_day.day_number for day in self._hospital_days):
            raise DuplicateEntityError(
                f"Hospital-day number {hospital_day.day_number} already exists."
            )
        if any(day.calendar_date == hospital_day.calendar_date for day in self._hospital_days):
            raise DuplicateEntityError(
                f"A hospital day already exists for {hospital_day.calendar_date.isoformat()}."
            )
        self._hospital_days.append(hospital_day)
        for position, day in enumerate(self.hospital_days, start=1):
            day.assign_day_number(position)
        self._touch()

    def update_body_weight(self, body_weight_kg: float | None) -> None:
        """Record a positive body weight or clear an unknown weight."""
        self._validate_weight(body_weight_kg)
        self.body_weight_kg = body_weight_kg
        self._touch()

    def change_admission_status(self, status: AdmissionStatus) -> None:
        """Record the patient's current hospitalization disposition."""
        target = require_enum(status, AdmissionStatus, "admission_status")
        if target is self.admission_status:
            raise InvalidStateTransitionError(f"Patient is already {self.admission_status.value}.")
        if target not in self.allowed_admission_statuses:
            raise InvalidStateTransitionError(
                f"Patient cannot transition from {self.admission_status.value} to {target.value}."
            )
        self.admission_status = target
        self._touch()

    @property
    def allowed_admission_statuses(self) -> tuple[AdmissionStatus, ...]:
        """Return valid next dispositions in controlled-vocabulary order."""
        transitions = {
            AdmissionStatus.ADMITTED: {
                AdmissionStatus.TRANSFERRED,
                AdmissionStatus.DISCHARGED,
                AdmissionStatus.DECEASED,
                AdmissionStatus.ARCHIVED,
            },
            AdmissionStatus.TRANSFERRED: {
                AdmissionStatus.ADMITTED,
                AdmissionStatus.ARCHIVED,
            },
            AdmissionStatus.DISCHARGED: {
                AdmissionStatus.ADMITTED,
                AdmissionStatus.ARCHIVED,
            },
            AdmissionStatus.ARCHIVED: {AdmissionStatus.ADMITTED},
            AdmissionStatus.DECEASED: set(),
        }
        allowed = transitions[self.admission_status]
        return tuple(status for status in AdmissionStatus if status in allowed)

    def rename(self, name: str) -> None:
        """Change the non-unique display name without changing patient identity."""
        self.name = require_text(name, "name")
        self._touch()

    def update_mrn(self, mrn: str | None) -> None:
        """Correct or clear the optional medical record number without changing identity."""
        self.mrn = require_text(mrn, "mrn") if mrn is not None else None
        self._touch()

    def update_species(self, species: str) -> None:
        """Correct the recorded species, including an imported Unknown value."""
        self.species = require_text(species, "species")
        self._touch()

    def update_summary(
        self,
        *,
        one_line_summary: str | None = None,
        code_status: CodeStatus | None = None,
        blood_type: str | None = None,
        acuity: Acuity | None = None,
    ) -> None:
        """Update supported patient-level summary fields."""
        if one_line_summary is not None:
            self.one_line_summary = one_line_summary.strip()
        if code_status is not None:
            self.code_status = require_enum(code_status, CodeStatus, "code_status")
        if blood_type is not None:
            self.blood_type = require_text(blood_type, "blood_type")
        if acuity is not None:
            self.acuity = require_enum(acuity, Acuity, "acuity")
        self._touch()

    def update_profile(
        self,
        *,
        name: str,
        species: str,
        mrn: str | None,
        one_line_summary: str,
        code_status: CodeStatus,
        blood_type: str | None,
        acuity: Acuity,
    ) -> None:
        """Replace the editable patient-owned summary while retaining UUID identity."""
        normalized_name = require_text(name, "name")
        normalized_species = require_text(species, "species")
        normalized_mrn = require_text(mrn, "mrn") if mrn is not None else None
        normalized_code_status = require_enum(code_status, CodeStatus, "code_status")
        normalized_blood_type = (
            require_text(blood_type, "blood_type") if blood_type is not None else None
        )
        normalized_acuity = require_enum(acuity, Acuity, "acuity")
        self.name = normalized_name
        self.species = normalized_species
        self.mrn = normalized_mrn
        self.one_line_summary = one_line_summary.strip()
        self.code_status = normalized_code_status
        self.blood_type = normalized_blood_type
        self.acuity = normalized_acuity
        self._touch()

    def set_active_order(self, active_order: int) -> None:
        """Assign deterministic presentation order among admitted patients."""
        if active_order < 0:
            raise DomainValidationError("active_order must not be negative.")
        self.active_order = active_order
        self._touch()

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    @staticmethod
    def _validate_weight(body_weight_kg: float | None) -> None:
        if body_weight_kg is not None and body_weight_kg <= 0:
            raise DomainValidationError("body_weight_kg must be greater than zero.")

    def __repr__(self) -> str:
        return (
            f"Patient(id={self.id!r}, mrn={self.mrn!r}, name={self.name!r}, "
            f"status={self.admission_status.value!r})"
        )
