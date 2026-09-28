"""Database-agnostic contract for patient aggregate persistence."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from icu_patient_tracker.domain.patient import Patient


class PatientRepository(Protocol):
    """Persist and retrieve complete patient aggregates by immutable UUID."""

    def add(self, patient: Patient) -> None:
        """Stage a new patient aggregate for persistence."""
        ...

    def get(self, patient_id: UUID) -> Patient:
        """Load one complete patient aggregate or raise RecordNotFoundError."""
        ...

    def get_by_mrn(self, mrn: str) -> Patient:
        """Load one aggregate by its optional unique MRN."""
        ...

    def list(self) -> tuple[Patient, ...]:
        """Load every patient aggregate in deterministic display order."""
        ...

    def save(self, patient: Patient) -> None:
        """Replace the stored representation of an existing aggregate atomically."""
        ...

    def delete(self, patient_id: UUID) -> None:
        """Delete an aggregate explicitly or raise RecordNotFoundError."""
        ...

    def exists(self, patient_id: UUID) -> bool:
        """Return whether an immutable patient identity exists."""
        ...

    def mrn_exists(self, mrn: str, *, excluding: UUID | None = None) -> bool:
        """Return whether an MRN belongs to another patient."""
        ...
