"""Transport-neutral synchronization request and response contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from icu_patient_tracker.persistence.sync_repository import SyncOperation

PushStatus = Literal["accepted", "conflict"]


@dataclass(frozen=True, slots=True)
class PushResult:
    operation_id: str
    status: PushStatus
    entity_type: str
    entity_id: str
    server_version: int
    change_sequence: int | None
    server_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ServerChange:
    sequence: int
    entity_type: str
    entity_id: str
    operation: str
    server_version: int
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ChangePage:
    changes: tuple[ServerChange, ...]
    next_cursor: int
    has_more: bool


class SyncGateway(Protocol):
    """Authenticated transport boundary used by the desktop sync coordinator."""

    def health(self) -> dict[str, object]: ...

    def push(
        self,
        *,
        workspace_id: str,
        device_id: str,
        operations: tuple[SyncOperation, ...],
    ) -> tuple[PushResult, ...]: ...

    def changes(
        self,
        *,
        workspace_id: str,
        after: int,
        limit: int = 100,
    ) -> ChangePage: ...
