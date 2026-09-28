"""Compact independent editor for creating one patient."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from icu_patient_tracker.ui.save_shortcut import bind_standard_save


@dataclass(frozen=True, slots=True)
class NewPatientValues:
    name: str
    mrn: str | None
    species: str


class NewPatientDialog(QDialog):
    """Collect patient identity while leaving the EMR visible behind it."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("New Patient")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.name = QLineEdit()
        self.name.setPlaceholderText("Patient name")
        self.mrn = QLineEdit()
        self.mrn.setPlaceholderText("6-digit MRN")
        self.mrn.setMaxLength(6)
        self.mrn.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}")))
        self.species = QComboBox()
        self.species.addItems(("Canine", "Feline"))
        form = QFormLayout()
        form.addRow("Patient name", self.name)
        form.addRow("MRN", self.mrn)
        form.addRow("Species", self.species)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bind_standard_save(buttons)
        buttons.accepted.connect(self._accept_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(360, self.sizeHint().height())

    def values(self) -> NewPatientValues:
        return NewPatientValues(
            self.name.text().strip(),
            self.mrn.text().strip() or None,
            self.species.currentText(),
        )

    def _accept_valid(self) -> None:
        if self.name.text().strip():
            self.accept()
        else:
            self.name.setFocus()
