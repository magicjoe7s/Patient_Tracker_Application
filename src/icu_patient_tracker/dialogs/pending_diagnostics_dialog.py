"""Focused selected-day pending-diagnostics editor."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.dialogs.task_editor_dialog import TaskEditorDialog
from icu_patient_tracker.domain.enums import TaskCategory, TaskStatus
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.models import ListRow, StableListModel


class PendingDiagnosticsDialog(QDialog):
    """Edit structured diagnostics for the selected day without owning a checklist copy."""

    result_requested = Signal(object)

    def __init__(self, controller: PresentationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._tasks: dict[UUID, Task] = {}
        self.setWindowTitle("Pending Diagnostics")
        self.resize(600, 460)
        self.patient_label = QLabel("Select a patient day")
        self.patient_label.setAccessibleName("Pending diagnostics patient and day")
        self.hide_completed = QCheckBox("Hide completed")
        config = self._controller.settings()
        stored = config.user_preferences.get("task_hide_completed", {}) if config else {}
        self.hide_completed.setChecked(
            stored.get(TaskCategory.DIAGNOSTIC.value, True)
            if isinstance(stored, dict)
            else True
        )
        self.model = StableListModel()
        self.list_view = QListView()
        self.list_view.setAccessibleName("Selected-day pending diagnostics")
        self.list_view.setModel(self.model)
        self.add_button = QPushButton("Add Diagnostic")
        self.edit_button = QPushButton("Edit")
        self.toggle_button = QPushButton("Complete / Reopen")
        self.result_button = QPushButton("Enter Result")
        self.omit_button = QPushButton("Omit forward")
        self.close_button = QPushButton("Close")
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.toggle_button,
            self.result_button,
            self.omit_button,
            self.close_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.patient_label)
        layout.addWidget(self.hide_completed)
        layout.addWidget(self.list_view)
        layout.addLayout(buttons)
        self.hide_completed.toggled.connect(self._hide_completed_changed)
        self.add_button.clicked.connect(self._add)
        self.edit_button.clicked.connect(self._edit)
        self.toggle_button.clicked.connect(self._toggle)
        self.result_button.clicked.connect(self._request_result)
        self.omit_button.clicked.connect(self._omit)
        self.close_button.clicked.connect(self.hide)
        self.list_view.doubleClicked.connect(self._edit)
        self.list_view.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._update_actions()
        )
        self.refresh()

    def refresh(self) -> None:
        selected_id = self.selected_id()
        patient = self._controller.selected_patient()
        day = self._controller.selected_day()
        tasks = (
            tuple(
                task
                for task in self._controller.tasks()
                if task.category is TaskCategory.DIAGNOSTIC
                and (not self.hide_completed.isChecked() or task.status is not TaskStatus.COMPLETED)
            )
            if patient is not None and day is not None
            else ()
        )
        self._tasks = {task.id: task for task in tasks}
        self.model.replace(
            ListRow(
                task.id,
                self._controller.diagnostic_result_line(task),
                f"{task.status.value} · {task.bucket.value}",
            )
            for task in tasks
        )
        self.patient_label.setText(
            "Select a patient day"
            if patient is None or day is None
            else f"{patient.name} · ICU {day.day_number} · {day.calendar_date.isoformat()}"
        )
        index = self.model.index_for(selected_id)
        if index.isValid():
            self.list_view.setCurrentIndex(index)
        self.setEnabled(patient is not None and day is not None)
        self._update_actions()

    def selected_id(self) -> UUID | None:
        value = self.model.identifier(self.list_view.currentIndex())
        return value if isinstance(value, UUID) else None

    def _add(self) -> None:
        dialog = TaskEditorDialog(self, category=TaskCategory.DIAGNOSTIC)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values.title:
            self._controller.error_raised.emit("Invalid task", "Task title must not be empty.")
            return
        if self._controller.add_task(
            values.title,
            category=TaskCategory.DIAGNOSTIC,
            priority=values.priority,
            bucket=values.bucket,
            carry_forward=values.carry_forward,
        ):
            self.refresh()

    def _edit(self, _index: object = None) -> None:
        task_id = self.selected_id()
        if task_id is None:
            return
        dialog = TaskEditorDialog(self, task=self._tasks[task_id])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values.title:
            answer = QMessageBox.question(
                self,
                "Delete task lineage",
                "The task text is empty. Delete this diagnostic and every carried occurrence?",
            )
            if answer is QMessageBox.StandardButton.Yes:
                self._controller.delete_task_lineage(self._tasks[task_id].lineage_id)
                self.refresh()
            return
        if self._controller.update_task(
            task_id,
            title=values.title,
            category=TaskCategory.DIAGNOSTIC,
            priority=values.priority,
            bucket=values.bucket,
            carry_forward=values.carry_forward,
        ):
            self.refresh()

    def _toggle(self) -> None:
        task_id = self.selected_id()
        if task_id is not None and self._controller.toggle_task(self._tasks[task_id]):
            self.refresh()

    def _omit(self) -> None:
        task_id = self.selected_id()
        if task_id is not None and self._controller.omit_diagnostic(task_id):
            self.refresh()

    def _request_result(self) -> None:
        task_id = self.selected_id()
        if task_id is not None:
            self.result_requested.emit(self._tasks[task_id])

    def _update_actions(self) -> None:
        task_id = self.selected_id()
        selected = self._tasks.get(task_id) if task_id is not None else None
        enabled = selected is not None
        self.edit_button.setEnabled(enabled)
        self.toggle_button.setEnabled(enabled)
        self.result_button.setEnabled(enabled)
        self.omit_button.setEnabled(
            selected is not None and selected.status is not TaskStatus.COMPLETED
        )

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)

    def reload_hide_preference(self) -> None:
        config = self._controller.settings()
        stored = config.user_preferences.get("task_hide_completed", {}) if config else {}
        hidden = (
            stored.get(TaskCategory.DIAGNOSTIC.value, True)
            if isinstance(stored, dict)
            else True
        )
        self.hide_completed.blockSignals(True)
        self.hide_completed.setChecked(hidden)
        self.hide_completed.blockSignals(False)
        self.refresh()

    def _hide_completed_changed(self, hidden: bool) -> None:
        config = self._controller.settings()
        if config is not None:
            preferences = dict(config.user_preferences)
            stored = preferences.get("task_hide_completed", {})
            by_category = dict(stored) if isinstance(stored, dict) else {}
            by_category[TaskCategory.DIAGNOSTIC.value] = hidden
            preferences["task_hide_completed"] = by_category
            self._controller.update_settings(user_preferences=preferences)
        self.refresh()
