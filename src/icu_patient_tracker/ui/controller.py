"""Presentation coordinator translating user intent into service calls."""

from __future__ import annotations

import logging
import time as timing
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, Signal

from icu_patient_tracker.app.config import AppConfig
from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    ClinicalPriority,
    CodeStatus,
    DeviceType,
    ProblemStatus,
    SOAPDocumentType,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.services.analytics_service import AnalyticsService, AnalyticsSnapshot
from icu_patient_tracker.services.autosave_coordinator import AutosaveCoordinator
from icu_patient_tracker.services.backup_service import BackupDescriptor, BackupService
from icu_patient_tracker.services.clipboard_service import ClipboardService
from icu_patient_tracker.services.diagnostic_result_service import DiagnosticResultService
from icu_patient_tracker.services.exceptions import ApplicationServiceError
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.instrumentation_service import InstrumentationService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.problem_service import ProblemService
from icu_patient_tracker.services.recovery_service import RecoveryService, RecoverySnapshot
from icu_patient_tracker.services.reminder_service import ReminderService
from icu_patient_tracker.services.sandbox_service import (
    SandboxExtractionPreview,
    SandboxService,
)
from icu_patient_tracker.services.search_service import (
    SearchFilters,
    SearchService,
    SearchSort,
    SearchView,
)
from icu_patient_tracker.services.settings_service import SettingsService
from icu_patient_tracker.services.soap_service import SOAPService
from icu_patient_tracker.services.task_service import TaskBoardRow, TaskService
from icu_patient_tracker.ui.context import PresentationContext
from icu_patient_tracker.utils.diagnostic_text import parse_diagnostic_text
from icu_patient_tracker.utils.problem_list_text import ProblemListEntry
from icu_patient_tracker.utils.task_input import TaskInput, parse_task_input


@dataclass(frozen=True, slots=True)
class ServiceBundle:
    """Explicit presentation dependencies assembled only by the composition root."""

    patients: PatientService
    days: HospitalDayService
    problems: ProblemService
    tasks: TaskService
    diagnostic_results: DiagnosticResultService
    instrumentation: InstrumentationService
    soap: SOAPService
    sandbox: SandboxService
    search: SearchService
    settings: SettingsService
    reminders: ReminderService
    backup: BackupService
    clipboard: ClipboardService
    analytics: AnalyticsService
    recovery: RecoveryService


