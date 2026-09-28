"""Structured editor for one problem occurrence and its forward lineage values."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.ui.save_shortcut import bind_standard_save


@dataclass(frozen=True, slots=True)
class ProblemEditorValues:
    """Editable structured values collected from the problem dialog."""

    title: str
    description: str


class ProblemEditorDialog(QDialog):
    """Collect problem content without owning persistence or lineage behavior."""

    def __init__(self, parent: QWidget | None = None, *, problem: Problem | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Problem" if problem is not None else "Add Problem")
        self.title = QLineEdit(problem.title if problem is not None else "")
        self.description = QPlainTextEdit(problem.description if problem is not None else "")
        form = QFormLayout()
        form.addRow("Problem", self.title)
        self.description.setPlaceholderText("One supporting detail per line")
        form.addRow("Supporting details", self.description)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bind_standard_save(buttons)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def values(self) -> ProblemEditorValues:
        """Return validated-enum values; domain validation owns required text rules."""
        return ProblemEditorValues(
            title=self.title.text().strip(),
            description=self.description.toPlainText(),
        )
