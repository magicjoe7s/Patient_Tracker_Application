"""Consistent optional keyboard activation for visible save controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractButton, QDialogButtonBox


def bind_ctrl_s(button: QAbstractButton) -> None:
    """Let Ctrl+S activate the same operation as clicking a Save button."""
    shortcut = QShortcut(QKeySequence("Ctrl+S"), button)
    shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
    shortcut.activated.connect(button.click)


def bind_standard_save(buttons: QDialogButtonBox) -> None:
    save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
    if save_button is not None:
        bind_ctrl_s(save_button)
