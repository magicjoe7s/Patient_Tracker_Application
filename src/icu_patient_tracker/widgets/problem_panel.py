"""Selected-day ordered running-problem workflow."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QListView,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.dialogs.problem_editor_dialog import ProblemEditorDialog
from icu_patient_tracker.domain.enums import ClinicalPriority, ProblemStatus
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.models import ListRow, StableListModel


class ProblemPanel(QWidget):
    """Render ordered daily occurrences and delegate forward lineage mutations."""

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self._problems: dict[UUID, Problem] = {}
        self.model = StableListModel()
        self.model.set_movable(True)
        self.list_view = QListView()
        self.list_view.setObjectName("problemList")
        self.list_view.setAccessibleName("Problems for selected hospital day")
        self.list_view.setModel(self.model)
        self.list_view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_view.setDragDropOverwriteMode(False)
        self.add_button = QPushButton("Add")
        self.resolve_button = QPushButton("Resolve")
        self.reopen_button = QPushButton("Reopen")
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.resolve_button,
            self.reopen_button,
            self.remove_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list_view)
        layout.addLayout(buttons)
        self.add_button.clicked.connect(self._prompt_add)
        self.resolve_button.clicked.connect(
            lambda: self._set_status(ProblemStatus.RESOLVED)
        )
        self.reopen_button.clicked.connect(lambda: self._set_status(ProblemStatus.ACTIVE))
        self.remove_button.clicked.connect(self._confirm_remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.list_view.doubleClicked.connect(self._prompt_edit)
        self.list_view.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._update_action_state()
        )
        self.model.rowsMoved.connect(lambda *_args: self._persist_drag_order())

    def refresh(self) -> None:
        selected = self.selected_id()
        context = self._controller.context
        problems = (
            ()
            if context.patient_id is None or context.hospital_day_id is None
            else self._controller.problems()
        )
        self._problems = {problem.id: problem for problem in problems}
        self.model.replace(
            ListRow(
                problem.id,
                f"{problem.ordering_position + 1}. {problem.title}",
                " · ".join(
                    part
                    for part in (
                        "; ".join(
                            line.strip()
                            for line in problem.description.splitlines()
                            if line.strip()
                        ),
                    )
                    if part
                ),
            )
            for problem in problems
        )
        index = self.model.index_for(selected)
        if index.isValid():
            self.list_view.setCurrentIndex(index)
        self._update_action_state()

    def add_problem(
        self,
        title: str,
        *,
        description: str = "",
        priority: ClinicalPriority = ClinicalPriority.ROUTINE,
    ) -> bool:
        created = self._controller.add_problem(title, description=description, priority=priority)
        if created is None:
            return False
        self.refresh()
        self.list_view.setCurrentIndex(self.model.index_for(created.id))
        return True

    def selected_id(self) -> UUID | None:
        value = self.model.identifier(self.list_view.currentIndex())
        return value if isinstance(value, UUID) else None

    def _prompt_add(self) -> None:
        dialog = ProblemEditorDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values.title:
            self._controller.error_raised.emit("Invalid problem", "Problem title is required.")
            return
        created = self._controller.add_problem(
            values.title,
            description=values.description,
        )
        if created is not None:
            self.refresh()
            self.list_view.setCurrentIndex(self.model.index_for(created.id))

    def _prompt_edit(self, index: QModelIndex | None = None) -> None:
        del index
        problem_id = self.selected_id()
        if problem_id is None:
            return
        dialog = ProblemEditorDialog(self, problem=self._problems[problem_id])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        current = self._problems[problem_id]
        if values.title and self._controller.update_problem(
            problem_id,
            title=values.title,
            description=values.description,
            priority=current.priority,
            assessment=current.assessment,
            plan=current.plan,
            notes=current.notes,
        ):
            self.refresh()

    def _set_status(self, target: ProblemStatus) -> None:
        problem_id = self.selected_id()
        if problem_id is None:
            return
        if self._controller.set_problem_status(problem_id, target):
            self.refresh()

    def _toggle_status(self) -> None:
        """Retain the existing direct test seam."""
        problem_id = self.selected_id()
        if problem_id is None:
            return
        target = (
            ProblemStatus.ACTIVE
            if self._problems[problem_id].status is ProblemStatus.RESOLVED
            else ProblemStatus.RESOLVED
        )
        self._set_status(target)

    def _confirm_remove(self) -> None:
        problem_id = self.selected_id()
        if problem_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove problem forward",
            "Remove this problem from the selected day and all later carried occurrences? "
            "Earlier hospital days will remain unchanged.",
        )
        if answer is QMessageBox.StandardButton.Yes and self._controller.remove_problem(problem_id):
            self.refresh()

    def _remove(self) -> None:
        """Retain the existing direct test seam while using forward removal semantics."""
        problem_id = self.selected_id()
        if problem_id is not None and self._controller.remove_problem(problem_id):
            self.refresh()

    def _move(self, offset: int) -> None:
        problem_id = self.selected_id()
        ordered = list(self._problems)
        if problem_id is None:
            return
        position = ordered.index(problem_id)
        target = position + offset
        if 0 <= target < len(ordered):
            ordered[position], ordered[target] = ordered[target], ordered[position]
            if self._controller.reorder_problems(ordered):
                self.refresh()
                self.list_view.setCurrentIndex(self.model.index_for(problem_id))

    def _persist_drag_order(self) -> None:
        """Persist the UUID order produced by a drag instead of relying on row text."""
        ordered = [value for value in self.model.identifiers() if isinstance(value, UUID)]
        if len(ordered) == len(self._problems):
            self._controller.reorder_problems(ordered)

    def _update_action_state(self) -> None:
        selected_id = self.selected_id()
        has_selection = selected_id is not None
        selected = self._problems.get(selected_id) if selected_id is not None else None
        self.resolve_button.setEnabled(
            selected is not None and selected.status is not ProblemStatus.RESOLVED
        )
        self.reopen_button.setEnabled(
            selected is not None and selected.status is ProblemStatus.RESOLVED
        )
        self.remove_button.setEnabled(has_selection)
        self.up_button.setEnabled(has_selection)
        self.down_button.setEnabled(has_selection)
