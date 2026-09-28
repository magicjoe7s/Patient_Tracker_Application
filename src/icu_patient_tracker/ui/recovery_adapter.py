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
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        try:
            self._service.poll()
        except RecoveryServiceError as error:
            self.failure.emit(str(error))
