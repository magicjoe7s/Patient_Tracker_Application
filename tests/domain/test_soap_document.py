"""SOAP section, reference, finalization, and amendment tests."""

from uuid import uuid4

import pytest

from icu_patient_tracker.domain.enums import (
    DocumentStatus,
    SOAPDocumentType,
    SOAPUpdateType,
)
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    FinalizedDocumentError,
)
from icu_patient_tracker.domain.soap_document import SOAPDocument


def make_document() -> SOAPDocument:
    return SOAPDocument(
        uuid4(),
        uuid4(),
        SOAPDocumentType.DAILY,
        "Dr. Rivera",
        subjective="Resting comfortably",
    )


def test_soap_document_preserves_sections_during_targeted_update() -> None:
    document = make_document()
    document.update_sections(objective="HR 100 bpm")

    assert document.subjective == "Resting comfortably"
    assert document.objective == "HR 100 bpm"
    assert document.status is DocumentStatus.DRAFT


def test_finalized_document_is_immutable() -> None:
    document = make_document()
    document.finalize()

    assert document.status is DocumentStatus.FINALIZED
    assert not document.is_editable
    with pytest.raises(FinalizedDocumentError):
        document.update_sections(plan="Discharge")


def test_amendment_is_new_editable_document_with_source_reference() -> None:
    original = make_document()
    original.finalize()
    amendment = original.create_amendment("Dr. Chen")

    assert amendment.id != original.id
    assert amendment.update_type is SOAPUpdateType.AMENDMENT
    assert amendment.amends_document_id == original.id
    assert amendment.is_editable
    amendment.finalize()
    assert amendment.status is DocumentStatus.AMENDED


def test_soap_document_rejects_duplicate_problem_references() -> None:
    document = make_document()
    problem_id = uuid4()
    with pytest.raises(DomainValidationError, match="duplicates"):
        document.set_problem_references((problem_id, problem_id))
