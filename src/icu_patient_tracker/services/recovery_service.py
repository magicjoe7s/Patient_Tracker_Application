"""Application policy for debounced, conflict-aware editor recovery snapshots."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from icu_patient_tracker.persistence.exceptions import RecoveryError
from icu_patient_tracker.persistence.recovery import (
    RecoveryEntry,
    RecoverySnapshot,
    RecoveryStore,
)
from icu_patient_tracker.services.events import (
    EventPublisher,
    NullEventPublisher,
    PersistenceLifecycleEvent,
)
from icu_patient_tracker.services.exceptions import RecoveryServiceError

__all__ = ["RecoveryService", "RecoverySnapshot"]


class RecoveryService:
    """Stage one-context drafts and reject silent recovery over changed canonical values."""

    def __init__(
        self,
        store: RecoveryStore,
        publisher: EventPublisher | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        debounce_seconds: float = 2.0,
    ) -> None:
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must not be negative.")
        self._store = store
        self._publisher = publisher or NullEventPublisher()
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._debounce_seconds = debounce_seconds
        self._staged: RecoverySnapshot | None = None
        self._staged_context: tuple[UUID, UUID | None] | None = None
        self._staged_values: dict[
            str,
            tuple[Callable[[], Mapping[str, str]], Callable[[], Mapping[str, str]]],
        ] = {}
        self._deadline: float | None = None

    def stage(
        self,
        *,
        key: str,
        patient_id: UUID,
        hospital_day_id: UUID | None,
        base_values: Mapping[str, str] | Callable[[], Mapping[str, str]],
        draft_values: Mapping[str, str] | Callable[[], Mapping[str, str]],
    ) -> None:
        context = (patient_id, hospital_day_id)
        if self._staged_context is not None and self._staged_context != context:
            raise RecoveryServiceError(
                "Pending recovery data belongs to a different patient context."
            )
        self._staged_context = context
        self._staged_values[key] = (
            _value_provider(base_values),
            _value_provider(draft_values),
        )
        self._staged = None
        self._deadline = self._monotonic() + self._debounce_seconds

    def poll(self) -> bool:
        if not self._staged_values or self._deadline is None or self._monotonic() < self._deadline:
            return False
        return self.flush()

    def unstage(self, key: str) -> None:
        """Remove one explicitly saved editor while retaining other staged drafts."""
        if key not in self._staged_values:
            return
        self._staged_values.pop(key, None)
        self._staged = None
        if not self._staged_values:
            self.discard()

    def flush(self) -> bool:
        if not self._staged_values or self._staged_context is None:
            return False
        patient_id, hospital_day_id = self._staged_context
        entries = tuple(
            RecoveryEntry(
                key,
                recovery_fingerprint(base_provider()),
                dict(draft_provider()),
            )
            for key, (base_provider, draft_provider) in sorted(self._staged_values.items())
        )
        self._staged = RecoverySnapshot(
            patient_id,
            hospital_day_id,
            self._now(),
            entries,
        )
        try:
            self._store.write(self._staged)
        except RecoveryError as error:
            raise RecoveryServiceError(
                "Unsaved edits could not be written to the recovery snapshot."
            ) from error
        self._deadline = None
        self._publisher.publish(PersistenceLifecycleEvent("recovery", "draft_saved"))
        return True

    def available(self) -> RecoverySnapshot | None:
        try:
            return self._store.load()
        except RecoveryError as error:
            raise RecoveryServiceError("The recovery snapshot could not be read.") from error

    def conflicting_entries(
        self,
        snapshot: RecoverySnapshot,
        current_values: Mapping[str, Mapping[str, str]],
    ) -> tuple[str, ...]:
        return tuple(
            entry.key
            for entry in snapshot.entries
            if entry.key not in current_values
            or recovery_fingerprint(current_values[entry.key]) != entry.base_fingerprint
        )

    def discard(self) -> None:
        self._staged = None
        self._staged_context = None
        self._staged_values.clear()
        self._deadline = None
        try:
            self._store.clear()
        except RecoveryError as error:
            raise RecoveryServiceError("The recovery snapshot could not be cleared.") from error
        self._publisher.publish(PersistenceLifecycleEvent("recovery", "draft_cleared"))


def recovery_fingerprint(values: Mapping[str, str]) -> str:
    """Hash canonical editor values without relying on filesystem timestamps."""
    encoded = json.dumps(dict(values), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _value_provider(
    values: Mapping[str, str] | Callable[[], Mapping[str, str]],
) -> Callable[[], Mapping[str, str]]:
    if callable(values):
        return values
    captured = dict(values)
    return lambda: captured
