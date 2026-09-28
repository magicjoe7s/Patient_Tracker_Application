"""Day-owned Sandbox Markdown editor and explicit extraction workflow."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.dialogs.sandbox_extraction_dialog import SandboxExtractionDialog
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.text_refresh import set_plain_text_safely
from icu_patient_tracker.utils.sandbox_input import format_sandbox_paste


class SandboxMarkdownEdit(QPlainTextEdit):
    """Plain Markdown editor with conservative formatting of pasted text."""

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasText():
            self.insertPlainText(format_sandbox_paste(source.text()))
            return
        super().insertFromMimeData(source)


class SandboxPanel(QWidget):
    """Persist scratch text exactly and never extract tasks as a save side effect."""

    popup_requested = Signal(str)

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self._loaded_generation = -1
        self._base_recovery_values: dict[str, str] = {}
        self.status_label = QLabel("No Sandbox")
        self.editor = SandboxMarkdownEdit()
        self.editor.setAccessibleName("Sandbox Markdown")
        self.editor.setTabChangesFocus(False)
        self.save_button = QPushButton("Save Sandbox")
        self.save_button.hide()
        self.extract_button = QPushButton("Preview checklist tasks")
        self.popup_button = QPushButton("Pop out")
        buttons = QHBoxLayout()
        for button in (
            self.extract_button,
            self.popup_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.editor)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self.save)
        self.extract_button.clicked.connect(self.preview_extraction)
        self.popup_button.clicked.connect(lambda: self.popup_requested.emit("sandbox"))
        self.editor.textChanged.connect(self._mark_dirty)

    def refresh(self, *, force: bool = False) -> None:
        generation = self._controller.context.generation
        if (
            not force
            and self._controller.context.is_dirty
            and generation == self._loaded_generation
        ):
            return
        day = self._controller.selected_day()
        self.editor.blockSignals(True)
        set_plain_text_safely(
            self.editor,
            day.sandbox_text if day is not None else "",
            force=force or generation != self._loaded_generation,
        )
        self.editor.blockSignals(False)
        self._loaded_generation = generation
        self._base_recovery_values = self.recovery_values()
        self.status_label.setText("Loaded" if day is not None else "No Sandbox")

    def save(self) -> bool:
        if self._loaded_generation != self._controller.context.generation:
            return False
        saved = self._controller.save_sandbox(self.editor.toPlainText())
        if saved is None:
            self.status_label.setText("Save failed")
            return False
        self.status_label.setText("Saved")
        return True

    def preview_extraction(self) -> None:
        """Save, preview, and require confirmation before creating any task."""
        if not self.save():
            return
        preview = self._controller.preview_sandbox_tasks()
        if preview is None:
            return
        if not preview.candidates:
            self.status_label.setText("No new unchecked tasks")
            return
        dialog = SandboxExtractionDialog(preview, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_line_numbers()
        created = self._controller.extract_sandbox_tasks(preview, selected)
        if created is not None:
            self.status_label.setText(f"Created {len(created)} task(s); Sandbox unchanged")

    def _move_input(self, backwards: bool) -> bool:
        cursor = self.editor.textCursor()
        text = self.editor.toPlainText()
        if backwards:
            position = text.rfind("#INPUT#", 0, cursor.selectionStart())
            if position < 0:
                position = text.rfind("#INPUT#")
        else:
            position = text.find("#INPUT#", cursor.selectionEnd())
            if position < 0:
                position = text.find("#INPUT#")
        if position < 0:
            return False
        cursor.setPosition(position)
        cursor.setPosition(position + len("#INPUT#"), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        return True

    def _mark_dirty(self) -> None:
        self.status_label.setText("Unsaved")
        self._controller.mark_editor_dirty(
            "sandbox",
            self._save_pending,
            base_values=self._base_recovery_values,
            draft_values=self.recovery_values,
        )

    def recovery_values(self) -> dict[str, str]:
        return {"markdown_text": self.editor.toPlainText()}

    def apply_recovery(self, values: dict[str, str]) -> None:
        self.editor.blockSignals(True)
        set_plain_text_safely(
            self.editor,
            values.get("markdown_text", self.editor.toPlainText()),
            force=True,
        )
        self.editor.blockSignals(False)
        self._mark_dirty()

    def _save_pending(self) -> None:
        if not self.save():
            raise RuntimeError("Sandbox editor could not be saved.")
