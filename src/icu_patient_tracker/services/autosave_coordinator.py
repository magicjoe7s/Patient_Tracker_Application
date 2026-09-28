"""Application events and error translation around debounced persistence."""

from collections.abc import Callable

from icu_patient_tracker.persistence.autosave import AutosaveController
from icu_patient_tracker.persistence.exceptions import AutosaveError
from icu_patient_tracker.services.events import (
    EventPublisher,
    NullEventPublisher,
    PersistenceLifecycleEvent,
)
from icu_patient_tracker.services.exceptions import AutosaveServiceError


class AutosaveCoordinator:
    """Expose explicit scheduler hooks without coupling autosave to Qt."""

    def __init__(
        self, controller: AutosaveController, publisher: EventPublisher | None = None
    ) -> None:
        self._controller = controller
        self._publisher = publisher or NullEventPublisher()

    def mark_dirty(self) -> None:
        self._controller.mark_dirty()
        self._publisher.publish(PersistenceLifecycleEvent("autosave", "scheduled"))

    def poll(self) -> bool:
        return self._save(self._controller.poll)

    def save_now(self) -> bool:
        return self._save(self._controller.save_now)

    def retry(self) -> None:
        self._controller.schedule_retry()
        self._publisher.publish(PersistenceLifecycleEvent("autosave", "retry_scheduled"))

    def shutdown(self) -> bool:
        return self._save(self._controller.shutdown)

    def _save(self, operation: Callable[[], bool]) -> bool:
        try:
            saved = operation()
        except AutosaveError as error:
            self._publisher.publish(PersistenceLifecycleEvent("autosave", "failed"))
            raise AutosaveServiceError(
                "Autosave failed; unsaved changes remain pending."
            ) from error
        if saved:
            self._publisher.publish(PersistenceLifecycleEvent("autosave", "completed"))
        return saved
