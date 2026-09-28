"""SQLAlchemy transaction boundary shared by persistence repositories."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Literal, Self

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from icu_patient_tracker.persistence.clinical_sync_repository import ClinicalSyncRepository
from icu_patient_tracker.persistence.exceptions import (
    ConstraintViolationError,
    TransactionError,
)
from icu_patient_tracker.persistence.sqlalchemy_patient_repository import (
    SqlAlchemyPatientRepository,
)
from icu_patient_tracker.persistence.sync_repository import SqlAlchemySyncRepository


class SqlAlchemyUnitOfWork:
    """Own one session and commit or roll back all participating repositories."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._active = False
        self._logger = logging.getLogger(__name__)
        self.patients: SqlAlchemyPatientRepository
        self.sync: SqlAlchemySyncRepository
        self.clinical_sync: ClinicalSyncRepository

    def __enter__(self) -> Self:
        """Open one transaction; the same unit cannot be nested or reused while active."""
        if self._active:
            raise TransactionError("A unit of work cannot start a competing nested transaction.")
        self._session = self._session_factory()
        self.patients = SqlAlchemyPatientRepository(self._session)
        self.sync = SqlAlchemySyncRepository(self._session)
        self.clinical_sync = ClinicalSyncRepository(self._session)
        self._active = True
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Commit success, roll back failure, and always close the session."""
        try:
            if exception_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            if self._session is not None:
                self._session.close()
            self._session = None
            self._active = False
        return False

    def commit(self) -> None:
        """Commit all staged changes and translate database failures."""
        session = self._require_session()
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            self._logger.exception("Transaction constraint failure; changes rolled back")
            raise ConstraintViolationError(
                "The transaction violates a persistence constraint."
            ) from error
        except SQLAlchemyError as error:
            session.rollback()
            self._logger.exception("Transaction failed; changes rolled back")
            raise TransactionError("The transaction could not be committed.") from error

    def rollback(self) -> None:
        """Discard all staged changes in the active transaction."""
        self._require_session().rollback()

    def _require_session(self) -> Session:
        if not self._active or self._session is None:
            raise TransactionError("The unit of work is not active.")
        return self._session
