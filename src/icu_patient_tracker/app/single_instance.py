"""Single-process coordination with activation forwarding for desktop launches."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceCoordinator(QObject):
    """Own an atomic process lock and forward launches to the active instance."""

    activation_requested = Signal()

    def __init__(self, data_directory: Path) -> None:
        super().__init__()
        identity = hashlib.sha256(str(data_directory.resolve()).encode("utf-8")).hexdigest()[:16]
        self._server_name = f"icu-patient-tracker-{identity}"
        self._lock = QLockFile(str(data_directory / "application.lock"))
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._receive_activation)
        self._owns_instance = False
        self._activation_socket: QLocalSocket | None = None

    @property
    def owns_instance(self) -> bool:
        """Report whether this coordinator owns the process lock and local server."""
        return self._owns_instance

    def acquire_or_notify(self) -> bool:
        """Become the primary instance or notify the process that already owns it."""
        if not self._lock.tryLock(0):
            self._send_activation()
            return False

        QLocalServer.removeServer(self._server_name)
        if not self._server.listen(self._server_name):
            self._lock.unlock()
            raise RuntimeError(
                f"Unable to initialize the application activation channel: "
                f"{self._server.errorString()}"
            )
        self._owns_instance = True
        return True

    def close(self) -> None:
        """Release the local server and process lock when owned by this process."""
        if self._activation_socket is not None:
            self._activation_socket.disconnectFromServer()
            self._activation_socket.waitForDisconnected(250)
            self._activation_socket = None
        if not self._owns_instance:
            return
        self._server.close()
        QLocalServer.removeServer(self._server_name)
        self._lock.unlock()
        self._owns_instance = False

    def _send_activation(self) -> None:
        socket = QLocalSocket()
        self._activation_socket = socket
        socket.connectToServer(self._server_name)
        if not socket.waitForConnected(1_000):
            return
        socket.write(b"activate\n")
        socket.flush()
        socket.waitForBytesWritten(1_000)

    def _receive_activation(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.setParent(self)
            socket.readyRead.connect(lambda active_socket=socket: self._consume(active_socket))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._consume(socket)

    def _consume(self, socket: QLocalSocket) -> None:
        if socket.readAll().trimmed() == b"activate":
            self.activation_requested.emit()
