"""Device-local synchronization state and transactional outbox persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from icu_patient_tracker.persistence.exceptions import RecordNotFoundError
from icu_patient_tracker.persistence.orm_models import (
    SyncConflictRecord,
    SyncDeviceRecord,
    SyncOutboxRecord,
    SyncStateRecord,
)

SyncOperationKind = Literal["upsert", "delete"]
SyncStatus = Literal["disabled", "synced", "syncing", "offline", "conflict", "auth_required"]


@dataclass(frozen=True, slots=True)
class SyncDevice:
    """Stable local installation identity and its accepted pull cursor."""

    id: UUID
    display_name: str
    last_pull_sequence: int
    created_at: datetime
    last_seen_at: datetime | None


@dataclass(frozen=True, slots=True)
class SyncOperation:
    """One idempotent mutation waiting for server acknowledgement."""

    operation_id: UUID
    entity_type: str
    entity_id: UUID
    operation: SyncOperationKind
    base_server_version: int
    payload: dict[str, object]
    created_at: datetime
    attempt_count: int
    next_attempt_at: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class SyncConflict:
    """Both versions of a stale mutation retained for explicit resolution."""

    id: UUID
    operation_id: UUID
    entity_type: str
    entity_id: UUID
    local_payload: dict[str, object]
    server_payload: dict[str, object]
    server_version: int
    detected_at: datetime
    resolution: str | None
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class SyncState:
    """Current local synchronization account and status summary."""

    device_id: UUID
    workspace_id: UUID | None
    last_push_at: datetime | None
    last_pull_at: datetime | None
    status: str


class SqlAlchemySyncRepository:
    """Persist sync metadata inside the clinical unit-of-work transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_device(
        self,
        display_name: str,
        *,
        device_id: UUID | None = None,
        now: datetime | None = None,
    ) -> SyncDevice:
        """Return the existing installation identity or create it exactly once."""
        normalized_name = " ".join(display_name.split())
        if not normalized_name:
            raise ValueError("Device display name must not be empty.")
        timestamp = _aware(now)
        state = self._session.get(SyncStateRecord, 1)
        record = self._session.get(SyncDeviceRecord, state.device_id) if state is not None else None
        if record is None:
            existing = self._session.scalars(
                select(SyncDeviceRecord).order_by(SyncDeviceRecord.created_at)
            ).first()
            record = existing or SyncDeviceRecord(
                id=device_id or uuid4(),
                display_name=normalized_name,
                last_pull_sequence=0,
                created_at=timestamp,
                last_seen_at=timestamp,
            )
            if existing is None:
                self._session.add(record)
            self._session.add(
                SyncStateRecord(
                    id=1,
                    device_id=record.id,
                    workspace_id=None,
                    last_push_at=None,
                    last_pull_at=None,
                    status="disabled",
                )
            )
        else:
            record.last_seen_at = timestamp
        self._session.flush()
        return _device(record)

    def state(self) -> SyncState | None:
        record = self._session.get(SyncStateRecord, 1)
        return _state(record) if record is not None else None

    def device(self, device_id: UUID) -> SyncDevice:
        """Return a previously initialized synchronization device."""
        record = self._session.get(SyncDeviceRecord, device_id)
        if record is None:
            raise RecordNotFoundError("Synchronization device was not found.")
        return _device(record)

    def update_state(
        self,
        *,
        status: SyncStatus,
        workspace_id: UUID | None = None,
        last_push_at: datetime | None = None,
        last_pull_at: datetime | None = None,
    ) -> SyncState:
        record = self._session.get(SyncStateRecord, 1)
        if record is None:
            raise RecordNotFoundError("Synchronization state has not been initialized.")
        record.status = status
        if workspace_id is not None:
            record.workspace_id = workspace_id
        if last_push_at is not None:
            record.last_push_at = _aware(last_push_at)
        if last_pull_at is not None:
            record.last_pull_at = _aware(last_pull_at)
        self._session.flush()
        return _state(record)

    def advance_pull_cursor(self, device_id: UUID, sequence: int) -> SyncDevice:
        if sequence < 0:
            raise ValueError("Pull sequence must not be negative.")
        record = self._session.get(SyncDeviceRecord, device_id)
        if record is None:
            raise RecordNotFoundError("Synchronization device was not found.")
        if sequence < record.last_pull_sequence:
            raise ValueError("Pull cursor cannot move backwards.")
        record.last_pull_sequence = sequence
        self._session.flush()
        return _device(record)

    def queue(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        operation: SyncOperationKind,
        base_server_version: int,
        payload: Mapping[str, object],
        operation_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> SyncOperation:
        normalized_type = entity_type.strip().casefold()
        if not normalized_type or len(normalized_type) > 64:
            raise ValueError("Sync entity type must contain at most 64 characters.")
        if operation not in {"upsert", "delete"}:
            raise ValueError("Sync operation must be upsert or delete.")
        if base_server_version < 0:
            raise ValueError("Base server version must not be negative.")
        record = SyncOutboxRecord(
            operation_id=operation_id or uuid4(),
            entity_type=normalized_type,
            entity_id=entity_id,
            operation=operation,
            base_server_version=base_server_version,
            payload_json=_dump_payload(payload),
            created_at=_aware(created_at),
            attempt_count=0,
            next_attempt_at=None,
            last_error=None,
        )
        self._session.add(record)
        self._session.flush()
        return _operation(record)

    def pending(
        self, *, now: datetime | None = None, limit: int = 100
    ) -> tuple[SyncOperation, ...]:
        if limit < 1:
            raise ValueError("Pending operation limit must be at least one.")
        timestamp = _aware(now)
        records = self._session.scalars(
            select(SyncOutboxRecord)
            .where(
                or_(
                    SyncOutboxRecord.next_attempt_at.is_(None),
                    SyncOutboxRecord.next_attempt_at <= timestamp,
                ),
                ~SyncOutboxRecord.operation_id.in_(
                    select(SyncConflictRecord.operation_id).where(
                        SyncConflictRecord.resolution.is_(None)
                    )
                ),
            )
            .order_by(SyncOutboxRecord.created_at, SyncOutboxRecord.operation_id)
            .limit(limit)
        ).all()
        return tuple(_operation(record) for record in records)

    def mark_failed(
        self,
        operation_id: UUID,
        *,
        error: str,
        retry_at: datetime,
    ) -> SyncOperation:
        record = self._outbox(operation_id)
        normalized_error = " ".join(error.split())
        if not normalized_error:
            raise ValueError("Sync failure must include an error description.")
        record.attempt_count += 1
        record.last_error = normalized_error
        record.next_attempt_at = _aware(retry_at)
        self._session.flush()
        return _operation(record)

    def acknowledge(self, operation_id: UUID) -> None:
        self._session.delete(self._outbox(operation_id))
        self._session.flush()

    def operation(self, operation_id: UUID) -> SyncOperation:
        return _operation(self._outbox(operation_id))

    def record_conflict(
        self,
        operation_id: UUID,
        *,
        server_payload: Mapping[str, object],
        server_version: int,
        detected_at: datetime | None = None,
    ) -> SyncConflict:
        if server_version < 0:
            raise ValueError("Server version must not be negative.")
        operation = self._outbox(operation_id)
        record = SyncConflictRecord(
            id=uuid4(),
            operation_id=operation.operation_id,
            entity_type=operation.entity_type,
            entity_id=operation.entity_id,
            local_payload_json=operation.payload_json,
            server_payload_json=_dump_payload(server_payload),
            server_version=server_version,
            detected_at=_aware(detected_at),
            resolution=None,
            resolved_at=None,
        )
        self._session.add(record)
        self._session.flush()
        return _conflict(record)

    def unresolved_conflicts(self) -> tuple[SyncConflict, ...]:
        records = self._session.scalars(
            select(SyncConflictRecord)
            .where(SyncConflictRecord.resolution.is_(None))
            .order_by(SyncConflictRecord.detected_at)
        ).all()
        return tuple(_conflict(record) for record in records)

    def resolve_conflict(
        self,
        conflict_id: UUID,
        *,
        resolution: Literal["keep_local", "keep_server", "combined"],
        resolved_at: datetime | None = None,
    ) -> SyncConflict:
        record = self._session.get(SyncConflictRecord, conflict_id)
        if record is None:
            raise RecordNotFoundError("Synchronization conflict was not found.")
        record.resolution = resolution
        record.resolved_at = _aware(resolved_at)
        self._session.flush()
        return _conflict(record)

    def _outbox(self, operation_id: UUID) -> SyncOutboxRecord:
        record = self._session.get(SyncOutboxRecord, operation_id)
        if record is None:
            raise RecordNotFoundError("Synchronization operation was not found.")
        return record


def _aware(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Synchronization timestamps must include timezone information.")
    return timestamp


def _dump_payload(payload: Mapping[str, object]) -> str:
    try:
        return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("Synchronization payload must be JSON serializable.") from error


def _load_payload(payload_json: str) -> dict[str, object]:
    value = json.loads(payload_json)
    if not isinstance(value, dict):
        raise ValueError("Stored synchronization payload must be a JSON object.")
    return value


def _device(record: SyncDeviceRecord) -> SyncDevice:
    return SyncDevice(
        id=record.id,
        display_name=record.display_name,
        last_pull_sequence=record.last_pull_sequence,
        created_at=record.created_at,
        last_seen_at=record.last_seen_at,
    )


def _operation(record: SyncOutboxRecord) -> SyncOperation:
    operation: SyncOperationKind
    if record.operation == "upsert":
        operation = "upsert"
    elif record.operation == "delete":
        operation = "delete"
    else:
        raise ValueError("Stored synchronization operation is not recognized.")
    return SyncOperation(
        operation_id=record.operation_id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        operation=operation,
        base_server_version=record.base_server_version,
        payload=_load_payload(record.payload_json),
        created_at=record.created_at,
        attempt_count=record.attempt_count,
        next_attempt_at=record.next_attempt_at,
        last_error=record.last_error,
    )


def _conflict(record: SyncConflictRecord) -> SyncConflict:
    return SyncConflict(
        id=record.id,
        operation_id=record.operation_id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        local_payload=_load_payload(record.local_payload_json),
        server_payload=_load_payload(record.server_payload_json),
        server_version=record.server_version,
        detected_at=record.detected_at,
        resolution=record.resolution,
        resolved_at=record.resolved_at,
    )


def _state(record: SyncStateRecord) -> SyncState:
    return SyncState(
        device_id=record.device_id,
        workspace_id=record.workspace_id,
        last_push_at=record.last_push_at,
        last_pull_at=record.last_pull_at,
        status=record.status,
    )
