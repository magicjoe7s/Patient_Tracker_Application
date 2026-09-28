"""Editor for fields owned by the selected patient rather than a hospital day."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.enums import Acuity, CodeStatus
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.text_refresh import set_line_text_safely, set_plain_text_safely
from icu_patient_tracker.utils.problem_list_text import (
    ProblemListEntry,
    parse_problem_list,
    render_problem_list,
)


class PatientSummaryPanel(QWidget):
    """Edit the complete patient-owned clinical summary as one unit."""

    task_board_requested = Signal()
    save_now_requested = Signal()
    mapping_refresh_requested = Signal()

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self._loaded_generation = -1
        self._base_recovery_values: dict[str, str] = {}
        self._base_problem_values: dict[str, str] = {"titles": ""}
        self._problem_draft_dirty = False
        self.name = QLineEdit()
        self.species = QComboBox()
        self.species.addItems(("Canine", "Feline"))
        self.acuity = QComboBox()
        for acuity in Acuity:
            label = "#INPUT#" if acuity is Acuity.UNKNOWN else acuity.value.title()
            self.acuity.addItem(label, acuity)
        self.code_status = QComboBox()
        for code_status in (
            CodeStatus.FULL_CODE,
            CodeStatus.DO_NOT_RESUSCITATE,
            CodeStatus.DVM_DISCRETION,
            CodeStatus.DNR_ASSIST,
        ):
            self.code_status.addItem(self._code_status_label(code_status), code_status)
        self.one_line_summary = QPlainTextEdit()
        self.one_line_summary.setPlaceholderText("Patient-level one-line summary")
        self.running_problems = QPlainTextEdit()
        self.running_problems.setObjectName("runningProblemList")
        self.running_problems.setAccessibleName("Running problem list")
        self.running_problems.setReadOnly(False)
        self.running_problems.setPlaceholderText(
            "1. Problem title\n   • Supporting detail\n2. Next problem"
        )
        self.name.setObjectName("patientNameEditor")
        self.name.setAccessibleName("Patient name")
        identity = QHBoxLayout()
        identity.addWidget(QLabel("Species:"))
        identity.addWidget(self.species, 1)
        self.name.hide()
        self.copy_name_button = QPushButton("Copy Name")
        self.copy_mrn_button = QPushButton("Copy MRN")
        self.task_board_button = QPushButton("Task Board")
        self.save_now_button = QPushButton("Save Now")
        self.save_now_button.hide()
        identity.addWidget(self.copy_name_button)
        identity.addWidget(self.copy_mrn_button)
        identity.addWidget(self.task_board_button)
        form = QGridLayout()
        form.addWidget(QLabel("Code status:"), 0, 0)
        form.addWidget(self.code_status, 0, 1)
        form.addWidget(QLabel("Patient acuity:"), 0, 2)
        form.addWidget(self.acuity, 0, 3)
        form.addWidget(QLabel("One Liner:"), 1, 0, 1, 2)
        form.addWidget(QLabel("Running Problem List:"), 1, 2, 1, 2)
        form.addWidget(self.one_line_summary, 2, 0, 1, 2)
        form.addWidget(self.running_problems, 2, 2, 1, 2)
        self.save_button = QPushButton("Save Patient Summary")
        self.save_button.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(identity)
        layout.addLayout(form)
        layout.addWidget(self.save_button)
        self.save_button.clicked.connect(self.save)
        self.copy_name_button.clicked.connect(self._copy_name)
        self.copy_mrn_button.clicked.connect(self._copy_mrn)
        self.task_board_button.clicked.connect(self.task_board_requested)
        self.save_now_button.clicked.connect(self._request_save_now)
        for editor in (self.name,):
            editor.textChanged.connect(self._mark_dirty)
        self.species.currentTextChanged.connect(self._mark_dirty)
        self.acuity.currentIndexChanged.connect(self._mark_dirty)
        self.code_status.currentIndexChanged.connect(self._mark_dirty)
        self.one_line_summary.textChanged.connect(self._mark_dirty)
        self.running_problems.textChanged.connect(self._mark_problem_draft)

    def refresh(self, *, force: bool = False) -> None:
        """Load the selected patient's persisted summary without creating edits."""
        patient = self._controller.selected_patient()
        replace_focused = force or self._loaded_generation != self._controller.context.generation
        controls = (
            self.name,
            self.species,
            self.acuity,
            self.code_status,
            self.one_line_summary,
        )
        for control in controls:
            control.blockSignals(True)
        if patient is None:
            for editor in (self.name,):
                editor.clear()
            self._set_species("Canine")
            self.one_line_summary.clear()
            self._set_problem_text("")
        else:
            set_line_text_safely(self.name, patient.name, force=replace_focused)
            self._set_species(patient.species)
            selected_day = self._controller.selected_day()
            selected_acuity = selected_day.acuity if selected_day is not None else patient.acuity
            self.acuity.setCurrentIndex(self.acuity.findData(selected_acuity))
            self.code_status.setCurrentIndex(self.code_status.findData(patient.code_status))
            set_plain_text_safely(
                self.one_line_summary, patient.one_line_summary, force=replace_focused
            )
            self.refresh_running_problems(force=True)
        for control in controls:
            control.blockSignals(False)
        self._loaded_generation = self._controller.context.generation
        self._base_recovery_values = self.recovery_values()
        self.setEnabled(patient is not None)

    def refresh_running_problems(self, *, force: bool = False) -> None:
        """Project the selected day's ordered problems without editing their ownership."""
        if self._problem_draft_dirty and not force:
            return
        context = self._controller.context
        if context.patient_id is None or context.hospital_day_id is None:
            self._set_problem_text("")
            return
        problems = self._controller.problems()
        self._set_problem_text(
            render_problem_list(
                tuple(ProblemListEntry(problem.title, problem.description) for problem in problems)
            )
        )

    def apply_problem_list(self) -> bool:
        if not self._problem_draft_dirty:
            return True
        draft_text = self.running_problems.toPlainText()
        entries = parse_problem_list(draft_text)
        if self._controller.replace_problem_entries(entries) is None:
            return False
        self._problem_draft_dirty = False
        self._base_problem_values = {"titles": draft_text}
        # Replacing QPlainTextEdit content resets its cursor and selection. Autosave can
        # reach this path while the clinician is still typing, so retain the exact draft
        # until focus leaves the editor. Explicit button saves may still normalize the
        # projection because clicking the button moves focus away first.
        if not self.running_problems.hasFocus():
            self.refresh_running_problems(force=True)
        return True

    def _set_problem_text(self, value: str) -> None:
        self.running_problems.blockSignals(True)
        set_plain_text_safely(self.running_problems, value)
        self.running_problems.blockSignals(False)
        self._problem_draft_dirty = False
        self._base_problem_values = {"titles": value}

    def _mark_problem_draft(self) -> None:
        self._problem_draft_dirty = True
        self._controller.mark_editor_dirty(
            "problem-list",
            self._save_problem_pending,
            base_values=self._base_problem_values,
            draft_values=self.problem_recovery_values,
        )

    def _request_save_now(self) -> None:
        if self.apply_problem_list():
            self.save_now_requested.emit()

    def problem_recovery_values(self) -> dict[str, str]:
        return {"titles": self.running_problems.toPlainText()}

    def apply_problem_recovery(self, values: dict[str, str]) -> None:
        set_plain_text_safely(self.running_problems, values.get("titles", ""), force=True)

    def _save_problem_pending(self) -> None:
        if not self.apply_problem_list():
            raise RuntimeError("Running problem list could not be saved.")

    def _copy_mrn(self) -> None:
        if self._controller.copy_mrn():
            self.window().showMinimized()

    def _copy_name(self) -> None:
        if self._controller.copy_patient_name():
            self.window().showMinimized()

    def _set_species(self, value: str) -> None:
        self.species.clear()
        self.species.addItems(("Canine", "Feline"))
        if self.species.findText(value, Qt.MatchFlag.MatchFixedString) < 0:
            self.species.addItem(value)
        index = self.species.findText(value, Qt.MatchFlag.MatchFixedString)
        self.species.setCurrentIndex(index)

    def save(self) -> bool:
        """Persist the editor only when it still represents the selected patient."""
        patient_id = self._controller.context.patient_id
        if patient_id is None or self._loaded_generation != self._controller.context.generation:
            return False
        try:
            acuity = Acuity(str(self.acuity.currentData()))
            code_status = CodeStatus(str(self.code_status.currentData()))
        except ValueError:
            return False
        patient = self._controller.selected_patient()
        if patient is None or patient.id != patient_id:
            return False
        saved = (
            self._controller.update_patient_profile(
                patient_id,
                name=self.name.text().strip(),
                species=self.species.currentText().strip(),
                mrn=patient.mrn,
                acuity=acuity,
                code_status=code_status,
                blood_type=patient.blood_type,
                one_line_summary=self.one_line_summary.toPlainText(),
            )
            is not None
        )
        if saved:
            self.mapping_refresh_requested.emit()
        return saved

    def _mark_dirty(self) -> None:
        self._controller.mark_editor_dirty(
            "patient-summary",
            self._save_pending,
            base_values=self._base_recovery_values,
            draft_values=self.recovery_values,
        )

    def recovery_values(self) -> dict[str, str]:
        return {
            "name": self.name.text(),
            "species": self.species.currentText(),
            "acuity": str(self.acuity.currentData() or ""),
            "code_status": str(self.code_status.currentData() or ""),
            "one_line_summary": self.one_line_summary.toPlainText(),
        }

    def apply_recovery(self, values: dict[str, str]) -> None:
        controls = (
            self.name,
            self.species,
            self.acuity,
            self.code_status,
            self.one_line_summary,
        )
        for control in controls:
            control.blockSignals(True)
        set_line_text_safely(self.name, values.get("name", self.name.text()), force=True)
        self._set_species(values.get("species", self.species.currentText()))
        self.acuity.setCurrentIndex(self.acuity.findData(Acuity(values["acuity"])))
        self.code_status.setCurrentIndex(
            self.code_status.findData(CodeStatus(values["code_status"]))
        )
        set_plain_text_safely(
            self.one_line_summary,
            values.get("one_line_summary", self.one_line_summary.toPlainText()),
            force=True,
        )
        for control in controls:
            control.blockSignals(False)
        self._mark_dirty()

    def _save_pending(self) -> None:
        if not self.save():
            raise RuntimeError("Patient summary editor could not be saved.")

    @staticmethod
    def _code_status_label(status: CodeStatus) -> str:
        labels = {
            CodeStatus.FULL_CODE: "CPR",
            CodeStatus.DO_NOT_RESUSCITATE: "DNR",
            CodeStatus.DVM_DISCRETION: "DVM discretion",
            CodeStatus.DNR_ASSIST: "DNR with assist",
            CodeStatus.LIMITED: "Limited",
            CodeStatus.UNKNOWN: "Unknown",
        }
        return labels[status]
