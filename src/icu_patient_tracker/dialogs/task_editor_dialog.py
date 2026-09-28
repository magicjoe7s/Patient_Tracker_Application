"""Structured task editor with optional compact-grammar entry."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.enums import ClinicalPriority, TaskBucket, TaskCategory
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.ui.save_shortcut import bind_standard_save
from icu_patient_tracker.utils.task_input import TaskInput, parse_task_input


@dataclass(frozen=True, slots=True)
class TaskEditorValues:
    """Values collected by the structured task editor."""

    title: str
    category: TaskCategory
    priority: ClinicalPriority
    bucket: TaskBucket
    carry_forward: bool


class TaskEditorDialog(QDialog):
    """Collect task metadata without encoding it into the stored title."""

    CATEGORIES = (
        ("To Do", TaskCategory.CLINICAL),
        ("POCUS", TaskCategory.POCUS),
        ("Pending Diagnostic", TaskCategory.DIAGNOSTIC),
        ("Housekeeping", TaskCategory.HOUSEKEEPING),
    )

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        task: Task | None = None,
        category: TaskCategory = TaskCategory.CLINICAL,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Task" if task is not None else "Add Task")
        self.title = QLineEdit(task.title if task is not None else "")
        self.title.setPlaceholderText("Title, or compact grammar such as Lactate | r:60m")
        self.category = QComboBox()
        for label, task_category in self.CATEGORIES:
            self.category.addItem(label, task_category)
        selected_category = task.category if task is not None else category
        self.category.setCurrentIndex(self.category.findData(selected_category))
        self.bucket = QComboBox()
        for bucket in TaskBucket:
            self.bucket.addItem(bucket.value.replace("_", " ").title(), bucket)
        default_bucket = (
            task.bucket
            if task is not None
            else TaskBucket.DIAGNOSTIC
            if category is TaskCategory.DIAGNOSTIC
            else TaskBucket.TODAY
        )
        self.bucket.setCurrentIndex(self.bucket.findData(default_bucket))
        self.priority = QComboBox()
        for priority in ClinicalPriority:
            self.priority.addItem(priority.value.title(), priority)
        selected_priority = task.priority if task is not None else ClinicalPriority.ROUTINE
        self.priority.setCurrentIndex(self.priority.findData(selected_priority))
        self.carry_forward = QCheckBox("Carry incomplete task to the next hospital day")
        self.carry_forward.setChecked(task.carry_forward if task is not None else True)
        form = QFormLayout()
        form.addRow("Title", self.title)
        form.addRow("Task type", self.category)
        form.addRow("Priority", self.priority)
        self.bucket_label = QLabel("Bucket")
        form.addRow(self.bucket_label, self.bucket)
        form.addRow("", self.carry_forward)
        hint = QLabel(
            "Compact entry also accepts | r: and | nocarry. "
            "A reminder token is applied when adding a new task."
        )
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bind_standard_save(buttons)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.category.currentIndexChanged.connect(self._update_bucket_visibility)
        self._update_bucket_visibility()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def _update_bucket_visibility(self) -> None:
        """Keep workflow buckets out of the ordinary To Do editor."""
        visible = TaskCategory(str(self.category.currentData())) is not TaskCategory.CLINICAL
        self.bucket_label.setVisible(visible)
        self.bucket.setVisible(visible)

    def values(self) -> TaskEditorValues:
        """Return explicit control values for a plain title."""
        return TaskEditorValues(
            title=self.title.text().strip(),
            category=TaskCategory(str(self.category.currentData())),
            priority=ClinicalPriority(str(self.priority.currentData())),
            bucket=TaskBucket(str(self.bucket.currentData())),
            carry_forward=self.carry_forward.isChecked(),
        )

    def compact_input(self) -> TaskInput | None:
        """Parse compact syntax only when the title visibly uses that syntax."""
        value = self.title.text().strip()
        if "|" not in value and not value.startswith(("!", "[", "-", "*", "+")):
            return None
        return parse_task_input(
            value,
            TaskCategory(str(self.category.currentData())),
            discard_invalid_reminder=True,
        )
