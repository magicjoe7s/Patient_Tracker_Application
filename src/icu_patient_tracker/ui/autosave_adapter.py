"""Qt timer adapter for the framework-independent autosave coordinator."""

from PySide6.QtCore import QObject, QTimer, Signal

from icu_patient_tracker.services.autosave_coordinator import AutosaveCoordinator
from icu_patient_tracker.services.exceptions import AutosaveServiceError


class QtAutosaveAdapter(QObject):
    """Poll one shared autosave coordinator without creating per-widget timers."""

    failure = Signal(str)

    def __init__(self, coordinator: AutosaveCoordinator, interval_ms: int = 100) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._stopped = False
        self._timer = QTimer(self)
        self._poll_queued = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._poll_when_idle)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._stopped = False
        self._timer.start()

    def stop(self) -> None:
        self._stopped = True
        self._timer.stop()
        if self._idle_timer.isActive():
            self._idle_timer.stop()
            self._poll_queued = False

    @property
    def is_active(self) -> bool:
        return self._timer.isActive()

    def _poll(self) -> None:
        if self._stopped or self._poll_queued:
            return
        self._poll_queued = True
        self._idle_timer.start(0)

    def _poll_when_idle(self) -> None:
        """Run persistence only after Qt has returned to its event queue."""
        try:
            self._coordinator.poll()
        except AutosaveServiceError as error:
            self._timer.stop()
            if not self._stopped:
                self.failure.emit(str(error))
        finally:
            self._poll_queued = False
