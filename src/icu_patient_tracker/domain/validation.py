"""Small validation helpers shared by clinical domain objects."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from icu_patient_tracker.domain.exceptions import DomainValidationError


def require_text(value: str, field_name: str) -> str:
    """Return trimmed required text or raise an actionable validation error."""
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} must not be empty.")
    return normalized


def require_aware_datetime(value: datetime, field_name: str) -> None:
    """Reject ambiguous naive timestamps at a model boundary."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must include timezone information.")


def require_enum[EnumType: Enum](
    value: object, enum_type: type[EnumType], field_name: str
) -> EnumType:
    """Reject raw strings and values from the wrong controlled vocabulary."""
    if not isinstance(value, enum_type):
        raise DomainValidationError(f"{field_name} must be a valid {enum_type.__name__} value.")
    return value


def require_uuid(value: object, field_name: str) -> UUID:
    """Require an already-parsed stable UUID at domain boundaries."""
    if not isinstance(value, UUID):
        raise DomainValidationError(f"{field_name} must be a UUID.")
    return value


def validate_timestamp_order(
    start: datetime, end: datetime | None, start_name: str, end_name: str
) -> None:
    """Validate timezone awareness and chronological ordering."""
    require_aware_datetime(start, start_name)
    if end is None:
        return
    require_aware_datetime(end, end_name)
    if end < start:
        raise DomainValidationError(f"{end_name} must not be earlier than {start_name}.")


def validate_audit_timestamps(created_at: datetime, updated_at: datetime) -> None:
    """Validate timestamps shared by mutable persistent entities."""
    validate_timestamp_order(created_at, updated_at, "created_at", "updated_at")
