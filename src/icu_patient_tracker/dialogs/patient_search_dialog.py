"""Legacy-oriented live patient search window."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListView, QVBoxLayout, QWidget

from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.models import ListRow, StableListModel


class PatientSearchDialog(QDialog):
    """Select an admitted patient from a compact keyboard-first search surface."""

    def __init__(
        self,
        controller: PresentationController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self._controller = controller
        self.setWindowTitle("Patient Search")
        self.resize(440, 380)
        self.search = QLineEdit()
        self.search.setAccessibleName("Patient search query")
        self.results = QListView()
        self.results.setAccessibleName("Patient search results")
        self.model = StableListModel()
        self.results.setModel(self.model)
        self.preview = QLabel("No matching patients")
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.preview)
        self.search.textChanged.connect(self.refresh)
        self.results.clicked.connect(self._update_preview)
        self.results.doubleClicked.connect(self._activate)
        self.refresh()

    def show_search(self) -> None:
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
        self.search.selectAll()

    def refresh(self) -> None:
        selected = self.selected_id()
        patients = self._controller.patients(self.search.text())
        self.model.replace(
            ListRow(patient.id, patient.name, f"MRN {patient.mrn or 'Not recorded'}")
            for patient in patients
        )
        index = self.model.index_for(selected)
        if not index.isValid() and self.model.rowCount() > 0:
            index = self.model.index(0, 0)
        if index.isValid():
            self.results.setCurrentIndex(index)
        self._update_preview()

    def selected_id(self) -> UUID | None:
        value = self.model.identifier(self.results.currentIndex())
        return value if isinstance(value, UUID) else None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._activate()
            return
        super().keyPressEvent(event)

    def _update_preview(self, index: QModelIndex | None = None) -> None:
        del index
        row = self.results.currentIndex().row()
        count = self.model.rowCount()
        self.preview.setText(
            "No matching patients"
            if row < 0
            else f"Preview: {self.model.data(self.results.currentIndex())} ({row + 1}/{count})"
        )

    def _activate(self, index: QModelIndex | None = None) -> None:
        del index
        patient_id = self.selected_id()
        if patient_id is not None and self._controller.select_patient(patient_id):
            self.accept()
