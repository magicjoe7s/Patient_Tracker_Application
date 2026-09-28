"""Selected-day categorized task workflow."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QListView,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.dialogs.task_editor_dialog import TaskEditorDialog
from icu_patient_tracker.domain.enums import ReminderScheduleType, TaskCategory, TaskStatus
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.models import ListRow, StableListModel


class TaskPanel(QWidget):
    """Display categorized occurrences while delegating lineage behavior to services."""

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self._tasks: dict[UUID, Task] = {}
        self._preferred_category = TaskCategory.CLINICAL
        self.model = StableListModel()
        self.list_view = QListView()
        self.list_view.setObjectName("taskList")
        self.list_view.setAccessibleName("Tasks for selected hospital day")
        self.list_view.setModel(self.model)
        self.category_toggles: dict[TaskCategory, QCheckBox] = {}
        category_row = QHBoxLayout()
        for label, category in TaskEditorDialog.CATEGORIES:
            if category is TaskCategory.ADMINISTRATIVE:
                continue
            toggle = QCheckBox(label)
            toggle.setChecked(True)
            toggle.toggled.connect(lambda _checked: self.refresh())
            self.category_toggles[category] = toggle
            category_row.addWidget(toggle)
        self.hide_completed_by_category: dict[TaskCategory, QCheckBox] = {}
        hide_row = QHBoxLayout()
        hide_labels = {
            TaskCategory.CLINICAL: "To Do",
            TaskCategory.POCUS: "POCUS",
            TaskCategory.DIAGNOSTIC: "Pending",
            TaskCategory.HOUSEKEEPING: "Housekeeping",
        }
        for category, label in hide_labels.items():
            toggle = QCheckBox(f"Hide completed {label}")
            toggle.toggled.connect(
                lambda hidden, category=category: self._hide_completed_changed(
                    category, hidden
                )
            )
            self.hide_completed_by_category[category] = toggle
            hide_row.addWidget(toggle)
        # Compatibility alias for callers that historically controlled To Do only.
        self.hide_completed = self.hide_completed_by_category[TaskCategory.CLINICAL]
        self.add_button = QPushButton("Add")
        self.edit_button = QPushButton("Edit")
        self.toggle_button = QPushButton("Complete / Reopen")
        self.omit_button = QPushButton("Omit Diagnostic")
        self.delete_button = QPushButton("Delete lineage")
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.toggle_button,
            self.omit_button,
            self.delete_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(category_row)
        layout.addLayout(hide_row)
        layout.addWidget(self.list_view)
        layout.addLayout(buttons)
        self.add_button.clicked.connect(lambda: self._prompt_add())
        self.edit_button.clicked.connect(self._prompt_edit)
        self.toggle_button.clicked.connect(self._toggle)
        self.omit_button.clicked.connect(self._omit_diagnostic)
        self.delete_button.clicked.connect(self._confirm_delete)
        self.list_view.doubleClicked.connect(self._prompt_edit)
        self.list_view.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._update_action_state()
        )
        self._load_hide_preference()

    def refresh(self) -> None:
        selected = self.selected_id()
        context = self._controller.context
        tasks = (
            ()
            if context.patient_id is None or context.hospital_day_id is None
            else self._controller.tasks()
        )
        self._tasks = {task.id: task for task in tasks}
        visible = tuple(
            task
            for task in tasks
            if self.category_toggles.get(task.category) is not None
            and self.category_toggles[task.category].isChecked()
            and (
                not self.hide_completed_by_category[task.category].isChecked()
                or task.status is not TaskStatus.COMPLETED
            )
        )
        self.model.replace(
            ListRow(
                task.id,
                ("✓ " if task.status is TaskStatus.COMPLETED else "") + task.title,
                f"{task.category.value} · {task.bucket.value}"
                + _reminder_label(task),
            )
            for task in visible
        )
        index = self.model.index_for(selected)
        if index.isValid():
            self.list_view.setCurrentIndex(index)
        self._update_action_state()

    def add_task(self, title: str, category: TaskCategory = TaskCategory.CLINICAL) -> bool:
        """Accept plain titles and the compact reference grammar."""
        task = self._controller.add_task_input(title, category)
        if task is None:
            return False
        self._preferred_category = task.category
        toggle = self.category_toggles.get(task.category)
        if toggle is not None:
            toggle.setChecked(True)
        self.refresh()
        self.list_view.setCurrentIndex(self.model.index_for(task.id))
        return True

    def selected_id(self) -> UUID | None:
        value = self.model.identifier(self.list_view.currentIndex())
        return value if isinstance(value, UUID) else None

    def selected_category(self) -> TaskCategory:
        task_id = self.selected_id()
        task = self._tasks.get(task_id) if task_id is not None else None
        return task.category if task is not None else self._preferred_category

    def select_category(self, category: TaskCategory) -> None:
        """Retain an explicitly focused category even when it has no visible tasks."""
        self._preferred_category = category
        toggle = self.category_toggles.get(category)
        if toggle is not None:
            toggle.setChecked(True)

    def prompt_add(self, category: TaskCategory) -> None:
        """Select a category and open the shared structured task editor."""
        self.select_category(category)
        self._prompt_add(category)

    def set_all_hide_completed(self, hidden: bool) -> None:
        """Persist one explicit visibility state for every task category."""
        config = self._controller.settings()
        if config is not None:
            preferences = dict(config.user_preferences)
            preferences["task_hide_completed"] = {
                category.value: hidden for category in TaskCategory
            }
            self._controller.update_settings(user_preferences=preferences)
        for toggle in self.hide_completed_by_category.values():
            toggle.blockSignals(True)
            toggle.setChecked(hidden)
            toggle.blockSignals(False)
        self.refresh()

    def reload_hide_preferences(self) -> None:
        self._load_hide_preference()
        self.refresh()

    def _prompt_add(self, category: TaskCategory = TaskCategory.CLINICAL) -> None:
        dialog = TaskEditorDialog(self, category=category)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            compact = dialog.compact_input()
        except ValueError as error:
            self._controller.error_raised.emit("Invalid task", str(error))
            return
        if compact is not None:
            self.add_task(dialog.title.text(), dialog.values().category)
            return
        values = dialog.values()
        if not values.title:
            self._controller.error_raised.emit("Invalid task", "Task title must not be empty.")
            return
        task = self._controller.add_task(
            values.title,
            category=values.category,
            priority=values.priority,
            bucket=values.bucket,
            carry_forward=values.carry_forward,
        )
        if task is not None:
            toggle = self.category_toggles.get(task.category)
            if toggle is not None:
                toggle.setChecked(True)
            self.refresh()
            self.list_view.setCurrentIndex(self.model.index_for(task.id))

    def _prompt_edit(self, index: QModelIndex | None = None) -> None:
        del index
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
                "The task text is empty. Delete this task and every carried occurrence?",
            )
            if answer is QMessageBox.StandardButton.Yes:
                self._controller.delete_task_lineage(self._tasks[task_id].lineage_id)
                self.refresh()
            return
        if self._controller.update_task(
            task_id,
            title=values.title,
            category=values.category,
            priority=values.priority,
            bucket=values.bucket,
            carry_forward=values.carry_forward,
        ):
            toggle = self.category_toggles.get(values.category)
            if toggle is not None:
                toggle.setChecked(True)
            self.refresh()

    def _toggle(self) -> None:
        task_id = self.selected_id()
        if task_id is not None and self._controller.toggle_task(self._tasks[task_id]):
            self.refresh()

    def _omit_diagnostic(self) -> None:
        task_id = self.selected_id()
        if task_id is not None and self._controller.omit_diagnostic(task_id):
            self.refresh()

    def _confirm_delete(self) -> None:
        task_id = self.selected_id()
        if task_id is None:
            return
        task = self._tasks[task_id]
        answer = QMessageBox.question(
            self,
            "Delete task lineage",
            "Delete this task and every carried occurrence in its lineage? This cannot be undone.",
        )
        if answer is QMessageBox.StandardButton.Yes and self._controller.delete_task_lineage(
            task.lineage_id
        ):
            self.refresh()

    def _load_hide_preference(self) -> None:
        config = self._controller.settings()
        preferences = config.user_preferences if config is not None else {}
        stored = preferences.get("task_hide_completed", {})
        for category, toggle in self.hide_completed_by_category.items():
            hidden = stored.get(category.value, True) if isinstance(stored, dict) else True
            toggle.blockSignals(True)
            toggle.setChecked(hidden is True)
            toggle.blockSignals(False)

    def _hide_completed_changed(self, category: TaskCategory, hidden: bool) -> None:
        config = self._controller.settings()
        if config is not None:
            preferences = dict(config.user_preferences)
            stored = preferences.get("task_hide_completed", {})
            by_category = dict(stored) if isinstance(stored, dict) else {}
            by_category[category.value] = hidden
            preferences["task_hide_completed"] = by_category
            self._controller.update_settings(user_preferences=preferences)
        self.refresh()

    def _update_action_state(self) -> None:
        task_id = self.selected_id()
        selected = self._tasks.get(task_id) if task_id is not None else None
        has_selection = selected is not None
        self.edit_button.setEnabled(has_selection)
        self.toggle_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.omit_button.setEnabled(
            selected is not None
            and selected.category is TaskCategory.DIAGNOSTIC
            and selected.status is not TaskStatus.COMPLETED
        )


def _reminder_label(task: Task) -> str:
    """Show the user-entered reminder rule while hiding internal timestamps."""
    reminder = task.reminder
    if reminder is None:
        return ""
    if (
        reminder.schedule_type is ReminderScheduleType.INTERVAL
        and reminder.interval_minutes is not None
    ):
        return f" · r:{reminder.interval_minutes}m"
    if (
        reminder.schedule_type is ReminderScheduleType.FIXED_TIME
        and reminder.fixed_time is not None
    ):
        return f" · r:{reminder.fixed_time:%H:%M}"
    return " · reminder set"
