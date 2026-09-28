"""Database-agnostic transaction boundary for related repository operations."""

from __future__ import annotations

from types import TracebackType
from typing import Literal, Protocol, Self

from icu_patient_tracker.repositories.patient_repository import PatientRepository


class UnitOfWork(Protocol):
    """Coordinate repositories participating in one atomic transaction."""

    patients: PatientRepository

    def __enter__(self) -> Self:
        """Open a transaction and initialize participating repositories."""
        ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Commit success, roll back failure, and always close resources."""
        ...

    def commit(self) -> None:
        """Commit all staged repository operations atomically."""
        ...

    def rollback(self) -> None:
        """Discard all staged repository operations."""
        ...
