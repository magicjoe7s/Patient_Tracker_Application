"""Selected-patient hospital-day workspace and clinical panels."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from icu_patient_tracker.domain.enums import Acuity
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.services.instrumentation_service import device_line
from icu_patient_tracker.ui.controller import PresentationController
from icu_patient_tracker.ui.text_refresh import set_line_text_safely, set_plain_text_safely
from icu_patient_tracker.utils.hospital_day_input import parse_hospital_day_input
from icu_patient_tracker.widgets.instrumentation_panel import InstrumentationPanel
from icu_patient_tracker.widgets.patient_summary_panel import PatientSummaryPanel
from icu_patient_tracker.widgets.problem_panel import ProblemPanel
from icu_patient_tracker.widgets.sandbox_panel import SandboxPanel
from icu_patient_tracker.widgets.soap_panel import SOAPPanel
from icu_patient_tracker.widgets.task_panel import TaskPanel


class DoubleClickPlainTextEdit(QPlainTextEdit):
    """Plain-text editor that exposes a compact-editor gesture."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class DayWorkspace(QWidget):
    """Coordinate one selected day and refresh every dependent panel together."""

    def __init__(self, controller: PresentationController) -> None:
        super().__init__()
        self._controller = controller
        self.header = QLabel("Select a patient")
        self.header.setObjectName("patientHeader")
        self.save_indicator = QLabel("●")
        self.save_indicator.setObjectName("patientSaveIndicator")
        self.save_indicator.setFixedWidth(18)
        self.save_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emr_badge = QLabel("SELECT DAY")
        self.emr_badge.setAccessibleName("EMR upload status")
        self.emr_uploaded = QCheckBox("Uploaded to EMR")
        self.emr_uploaded.setAccessibleName("Selected day uploaded to EMR")
        self.day_combo = QComboBox()
        self.day_combo.setAccessibleName("Hospital day timeline")
        self.previous_button = QPushButton("<")
        self.previous_button.setAccessibleName("Previous day")
        self.next_button = QPushButton(">")
        self.next_button.setAccessibleName("Next day")
        self.new_day_button = QPushButton("New Day")
        timeline = QHBoxLayout()
        timeline.addWidget(QLabel("Day:"))
        timeline.addWidget(self.previous_button)
        timeline.addWidget(self.day_combo, 1)
        timeline.addWidget(self.next_button)
        timeline.addWidget(self.new_day_button)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("clinicalWorkspaceTabs")
        self.patient_summary = PatientSummaryPanel(controller)
        self.instrumentation = InstrumentationPanel(controller)
        self.devices_page = QGroupBox("Devices")
        devices_layout = QVBoxLayout(self.devices_page)
        devices_layout.setContentsMargins(4, 4, 4, 4)
        devices_layout.addWidget(self.instrumentation)
        self.charting = ClinicalDayPanel(controller, self.instrumentation)
        self.diagnostics_page = self.charting.diagnostics_group
        self.problems = ProblemPanel(controller)
        self.tasks = TaskPanel(controller)
        self.soap = SOAPPanel(controller)
        self.sandbox = SandboxPanel(controller)
        self.tabs.addTab(self.charting, "[Charting]")
        self.tabs.addTab(self.problems, "Problems")
        self.tabs.addTab(self.tasks, "Tasks")
        self.tabs.addTab(self.diagnostics_page, "Diagnostics")
        self.tabs.addTab(self.devices_page, "Devices")
        self.tabs.addTab(self.soap, "[SOAP]")
        self.tabs.addTab(self.sandbox, "Sandbox")
        self.charting.refresh_soap_requested.connect(self.soap.refresh_am_charting)
        self.charting.devices_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.devices_page)
        )
        self.patient_summary.mapping_refresh_requested.connect(
            lambda: self.soap.refresh_mapped(("meta", "one_liner"))
        )
        summary_group = QGroupBox("Patient Summary")
        summary_group.setMaximumHeight(250)
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(4, 4, 4, 4)
        header_row = QHBoxLayout()
        header_row.setSpacing(4)
        header_row.addWidget(self.save_indicator)
        header_row.addWidget(self.header, 1)
        summary_layout.addLayout(header_row)
        summary_layout.addWidget(self.patient_summary)
        day_group = QGroupBox("Day Workspace")
        day_layout = QVBoxLayout(day_group)
        day_layout.setContentsMargins(6, 6, 6, 6)
        day_layout.addLayout(timeline)
        emr_row = QHBoxLayout()
        emr_row.addWidget(QLabel("Acuity:"))
        emr_row.addWidget(self.charting.acuity)
        emr_row.addWidget(self.charting.acuity_badge)
        emr_row.addStretch(1)
        emr_row.addWidget(self.emr_badge)
        emr_row.addWidget(self.emr_uploaded)
        day_layout.addLayout(emr_row)
        day_layout.addWidget(self.tabs, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(summary_group)
        layout.addWidget(day_group, 1)
        self.day_combo.currentIndexChanged.connect(self._select_day)
        self.previous_button.clicked.connect(lambda: self.move_day(-1))
        self.next_button.clicked.connect(lambda: self.move_day(1))
        self.new_day_button.clicked.connect(self.prompt_create_day)
        self.emr_uploaded.toggled.connect(self._set_emr_uploaded)
        self._controller.context_changed.connect(self.refresh)
        self._controller.save_status_changed.connect(self._refresh_save_indicator)
        self.refresh()

    def refresh(self) -> None:
        self.refresh_timeline()
        self._refresh_panels()

    def refresh_timeline(self) -> None:
        """Refresh patient/day navigation without touching in-progress editors."""
        patient = self._controller.selected_patient()
        selected_day = self._controller.context.hospital_day_id
        self.header.setText(
            "Select a patient"
            if patient is None
            else (
                f"{patient.name} · MRN {patient.mrn or 'Not recorded'} · "
                f"{patient.admission_status.value}"
            )
        )
        self._refresh_save_indicator(self._controller.context.save_status)
        days = patient.hospital_days if patient is not None else ()
        self.day_combo.blockSignals(True)
        self.day_combo.clear()
        selected_index = -1
        for position, day in enumerate(days):
            self.day_combo.addItem(format_day_timeline_entry(day), day.id)
            if day.id == selected_day:
                selected_index = position
        self.day_combo.setCurrentIndex(selected_index)
        self.day_combo.blockSignals(False)
        enabled = selected_index >= 0
        selected = next((day for day in days if day.id == selected_day), None)
        self.emr_uploaded.blockSignals(True)
        self.emr_uploaded.setChecked(selected.emr_uploaded if selected is not None else False)
        self.emr_uploaded.blockSignals(False)
        self.emr_uploaded.setEnabled(selected is not None)
        self.emr_badge.setText(
            "SELECT DAY"
            if selected is None
            else ("SOAP IN EMR" if selected.emr_uploaded else "SOAP NOT IN EMR")
        )
        self.day_combo.setEnabled(bool(days))
        self.previous_button.setEnabled(enabled and len(days) > 1)
        self.next_button.setEnabled(enabled and len(days) > 1)
        self.new_day_button.setEnabled(patient is not None)

    def _refresh_save_indicator(self, status: str) -> None:
        """Show selected-patient persistence state next to the patient name."""
        if self._controller.context.patient_id is None:
            color = "#8b949e"
            description = "No patient selected"
        elif status == "Saved":
            color = "#2da44e"
            description = "Saved"
        elif status == "Save failed":
            color = "#cf222e"
            description = "Save failed — changes remain unsaved"
        elif status == "Saving":
            color = "#bf8700"
            description = "Saving"
        else:
            color = "#bf8700"
            description = status
        self.save_indicator.setStyleSheet(f"color: {color}; font-size: 16px;")
        self.save_indicator.setToolTip(description)
        self.save_indicator.setAccessibleName(f"Save status: {description}")

    def _set_emr_uploaded(self, uploaded: bool) -> None:
        if self._controller.set_emr_uploaded(uploaded) is None:
            self.refresh_timeline()

    def create_day(self, start_at: datetime, label: str | None = None) -> HospitalDay | None:
        day = self._controller.create_day(start_at, label)
        if day is not None:
            self.refresh()
        return day

    def _select_day(self, index: int) -> None:
        value = self.day_combo.itemData(index)
        if isinstance(value, UUID) and not self._controller.select_day(value):
            self.refresh_timeline()

    def move_day(self, offset: int) -> None:
        """Navigate by chronological timeline position while retaining stable identity."""
        count = self.day_combo.count()
        if count > 1:
            target = (self.day_combo.currentIndex() + offset) % count
            self.day_combo.setCurrentIndex(target)

    def prompt_create_day(self) -> None:
        """Collect a date/label and delegate duplicate validation and carry-forward."""
        default = date.today().isoformat()
        value, accepted = QInputDialog.getText(
            self,
            "Add Hospital Day",
            "Date (YYYY-MM-DD), optionally followed by | and a label:",
            text=default,
        )
        if not accepted:
            return
        try:
            parsed = parse_hospital_day_input(value)
        except ValueError:
            self._controller.error_raised.emit(
                "Invalid hospital-day date",
                "Enter the date as YYYY-MM-DD, optionally followed by | note.",
            )
            return
        local_zone = datetime.now().astimezone().tzinfo
        start_at = datetime.combine(parsed.calendar_date, time(hour=8), tzinfo=local_zone)
        self.create_day(start_at, parsed.label)

    def _refresh_panels(self) -> None:
        self.patient_summary.refresh()
        self._refresh_day_panels()

    def refresh_patient_views(self) -> None:
        """Refresh navigation and a clean patient-owned editor after an event."""
        self.refresh_timeline()
        if not self._controller.context.is_dirty:
            self.patient_summary.refresh()

    def refresh_day_views(self) -> None:
        """Refresh navigation and clean day-owned editors after an event."""
        self.refresh_timeline()
        if not self._controller.context.is_dirty:
            self._refresh_day_panels()

    def _refresh_day_panels(self) -> None:
        self.charting.refresh()
        self.problems.refresh()
        self.tasks.refresh()
        self.instrumentation.refresh()
        self.soap.refresh(force=True)
        self.sandbox.refresh(force=True)


def format_day_timeline_entry(day: HospitalDay, *, today: date | None = None) -> str:
    """Build the ICU ordinal, date, note, and Today timeline label."""
    parts = [f"ICU {day.day_number}", day.calendar_date.strftime("%b %d, '%y")]
    if day.label:
        parts.append(day.label)
    if day.calendar_date == (today or date.today()):
        parts.append("Today")
    if day.emr_uploaded:
        parts.append("EMR")
    return " | ".join(parts)


class ClinicalDayPanel(QWidget):
    """Edit canonical day-owned fields and queue one coordinated save."""

    refresh_soap_requested = Signal()
    diagnostics_popup_requested = Signal()
    devices_requested = Signal()

    def __init__(
        self,
        controller: PresentationController,
        instrumentation: InstrumentationPanel,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._loaded_generation = -1
        self._base_recovery_values: dict[str, str] = {}
        self.acuity = QComboBox()
        for value in Acuity:
            label = "#INPUT#" if value is Acuity.UNKNOWN else value.value.title()
            self.acuity.addItem(label, value)
        self.acuity_badge = QLabel("[#INPUT#]")
        self.acuity_badge.setObjectName("dayAcuityBadge")
        self.label = QLineEdit()
        self.diagnostics = DoubleClickPlainTextEdit()
        self.summary = self.diagnostics
        self._diagnostic_tasks: dict[UUID, Task] = {}
        self.diagnostic_task_list = QListWidget()
        self.diagnostic_task_list.setAccessibleName("Diagnostic tests")
        self.diagnostic_result_editor = self.diagnostics
        self.diagnostic_result_editor.setAccessibleName("Selected diagnostic result")
        self.diagnostic_result_editor.setPlaceholderText(
            "Select a diagnostic test, then enter or edit its result"
        )
        self.save_result_button = QPushButton("Save Result")
        self.diagnostic_result_status = QLabel("")
        self.treatment = QPlainTextEdit()
        self.examination = QPlainTextEdit()
        self.assessment = QPlainTextEdit()
        self.device_summary = DoubleClickPlainTextEdit()
        self.device_summary.setReadOnly(True)
        self.device_summary.setAccessibleName("Active device summary")
        self.device_summary.setPlaceholderText("No active devices")
        self.examination.setAccessibleName("AM pertinent examination findings")
        self.diagnostics.setAccessibleName("AM diagnostic summary")
        self.treatment.setAccessibleName("AM treatment changes")
        self.assessment.setAccessibleName("AM assessment")
        self.instrumentation = instrumentation
        self.label.hide()
        self.save_button = QPushButton("Save Charting")
        self.save_button.hide()
        self.copy_button = QPushButton("Copy Chart")
        self.refresh_soap_button = QPushButton("Refresh SOAP")
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button, 1)
        buttons.addWidget(self.refresh_soap_button, 1)
        editor_grid = QGridLayout()
        editor_grid.setColumnStretch(0, 1)
        editor_grid.setColumnStretch(1, 1)
        editor_grid.setRowStretch(0, 1)
        editor_grid.setRowStretch(1, 1)
        for row, column, title, editor in (
            (0, 0, "Treatment changes (AM)", self.treatment),
            (0, 1, "Pertinent exam findings (AM)", self.examination),
        ):
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(4, 4, 4, 4)
            group_layout.addWidget(editor)
            editor_grid.addWidget(group, row, column)
        self.diagnostics_group = QGroupBox("Diagnostics")
        diagnostics_layout = QVBoxLayout(self.diagnostics_group)
        diagnostics_layout.setContentsMargins(4, 4, 4, 4)
        diagnostics_layout.addWidget(QLabel("Tests for the selected hospital day"))
        diagnostics_layout.addWidget(self.diagnostic_task_list, 1)
        diagnostics_layout.addWidget(QLabel("Selected result — editable"))
        diagnostics_layout.addWidget(self.diagnostic_result_editor, 1)
        result_buttons = QHBoxLayout()
        result_buttons.addWidget(self.diagnostic_result_status, 1)
        result_buttons.addWidget(self.save_result_button)
        diagnostics_layout.addLayout(result_buttons)
        self.diagnostic_task_list.hide()
        self.save_result_button.hide()
        self.diagnostic_result_status.hide()
        self.diagnostics.setPlaceholderText(
            "One diagnostic per line: [ ] pending, or CBC: result"
        )
        devices_group = QGroupBox("Devices/lines")
        devices_layout = QVBoxLayout(devices_group)
        devices_layout.setContentsMargins(4, 4, 4, 4)
        devices_layout.addWidget(self.device_summary)
        editor_grid.addWidget(devices_group, 1, 0)
        assessment_group = QGroupBox("Assessment (AM)")
        assessment_layout = QVBoxLayout(assessment_group)
        assessment_layout.setContentsMargins(4, 4, 4, 4)
        assessment_layout.addWidget(self.assessment)
        editor_grid.addWidget(assessment_group, 1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(buttons)
        layout.addLayout(editor_grid, 1)
        self.save_button.clicked.connect(self.save)
        self.copy_button.clicked.connect(self._controller.copy_chart)
        self.refresh_soap_button.clicked.connect(self.save)
        self.device_summary.double_clicked.connect(self.devices_requested)
        self.diagnostic_task_list.currentItemChanged.connect(
            lambda _current, _previous: self._load_selected_diagnostic_result()
        )
        self.save_result_button.clicked.connect(self._save_selected_diagnostic_result)
        self.diagnostics.double_clicked.connect(self.diagnostics_popup_requested)
        self.acuity.currentIndexChanged.connect(self._mark_dirty)
        self.acuity.currentIndexChanged.connect(self._refresh_acuity_badge)
        self.label.textChanged.connect(self._mark_dirty)
        for editor in (self.summary, self.treatment, self.examination, self.assessment):
            editor.textChanged.connect(self._mark_dirty)

    def refresh(self) -> None:
        day = self._controller.selected_day()
        replace_focused = self._loaded_generation != self._controller.context.generation
        controls = (
            self.acuity,
            self.label,
            self.summary,
            self.treatment,
            self.examination,
            self.assessment,
        )
        for control in controls:
            control.blockSignals(True)
        if day is None:
            self.label.clear()
            for editor in (self.summary, self.treatment, self.examination, self.assessment):
                editor.clear()
        else:
            self.acuity.setCurrentIndex(self.acuity.findData(day.acuity))
            set_line_text_safely(self.label, day.label or "", force=replace_focused)
            patient_id = self._controller.context.patient_id
            day_id = self._controller.context.hospital_day_id
            diagnostic_text = (
                self._controller.diagnostic_text(patient_id, day_id)
                if patient_id is not None and day_id is not None
                else ""
            )
            set_plain_text_safely(self.summary, diagnostic_text, force=replace_focused)
            set_plain_text_safely(self.treatment, day.treatment_changes, force=replace_focused)
            set_plain_text_safely(self.examination, day.physical_examination, force=replace_focused)
            set_plain_text_safely(self.assessment, day.assessment, force=replace_focused)
        self._refresh_acuity_badge()
        self.refresh_device_summary(force=replace_focused)
        for control in controls:
            control.blockSignals(False)
        self._loaded_generation = self._controller.context.generation
        self._base_recovery_values = self.recovery_values()
        self.acuity.setEnabled(day is not None)
        self.acuity_badge.setEnabled(day is not None)
        self.setEnabled(day is not None)

    def _refresh_acuity_badge(self) -> None:
        value = self.acuity.currentData()
        label = "#INPUT#" if value is None else str(value).split(".")[-1].upper()
        if isinstance(value, Acuity):
            label = "#INPUT#" if value is Acuity.UNKNOWN else value.value.upper()
        self.acuity_badge.setText(f"[{label}]")

    def refresh_device_summary(self, *, force: bool = False) -> None:
        devices = self._controller.devices() if self._controller.context.hospital_day_id else ()
        value = "\n".join(
            device_line(device) for device in devices if device.status.value == "active"
        )
        set_plain_text_safely(self.device_summary, value, force=force)

    def refresh_diagnostic_results(self, *, force: bool = False) -> None:
        """Refresh the canonical free-form projection without replacing a focused draft."""
        patient_id = self._controller.context.patient_id
        day_id = self._controller.context.hospital_day_id
        text = (
            self._controller.diagnostic_text(patient_id, day_id)
            if patient_id is not None and day_id is not None
            else ""
        )
        set_plain_text_safely(self.diagnostics, text, force=force)

    def selected_diagnostic_task_id(self) -> UUID | None:
        item = self.diagnostic_task_list.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, UUID) else None

    def _load_selected_diagnostic_result(self, *, force: bool = False) -> None:
        task_id = self.selected_diagnostic_task_id()
        task = self._diagnostic_tasks.get(task_id) if task_id is not None else None
        text = (
            task.diagnostic_result.result_text
            if task is not None and task.diagnostic_result is not None
            else ""
        )
        set_plain_text_safely(self.diagnostic_result_editor, text, force=force)
        enabled = task is not None
        self.diagnostic_result_editor.setEnabled(enabled)
        self.save_result_button.setEnabled(enabled)
        self.diagnostic_result_status.clear()

    def _save_selected_diagnostic_result(self) -> bool:
        return self.save()

    def save(self) -> bool:
        if self._loaded_generation != self._controller.context.generation:
            return False
        try:
            acuity = Acuity(str(self.acuity.currentData()))
        except ValueError:
            return False
        patient_id = self._controller.context.patient_id
        day_id = self._controller.context.hospital_day_id
        if patient_id is None or day_id is None:
            return False
        if not self._controller.replace_diagnostic_text(
            patient_id, day_id, self.diagnostics.toPlainText()
        ):
            return False
        saved = (
            self._controller.update_day(
                acuity=acuity,
                label=self.label.text().strip() or None,
                clinical_summary="",
                treatment_changes=self.treatment.toPlainText(),
                physical_examination=self.examination.toPlainText(),
                assessment=self.assessment.toPlainText(),
            )
            is not None
        )
        if saved:
            self.refresh_soap_requested.emit()
        return saved

    def _mark_dirty(self) -> None:
        self._controller.mark_editor_dirty(
            "charting",
            self._save_pending,
            base_values=self._base_recovery_values,
            draft_values=self.recovery_values,
        )

    def recovery_values(self) -> dict[str, str]:
        return {
            "acuity": str(self.acuity.currentData() or ""),
            "label": self.label.text(),
            "clinical_summary": self.summary.toPlainText(),
            "treatment_changes": self.treatment.toPlainText(),
            "physical_examination": self.examination.toPlainText(),
            "assessment": self.assessment.toPlainText(),
        }

    def apply_recovery(self, values: dict[str, str]) -> None:
        controls = (
            self.acuity,
            self.label,
            self.summary,
            self.treatment,
            self.examination,
            self.assessment,
        )
        for control in controls:
            control.blockSignals(True)
        self.acuity.setCurrentIndex(self.acuity.findData(Acuity(values["acuity"])))
        set_line_text_safely(self.label, values.get("label", self.label.text()), force=True)
        set_plain_text_safely(
            self.summary,
            values.get("clinical_summary", self.summary.toPlainText()),
            force=True,
        )
        set_plain_text_safely(
            self.treatment,
            values.get("treatment_changes", self.treatment.toPlainText()),
            force=True,
        )
        set_plain_text_safely(
            self.examination,
            values.get("physical_examination", self.examination.toPlainText()),
            force=True,
        )
        set_plain_text_safely(
            self.assessment,
            values.get("assessment", self.assessment.toPlainText()),
            force=True,
        )
        for control in controls:
            control.blockSignals(False)
        self._mark_dirty()

    def _save_pending(self) -> None:
        if not self.save():
            raise RuntimeError("Charting editor could not be saved.")
