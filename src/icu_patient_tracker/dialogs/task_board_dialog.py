"""Derived four-pane cross-patient task board."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QGroupBox,
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
from icu_patient_tracker.services.task_service import TaskBoardRow
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.models import ListRow, StableListModel


class TaskBoardPane(QGroupBox):
    """Render one category from immutable board projections."""

    navigated = Signal()
    diagnostic_result_requested = Signal(object)

    def __init__(
        self,
        title: str,
        category: TaskCategory,
        controller: PresentationController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self._category = category
        self._controller = controller
        self._rows: dict[UUID, TaskBoardRow] = {}
        self._pending_checks: dict[UUID, bool] = {}
        self._flushing_checks = False
        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.setInterval(250)
        self._check_timer.timeout.connect(self._flush_checkbox_changes)
        self.model = StableListModel()
        self.list_view = QListView()
        self.list_view.setAccessibleName(f"{title} task board")
        self.list_view.setModel(self.model)
        self.hide_completed = QCheckBox("Hide completed")
        config = self._controller.settings()
        stored = config.user_preferences.get("task_hide_completed", {}) if config else {}
        self.hide_completed.setChecked(
            stored.get(category.value, True) if isinstance(stored, dict) else True
        )
        self.add_button = QPushButton("Add")
        self.edit_button = QPushButton("Edit")
        self.toggle_button = QPushButton("Complete / Reopen")
        self.result_button = QPushButton("Enter Result")
        self.result_button.setVisible(category is TaskCategory.DIAGNOSTIC)
        self.delete_button = QPushButton("Delete")
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.toggle_button,
            self.result_button,
            self.delete_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.hide_completed)
        layout.addWidget(self.list_view)
        layout.addLayout(buttons)
        self.hide_completed.toggled.connect(self._hide_completed_changed)
        self.model.check_state_changed.connect(self._queue_checkbox_change)
        self.add_button.clicked.connect(self._add)
        self.edit_button.clicked.connect(self._edit)
        self.toggle_button.clicked.connect(self._toggle)
        self.result_button.clicked.connect(self._request_result)
        self.delete_button.clicked.connect(self._delete)
        self.list_view.doubleClicked.connect(self._navigate)
        self.list_view.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._update_actions()
        )
        self._update_actions()

    def refresh(self) -> None:
        if self._flushing_checks:
            return
        selected = self.selected_row()
        rows = self._controller.task_board(
            self._category,
            include_completed=not self.hide_completed.isChecked(),
        )
        self._rows = {row.task.id: row for row in rows}
        self.model.replace(
            ListRow(
                row.task.id,
                (
                    self._controller.diagnostic_result_line(row.task)
                    if self._category is TaskCategory.DIAGNOSTIC
                    else ("✓ " if row.task.status is TaskStatus.COMPLETED else "") + row.task.title
                ),
                (
                    f"{row.patient_name} · ICU {row.day_number} · {row.day_label} · "
                    f"{row.patient_status.value}"
                ),
                row.task.status is TaskStatus.COMPLETED,
            )
            for row in rows
        )
        if selected is not None:
            index = self.model.index_for(selected.task.id)
            if index.isValid():
                self.list_view.setCurrentIndex(index)
        self._update_actions()

    def selected_row(self) -> TaskBoardRow | None:
        identifier = self.model.identifier(self.list_view.currentIndex())
        return self._rows.get(identifier) if isinstance(identifier, UUID) else None

    def _add(self) -> None:
        dialog = TaskEditorDialog(self, category=self._category)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values.title:
            self._controller.error_raised.emit("Invalid task", "Task title must not be empty.")
            return
        if self._controller.add_board_task(
            values.title,
            category=self._category,
            priority=values.priority,
            bucket=values.bucket,
            carry_forward=values.carry_forward,
        ):
            self.refresh()

    def _edit(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        dialog = TaskEditorDialog(self, task=row.task)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values.title:
            self._delete()
            return
        if self._controller.update_board_task(
            row,
            title=values.title,
            category=values.category,
            priority=values.priority,
            bucket=values.bucket,
            carry_forward=values.carry_forward,
        ):
            self.refresh()

    def _toggle(self) -> None:
        row = self.selected_row()
        if row is not None and self._controller.toggle_board_task(row):
            self.refresh()

    def _queue_checkbox_change(self, identifier: object, checked: bool) -> None:
        """Coalesce rapid ID-based checks before persistence and board rebuilding."""
        if isinstance(identifier, UUID):
            self._pending_checks[identifier] = checked
            self._check_timer.start()

    def _flush_checkbox_changes(self) -> None:
        changes = self._pending_checks
        self._pending_checks = {}
        self._flushing_checks = True
        try:
            for task_id, checked in changes.items():
                row = self._rows.get(task_id)
                if row is None:
                    continue
                completed = row.task.status is TaskStatus.COMPLETED
                if checked != completed:
                    self._controller.toggle_board_task(row)
        finally:
            self._flushing_checks = False
        self.refresh()

    def _hide_completed_changed(self, hidden: bool) -> None:
        config = self._controller.settings()
        if config is not None:
            preferences = dict(config.user_preferences)
            stored = preferences.get("task_hide_completed", {})
            by_category = dict(stored) if isinstance(stored, dict) else {}
            by_category[self._category.value] = hidden
            preferences["task_hide_completed"] = by_category
            self._controller.update_settings(user_preferences=preferences)
        self.refresh()

    def reload_hide_preference(self) -> None:
        config = self._controller.settings()
        stored = config.user_preferences.get("task_hide_completed", {}) if config else {}
        hidden = stored.get(self._category.value, True) if isinstance(stored, dict) else True
        self.hide_completed.blockSignals(True)
        self.hide_completed.setChecked(hidden)
        self.hide_completed.blockSignals(False)
        self.refresh()

    def _delete(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete task lineage",
            "Delete this task and every carried occurrence in its lineage?",
        )
        if answer is QMessageBox.StandardButton.Yes and self._controller.delete_board_task_lineage(
            row
        ):
            self.refresh()

    def _request_result(self) -> None:
        row = self.selected_row()
        if row is not None:
            self.diagnostic_result_requested.emit(row)

    def _navigate(self, index: QModelIndex | None = None) -> None:
        del index
        row = self.selected_row()
        if row is None:
            return
        if self._category is TaskCategory.DIAGNOSTIC:
            self.diagnostic_result_requested.emit(row)
        elif self._controller.select_task_board_row(row):
            self.navigated.emit()

    def _update_actions(self) -> None:
        enabled = self.selected_row() is not None
        self.edit_button.setEnabled(enabled)
        self.toggle_button.setEnabled(enabled)
        self.result_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)


class TaskBoardDialog(QDialog):
    """Present four synchronized views without storing any board-owned task state."""

    navigated = Signal()
    diagnostic_result_requested = Signal(object)

    _PANES = (
        ("Pending Diagnostics + Follow-up", TaskCategory.DIAGNOSTIC),
        ("All Patients To Do", TaskCategory.CLINICAL),
        ("POCUS", TaskCategory.POCUS),
        ("Global Housekeeping", TaskCategory.HOUSEKEEPING),
    )

    def __init__(self, controller: PresentationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ICU Tracker Task Board")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(900, 600)
        self.resize(1100, 680)
        self.panes: dict[TaskCategory, TaskBoardPane] = {}
        self.category_toggles: dict[TaskCategory, QCheckBox] = {}
        category_row = QHBoxLayout()
        grid = QGridLayout()
        for index, (title, category) in enumerate(self._PANES):
            label = {
                TaskCategory.CLINICAL: "To Do",
                TaskCategory.POCUS: "POCUS",
                TaskCategory.DIAGNOSTIC: "Diagnostics",
                TaskCategory.HOUSEKEEPING: "Housekeeping",
            }[category]
            toggle = QCheckBox(label)
            toggle.setChecked(True)
            toggle.toggled.connect(
                lambda visible, category=category: self._set_category_visible(
                    category, visible
                )
            )
            self.category_toggles[category] = toggle
            category_row.addWidget(toggle)
            pane = TaskBoardPane(title, category, controller, self)
            pane.navigated.connect(self.navigated)
            pane.diagnostic_result_requested.connect(self.diagnostic_result_requested)
            self.panes[category] = pane
            grid.addWidget(pane, index // 2, index % 2)
        refresh_button = QPushButton("Refresh")
        close_button = QPushButton("Close")
        refresh_button.clicked.connect(self.refresh)
        close_button.clicked.connect(self.hide)
        guidance = QLabel(
            "Check or update a row; double-click to jump to its patient and hospital day."
        )
        guidance.setObjectName("taskBoardGuidance")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(refresh_button)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(guidance)
        layout.addLayout(category_row)
        layout.addLayout(grid, 1)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        for pane in self.panes.values():
            pane.refresh()

    def _set_category_visible(self, category: TaskCategory, visible: bool) -> None:
        self.panes[category].setVisible(visible)

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)
