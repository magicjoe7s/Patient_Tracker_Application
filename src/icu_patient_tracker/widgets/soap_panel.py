"""Lossless canonical SOAP Markdown editor."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.text_refresh import set_plain_text_safely


class SOAPMarkdownEdit(QPlainTextEdit):
    """Traverse literal input tokens with Tab while retaining ordinary text editing."""

    placeholder_requested = Signal(bool)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Tab:
            backwards = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.placeholder_requested.emit(backwards)
            event.accept()
            return
        super().keyPressEvent(event)


class SOAPPanel(QWidget):
    """Edit one complete Markdown document; mapping remains in the service layer."""

    popup_requested = Signal(str)

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self._document_id: UUID | None = None
        self._loaded_generation = -1
        self._base_recovery_values: dict[str, str] = {}
        self.status_label = QLabel("No SOAP document")
        self.markdown = SOAPMarkdownEdit()
        self.markdown.setAccessibleName("SOAP Markdown")
        self.markdown.setTabChangesFocus(False)
        self.save_button = QPushButton("Save SOAP")
        self.save_button.hide()
        self.copy_button = QPushButton("Copy SOAP")
        self.popup_button = QPushButton("Pop out")
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.popup_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.markdown)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self.save)
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        self.popup_button.clicked.connect(lambda: self.popup_requested.emit("soap"))
        self.markdown.textChanged.connect(self._mark_dirty)
        self.markdown.placeholder_requested.connect(self._move_placeholder)

    def refresh(self, *, force: bool = False) -> None:
        generation = self._controller.context.generation
        # Autosave and cross-panel synchronization may request a refresh while the
        # clinician is paused mid-sentence. Never reload the focused document for the
        # same patient/day; a genuine context change has a new generation.
        if self.markdown.hasFocus() and generation == self._loaded_generation:
            return
        if (
            not force
            and self._controller.context.is_dirty
            and generation == self._loaded_generation
        ):
            return
        day = self._controller.selected_day()
        documents = day.soap_documents if day is not None else ()
        document = documents[-1] if documents else None
        if day is not None and document is None:
            document = self._controller.save_soap(None, markdown_text="")
        if document is not None and not document.markdown_text:
            document = self._controller.ensure_soap_markdown(document.id)
        self._load(document, generation, force=force or generation != self._loaded_generation)

    def save(self) -> bool:
        if self._loaded_generation != self._controller.context.generation:
            return False
        cursor = self.markdown.textCursor()
        anchor = cursor.anchor()
        position = cursor.position()
        vertical = self.markdown.verticalScrollBar().value()
        horizontal = self.markdown.horizontalScrollBar().value()
        focused = self.markdown.hasFocus()
        document = self._controller.save_soap(
            self._document_id,
            markdown_text=self.markdown.toPlainText(),
        )
        if document is None:
            self.status_label.setText("Save failed")
            return False
        self._document_id = document.id
        self._set_text(document.markdown_text)
        restored = self.markdown.textCursor()
        limit = len(self.markdown.toPlainText())
        restored.setPosition(min(anchor, limit))
        restored.setPosition(min(position, limit), QTextCursor.MoveMode.KeepAnchor)
        self.markdown.setTextCursor(restored)
        self.markdown.verticalScrollBar().setValue(vertical)
        self.markdown.horizontalScrollBar().setValue(horizontal)
        if focused:
            self.markdown.setFocus()
        self.status_label.setText("Saved and synchronized")
        return True

    def refresh_mapped(self, sections: tuple[str, ...]) -> None:
        if self._document_id is None and not self.save():
            return
        if self._document_id is not None:
            document = self._controller.refresh_soap(self._document_id, sections=sections)
            if document is not None:
                self._load(document, self._controller.context.generation)

    def refresh_am_charting(self) -> None:
        """Refresh only AM-owned Charting regions, preserving PM and recommendations."""
        self.refresh_mapped(
            (
                "physical_examination",
                "diagnostics",
                "treatment_changes",
                "instrumentation",
                "assessment",
            )
        )

    def synchronize(self) -> None:
        """Compatibility command: saving Markdown performs conservative reverse mapping."""
        self.save()

    def copy_to_clipboard(self) -> bool:
        """Flush the canonical document, copy it, and honor the minimize preference."""
        copied = self._controller.copy_soap()
        if copied and self._controller.minimize_after_copy():
            self.window().showMinimized()
        return copied

    def focus_next_placeholder(self) -> bool:
        """Select the next literal #INPUT# token, wrapping without changing text."""
        return self._move_placeholder(False)

    def focus_previous_placeholder(self) -> bool:
        """Select the previous literal token, wrapping without changing text."""
        return self._move_placeholder(True)

    def _move_placeholder(self, backwards: bool) -> bool:
        cursor = self.markdown.textCursor()
        text = self.markdown.toPlainText()
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
        self.markdown.setTextCursor(cursor)
        self.markdown.setFocus()
        return True

    def _load(self, document: SOAPDocument | None, generation: int, *, force: bool = False) -> None:
        self._document_id = document.id if document is not None else None
        self._set_text(document.markdown_text if document is not None else "", force=force)
        self._loaded_generation = generation
        self._base_recovery_values = self.recovery_values()
        self.status_label.setText("Loaded" if document else "New SOAP document")

    def _set_text(self, value: str, *, force: bool = False) -> None:
        self.markdown.blockSignals(True)
        set_plain_text_safely(self.markdown, value, force=force)
        self.markdown.blockSignals(False)

    def _mark_dirty(self) -> None:
        self.status_label.setText("Unsaved")
        self._controller.mark_editor_dirty(
            "soap",
            self._save_pending,
            base_values=self._base_recovery_values,
            draft_values=self.recovery_values,
        )

    def recovery_values(self) -> dict[str, str]:
        return {"markdown_text": self.markdown.toPlainText()}

    def apply_recovery(self, values: dict[str, str]) -> None:
        self._set_text(values.get("markdown_text", self.markdown.toPlainText()), force=True)
        self._mark_dirty()

    def _save_pending(self) -> None:
        if not self.save():
            raise RuntimeError("SOAP editor could not be saved.")
