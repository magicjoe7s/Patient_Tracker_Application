"""Structured result text owned by one diagnostic task occurrence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from icu_patient_tracker.domain.validation import (
    require_text,
    require_uuid,
    validate_audit_timestamps,
)


@dataclass(slots=True)
class DiagnosticResult:
    """One lossless result linked to a diagnostic task and hospital-day context."""

    patient_id: UUID
    hospital_day_id: UUID
    task_id: UUID
    result_text: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.hospital_day_id = require_uuid(self.hospital_day_id, "hospital_day_id")
        self.task_id = require_uuid(self.task_id, "task_id")
        self.id = require_uuid(self.id, "id")
        self.result_text = require_text(self.result_text, "result_text")
        validate_audit_timestamps(self.created_at, self.updated_at)

    def update(self, result_text: str) -> None:
        """Replace the result without changing its stable task linkage."""
        self.result_text = require_text(result_text, "result_text")
        self.updated_at = datetime.now(UTC)
