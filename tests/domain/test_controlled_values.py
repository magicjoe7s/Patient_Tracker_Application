"""Runtime validation tests for controlled vocabulary and stable identifiers."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.application_state import ApplicationState
from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import CodeStatus, DeviceType, SOAPDocumentType
from icu_patient_tracker.domain.exceptions import DomainValidationError
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task


def test_models_reject_raw_strings_for_controlled_enums() -> None:
    timestamp = datetime(2026, 7, 20, 8, tzinfo=UTC)

    with pytest.raises(DomainValidationError, match="Sex"):
        Patient("Bella", "Canine", sex="female")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="HospitalDayStatus"):
        HospitalDay(uuid4(), timestamp.date(), 1, timestamp, status="open")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="ProblemStatus"):
        Problem(uuid4(), uuid4(), "Hypotension", status="active")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="DeviceType"):
        Device(uuid4(), uuid4(), "catheter", "Left", timestamp)  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="TaskCategory"):
        Task(uuid4(), uuid4(), "Recheck", category="clinical")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="ReminderStatus"):
        Reminder(uuid4(), uuid4(), uuid4(), timestamp, "Due", status="pending")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="SOAPDocumentType"):
        SOAPDocument(uuid4(), uuid4(), "daily", "Dr. Rivera")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="Workspace"):
        ApplicationState(workspace="census")  # type: ignore[arg-type]


def test_models_reject_unparsed_uuid_identifiers() -> None:
    timestamp = datetime(2026, 7, 20, 8, tzinfo=UTC)
    with pytest.raises(DomainValidationError, match="hospital_day_id"):
        Device(
            uuid4(),
            "not-a-uuid",  # type: ignore[arg-type]
            DeviceType.URINARY_CATHETER,
            "Urinary bladder",
            timestamp,
        )
    with pytest.raises(DomainValidationError, match="problem_id"):
        SOAPDocument(
            uuid4(),
            uuid4(),
            SOAPDocumentType.DAILY,
            "Dr. Rivera",
            problem_ids=("not-a-uuid",),  # type: ignore[arg-type]
        )


def test_legacy_code_status_vocabulary_is_preserved() -> None:
    assert CodeStatus.DVM_DISCRETION.value == "dvm_discretion"
    assert CodeStatus.DNR_ASSIST.value == "dnr_assist"
