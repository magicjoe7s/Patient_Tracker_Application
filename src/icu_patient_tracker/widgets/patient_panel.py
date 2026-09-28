"""Patient census navigation and confirmation-driven lifecycle actions."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.dialogs.new_patient_dialog import NewPatientDialog
from icu_patient_tracker.domain.enums import AdmissionStatus
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.services.search_service import SearchSort, SearchView
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.models import ListRow, StableListModel
from icu_patient_tracker.widgets.task_panel import TaskPanel

DISPOSITION_LABELS = {
    AdmissionStatus.ADMITTED: "Active",
    AdmissionStatus.DISCHARGED: "Home",
    AdmissionStatus.TRANSFERRED: "IMC",
    AdmissionStatus.ARCHIVED: "Archived",
    AdmissionStatus.DECEASED: "Death",
}

SEARCH_VIEW_LABELS = {
    SearchView.ALL_ACTIVE: "All Active",
    SearchView.NEEDS_ATTENTION: "Needs Attention",
    SearchView.NO_TODAY: "No Today",
    SearchView.PENDING_DIAGNOSTIC: "Pending DX",
    SearchView.OPEN_TODOS: "Open To-Dos",
    SearchView.CRITICAL_WATCHER: "Critical/Watcher",
}


class PatientPanel(QWidget):
    """Render the census and delegate patient intent to the controller."""

    new_day_requested = Signal()
    task_board_requested = Signal()
    menu_requested = Signal()
    popup_requested = Signal()
    backup_requested = Signal()
    collapse_requested = Signal()

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self.model = StableListModel()

        self.search = QLineEdit()
        self.search.setObjectName("patientSearch")
        self.search.setPlaceholderText("Search patients…")
        self.search.setAccessibleName("Patient search")

        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Census disposition bin")
        self.status_filter.addItem("Active", AdmissionStatus.ADMITTED)
        self.status_filter.addItem("All bins", None)
        for status in AdmissionStatus:
            if status is not AdmissionStatus.ADMITTED:
                self.status_filter.addItem(DISPOSITION_LABELS[status], status)
        self.view_filter = QComboBox()
        self.view_filter.setAccessibleName("Census clinical filter")
        for view, label in SEARCH_VIEW_LABELS.items():
            self.view_filter.addItem(label, view)
        self.sort_mode = QComboBox()
        for sort in SearchSort:
            self.sort_mode.addItem(sort.value.title(), sort)

        self.clear_search_button = QPushButton("X")
        self.clear_search_button.setAccessibleName("Clear patient search")
        self.popup_button = QPushButton("Popup")
        self.show_bins = QCheckBox("Show bins")

        self.list_view = QListView()
        self.list_view.setObjectName("patientList")
        self.list_view.setAccessibleName("Patient census")
        self.list_view.setModel(self.model)
        self.empty_label = QLabel("No patients in this census view")

        self.new_button = QPushButton("New Patient")
        self.new_day_button = QPushButton("New Day")
        self.backup_button = QPushButton("Backup")
        self.rename_button = QPushButton("Rename")
        self.details_button = QPushButton("Edit Details")
        self.status_button = QPushButton("Disposition")
        self.readmit_button = QPushButton("Readmit")
        self.archive_button = QPushButton("Archive")
        self.purge_button = QPushButton("Delete Permanently")
        self.move_up_button = QPushButton("Move Up")
        self.move_down_button = QPushButton("Move Down")

        self.patients_mode_button = QPushButton("[Patients]")
        self.tasks_mode_button = QPushButton("Tasks")
        self.collapse_button = QPushButton("<")
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.patients_mode_button, 1)
        mode_row.addWidget(self.tasks_mode_button, 1)
        mode_row.addWidget(self.collapse_button)

        actions_group = QGroupBox("Actions")
        actions = QHBoxLayout(actions_group)
        actions.addWidget(self.new_button)
        actions.addWidget(self.new_day_button)
        actions.addWidget(self.backup_button)

        filters_group = QGroupBox("Filters")
        filters_layout = QVBoxLayout(filters_group)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.clear_search_button)
        search_row.addWidget(self.popup_button)
        filters_layout.addLayout(search_row)
        filters_layout.addWidget(self.show_bins)
        for label, control in (
            ("Status:", self.status_filter),
            ("View:", self.view_filter),
            ("Sort:", self.sort_mode),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(control, 1)
            filters_layout.addLayout(row)

        self.census_status = QLabel()
        self.census_status.setObjectName("censusStatus")
        self.selected_status = QLabel("Selected: none")
        self.selected_status.setWordWrap(True)
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        status_layout.addWidget(self.census_status)
        status_layout.addWidget(self.selected_status)

        self.home_button = QPushButton("Home")
        self.imc_button = QPushButton("IMC")
        self.active_button = QPushButton("Active")
        self.death_button = QPushButton("Death")
        self.menu_button = QPushButton("Menu")
        disposition_row = QHBoxLayout()
        for button in (
            self.home_button,
            self.imc_button,
            self.active_button,
            self.death_button,
            self.menu_button,
        ):
            disposition_row.addWidget(button)

        self.patient_menu = QMenu(self)
        for label, button in (
            ("Rename Selected", self.rename_button),
            ("Edit Patient Details", self.details_button),
            ("Change Disposition", self.status_button),
            ("Readmit to ICU", self.readmit_button),
            ("Archive", self.archive_button),
            ("Delete Permanently", self.purge_button),
            ("Move Up", self.move_up_button),
            ("Move Down", self.move_down_button),
        ):
            action = self.patient_menu.addAction(label)
            action.triggered.connect(button.click)

        self.patient_page = QWidget()
        patient_layout = QVBoxLayout(self.patient_page)
        patient_layout.setContentsMargins(0, 0, 0, 0)
        patient_layout.addWidget(actions_group)
        patient_layout.addWidget(filters_group)
        patient_layout.addWidget(status_group)
        patient_layout.addWidget(self.list_view, 1)
        patient_layout.addWidget(self.empty_label)
        patient_layout.addLayout(disposition_row)

        self.sidebar_tasks = TaskPanel(controller)
        self.open_task_board_button = QPushButton("Open Task Board")
        self.task_page = QWidget()
        task_layout = QVBoxLayout(self.task_page)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.addWidget(self.sidebar_tasks, 1)
        task_layout.addWidget(self.open_task_board_button)
        self.sidebar_stack = QStackedWidget()
        self.sidebar_stack.addWidget(self.patient_page)
        self.sidebar_stack.addWidget(self.task_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(mode_row)
        layout.addWidget(self.sidebar_stack, 1)

        self.search.textChanged.connect(self.refresh)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.view_filter.currentIndexChanged.connect(self.refresh)
        self.sort_mode.currentIndexChanged.connect(self.refresh)
        self.show_bins.toggled.connect(self._toggle_bins)
        self.clear_search_button.clicked.connect(self.search.clear)
        self.popup_button.clicked.connect(self.popup_requested)
        self.new_day_button.clicked.connect(self.new_day_requested)
        self.backup_button.clicked.connect(self.backup_requested)
        self.patients_mode_button.clicked.connect(self.show_patients_mode)
        self.tasks_mode_button.clicked.connect(self.show_tasks_mode)
        self.open_task_board_button.clicked.connect(self.task_board_requested)
        self.collapse_button.clicked.connect(self.collapse_requested)
        self.menu_button.clicked.connect(self.menu_requested)
        self.home_button.clicked.connect(lambda: self._set_disposition(AdmissionStatus.DISCHARGED))
        self.imc_button.clicked.connect(lambda: self._set_disposition(AdmissionStatus.TRANSFERRED))
        self.active_button.clicked.connect(lambda: self._set_disposition(AdmissionStatus.ADMITTED))
        self.death_button.clicked.connect(lambda: self._set_disposition(AdmissionStatus.DECEASED))
        self.list_view.clicked.connect(self._select)
        self.list_view.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._update_action_state()
        )
        self.new_button.clicked.connect(self.prompt_create)
        self.rename_button.clicked.connect(self._prompt_rename)
        self.details_button.clicked.connect(self._prompt_details)
        self.status_button.clicked.connect(self._prompt_status)
        self.readmit_button.clicked.connect(self._readmit)
        self.archive_button.clicked.connect(self._confirm_archive)
        self.purge_button.clicked.connect(self._confirm_purge)
        self.move_up_button.clicked.connect(lambda: self._move(-1))
        self.move_down_button.clicked.connect(lambda: self._move(1))
        self._toggle_bins(False)
        self.refresh()

    def show_patients_mode(self) -> None:
        self.sidebar_stack.setCurrentWidget(self.patient_page)
        self.patients_mode_button.setText("[Patients]")
        self.tasks_mode_button.setText("Tasks")

    def show_tasks_mode(self) -> None:
        self.sidebar_tasks.refresh()
        self.sidebar_stack.setCurrentWidget(self.task_page)
        self.patients_mode_button.setText("Patients")
        self.tasks_mode_button.setText("[Tasks]")

    def refresh(self) -> None:
        selected = self._controller.context.patient_id
        raw_status = self.status_filter.currentData()
        raw_sort = self.sort_mode.currentData()
        raw_view = self.view_filter.currentData()
        status = AdmissionStatus(str(raw_status)) if raw_status is not None else None
        sort = SearchSort(str(raw_sort)) if raw_sort is not None else SearchSort.MANUAL
        view = SearchView(str(raw_view)) if raw_view is not None else SearchView.ALL_ACTIVE
        patients = self._controller.patients(
            self.search.text(), status=status, sort=sort, view=view
        )
        self.model.replace(self._row(patient) for patient in patients)
        self.empty_label.setVisible(not patients)
        index = self.model.index_for(selected)
        if index.isValid():
            self.list_view.setCurrentIndex(index)
        self._update_action_state()

    def _toggle_bins(self, visible: bool) -> None:
        self.status_filter.setVisible(visible)
        if not visible and self.status_filter.currentIndex() != 0:
            self.status_filter.setCurrentIndex(0)

    def _set_disposition(self, status: AdmissionStatus) -> None:
        patient = self._selected_patient()
        if patient is None or status not in patient.allowed_admission_statuses:
            return
        if status is AdmissionStatus.DECEASED:
            answer = QMessageBox.question(
                self,
                "Confirm death status",
                "Mark the selected patient as deceased? This clinical status requires "
                "explicit confirmation.",
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
        if self._controller.change_patient_status(patient.id, status):
            self.refresh()

    def create_patient(self, *, mrn: str | None, name: str, species: str) -> bool:
        patient = self._controller.create_patient(mrn=mrn, name=name, species=species)
        if patient is None:
            return False
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        self.refresh()
        self._controller.select_patient(patient.id)
        self.list_view.setCurrentIndex(self.model.index_for(patient.id))
        self._update_action_state()
        return True

    def prompt_create(self) -> None:
        """Collect identity in an independent window while the tracker is minimized."""
        main_window = self.window()
        main_window.showMinimized()
        dialog = NewPatientDialog()
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                values = dialog.values()
                self.create_patient(
                    mrn=values.mrn,
                    name=values.name,
                    species=values.species,
                )
        finally:
            main_window.showNormal()
            main_window.raise_()
            main_window.activateWindow()

    def prompt_rename(self) -> None:
        """Expose rename intent to registered keyboard and command surfaces."""
        self._prompt_rename()

    def _select(self, index: QModelIndex) -> None:
        identifier = self.model.identifier(index)
        if isinstance(identifier, UUID):
            self._controller.select_patient(identifier)
            self._update_action_state()

    def _prompt_rename(self) -> None:
        patient = self._selected_patient()
        if patient is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename Patient", "Patient name:", text=patient.name
        )
        if accepted and name.strip() and self._controller.rename_patient(patient.id, name):
            self.refresh()

    def _prompt_details(self) -> None:
        patient = self._selected_patient()
        if patient is None:
            return
        choices = ["Canine", "Feline"]
        if patient.species not in choices:
            choices.append(patient.species)
        species, accepted = QInputDialog.getItem(
            self,
            "Edit Patient Details",
            "Species:",
            choices,
            choices.index(patient.species),
            editable=False,
        )
        if not accepted:
            return
        if self._controller.update_patient_identity_details(
            patient.id, mrn=patient.mrn, species=species
        ):
            self.refresh()

    def _prompt_status(self) -> None:
        patient = self._selected_patient()
        if patient is None:
            return
        statuses = list(patient.allowed_admission_statuses)
        if not statuses:
            return
        labels = [DISPOSITION_LABELS[status] for status in statuses]
        value, accepted = QInputDialog.getItem(
            self, "Change Patient Disposition", "New disposition:", labels, editable=False
        )
        if not accepted:
            return
        target = statuses[labels.index(value)]
        if target is AdmissionStatus.DECEASED:
            answer = QMessageBox.question(
                self,
                "Confirm death status",
                "Mark the selected patient as deceased? This clinical status requires "
                "explicit confirmation.",
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
        if target is AdmissionStatus.ARCHIVED and not self._confirm_archive_change():
            return
        if self._controller.change_patient_status(patient.id, target):
            self.refresh()

    def _readmit(self) -> None:
        patient = self._selected_patient()
        if patient is not None and self._controller.readmit_patient(patient.id):
            self.status_filter.setCurrentIndex(0)
            self.refresh()
            self.list_view.setCurrentIndex(self.model.index_for(patient.id))

    def _confirm_archive(self) -> None:
        patient = self._selected_patient()
        if patient is None or not self._confirm_archive_change():
            return
        if self._controller.archive_patient(patient.id):
            self.refresh()

    def _confirm_archive_change(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Confirm archive",
            "Archive the selected patient? The record will leave the active census but remain "
            "available for readmission.",
        )
        return answer is QMessageBox.StandardButton.Yes

    def _confirm_purge(self) -> None:
        patient = self._selected_patient()
        if patient is None:
            return
        answer = QMessageBox.warning(
            self,
            "Confirm permanent deletion",
            "Permanently delete this archived patient and all owned records? "
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is QMessageBox.StandardButton.Yes and self._controller.purge_patient(patient.id):
            self.refresh()

    def _move(self, offset: int) -> None:
        patient = self._selected_patient()
        if (
            patient is not None
            and self._controller.move_active_patient(patient.id, offset) is not None
        ):
            self.refresh()

    def _selected_patient(self) -> Patient | None:
        identifier = self.model.identifier(self.list_view.currentIndex())
        if not isinstance(identifier, UUID):
            return None
        patient = self._controller.selected_patient()
        if patient is not None and patient.id == identifier:
            return patient
        return None

    def _update_action_state(self) -> None:
        patient = self._selected_patient()
        counts = {
            status: len(self._controller.patients(status=status)) for status in AdmissionStatus
        }
        self.census_status.setText(
            f"Active {counts[AdmissionStatus.ADMITTED]} | "
            f"Home {counts[AdmissionStatus.DISCHARGED]} | "
            f"IMC {counts[AdmissionStatus.TRANSFERRED]} | "
            f"Shown {self.model.rowCount()}"
        )
        self.selected_status.setText(
            "Selected: none"
            if patient is None
            else f"Selected: {patient.name} | {DISPOSITION_LABELS[patient.admission_status]}"
        )
        if patient is None:
            for button in (
                self.rename_button,
                self.details_button,
                self.status_button,
                self.readmit_button,
                self.archive_button,
                self.purge_button,
                self.move_up_button,
                self.move_down_button,
            ):
                button.setEnabled(False)
            for button in (
                self.home_button,
                self.imc_button,
                self.active_button,
                self.death_button,
            ):
                button.setEnabled(False)
            return
        self.rename_button.setEnabled(True)
        self.details_button.setEnabled(True)
        self.status_button.setEnabled(bool(patient.allowed_admission_statuses))
        self.readmit_button.setEnabled(
            patient.admission_status
            in {
                AdmissionStatus.DISCHARGED,
                AdmissionStatus.TRANSFERRED,
                AdmissionStatus.ARCHIVED,
            }
        )
        self.archive_button.setEnabled(
            patient.admission_status
            in {
                AdmissionStatus.ADMITTED,
                AdmissionStatus.DISCHARGED,
                AdmissionStatus.TRANSFERRED,
            }
        )
        self.purge_button.setEnabled(patient.admission_status is AdmissionStatus.ARCHIVED)
        manual_active = (
            patient.admission_status is AdmissionStatus.ADMITTED
            and self.sort_mode.currentData() == SearchSort.MANUAL
        )
        self.move_up_button.setEnabled(manual_active)
        self.move_down_button.setEnabled(manual_active)
        self.home_button.setEnabled(
            AdmissionStatus.DISCHARGED in patient.allowed_admission_statuses
        )
        self.imc_button.setEnabled(
            AdmissionStatus.TRANSFERRED in patient.allowed_admission_statuses
        )
        self.active_button.setEnabled(
            AdmissionStatus.ADMITTED in patient.allowed_admission_statuses
        )
        self.death_button.setEnabled(AdmissionStatus.DECEASED in patient.allowed_admission_statuses)

    @staticmethod
    def _row(patient: Patient) -> ListRow:
        latest = patient.hospital_days[-1] if patient.hospital_days else None
        acuity = latest.acuity if latest is not None else patient.acuity
        metadata = (
            f"{patient.species} · {acuity.value} · "
            f"{DISPOSITION_LABELS[patient.admission_status]} · "
            f"MRN {patient.mrn or 'Not recorded'}"
        )
        return ListRow(patient.id, patient.name, metadata)
