"""Shared-context SOAP and Sandbox tool window for side-by-side EMR work."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QMouseEvent, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.text_refresh import set_plain_text_safely
from icu_patient_tracker.widgets.sandbox_panel import SandboxMarkdownEdit
from icu_patient_tracker.widgets.soap_panel import SOAPMarkdownEdit


class PatientPopup(QDialog):
    """Edit canonical selected-day text while the main workspace is hidden."""

    returned_to_main = Signal()
    save_requested = Signal()
    new_patient_requested = Signal()
    find_patient_requested = Signal()

    NORMAL_SIZE = (520, 720)
    COMPACT_SIZE = (220, 40)

    def __init__(
        self,
        controller: PresentationController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self._controller = controller
        self._document_id: UUID | None = None
        self._loaded_generation = -1
        self._base_soap_values: dict[str, str] = {}
        self._base_sandbox_values: dict[str, str] = {}
        self._mode = "soap"
        self._compact = False
        self._drag_offset: QPoint | None = None
        self._drag_origin: QPoint | None = None
        self._drag_started = False
        self._carets: dict[tuple[UUID, UUID, str], tuple[int, int]] = {}
        self.setObjectName("patientPopup")
        self.setWindowTitle("Patient Popup")
        self.resize(*self.NORMAL_SIZE)

        self.main_button = QPushButton("Main")
        self.soap_button = QPushButton("[S]")
        self.soap_button.setToolTip("SOAP")
        self.sandbox_button = QPushButton("SB")
        self.sandbox_button.setToolTip("Sandbox")
        self.compact_button = QPushButton("Min")
        self.previous_button = QPushButton("<")
        self.previous_button.setAccessibleName("Previous patient")
        self.next_button = QPushButton(">")
        self.next_button.setAccessibleName("Next patient")
        self.pin = QCheckBox("Pin")
        self.pin.setChecked(True)
        controls = QHBoxLayout()
        for widget in (
            self.main_button,
            self.soap_button,
            self.sandbox_button,
            self.compact_button,
            self.previous_button,
            self.next_button,
            self.pin,
        ):
            controls.addWidget(widget)

        self.patient_label = QLabel("No patient selected")
        self.patient_label.setObjectName("popupPatientHeader")
        self.patient_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.day_label = QLabel("Select a hospital day")
        self.day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label = QLabel("No editor loaded")
        self.status_label.setAccessibleName("Patient popup save status")

        self.soap_editor = SOAPMarkdownEdit()
        self.soap_editor.setAccessibleName("Popup SOAP Markdown")
        self.soap_editor.setTabChangesFocus(False)
        self.sandbox_editor = SandboxMarkdownEdit()
        self.sandbox_editor.setAccessibleName("Popup Sandbox Markdown")
        self.sandbox_editor.setTabChangesFocus(False)
        self.editors = QStackedWidget()
        self.editors.addWidget(self.soap_editor)
        self.editors.addWidget(self.sandbox_editor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        layout.addLayout(controls)
        layout.addWidget(self.patient_label)
        layout.addWidget(self.day_label)
        layout.addWidget(self.editors, 1)
        layout.addWidget(self.status_label)

        self.main_button.clicked.connect(self.return_to_main)
        self.soap_button.clicked.connect(lambda: self.set_mode("soap"))
        self.sandbox_button.clicked.connect(lambda: self.set_mode("sandbox"))
        self.compact_button.clicked.connect(self.toggle_compact)
        self.previous_button.clicked.connect(lambda: self.select_relative_patient(-1))
        self.next_button.clicked.connect(lambda: self.select_relative_patient(1))
        self.pin.toggled.connect(self._apply_pin)
        self.soap_editor.textChanged.connect(lambda: self._mark_dirty("soap"))
        self.sandbox_editor.textChanged.connect(lambda: self._mark_dirty("sandbox"))
        self.soap_editor.placeholder_requested.connect(self._move_soap_placeholder)
        self._controller.context_changed.connect(lambda _context: self.refresh(force=True))

        QShortcut(QKeySequence("Ctrl+P"), self, self.return_to_main)
        QShortcut(QKeySequence("Escape"), self, self.return_to_main)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_requested.emit)
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_patient_requested.emit)
        QShortcut(QKeySequence("Ctrl+F"), self, self.find_patient_requested.emit)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, lambda: self.set_mode("sandbox"))
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, lambda: self.set_mode("soap"))
        QShortcut(QKeySequence("Alt+M"), self, self.toggle_compact)
        self._apply_pin(True)
        self._update_mode_controls()
        for drag_surface in (
            self.main_button,
            self.compact_button,
            self.patient_label,
            self.day_label,
            self.status_label,
        ):
            drag_surface.installEventFilter(self)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_compact(self) -> bool:
        return self._compact

    def show_for(self, mode: str = "soap") -> None:
        """Load the shared context and activate the requested editor."""
        self.set_mode(mode, restore_caret=False)
        self.refresh(force=True)
        self.show()
        self.raise_()
        self.activateWindow()
        if not self._compact:
            self._restore_caret()

    def refresh(self, *, force: bool = False) -> None:
        """Reload canonical values unless this popup owns unsaved text."""
        generation = self._controller.context.generation
        if (
            not force
            and self._controller.context.is_dirty
            and generation == self._loaded_generation
        ):
            return
        patient = self._controller.selected_patient()
        day = self._controller.selected_day()
        documents = day.soap_documents if day is not None else ()
        document = documents[-1] if documents else None
        if day is not None and document is None:
            document = self._controller.save_soap(None, markdown_text="")
        if document is not None and not document.markdown_text:
            document = self._controller.ensure_soap_markdown(document.id)
        replace_focused = force or generation != self._loaded_generation
        self._load_soap(document, force=replace_focused)
        self._set_text(
            self.sandbox_editor,
            day.sandbox_text if day is not None else "",
            force=replace_focused,
        )
        self._base_sandbox_values = {"markdown_text": self.sandbox_editor.toPlainText()}
        self._loaded_generation = generation
        self.patient_label.setText(patient.name if patient is not None else "No patient selected")
        self.day_label.setText(
            "Select a hospital day"
            if day is None
            else f"ICU {day.day_number} · {day.calendar_date.isoformat()}"
        )
        enabled = patient is not None and day is not None
        self.editors.setEnabled(enabled)
        active_count = len(self._controller.patients())
        self.previous_button.setEnabled(active_count > 0)
        self.next_button.setEnabled(active_count > 0)
        self.status_label.setText("Loaded" if enabled else "No editor loaded")
        self._restore_caret()

    def set_mode(self, mode: str, *, restore_caret: bool = True) -> None:
        normalized = "sandbox" if mode == "sandbox" else "soap"
        if normalized != self._mode:
            self._save_caret()
            self._mode = normalized
        self.editors.setCurrentWidget(self._current_editor())
        self._update_mode_controls()
        if restore_caret and not self._compact:
            self._restore_caret()

    def toggle_compact(self) -> None:
        self.set_compact(not self._compact)

    def set_compact(self, compact: bool) -> None:
        self._save_caret()
        self._compact = compact
        for widget in (
            self.main_button,
            self.soap_button,
            self.sandbox_button,
            self.previous_button,
            self.next_button,
            self.pin,
            self.day_label,
            self.editors,
            self.status_label,
        ):
            widget.setVisible(not compact)
        self.compact_button.setText("Full" if compact else "Min")
        if compact:
            self.setFixedSize(*self.COMPACT_SIZE)
        else:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16_777_215, 16_777_215)
            self.resize(*self.NORMAL_SIZE)
        if not compact:
            self._restore_caret()

    def select_relative_patient(self, offset: int) -> bool:
        """Wrap through the admitted census after safely saving the outgoing context."""
        patients = self._controller.patients()
        if not patients:
            return False
        self._save_caret()
        current_id = self._controller.context.patient_id
        current = next(
            (index for index, patient in enumerate(patients) if patient.id == current_id),
            None,
        )
        destination = 0 if current is None else (current + offset) % len(patients)
        return self._controller.select_patient(patients[destination].id)

    def return_to_main(self) -> bool:
        """Commit popup edits before restoring the main workspace."""
        self._save_caret()
        if not self._controller.flush_pending():
            self.status_label.setText("Save failed; popup remains open")
            return False
        self.hide()
        self.returned_to_main.emit()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_caret()
        if not self._controller.flush_pending():
            self.status_label.setText("Save failed; popup remains open")
            event.ignore()
            return
        event.accept()
        self.returned_to_main.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched
            in {
                self.main_button,
                self.compact_button,
                self.patient_label,
                self.day_label,
                self.status_label,
            }
            and isinstance(event, QMouseEvent)
            and self._handle_drag_event(
                event,
                preserve_click=watched in {self.main_button, self.compact_button},
            )
        ):
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._handle_drag_event(event):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._handle_drag_event(event):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._handle_drag_event(event):
            super().mouseReleaseEvent(event)

    def _handle_drag_event(self, event: QMouseEvent, *, preserve_click: bool = False) -> bool:
        if event.button() is Qt.MouseButton.LeftButton:
            if event.type() is QEvent.Type.MouseButtonPress:
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_offset = self._drag_origin - self.frameGeometry().topLeft()
                self._drag_started = False
                return not preserve_click
            if event.type() is QEvent.Type.MouseButtonRelease:
                dragged = self._drag_started
                self._drag_offset = None
                self._drag_origin = None
                self._drag_started = False
                return dragged or not preserve_click
        if (
            event.type() is QEvent.Type.MouseMove
            and self._drag_offset is not None
            and self._drag_origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            distance = (event.globalPosition().toPoint() - self._drag_origin).manhattanLength()
            if not self._drag_started and distance < QApplication.startDragDistance():
                return False
            self._drag_started = True
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return True
        return False

    def _mark_dirty(self, mode: str) -> None:
        if self._loaded_generation != self._controller.context.generation:
            return
        self.status_label.setText("Unsaved")
        saver = self._save_soap if mode == "soap" else self._save_sandbox
        base_values = self._base_soap_values if mode == "soap" else self._base_sandbox_values
        editor = self.soap_editor if mode == "soap" else self.sandbox_editor

        def draft_values() -> dict[str, str]:
            return {"markdown_text": editor.toPlainText()}

        self._controller.mark_editor_dirty(
            mode,
            saver,
            base_values=base_values,
            draft_values=draft_values,
        )

    def _save_soap(self) -> None:
        if self._loaded_generation != self._controller.context.generation:
            raise RuntimeError("Popup SOAP context changed before save.")
        document = self._controller.save_soap(
            self._document_id,
            markdown_text=self.soap_editor.toPlainText(),
        )
        if document is None:
            raise RuntimeError("Popup SOAP could not be saved.")
        self._document_id = document.id
        self.status_label.setText("Saved")

    def _save_sandbox(self) -> None:
        if self._loaded_generation != self._controller.context.generation:
            raise RuntimeError("Popup Sandbox context changed before save.")
        if self._controller.save_sandbox(self.sandbox_editor.toPlainText()) is None:
            raise RuntimeError("Popup Sandbox could not be saved.")
        self.status_label.setText("Saved")

    def _load_soap(self, document: SOAPDocument | None, *, force: bool = False) -> None:
        self._document_id = document.id if document is not None else None
        self._set_text(
            self.soap_editor,
            document.markdown_text if document is not None else "",
            force=force,
        )
        self._base_soap_values = {"markdown_text": self.soap_editor.toPlainText()}

    @staticmethod
    def _set_text(editor: QPlainTextEdit, value: str, *, force: bool = False) -> None:
        editor.blockSignals(True)
        set_plain_text_safely(editor, value, force=force)
        editor.blockSignals(False)

    def _caret_key(self) -> tuple[UUID, UUID, str] | None:
        patient_id = self._controller.context.patient_id
        day_id = self._controller.context.hospital_day_id
        return None if patient_id is None or day_id is None else (patient_id, day_id, self._mode)

    def _save_caret(self) -> None:
        key = self._caret_key()
        if key is None:
            return
        cursor = self._current_editor().textCursor()
        self._carets[key] = (cursor.selectionStart(), cursor.selectionEnd())

    def _restore_caret(self) -> None:
        if self._compact:
            return
        editor = self._current_editor()
        text_length = len(editor.toPlainText())
        default = (text_length, text_length) if self._mode == "sandbox" else (0, 0)
        key = self._caret_key()
        start, end = default if key is None else self._carets.get(key, default)
        start = min(max(start, 0), text_length)
        end = min(max(end, 0), text_length)
        cursor = editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.setFocus()

    def _current_editor(self) -> QPlainTextEdit:
        return self.sandbox_editor if self._mode == "sandbox" else self.soap_editor

    def _move_soap_placeholder(self, backwards: bool) -> None:
        self._move_placeholder(self.soap_editor, backwards)

    @staticmethod
    def _move_placeholder(editor: QPlainTextEdit, backwards: bool) -> bool:
        cursor = editor.textCursor()
        text = editor.toPlainText()
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
        editor.setTextCursor(cursor)
        return True

    def _update_mode_controls(self) -> None:
        self.soap_button.setText("[S]" if self._mode == "soap" else "S")
        self.sandbox_button.setText("[SB]" if self._mode == "sandbox" else "SB")

    def _apply_pin(self, pinned: bool) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        if was_visible:
            self.show()
