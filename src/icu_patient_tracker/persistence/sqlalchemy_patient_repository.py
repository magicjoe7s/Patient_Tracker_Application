"""SQLAlchemy-backed patient aggregate repository."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.clinical_capture import capture
from icu_patient_tracker.persistence.exceptions import (
    ConstraintViolationError,
    DuplicateIdentityError,
    RecordNotFoundError,
    TransactionError,
)
from icu_patient_tracker.persistence.mapping import patient_from_record, patient_to_record
from icu_patient_tracker.persistence.orm_models import (
    HospitalDayRecord,
    InstrumentationRecord,
    PatientRecord,
    ProblemListRecord,
    SOAPDocumentRecord,
    TaskRecord,
)


class SqlAlchemyPatientRepository:
    """Persist complete patient aggregates without exposing SQLAlchemy to callers."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._logger = logging.getLogger(__name__)

    def add(self, patient: Patient) -> None:
        """Stage a new patient aggregate and detect identity conflicts immediately."""
        if self.exists(patient.id):
            raise DuplicateIdentityError(f"Patient {patient.id!s} already exists.")
        if patient.mrn is not None and self.mrn_exists(patient.mrn):
            raise DuplicateIdentityError(f"Patient MRN {patient.mrn!r} already exists.")
        try:
            self._session.add(patient_to_record(patient))
            self._session.flush()
            capture(self._session, patient.id, patient)
        except IntegrityError as error:
            self._session.rollback()
            raise ConstraintViolationError(
                "The patient aggregate violates a persistence constraint."
            ) from error
        except (SQLAlchemyError, ValueError) as error:
            self._session.rollback()
            raise TransactionError("The patient aggregate could not be added.") from error

    def get(self, patient_id: UUID) -> Patient:
        """Load a complete aggregate or report its absence explicitly."""
        try:
            record = self._session.scalars(self._aggregate_query(patient_id)).one_or_none()
        except SQLAlchemyError as error:
            raise TransactionError("The patient aggregate could not be loaded.") from error
        if record is None:
            raise RecordNotFoundError(f"Patient {patient_id!s} was not found.")
        try:
            return patient_from_record(record)
        except (ValueError, TypeError) as error:
            raise ConstraintViolationError(
                f"Stored patient {patient_id!s} contains invalid domain data."
            ) from error

    def get_by_mrn(self, mrn: str) -> Patient:
        """Load a complete aggregate by its optional unique MRN."""
        try:
            record = self._session.scalars(
                self._aggregate_query().where(PatientRecord.mrn == mrn)
            ).one_or_none()
        except SQLAlchemyError as error:
            raise TransactionError("The patient aggregate could not be loaded.") from error
        if record is None:
            raise RecordNotFoundError(f"Patient MRN {mrn!r} was not found.")
        return patient_from_record(record)

    def list(self) -> tuple[Patient, ...]:
        """Load all aggregates in deterministic display order."""
        statement = self._aggregate_query().order_by(PatientRecord.name, PatientRecord.id)
        try:
            records = self._session.scalars(statement).unique().all()
            return tuple(patient_from_record(record) for record in records)
        except SQLAlchemyError as error:
            raise TransactionError("Patient aggregates could not be listed.") from error
        except (ValueError, TypeError) as error:
            raise ConstraintViolationError(
                "A stored patient aggregate contains invalid domain data."
            ) from error

    def save(self, patient: Patient) -> None:
        """Replace an aggregate inside the surrounding transaction."""
        existing = self._session.get(PatientRecord, patient.id)
        if existing is None:
            raise RecordNotFoundError(f"Patient {patient.id!s} was not found.")
        if patient.mrn is not None and self.mrn_exists(patient.mrn, excluding=patient.id):
            raise DuplicateIdentityError(f"Patient MRN {patient.mrn!r} already exists.")
        try:
            replacement = patient_to_record(patient)
            self._session.delete(existing)
            self._session.flush()
            self._session.add(replacement)
            self._session.flush()
            capture(self._session, patient.id, patient)
        except IntegrityError as error:
            self._session.rollback()
            raise ConstraintViolationError(
                "The updated patient aggregate violates a persistence constraint."
            ) from error
        except (SQLAlchemyError, ValueError) as error:
            self._session.rollback()
            raise TransactionError("The patient aggregate could not be saved.") from error

    def delete(self, patient_id: UUID) -> None:
        """Delete a complete patient aggregate after an explicit caller request."""
        record = self._session.get(PatientRecord, patient_id)
        if record is None:
            raise RecordNotFoundError(f"Patient {patient_id!s} was not found.")
        try:
            self._session.delete(record)
            self._session.flush()
            capture(self._session, patient_id, None)
        except IntegrityError as error:
            self._session.rollback()
            raise ConstraintViolationError(
                "The patient aggregate cannot be deleted while referenced."
            ) from error
        except SQLAlchemyError as error:
            self._session.rollback()
            raise TransactionError("The patient aggregate could not be deleted.") from error

    def exists(self, patient_id: UUID) -> bool:
        """Check identity existence without loading the aggregate graph."""
        try:
            return self._session.get(PatientRecord, patient_id) is not None
        except SQLAlchemyError as error:
            raise TransactionError("Patient identity could not be checked.") from error

    def mrn_exists(self, mrn: str, *, excluding: UUID | None = None) -> bool:
        """Check optional MRN uniqueness without loading the aggregate graph."""
        statement = select(PatientRecord.id).where(PatientRecord.mrn == mrn)
        if excluding is not None:
            statement = statement.where(PatientRecord.id != excluding)
        try:
            return self._session.scalar(statement) is not None
        except SQLAlchemyError as error:
            raise TransactionError("Patient MRN uniqueness could not be checked.") from error

    @staticmethod
    def _aggregate_query(patient_id: UUID | None = None) -> Select[tuple[PatientRecord]]:
        statement = select(PatientRecord).options(
            selectinload(PatientRecord.hospital_days)
            .selectinload(HospitalDayRecord.problem_list)
            .selectinload(ProblemListRecord.problems),
            selectinload(PatientRecord.hospital_days)
            .selectinload(HospitalDayRecord.instrumentation)
            .selectinload(InstrumentationRecord.devices),
            selectinload(PatientRecord.hospital_days)
            .selectinload(HospitalDayRecord.tasks)
            .selectinload(TaskRecord.reminder),
            selectinload(PatientRecord.hospital_days)
            .selectinload(HospitalDayRecord.soap_documents)
            .selectinload(SOAPDocumentRecord.problem_links),
        )
        return (
            statement.where(PatientRecord.id == patient_id) if patient_id is not None else statement
        )
