"""Patient validation and aggregate ownership tests."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from icu_patient_tracker.domain.enums import Acuity, AdmissionStatus, CodeStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    InvalidStateTransitionError,
    RelationshipError,
)
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient


def make_day(patient_id: UUID, day_number: int = 1) -> HospitalDay:
    """Create a valid calendar-based hospital day."""
    start = datetime(2026, 7, 20 + day_number - 1, 8, tzinfo=UTC)
    return HospitalDay(patient_id, start.date(), day_number, start)


def test_patient_creation_defaults_and_debug_representation() -> None:
    patient = Patient(" Bella ", "Canine", mrn=" 123456 ", body_weight_kg=12.5)

    assert patient.mrn == "123456"
    assert patient.name == "Bella"
    assert patient.admission_status is AdmissionStatus.ADMITTED
    assert patient.hospital_days == ()
    assert "Bella" in repr(patient)


def test_patient_uuid_is_generated_and_mrn_is_optional_and_correctable() -> None:
    first = Patient("Bella", "Unknown")
    second = Patient("Milo", "Feline")

    assert first.id != second.id
    assert first.mrn is None
    first.update_mrn("123456")
    first.update_species("Canine")
    assert first.mrn == "123456"
    assert first.species == "Canine"
    first.update_mrn(None)
    assert first.mrn is None


def test_patient_profile_replaces_owned_summary_and_preserves_uuid() -> None:
    patient = Patient("Bella", "Unknown", mrn="123456", blood_type="DEA 1 positive")
    patient_id = patient.id

    patient.update_profile(
        name="Bella Rose",
        species="Canine",
        mrn=None,
        one_line_summary="Post-operative monitoring",
        code_status=CodeStatus.DVM_DISCRETION,
        blood_type=None,
        acuity=Acuity.CRITICAL,
    )

    assert patient.id == patient_id
    assert patient.name == "Bella Rose"
    assert patient.species == "Canine"
    assert patient.mrn is None
    assert patient.one_line_summary == "Post-operative monitoring"
    assert patient.code_status is CodeStatus.DVM_DISCRETION
    assert patient.blood_type is None
    assert patient.acuity is Acuity.CRITICAL


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mrn": ""}, "mrn"),
        ({"body_weight_kg": 0}, "body_weight_kg"),
        ({"estimated_age_years": -1}, "estimated_age_years"),
        (
            {"date_of_birth": date(2020, 1, 1), "estimated_age_years": 6},
            "not both",
        ),
    ],
)
def test_patient_rejects_invalid_values(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {"mrn": "123456", "name": "Bella", "species": "Canine"}
    values.update(kwargs)
    with pytest.raises(DomainValidationError, match=message):
        Patient(**values)  # type: ignore[arg-type]


def test_patient_owns_unique_hospital_days() -> None:
    patient = Patient("Bella", "Canine", mrn="123456")
    first_day = make_day(patient.id)
    patient.add_hospital_day(first_day)

    assert patient.hospital_days == (first_day,)
    with pytest.raises(DuplicateEntityError):
        patient.add_hospital_day(make_day(patient.id))
    with pytest.raises(RelationshipError):
        patient.add_hospital_day(make_day(uuid4(), 2))


def test_patient_updates_weight_and_disposition() -> None:
    patient = Patient("Bella", "Canine", mrn="123456")
    patient.update_body_weight(13.2)
    patient.change_admission_status(AdmissionStatus.DISCHARGED)

    assert patient.body_weight_kg == 13.2
    assert patient.admission_status is AdmissionStatus.DISCHARGED


@pytest.mark.parametrize(
    "starting_status",
    [
        AdmissionStatus.DISCHARGED,
        AdmissionStatus.TRANSFERRED,
        AdmissionStatus.ARCHIVED,
    ],
)
def test_home_imc_and_archived_patients_can_be_readmitted(
    starting_status: AdmissionStatus,
) -> None:
    patient = Patient("Bella", "Canine", admission_status=starting_status)

    assert AdmissionStatus.ADMITTED in patient.allowed_admission_statuses
    patient.change_admission_status(AdmissionStatus.ADMITTED)

    assert patient.admission_status is AdmissionStatus.ADMITTED


def test_death_is_a_terminal_disposition() -> None:
    patient = Patient("Bella", "Canine", admission_status=AdmissionStatus.DECEASED)

    assert patient.allowed_admission_statuses == ()
    with pytest.raises(InvalidStateTransitionError):
        patient.change_admission_status(AdmissionStatus.ADMITTED)
