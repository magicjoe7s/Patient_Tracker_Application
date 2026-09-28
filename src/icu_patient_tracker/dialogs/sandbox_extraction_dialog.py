"""Explicit checklist extraction preview for Sandbox Markdown."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from icu_patient_tracker.services.sandbox_service import SandboxExtractionPreview


class SandboxExtractionDialog(QDialog):
    """Let the user confirm individual validated task candidates before persistence."""

    def __init__(self, preview: SandboxExtractionPreview, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Extract Sandbox tasks")
        self.candidates = QListWidget()
        self.candidates.setAccessibleName("Sandbox task extraction candidates")
        for candidate in preview.candidates:
            item = QListWidgetItem(
                f"Line {candidate.line_number}: {candidate.task.title} "
                f"({candidate.task.category.value})"
            )
            item.setData(Qt.ItemDataRole.UserRole, candidate.line_number)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.candidates.addItem(item)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create selected tasks")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Only unchecked Markdown checklist rows are shown. "
                "The Sandbox text will not be changed."
            )
        )
        layout.addWidget(self.candidates)
        if preview.ignored:
            layout.addWidget(
                QLabel(f"{len(preview.ignored)} row(s) skipped as duplicate or invalid.")
            )
        layout.addWidget(buttons)

    def selected_line_numbers(self) -> tuple[int, ...]:
        """Return checked source line numbers in display order."""
        selected: list[int] = []
        for index in range(self.candidates.count()):
            item = self.candidates.item(index)
            if item.checkState() is Qt.CheckState.Checked:
                value = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(value, int):
                    selected.append(value)
        return tuple(selected)