class PresentationController(QObject):
    """Own selected context, pending editor commits, and service error translation."""

    context_changed = Signal(object)
    save_status_changed = Signal(str)
    error_raised = Signal(str, str)
    operation_status = Signal(str)

    def __init__(self, services: ServiceBundle) -> None:
        super().__init__()
        self.services = services
        self.context = PresentationContext()
        self._autosave: AutosaveCoordinator | None = None
        self._pending_savers: dict[str, Callable[[], None]] = {}
        self._logger = logging.getLogger(__name__)

    def attach_autosave(self, autosave: AutosaveCoordinator) -> None:
        """Complete the composition cycle after the save callback is constructed."""
        if self._autosave is not None:
            raise RuntimeError("Autosave is already attached.")
        self._autosave = autosave

    def patients(
        self,
        query: str = "",
        *,
        status: AdmissionStatus | None = AdmissionStatus.ADMITTED,
        sort: SearchSort = SearchSort.MANUAL,
        view: SearchView = SearchView.ALL_ACTIVE,
    ) -> tuple[Patient, ...]:
        results = self.services.search.search(
            query, filters=SearchFilters(status=status, view=view), sort=sort
        )
        return tuple(self.services.patients.get(result.patient_id) for result in results)

    def create_patient(self, *, name: str, species: str, mrn: str | None = None) -> Patient | None:
        if not self.flush_pending():
            return None
        return self._call(
            "Create patient",
            lambda: self.services.patients.create(mrn=mrn, name=name, species=species),
        )

    def rename_patient(self, patient_id: UUID, name: str) -> Patient | None:
        return self._call(
            "Rename patient",
            lambda: self.services.patients.update_summary(patient_id, name=name),
        )

    def update_patient_identity_details(
        self, patient_id: UUID, *, mrn: str | None, species: str
    ) -> Patient | None:
        return self._call(
            "Update patient details",
            lambda: self.services.patients.update_identity_details(
                patient_id, mrn=mrn, species=species
            ),
        )

    def update_patient_profile(
        self,
        patient_id: UUID,
        *,
        name: str,
        species: str,
        mrn: str | None,
        one_line_summary: str,
        code_status: CodeStatus,
        blood_type: str | None,
        acuity: Acuity,
    ) -> Patient | None:
        """Save the complete patient-owned summary without changing its UUID."""
        patient = self._call(
            "Save patient summary",
            lambda: self.services.patients.update_profile(
                patient_id,
                name=name,
                species=species,
                mrn=mrn,
                one_line_summary=one_line_summary,
                code_status=code_status,
                blood_type=blood_type,
                acuity=acuity,
            ),
        )
        day_id = self.context.hospital_day_id
        if patient is not None and self.context.patient_id == patient_id and day_id is not None:
            day = self._call(
                "Synchronize selected-day acuity",
                lambda: self.services.days.update(patient_id, day_id, acuity=acuity),
            )
            if day is not None:
                self._refresh_existing_soap_sections(patient_id, day_id, ("meta", "one_liner"))
        return patient

    def change_patient_status(self, patient_id: UUID, status: AdmissionStatus) -> Patient | None:
        return self._call(
            "Change patient status",
            lambda: self.services.patients.change_status(patient_id, status),
        )

    def readmit_patient(self, patient_id: UUID) -> Patient | None:
        return self._call("Readmit patient", lambda: self.services.patients.reactivate(patient_id))

    def archive_patient(self, patient_id: UUID) -> Patient | None:
        return self._call("Archive patient", lambda: self.services.patients.archive(patient_id))

    def purge_patient(self, patient_id: UUID) -> bool:
        def purge() -> bool:
            self.services.patients.purge(patient_id)
            return True

        removed = self._call("Permanently delete patient", purge)
        if removed:
            self.context.select_patient(None)
            self.context_changed.emit(self.context)
        return bool(removed)

    def move_active_patient(self, patient_id: UUID, offset: int) -> tuple[Patient, ...] | None:
        def move() -> tuple[Patient, ...]:
            active = list(self.services.patients.list(status=AdmissionStatus.ADMITTED))
            current = next(
                (index for index, patient in enumerate(active) if patient.id == patient_id), -1
            )
            destination = current + offset
            if current < 0 or destination < 0 or destination >= len(active):
                return tuple(active)
            active[current], active[destination] = active[destination], active[current]
            return self.services.patients.reorder_active(tuple(patient.id for patient in active))

        return self._call("Reorder active census", move)

    def select_patient(self, patient_id: UUID | None) -> bool:
        if not self.flush_pending():
            return False
        self.context.select_patient(patient_id)
        if patient_id is not None:
            days = self.services.days.list(patient_id)
            self.context.select_day(days[-1].id if days else None)
        self.context_changed.emit(self.context)
        return True

    def select_day(self, day_id: UUID | None) -> bool:
        if not self.flush_pending():
            return False
        self.context.select_day(day_id)
        self.context_changed.emit(self.context)
        return True

    def selected_patient(self) -> Patient | None:
        if self.context.patient_id is None:
            return None
        return self._call(
            "Load patient",
            lambda: self.services.patients.get(self.context.patient_id or UUID(int=0)),
        )

    def selected_day(self) -> HospitalDay | None:
        if self.context.patient_id is None or self.context.hospital_day_id is None:
            return None
        return self._call(
            "Load hospital day",
            lambda: self.services.days.get(
                self.context.patient_id or UUID(int=0),
                self.context.hospital_day_id or UUID(int=0),
            ),
        )

    def problems(self) -> tuple[Problem, ...]:
        context = self._require_day()
        return () if context is None else self.services.problems.list(*context)

    def tasks(self) -> tuple[Task, ...]:
        context = self._require_day()
        return () if context is None else self.services.tasks.list_for_day(*context)

    def diagnostic_tasks_for(self, patient_id: UUID, day_id: UUID) -> tuple[Task, ...]:
        """Load diagnostic tasks for an explicit, stable capture context."""
        tasks = self._call(
            "Load diagnostics",
            lambda: self.services.tasks.list_for_day(patient_id, day_id),
        )
        return (
            ()
            if tasks is None
            else tuple(
                task
                for task in tasks
                if task.category is TaskCategory.DIAGNOSTIC
                and task.status is not TaskStatus.CANCELLED
            )
        )

    def diagnostic_text(self, patient_id: UUID, day_id: UUID) -> str:
        """Render the selected day's canonical diagnostics as editable checklist text."""
        return "\n".join(
            self.diagnostic_result_line(task)
            for task in self.diagnostic_tasks_for(patient_id, day_id)
        )

    def replace_diagnostic_text(self, patient_id: UUID, day_id: UUID, value: str) -> bool:
        """Reconcile free-form checklist lines with canonical diagnostic tasks."""
        parsed = parse_diagnostic_text(value)
        if len({entry.title.casefold() for entry in parsed}) != len(parsed):
            self.error_raised.emit(
                "Duplicate diagnostic", "Each diagnostic title can appear only once."
            )
            return False
        return (
            self._call(
                "Save diagnostics",
                lambda: self.services.tasks.replace_diagnostics_from(
                    patient_id, day_id, parsed
                ),
            )
            is not None
        )

    @staticmethod
    def diagnostic_result_line(task: Task) -> str:
        """Render the agreed compact same-line diagnostic projection."""
        marker = "x" if task.status is TaskStatus.COMPLETED else " "
        title = task.title.strip().rstrip(":")
        result = (
            " ".join(task.diagnostic_result.result_text.split())
            if task.diagnostic_result is not None
            else ""
        )
        return f"- [{marker}] {title}{f': {result}' if result else ''}"

    def record_diagnostic_result(
        self,
        patient_id: UUID,
        day_id: UUID,
        task_id: UUID,
        result_text: str,
        *,
        complete: bool,
    ) -> Task | None:
        """Persist a result, then refresh only diagnostics in an existing SOAP."""
        task = self._call(
            "Save diagnostic result",
            lambda: self.services.diagnostic_results.record(
                patient_id,
                day_id,
                task_id,
                result_text,
                complete=complete,
            ),
        )
        if task is None:
            return None
        day = self._call(
            "Load hospital day",
            lambda: self.services.days.get(patient_id, day_id),
        )
        if day is not None and day.soap_documents:
            config = self.settings()
            resident = config.soap_daytime_resident if config is not None else ""
            latest = max(day.soap_documents, key=lambda document: document.updated_at)
            self._call(
                "Refresh SOAP diagnostics",
                lambda: self.services.soap.refresh_markdown(
                    patient_id,
                    day_id,
                    latest.id,
                    sections=("diagnostics",),
                    daytime_resident=resident,
                ),
            )
        return task

    def task_board(
        self,
        category: TaskCategory,
        *,
        include_completed: bool = False,
    ) -> tuple[TaskBoardRow, ...]:
        return self.services.tasks.board(
            category=category,
            include_completed=include_completed,
        )

    def select_task_board_row(self, row: TaskBoardRow) -> bool:
        """Atomically navigate to the canonical patient/day owning a board row."""
        if not self.flush_pending():
            return False
        self.context.select_patient(row.patient_id)
        self.context.select_day(row.hospital_day_id)
        self.context_changed.emit(self.context)
        return True

    def devices(self) -> tuple[Device, ...]:
        context = self._require_day()
        return () if context is None else self.services.instrumentation.list(*context)

    def settings(self) -> AppConfig | None:
        return self._call("Load settings", self.services.settings.get)

    def update_settings(self, **changes: object) -> AppConfig | None:
        return self._call("Update settings", lambda: self.services.settings.update(**changes))

    def analytics_snapshot(self) -> AnalyticsSnapshot | None:
        return self._call("Load analytics", self.services.analytics.snapshot)

    def create_backup(self) -> Path | None:
        if not self.flush_pending():
            return None
        return self._call("Create backup", lambda: self.services.backup.create(label="manual"))

    def inspect_backup(self, path: Path) -> BackupDescriptor | None:
        return self._call("Verify backup", lambda: self.services.backup.inspect(path))

    def restore_backup(self, descriptor: BackupDescriptor) -> Path | None:
        if not self.flush_pending():
            return None
        safety_backup = self._call(
            "Restore backup",
            lambda: self.services.backup.restore(
                descriptor.path,
                expected_sha256=descriptor.sha256,
            ),
        )
        if safety_backup is not None:
            self._pending_savers.clear()
            self.context.select_patient(None)
            self.context.is_dirty = False
            self.context.save_status = "Restored — pre-restore safety backup created"
            self.save_status_changed.emit(self.context.save_status)
            self.context_changed.emit(self.context)
        return safety_backup

    def copy_analytics(self, snapshot: AnalyticsSnapshot) -> bool:
        copied = self._call("Copy analytics", lambda: self.services.analytics.copy_report(snapshot))
        if copied is None:
            return False
        self.operation_status.emit("Analytics report copied to clipboard")
        return True

    def reset_settings(self) -> AppConfig | None:
        return self._call("Reset settings", self.services.settings.reset)

    def copy_chart(self) -> bool:
        context = self._require_day()
        if context is None or not self.flush_pending():
            return False
        copied = self._call("Copy Chart", lambda: self.services.clipboard.copy_chart(*context))
        if copied is None:
            return False
        self.operation_status.emit("Chart copied to clipboard")
        return True

    def copy_mrn(self) -> bool:
        patient_id = self._require_patient()
        if patient_id is None or not self.flush_pending():
            return False
        copied = self._call("Copy MRN", lambda: self.services.clipboard.copy_mrn(patient_id))
        if copied is None:
            return False
        self.operation_status.emit("MRN copied to clipboard")
        return True

    def copy_patient_name(self) -> bool:
        patient_id = self._require_patient()
        if patient_id is None or not self.flush_pending():
            return False
        copied = self._call(
            "Copy patient name",
            lambda: self.services.clipboard.copy_patient_name(patient_id),
        )
        if copied is None:
            return False
        self.operation_status.emit("Patient name copied to clipboard")
        return True

    def copy_soap(self) -> bool:
        context = self._require_day()
        if context is None or not self.flush_pending():
            return False
        copied = self._call("Copy SOAP", lambda: self.services.clipboard.copy_soap(*context))
        if copied is None:
            return False
        self.operation_status.emit("SOAP copied to clipboard and marked uploaded")
        return True

    def set_emr_uploaded(self, uploaded: bool) -> HospitalDay | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Update EMR upload status",
                lambda: self.services.clipboard.set_emr_uploaded(*context, uploaded),
            )
        )

    def minimize_after_copy(self) -> bool:
        config = self.settings()
        return config.minimize_after_copy if config is not None else False

    def create_day(self, start_at: datetime, label: str | None = None) -> HospitalDay | None:
        patient_id = self._require_patient()
        if patient_id is None or not self.flush_pending():
            return None
        day = self._call(
            "Create hospital day",
            lambda: self.services.days.create(patient_id, start_at=start_at, label=label),
        )
        if day is not None:
            self.context.select_day(day.id)
            self.context_changed.emit(self.context)
        return day

    def update_day(
        self,
        *,
        acuity: Acuity,
        label: str | None,
        treatment_changes: str,
        physical_examination: str,
        assessment: str,
        clinical_summary: str,
    ) -> HospitalDay | None:
        context = self._require_day()
        if context is None:
            return None
        patient_id, day_id = context
        day = self._call(
            "Save hospital day",
            lambda: self.services.days.update(
                patient_id,
                day_id,
                acuity=acuity,
                label=label,
                treatment_changes=treatment_changes,
                physical_examination=physical_examination,
                assessment=assessment,
                clinical_summary=clinical_summary,
            ),
        )
        if day is not None:
            self._call(
                "Synchronize patient acuity",
                lambda: self.services.patients.update_summary(patient_id, acuity=acuity),
            )
            self._refresh_existing_soap_sections(patient_id, day_id, ("meta",))
        return day

    def _refresh_existing_soap_sections(
        self, patient_id: UUID, day_id: UUID, sections: tuple[str, ...]
    ) -> None:
        day = self._call(
            "Load SOAP header context",
            lambda: self.services.days.get(patient_id, day_id),
        )
        if day is None or not day.soap_documents:
            return
        latest = max(day.soap_documents, key=lambda document: document.updated_at)
        config = self.settings()
        daytime_resident = config.soap_daytime_resident if config is not None else ""
        self._call(
            "Refresh SOAP synchronized fields",
            lambda: self.services.soap.refresh_markdown(
                patient_id,
                day_id,
                latest.id,
                sections=sections,
                daytime_resident=daytime_resident,
            ),
        )

    def refresh_selected_problem_list_in_soap(self) -> None:
        """Project canonical problem changes into the selected day's existing SOAP."""
        context = self._require_day()
        if context is not None:
            self._refresh_existing_soap_sections(*context, ("problem_list",))

    def add_problem(
        self,
        title: str,
        *,
        description: str = "",
        priority: ClinicalPriority = ClinicalPriority.ROUTINE,
        assessment: str = "",
        plan: str = "",
        notes: str = "",
    ) -> Problem | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Add problem",
                lambda: self.services.problems.add(
                    *context,
                    title=title,
                    description=description,
                    priority=priority,
                    assessment=assessment,
                    plan=plan,
                    notes=notes,
                ),
            )
        )

    def update_problem(
        self,
        problem_id: UUID,
        *,
        title: str,
        description: str | None = None,
        priority: ClinicalPriority,
        assessment: str | None = None,
        plan: str | None = None,
        notes: str | None = None,
    ) -> tuple[Problem, ...] | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Edit problem",
                lambda: self.services.problems.update_from(
                    *context,
                    problem_id,
                    title=title,
                    description=description,
                    priority=priority,
                    assessment=assessment,
                    plan=plan,
                    notes=notes,
                ),
            )
        )

    def set_problem_status(
        self, problem_id: UUID, status: ProblemStatus
    ) -> tuple[Problem, ...] | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Change problem status",
                lambda: self.services.problems.change_status_from(*context, problem_id, status),
            )
        )

    def remove_problem(self, problem_id: UUID) -> tuple[Problem, ...] | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Remove problem",
                lambda: self.services.problems.remove_from(*context, problem_id),
            )
        )

    def replace_problem_titles(self, titles: tuple[str, ...]) -> tuple[Problem, ...] | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Update running problem list",
                lambda: self.services.problems.replace_titles_from(*context, titles),
            )
        )

    def replace_problem_entries(
        self, entries: tuple[ProblemListEntry, ...]
    ) -> tuple[Problem, ...] | None:
        """Update the canonical ordered list with nested supporting details."""
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Update running problem list",
                lambda: self.services.problems.replace_entries_from(*context, entries),
            )
        )

    def reorder_problems(self, ordered_ids: list[UUID]) -> bool:
        context = self._require_day()
        if context is None:
            return False

        def reorder() -> bool:
            self.services.problems.reorder(*context, ordered_ids)
            return True

        return self._call("Reorder problems", reorder) is True

    def add_task(
        self,
        title: str,
        *,
        category: TaskCategory = TaskCategory.CLINICAL,
        priority: ClinicalPriority = ClinicalPriority.ROUTINE,
        bucket: TaskBucket = TaskBucket.TODAY,
        carry_forward: bool = True,
    ) -> Task | None:
        if category is TaskCategory.CLINICAL:
            try:
                category = parse_task_input(title, category).category
            except ValueError:
                category = TaskCategory.CLINICAL
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Add task",
                lambda: self.services.tasks.create(
                    *context,
                    title=title,
                    category=category,
                    priority=priority,
                    bucket=bucket,
                    carry_forward=carry_forward,
                ),
            )
        )

    def add_task_input(
        self, value: str, category: TaskCategory = TaskCategory.CLINICAL
    ) -> Task | None:
        """Parse compact entry grammar and persist its structured task and reminder."""
        try:
            task_input = parse_task_input(
                value, category, discard_invalid_reminder=True
            )
        except ValueError as error:
            self.error_raised.emit("Invalid task", str(error))
            return None
        task = self.add_task(
            task_input.title,
            category=task_input.category,
            priority=task_input.priority,
            bucket=task_input.bucket,
            carry_forward=task_input.carry_forward,
        )
        if task is None or task_input.reminder is None:
            return task
        self._add_task_reminder(task, task_input)
        return task

    def add_board_task(
        self,
        title: str,
        *,
        category: TaskCategory,
        priority: ClinicalPriority = ClinicalPriority.ROUTINE,
        bucket: TaskBucket = TaskBucket.TODAY,
        carry_forward: bool = True,
    ) -> Task | None:
        """Add board work to the selected patient's newest hospital day."""
        patient_id = self._require_patient()
        if patient_id is None:
            return None
        days = self.services.days.list(patient_id)
        if not days:
            self.error_raised.emit("Add task", "The selected patient has no hospital day.")
            return None
        if category is TaskCategory.CLINICAL:
            try:
                category = parse_task_input(title, category).category
            except ValueError:
                category = TaskCategory.CLINICAL
        return self._call(
            "Add board task",
            lambda: self.services.tasks.create(
                patient_id,
                days[-1].id,
                title=title,
                category=category,
                priority=priority,
                bucket=bucket,
                carry_forward=carry_forward,
            ),
        )

    def update_task(
        self,
        task_id: UUID,
        *,
        title: str,
        category: TaskCategory | None = None,
        priority: ClinicalPriority | None = None,
        bucket: TaskBucket | None = None,
        carry_forward: bool | None = None,
    ) -> tuple[Task, ...] | None:
        if category is TaskCategory.CLINICAL:
            try:
                category = parse_task_input(title, category).category
            except ValueError:
                category = TaskCategory.CLINICAL
        patient_id = self._require_patient()
        return (
            None
            if patient_id is None
            else self._call(
                "Edit task",
                lambda: self.services.tasks.update_from(
                    patient_id,
                    task_id,
                    title=title,
                    category=category,
                    priority=priority,
                    bucket=bucket,
                    carry_forward=carry_forward,
                ),
            )
        )

    def toggle_task(self, task: Task) -> object | None:
        patient_id = self._require_patient()
        if patient_id is None:
            return None
        if task.status.value == "completed":
            return self._call(
                "Reopen task", lambda: self.services.tasks.reopen_from(patient_id, task.id)
            )
        return self._call(
            "Complete task", lambda: self.services.tasks.complete_from(patient_id, task.id)
        )

    def toggle_board_task(self, row: TaskBoardRow) -> object | None:
        if row.task.status in {
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.DEFERRED,
        }:
            return self._call(
                "Reopen board task",
                lambda: self.services.tasks.reopen_from(row.patient_id, row.task.id),
            )
        return self._call(
            "Complete board task",
            lambda: self.services.tasks.complete_from(row.patient_id, row.task.id),
        )

    def complete_digest_task(self, patient_id: UUID, task_id: UUID) -> object | None:
        """Complete a task selected directly from the hourly digest."""
        return self._call(
            "Complete digest task",
            lambda: self.services.tasks.complete_from(patient_id, task_id),
        )

    def update_board_task(
        self,
        row: TaskBoardRow,
        *,
        title: str,
        category: TaskCategory,
        priority: ClinicalPriority,
        bucket: TaskBucket,
        carry_forward: bool,
    ) -> tuple[Task, ...] | None:
        if category is TaskCategory.CLINICAL:
            try:
                category = parse_task_input(title, category).category
            except ValueError:
                category = TaskCategory.CLINICAL
        return self._call(
            "Edit board task",
            lambda: self.services.tasks.update_from(
                row.patient_id,
                row.task.id,
                title=title,
                category=category,
                priority=priority,
                bucket=bucket,
                carry_forward=carry_forward,
            ),
        )

    def delete_board_task_lineage(self, row: TaskBoardRow) -> int | None:
        return self._call(
            "Delete board task lineage",
            lambda: self.services.tasks.delete_lineage(row.patient_id, row.task.lineage_id),
        )

    def omit_diagnostic(self, task_id: UUID) -> tuple[Task, ...] | None:
        patient_id = self._require_patient()
        return (
            None
            if patient_id is None
            else self._call(
                "Omit pending diagnostic",
                lambda: self.services.tasks.omit_diagnostic_from(patient_id, task_id),
            )
        )

    def delete_task_lineage(self, lineage_id: UUID) -> int | None:
        patient_id = self._require_patient()
        return (
            None
            if patient_id is None
            else self._call(
                "Delete task lineage",
                lambda: self.services.tasks.delete_lineage(patient_id, lineage_id),
            )
        )

    def _add_task_reminder(self, task: Task, task_input: TaskInput) -> None:
        reminder = task_input.reminder
        if reminder is None:
            return
        if reminder.interval_minutes is not None:
            self._call(
                "Add task reminder",
                lambda: self.services.reminders.add_interval(
                    task.patient_id,
                    task.id,
                    interval_minutes=reminder.interval_minutes or 1,
                    message=task.title,
                ),
            )
        elif reminder.fixed_time is not None:
            self._call(
                "Add task reminder",
                lambda: self.services.reminders.add_fixed_time(
                    task.patient_id,
                    task.id,
                    fixed_time=reminder.fixed_time or time(),
                    message=task.title,
                ),
            )

    def add_device(
        self,
        device_type: DeviceType,
        location: str,
        placed_at: datetime,
        *,
        size: str | None = None,
    ) -> Device | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Add device",
                lambda: self.services.instrumentation.add(
                    *context,
                    device_type=device_type,
                    anatomical_location=location,
                    placed_at=placed_at,
                    size=size,
                ),
            )
        )

    def update_device(self, device_id: UUID, location: str) -> Device | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Edit device",
                lambda: self.services.instrumentation.update(
                    *context, device_id, anatomical_location=location
                ),
            )
        )

    def discontinue_device(self, device_id: UUID) -> Device | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Discontinue device",
                lambda: self.services.instrumentation.discontinue(*context, device_id),
            )
        )

    def replace_device_lines(self, lines: tuple[str, ...]) -> tuple[Device, ...] | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Update devices",
                lambda: self.services.instrumentation.replace_active_lines(*context, lines),
            )
        )

    def refresh_selected_instrumentation_in_soap(self) -> None:
        context = self._require_day()
        if context is not None:
            self._refresh_existing_soap_sections(*context, ("instrumentation",))

    def save_soap(
        self,
        document_id: UUID | None,
        *,
        markdown_text: str | None = None,
        subjective: str = "",
        objective: str = "",
        assessment: str = "",
        plan: str = "",
        author: str = "Clinician",
    ) -> SOAPDocument | None:
        context = self._require_day()
        if context is None:
            return None
        if document_id is None:
            config = self.settings()
            daytime_resident = config.soap_daytime_resident if config is not None else ""
            document = self._call(
                "Create SOAP",
                lambda: self.services.soap.create(
                    *context,
                    author=author,
                    document_type=SOAPDocumentType.DAILY,
                    daytime_resident=daytime_resident,
                ),
            )
            if document is None:
                return None
            document_id = document.id
            if markdown_text == "":
                return document
        if markdown_text is not None:
            return self._call(
                "Save SOAP Markdown",
                lambda: self.services.soap.save_markdown(*context, document_id, markdown_text),
            )
        return self._call(
            "Save SOAP",
            lambda: self.services.soap.update_sections(
                *context,
                document_id,
                subjective=subjective,
                objective=objective,
                assessment=assessment,
                plan=plan,
            ),
        )

    def refresh_soap(
        self,
        document_id: UUID,
        *,
        sections: tuple[str, ...] = (
            "meta",
            "one_liner",
            "problem_list",
            "physical_examination",
            "diagnostics",
            "treatment_changes",
            "instrumentation",
            "assessment",
            "staff",
        ),
    ) -> SOAPDocument | None:
        context = self._require_day()
        config = self.settings()
        daytime_resident = config.soap_daytime_resident if config is not None else ""
        return (
            None
            if context is None
            else self._call(
                "Refresh SOAP",
                lambda: self.services.soap.refresh_markdown(
                    *context,
                    document_id,
                    sections=sections,
                    daytime_resident=daytime_resident,
                ),
            )
        )

    def ensure_soap_markdown(self, document_id: UUID) -> SOAPDocument | None:
        """Upgrade an existing structured SOAP document when it is first opened."""
        context = self._require_day()
        config = self.settings()
        daytime_resident = config.soap_daytime_resident if config is not None else ""
        return (
            None
            if context is None
            else self._call(
                "Initialize SOAP Markdown",
                lambda: self.services.soap.ensure_markdown(
                    *context,
                    document_id,
                    daytime_resident=daytime_resident,
                ),
            )
        )

    def save_sandbox(self, sandbox_text: str) -> str | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Save Sandbox",
                lambda: self.services.sandbox.save(*context, sandbox_text),
            )
        )

    def preview_sandbox_tasks(self) -> SandboxExtractionPreview | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Preview Sandbox tasks",
                lambda: self.services.sandbox.preview(*context),
            )
        )

    def extract_sandbox_tasks(
        self, preview: SandboxExtractionPreview, line_numbers: tuple[int, ...]
    ) -> tuple[Task, ...] | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Extract Sandbox tasks",
                lambda: self.services.sandbox.extract(
                    *context,
                    expected_sandbox_text=preview.sandbox_text,
                    line_numbers=line_numbers,
                ),
            )
        )

    def synchronize_soap(self, document_id: UUID) -> HospitalDay | None:
        context = self._require_day()
        return (
            None
            if context is None
            else self._call(
                "Synchronize SOAP",
                lambda: self.services.soap.synchronize_to_day(
                    *context,
                    document_id,
                    section_mapping={
                        "objective": "physical_examination",
                        "assessment": "assessment",
                        "plan": "treatment_changes",
                    },
                ),
            )
        )

    def mark_editor_dirty(
        self,
        key: str,
        saver: Callable[[], None],
        *,
        base_values: dict[str, str] | Callable[[], dict[str, str]] | None = None,
        draft_values: dict[str, str] | Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self._pending_savers[key] = saver
        if (
            base_values is not None
            and draft_values is not None
            and self.context.patient_id is not None
        ):
            try:
                self.services.recovery.stage(
                    key=key,
                    patient_id=self.context.patient_id,
                    hospital_day_id=self.context.hospital_day_id,
                    base_values=base_values,
                    draft_values=draft_values,
                )
            except ApplicationServiceError as error:
                self._logger.warning("Recovery staging failed: %s", error)
                self.error_raised.emit("Protect unsaved edits", str(error))
        was_dirty = self.context.is_dirty
        self.context.is_dirty = True
        if not was_dirty or self.context.save_status != "Save scheduled":
            self.context.save_status = "Save scheduled"
            self.save_status_changed.emit(self.context.save_status)
        if self._autosave is not None:
            self._autosave.mark_dirty()

    def commit_pending(self) -> None:
        if not self._pending_savers:
            self.context.is_dirty = False
            return
        self.context.save_status = "Saving"
        self.save_status_changed.emit("Saving")
        try:
            for saver in tuple(self._pending_savers.values()):
                saver()
        except Exception:
            self.context.save_status = "Save failed"
            self.save_status_changed.emit("Save failed")
            raise
        self._pending_savers.clear()
        try:
            self.services.recovery.discard()
        except ApplicationServiceError as error:
            self._logger.warning("Saved data but could not clear recovery snapshot: %s", error)
            self.error_raised.emit("Clear recovery snapshot", str(error))
        self.context.is_dirty = False
        self.context.save_status = "Saved"
        self.save_status_changed.emit("Saved")

    def editor_saved(self, key: str) -> None:
        """Clear an editor that was explicitly saved before its debounce fires."""
        self._pending_savers.pop(key, None)
        try:
            self.services.recovery.unstage(key)
        except ApplicationServiceError as error:
            self._logger.warning("Recovery unstaging failed: %s", error)
        self.context.is_dirty = bool(self._pending_savers)
        self.context.save_status = "Save scheduled" if self._pending_savers else "Saved"
        self.save_status_changed.emit(self.context.save_status)

    def has_pending_editor(self, key: str) -> bool:
        """Report whether an editor owns a draft that canonical refreshes must preserve."""
        return key in self._pending_savers

    def flush_pending(self) -> bool:
        if not self._pending_savers:
            return True
        try:
            if self._autosave is not None:
                self._autosave.save_now()
            else:
                self.commit_pending()
        except Exception as error:
            self._present_unexpected("Save pending edits", error)
            return False
        return True

    def shutdown(self) -> bool:
        try:
            if self._autosave is not None:
                self._autosave.shutdown()
            else:
                self.commit_pending()
        except Exception as error:
            try:
                self.services.recovery.flush()
            except ApplicationServiceError:
                self._logger.exception("Recovery flush also failed during shutdown")
            self._present_unexpected("Close application", error)
            return False
        return True

    def recovery_snapshot(self) -> RecoverySnapshot | None:
        """Return the typed recovery snapshot through the standard error boundary."""
        return self._call("Load recovery draft", self.services.recovery.available)

    def recovery_conflicts(
        self,
        snapshot: RecoverySnapshot,
        current_values: dict[str, dict[str, str]],
    ) -> tuple[str, ...] | None:
        return self._call(
            "Check recovery draft",
            lambda: self.services.recovery.conflicting_entries(snapshot, current_values),
        )

    def discard_recovery(self) -> bool:
        def discard() -> bool:
            self.services.recovery.discard()
            return True

        return bool(self._call("Discard recovery draft", discard))

    def _require_patient(self) -> UUID | None:
        if self.context.patient_id is None:
            self.error_raised.emit("No patient selected", "Select a patient first.")
        return self.context.patient_id

    def _require_day(self) -> tuple[UUID, UUID] | None:
        patient_id = self._require_patient()
        if patient_id is None:
            return None
        if self.context.hospital_day_id is None:
            self.error_raised.emit("No hospital day selected", "Create or select a day first.")
            return None
        return patient_id, self.context.hospital_day_id

    def _call[T](self, action: str, operation: Callable[[], T]) -> T | None:
        started = timing.perf_counter()
        try:
            result = operation()
        except ApplicationServiceError as error:
            self._logger.warning("%s failed: %s", action, error)
            self.error_raised.emit(action, str(error))
            return None
        except Exception as error:
            self._present_unexpected(action, error)
            return None
        elapsed = timing.perf_counter() - started
        if elapsed >= 0.05:
            self._logger.info("Slow UI operation: %s took %.3f seconds", action, elapsed)
        self.operation_status.emit(f"{action} completed")
        return result

    def _present_unexpected(self, action: str, error: Exception) -> None:
        self._logger.exception("Unexpected presentation operation failure: %s", action)
        self.error_raised.emit(
            action,
            "The operation could not be completed. Existing saved data was protected.",
        )
