"""Transient application-state scope and selection hierarchy tests."""

from uuid import uuid4

import pytest

from icu_patient_tracker.domain.application_state import ApplicationState
from icu_patient_tracker.domain.enums import Workspace
from icu_patient_tracker.domain.exceptions import DomainValidationError


def test_application_state_defaults_are_narrow_and_transient() -> None:
    state = ApplicationState()

    assert state.workspace is Workspace.CENSUS
    assert state.selected_patient_id is None
    assert not state.has_unsaved_changes
    assert state.active_filters == {}


def test_selection_hierarchy_clears_narrower_context() -> None:
    state = ApplicationState()
    day_id = uuid4()
    document_id = uuid4()
    first_patient_id = uuid4()
    second_patient_id = uuid4()
    state.select_patient(first_patient_id)
    state.select_hospital_day(day_id)
    state.select_document(document_id)
    state.select_patient(second_patient_id)

    assert state.selected_patient_id == second_patient_id
    assert state.selected_hospital_day_id is None
    assert state.active_document_id is None


def test_selection_requires_parent_context() -> None:
    state = ApplicationState()
    with pytest.raises(DomainValidationError, match="patient"):
        state.select_hospital_day(uuid4())
    with pytest.raises(DomainValidationError, match="hospital day"):
        state.select_document(uuid4())


def test_filters_and_dirty_state_are_explicit() -> None:
    state = ApplicationState()
    state.set_filter("status", "active")
    filters = state.active_filters
    filters["status"] = "modified externally"
    state.mark_dirty()

    assert state.active_filters == {"status": "active"}
    assert state.has_unsaved_changes
    state.mark_saved()
    state.clear_filters()
    assert not state.has_unsaved_changes
    assert state.active_filters == {}
