"""Qt implementation of the application clipboard output port."""

from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import QApplication


class QtClipboardAdapter:
    """Write plain text to the process application's system clipboard."""

    def __init__(self, application: QApplication) -> None:
        self._application = application

    def set_text(self, text: str) -> None:
        clipboard = self._application.clipboard()
        if clipboard is None:
            raise RuntimeError("The system clipboard is unavailable.")
        clipboard.setText(text, QClipboard.Mode.Clipboard)
