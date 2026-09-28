"""Narrow transient selection, workspace, filter, and dirty state."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from icu_patient_tracker.domain.enums import Workspace
from icu_patient_tracker.domain.exceptions import DomainValidationError
from icu_patient_tracker.domain.validation import require_enum, require_text, require_uuid


@dataclass(slots=True)
class ApplicationState:
    """Transient navigation state; it never owns persistent clinical records."""

    selected_patient_id: UUID | None = None
    selected_hospital_day_id: UUID | None = None
    active_document_id: UUID | None = None
    workspace: Workspace = Workspace.CENSUS
    has_unsaved_changes: bool = False
    _active_filters: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.workspace = require_enum(self.workspace, Workspace, "workspace")
        if self.selected_patient_id is not None:
            self.selected_patient_id = require_uuid(self.selected_patient_id, "selected_patient_id")
        if self.selected_hospital_day_id is not None and self.selected_patient_id is None:
            raise DomainValidationError("A selected hospital day requires a selected patient.")
        if self.selected_hospital_day_id is not None:
            self.selected_hospital_day_id = require_uuid(
                self.selected_hospital_day_id, "selected_hospital_day_id"
            )
        if self.active_document_id is not None and self.selected_hospital_day_id is None:
            raise DomainValidationError("An active document requires a selected hospital day.")
        if self.active_document_id is not None:
            self.active_document_id = require_uuid(self.active_document_id, "active_document_id")
        initial_filters = dict(self._active_filters)
        self._active_filters.clear()
        for name, value in initial_filters.items():
            self.set_filter(name, value)

    @property
    def active_filters(self) -> dict[str, str]:
        """Return a copy so callers cannot bypass filter validation."""
        return dict(self._active_filters)

    def select_patient(self, patient_id: UUID | None) -> None:
        """Change patient context and clear all narrower selections."""
        self.selected_patient_id = (
            require_uuid(patient_id, "patient_id") if patient_id is not None else None
        )
        self.selected_hospital_day_id = None
        self.active_document_id = None

    def select_hospital_day(self, hospital_day_id: UUID | None) -> None:
        """Change hospital-day context within the current patient."""
        if hospital_day_id is not None and self.selected_patient_id is None:
            raise DomainValidationError("Select a patient before selecting a hospital day.")
        self.selected_hospital_day_id = (
            require_uuid(hospital_day_id, "hospital_day_id")
            if hospital_day_id is not None
            else None
        )
        self.active_document_id = None

    def select_document(self, document_id: UUID | None) -> None:
        """Change active document within the current hospital day."""
        if document_id is not None and self.selected_hospital_day_id is None:
            raise DomainValidationError("Select a hospital day before selecting a document.")
        self.active_document_id = (
            require_uuid(document_id, "document_id") if document_id is not None else None
        )

    def set_filter(self, name: str, value: str) -> None:
        """Set one non-empty transient filter using a stable key."""
        normalized_name = require_text(name, "filter name")
        self._active_filters[normalized_name] = require_text(value, "filter value")

    def clear_filters(self) -> None:
        """Remove all transient filters."""
        self._active_filters.clear()

    def mark_dirty(self) -> None:
        """Indicate that persistent state differs from its last saved state."""
        self.has_unsaved_changes = True

    def mark_saved(self) -> None:
        """Indicate that persistent state has been saved successfully."""
        self.has_unsaved_changes = False
