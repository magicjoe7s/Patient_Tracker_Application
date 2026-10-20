"""Qt timer adapter for framework-independent recovery snapshot scheduling."""

from PySide6.QtCore import QObject, QTimer, Signal

from icu_patient_tracker.services.exceptions import RecoveryServiceError
from icu_patient_tracker.services.recovery_service import RecoveryService


class QtRecoveryAdapter(QObject):
    """Poll one recovery service without putting timing or Qt in the service layer."""

    failure = Signal(str)

    def __init__(self, service: RecoveryService, interval_ms: int = 100) -> None:
        super().__init__()
        self._service = service
        self._polling = False
        self._last_failure: str | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        if self._polling:
            return
        self._polling = True
        try:
            self._service.poll()
            self._last_failure = None
        except RecoveryServiceError as error:
            # Keep retrying the draft, but notify once per persistent failure.
            message = str(error)
            if message != self._last_failure:
                self._last_failure = message
                self.failure.emit(message)
        finally:
            self._polling = False
