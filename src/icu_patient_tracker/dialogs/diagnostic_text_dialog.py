"""Compact always-on-top editor for the selected day's diagnostics."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from icu_patient_tracker.ui.save_shortcut import bind_ctrl_s


class DiagnosticTextDialog(QDialog):
    saved = Signal(str)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("Edit Diagnostics")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(580, 360)
        self.context_label = QLabel()
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("[ ] Pending test\nCBC: result")
        self.save_button = QPushButton("Save")
        bind_ctrl_s(self.save_button)
        self.cancel_button = QPushButton("Cancel")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.context_label)
        layout.addWidget(self.editor, 1)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.reject)

    def show_for(self, context: str, text: str) -> None:
        self.context_label.setText(context)
        self.editor.setPlainText(text)
        self.show()
        self.raise_()
        self.activateWindow()
        self.editor.setFocus()

    def _save(self) -> None:
        self.saved.emit(self.editor.toPlainText())
