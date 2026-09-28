"""Typed command entry and generated shortcut help dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.ui.action_registry import ActionRegistry


class CommandPaletteDialog(QDialog):
    """Offer typed command entry with registry-derived usage suggestions."""

    def __init__(self, registry: ActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self.setWindowTitle("Command Palette")
        self.resize(620, 390)
        self.prompt = QLabel("Type a command. Use help to see every shortcut and alias.")
        self.command = QLineEdit()
        self.command.setAccessibleName("Typed command")
        self.command.setPlaceholderText("Examples: p bella, status home, focus pending")
        self.suggestions = QListWidget()
        self.suggestions.setAccessibleName("Available command suggestions")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run")
        layout = QVBoxLayout(self)
        layout.addWidget(self.prompt)
        layout.addWidget(self.command)
        layout.addWidget(self.suggestions, 1)
        layout.addWidget(buttons)
        self.command.textChanged.connect(self._refresh_suggestions)
        self.suggestions.itemActivated.connect(
            lambda item: self.command.setText(item.data(Qt.ItemDataRole.UserRole))
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._refresh_suggestions("")

    def command_text(self) -> str:
        return self.command.text().strip()

    def _refresh_suggestions(self, query: str) -> None:
        normalized = self._registry.normalize(query)
        self.suggestions.clear()
        for definition in self._registry.definitions:
            usage = definition.command_usage
            if not usage:
                continue
            aliases = " ".join(definition.commands)
            if normalized and normalized not in f"{usage} {aliases} {definition.label}".casefold():
                continue
            self.suggestions.addItem(f"{usage} — {definition.description}")
            item = self.suggestions.item(self.suggestions.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, definition.commands[0])


class GeneratedHelpDialog(QDialog):
    """Render help generated from the live action registry."""

    command_palette_requested = Signal()

    def __init__(
        self,
        registry: ActionRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tracker Menu / Shortcuts")
        self.resize(760, 600)
        self.text = QPlainTextEdit()
        self.text.setAccessibleName("Generated commands and shortcuts")
        self.text.setReadOnly(True)
        self.text.setPlainText(registry.help_text())
        command_button = QPushButton("Command Palette")
        close_button = QPushButton("Close")
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addWidget(command_button)
        layout.addWidget(close_button)
        command_button.clicked.connect(self.command_palette_requested)
        close_button.clicked.connect(self.close)
