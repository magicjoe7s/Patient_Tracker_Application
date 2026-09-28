"""Structured SOAP content and immutable finalization behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import (
    DocumentStatus,
    SOAPDocumentType,
    SOAPUpdateType,
)
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    FinalizedDocumentError,
)
from icu_patient_tracker.domain.validation import (
    require_aware_datetime,
    require_enum,
    require_text,
    require_uuid,
    validate_audit_timestamps,
)


@dataclass(slots=True)
class SOAPDocument:
    """A section-preserving clinical document owned by one hospital day."""

    patient_id: UUID
    hospital_day_id: UUID
    document_type: SOAPDocumentType
    author: str
    update_type: SOAPUpdateType = SOAPUpdateType.ORIGINAL
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    markdown_text: str = ""
    problem_ids: tuple[UUID, ...] = ()
    status: DocumentStatus = DocumentStatus.DRAFT
    amends_document_id: UUID | None = None
    finalized_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.author = require_text(self.author, "author")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.id = require_uuid(self.id, "id")
        self.document_type = require_enum(self.document_type, SOAPDocumentType, "document_type")
        self.update_type = require_enum(self.update_type, SOAPUpdateType, "update_type")
        self.status = require_enum(self.status, DocumentStatus, "status")
        if self.amends_document_id is not None:
            self.amends_document_id = require_uuid(self.amends_document_id, "amends_document_id")
        for problem_id in self.problem_ids:
            require_uuid(problem_id, "problem_id")
        validate_audit_timestamps(self.created_at, self.updated_at)
        if len(self.problem_ids) != len(set(self.problem_ids)):
            raise DomainValidationError("problem_ids must not contain duplicates.")
        if self.update_type is SOAPUpdateType.ORIGINAL and self.amends_document_id is not None:
            raise DomainValidationError("An original document cannot amend another document.")
        if self.update_type is not SOAPUpdateType.ORIGINAL and self.amends_document_id is None:
            raise DomainValidationError("An amendment or correction must reference its source.")
        if self.status is DocumentStatus.DRAFT and self.finalized_at is not None:
            raise DomainValidationError("A draft document cannot have finalized_at.")
        if self.status is not DocumentStatus.DRAFT and self.finalized_at is None:
            raise DomainValidationError("A finalized document requires finalized_at.")
        if self.finalized_at is not None:
            require_aware_datetime(self.finalized_at, "finalized_at")

    @property
    def is_editable(self) -> bool:
        """Only drafts may be modified in place."""
        return self.status is DocumentStatus.DRAFT

    def update_sections(
        self,
        *,
        subjective: str | None = None,
        objective: str | None = None,
        assessment: str | None = None,
        plan: str | None = None,
    ) -> None:
        """Update explicitly supplied SOAP sections while preserving all others."""
        self._ensure_editable()
        if subjective is not None:
            self.subjective = subjective
        if objective is not None:
            self.objective = objective
        if assessment is not None:
            self.assessment = assessment
        if plan is not None:
            self.plan = plan
        self.updated_at = datetime.now(UTC)

    def update_markdown(self, markdown_text: str) -> None:
        """Replace the lossless canonical Markdown without interpreting unknown content."""
        self._ensure_editable()
        self.markdown_text = markdown_text
        self.updated_at = datetime.now(UTC)

    def set_problem_references(self, problem_ids: tuple[UUID, ...]) -> None:
        """Replace problem references while preventing duplicate membership."""
        self._ensure_editable()
        for problem_id in problem_ids:
            require_uuid(problem_id, "problem_id")
        if len(problem_ids) != len(set(problem_ids)):
            raise DomainValidationError("problem_ids must not contain duplicates.")
        self.problem_ids = problem_ids
        self.updated_at = datetime.now(UTC)

    def finalize(self, finalized_at: datetime | None = None) -> None:
        """Make this document immutable for audit-safe clinical history."""
        self._ensure_editable()
        timestamp = finalized_at or datetime.now(UTC)
        require_aware_datetime(timestamp, "finalized_at")
        if timestamp < self.created_at:
            raise DomainValidationError("finalized_at must not precede created_at.")
        self.finalized_at = timestamp
        self.status = (
            DocumentStatus.FINALIZED
            if self.update_type is SOAPUpdateType.ORIGINAL
            else DocumentStatus.AMENDED
        )
        self.updated_at = datetime.now(UTC)

    def create_amendment(self, author: str) -> SOAPDocument:
        """Create a new editable document without altering this finalized record."""
        if self.status not in {DocumentStatus.FINALIZED, DocumentStatus.AMENDED}:
            raise FinalizedDocumentError("Only an immutable document can be amended.")
        return SOAPDocument(
            patient_id=self.patient_id,
            hospital_day_id=self.hospital_day_id,
            document_type=self.document_type,
            author=author,
            update_type=SOAPUpdateType.AMENDMENT,
            subjective=self.subjective,
            objective=self.objective,
            assessment=self.assessment,
            plan=self.plan,
            markdown_text=self.markdown_text,
            problem_ids=self.problem_ids,
            amends_document_id=self.id,
        )

    def _ensure_editable(self) -> None:
        if not self.is_editable:
            raise FinalizedDocumentError("Finalized SOAP documents are immutable.")

    def __repr__(self) -> str:
        return (
            f"SOAPDocument(id={self.id!r}, type={self.document_type.value!r}, "
            f"status={self.status.value!r})"
        )
