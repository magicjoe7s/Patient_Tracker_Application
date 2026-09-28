"""Always-on-top result capture locked to one patient and hospital day."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.enums import TaskStatus
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.save_shortcut import bind_ctrl_s
from icu_patient_tracker.ui.text_refresh import set_plain_text_safely


class DiagnosticResultDialog(QDialog):
    """Capture a preliminary or final result without changing patient context."""

    closed = Signal()

    def __init__(self, controller: PresentationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._patient_id: UUID | None = None
        self._day_id: UUID | None = None
        self._tasks: dict[UUID, Task] = {}
        self.setWindowTitle("Enter Diagnostic Result")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(560, 330)
        self.context_label = QLabel("Select a patient day")
        self.diagnostic_combo = QComboBox()
        self.result_edit = QPlainTextEdit()
        self.result_edit.setPlaceholderText("Enter the result")
        self.status_label = QLabel("")
        self.save_button = QPushButton("Save Result")
        bind_ctrl_s(self.save_button)
        self.next_button = QPushButton("Save Result and Next")
        self.close_button = QPushButton("Close")
        buttons = QHBoxLayout()
        for button in (self.save_button, self.next_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.context_label)
        layout.addWidget(QLabel("Pending diagnostic:"))
        layout.addWidget(self.diagnostic_combo)
        layout.addWidget(QLabel("Result:"))
        layout.addWidget(self.result_edit, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)
        self.diagnostic_combo.currentIndexChanged.connect(self._load_selected_result)
        self.save_button.clicked.connect(lambda: self._save(advance=False))
        self.next_button.clicked.connect(lambda: self._save(advance=True))
        self.close_button.clicked.connect(self.hide)

    def show_for(self, patient_id: UUID, day_id: UUID, task_id: UUID | None = None) -> None:
        self._patient_id = patient_id
        self._day_id = day_id
        self.refresh(preferred_task_id=task_id)
        self.show()
        self.raise_()
        self.activateWindow()
        self.result_edit.setFocus()

    def refresh(self, *, preferred_task_id: UUID | None = None) -> None:
        if self._patient_id is None or self._day_id is None:
            return
        tasks = self._controller.diagnostic_tasks_for(self._patient_id, self._day_id)
        self._tasks = {task.id: task for task in tasks}
        current = preferred_task_id or self.current_task_id()
        self.diagnostic_combo.blockSignals(True)
        self.diagnostic_combo.clear()
        for task in tasks:
            self.diagnostic_combo.addItem(self._controller.diagnostic_result_line(task), task.id)
        index = self.diagnostic_combo.findData(current)
        if index < 0:
            index = self._first_pending_index()
        self.diagnostic_combo.setCurrentIndex(index)
        self.diagnostic_combo.blockSignals(False)
        patient = self._controller.services.patients.get(self._patient_id)
        day = self._controller.services.days.get(self._patient_id, self._day_id)
        self.context_label.setText(
            f"{patient.name} · ICU {day.day_number} · {day.calendar_date.isoformat()}"
        )
        self._load_selected_result()

    def current_task_id(self) -> UUID | None:
        value = self.diagnostic_combo.currentData()
        return value if isinstance(value, UUID) else None

    def _load_selected_result(self) -> None:
        task_id = self.current_task_id()
        task = self._tasks.get(task_id) if task_id is not None else None
        text = (
            ""
            if task is None or task.diagnostic_result is None
            else task.diagnostic_result.result_text
        )
        set_plain_text_safely(self.result_edit, text)
        self.status_label.clear()
        enabled = task is not None
        for widget in (self.result_edit, self.save_button, self.next_button):
            widget.setEnabled(enabled)

    def _save(self, *, advance: bool) -> None:
        task_id = self.current_task_id()
        text = self.result_edit.toPlainText()
        if self._patient_id is None or self._day_id is None or task_id is None:
            return
        if not text.strip():
            self.status_label.setText("Enter a result before saving.")
            return
        saved = self._controller.record_diagnostic_result(
            self._patient_id, self._day_id, task_id, text, complete=True
        )
        if saved is not None:
            self.refresh(preferred_task_id=task_id)
            if advance:
                next_index = self._first_pending_index(fallback=False)
                self.diagnostic_combo.setCurrentIndex(next_index)
                self.status_label.setText(
                    "Result saved. No pending diagnostics remain."
                    if next_index < 0
                    else "Result saved."
                )
            else:
                self.status_label.setText("Result saved.")

    def _first_pending_index(self, *, fallback: bool = True) -> int:
        for index in range(self.diagnostic_combo.count()):
            task_id = self.diagnostic_combo.itemData(index)
            task = self._tasks.get(task_id) if isinstance(task_id, UUID) else None
            if task is not None and task.status is not TaskStatus.COMPLETED:
                return index
        return 0 if fallback and self.diagnostic_combo.count() else -1

    def hideEvent(self, event: QHideEvent) -> None:
        self.closed.emit()
        super().hideEvent(event)
