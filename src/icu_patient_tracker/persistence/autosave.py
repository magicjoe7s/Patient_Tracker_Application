"""UI-independent debounced autosave primitives with explicit failure recovery."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from icu_patient_tracker.persistence.exceptions import AutosaveError


class Clock(Protocol):
    """Monotonic time source that tests can control without sleeping."""

    def monotonic(self) -> float:
        """Return monotonic seconds."""
        ...


class SystemClock:
    """Production monotonic time source."""

    def monotonic(self) -> float:
        """Return operating-system monotonic seconds."""
        return time.monotonic()


class AutosaveController:
    """Coalesce dirty notifications and invoke one caller-supplied atomic save operation."""

    def __init__(
        self,
        save_operation: Callable[[], None],
        *,
        clock: Clock | None = None,
        debounce_seconds: float = 2.0,
        retry_seconds: float = 5.0,
    ) -> None:
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must not be negative.")
        if retry_seconds < 0:
            raise ValueError("retry_seconds must not be negative.")
        self._save_operation = save_operation
        self._clock = clock or SystemClock()
        self._debounce_seconds = debounce_seconds
        self._retry_seconds = retry_seconds
        self._deadline: float | None = None
        self._last_error: AutosaveError | None = None
        self._logger = logging.getLogger(__name__)
        self.is_dirty = False
        self.is_paused = False

    @property
    def deadline(self) -> float | None:
        """Return the current monotonic deadline for scheduler integration."""
        return self._deadline

    @property
    def last_error(self) -> AutosaveError | None:
        """Return the most recent visible failure until a save succeeds."""
        return self._last_error

    def mark_dirty(self) -> None:
        """Mark unsaved state and reset the debounce deadline."""
        self.is_dirty = True
        if not self.is_paused:
            self._deadline = self._clock.monotonic() + self._debounce_seconds

    def poll(self) -> bool:
        """Flush once when due; return whether a save occurred."""
        if (
            not self.is_dirty
            or self.is_paused
            or self._deadline is None
            or self._clock.monotonic() < self._deadline
        ):
            return False
        return self.save_now()

    def save_now(self) -> bool:
        """Explicitly flush dirty state through the caller's transactional operation."""
        if not self.is_dirty:
            return False
        try:
            self._save_operation()
        except Exception as error:
            autosave_error = AutosaveError("Autosave failed; unsaved state was retained.")
            self._last_error = autosave_error
            self.is_paused = True
            self._deadline = None
            self._logger.exception("Autosave failed and automatic retries were paused")
            raise autosave_error from error
        self.is_dirty = False
        self.is_paused = False
        self._deadline = None
        self._last_error = None
        return True

    def schedule_retry(self) -> None:
        """Resume a failed dirty save after an explicit recovery decision."""
        if not self.is_dirty:
            return
        self.is_paused = False
        self._deadline = self._clock.monotonic() + self._retry_seconds

    def shutdown(self) -> bool:
        """Synchronously flush pending work or expose the failure to the caller."""
        return self.save_now()
