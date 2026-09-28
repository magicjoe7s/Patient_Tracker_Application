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
        self._timer = QTimer(self)
        self._poll_queued = False
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def is_active(self) -> bool:
        return self._timer.isActive()

    def _poll(self) -> None:
        if self._poll_queued:
            return
        self._poll_queued = True
        QTimer.singleShot(0, self._poll_when_idle)

    def _poll_when_idle(self) -> None:
        """Run persistence only after Qt has returned to its event queue."""
        self._poll_queued = False
        try:
            self._coordinator.poll()
        except AutosaveServiceError as error:
            self._timer.stop()
            self.failure.emit(str(error))
