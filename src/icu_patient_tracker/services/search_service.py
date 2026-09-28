"""Cross-aggregate patient search and stable result sorting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from icu_patient_tracker.domain.enums import Acuity, AdmissionStatus, TaskCategory, TaskStatus
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.events import EventPublisher


class SearchSort(StrEnum):
    """Supported deterministic patient result orders."""

    MANUAL = "manual"
    NAME = "name"
    ACUITY = "acuity"
    STATUS = "status"


class SearchView(StrEnum):
    """Reference-compatible derived census filters."""

    ALL_ACTIVE = "all_active"
    NEEDS_ATTENTION = "needs_attention"
    NO_TODAY = "no_today"
    PENDING_DIAGNOSTIC = "pending_diagnostic"
    OPEN_TODOS = "open_todos"
    CRITICAL_WATCHER = "critical_watcher"


@dataclass(frozen=True, slots=True)
class SearchFilters:
    status: AdmissionStatus | None = None
    acuity: Acuity | None = None
    view: SearchView = SearchView.ALL_ACTIVE
    missing_today: bool = False
    has_open_tasks: bool = False
    pending_diagnostic: bool = False


@dataclass(frozen=True, slots=True)
class SearchResult:
    patient_id: UUID
    mrn: str | None
    name: str
    species: str
    status: AdmissionStatus
    acuity: Acuity
    summary: str


class SearchService(ServiceBase):
    """Search clinical aggregates without leaking persistence records."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        publisher: EventPublisher | None = None,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory, publisher)
        self._today = today or date.today

    def search(
        self,
        query: str = "",
        *,
        filters: SearchFilters | None = None,
        sort: SearchSort = SearchSort.MANUAL,
    ) -> tuple[SearchResult, ...]:
        criteria = filters or SearchFilters()
        with self._unit_of_work_factory() as unit_of_work:
            patients = unit_of_work.patients.list()
        normalized = query.strip().casefold()
        selected = [
            patient
            for patient in patients
            if self._matches_text(patient, normalized) and self._matches_filters(patient, criteria)
        ]
        acuity_rank = {
            Acuity.CRITICAL: 0,
            Acuity.UNSTABLE: 1,
            Acuity.WATCHER: 2,
            Acuity.STABLE: 3,
            Acuity.UNKNOWN: 4,
        }
        keys = {
            SearchSort.MANUAL: lambda p: (p.active_order, p.name.casefold(), str(p.id)),
            SearchSort.NAME: lambda p: (p.name.casefold(), str(p.id)),
            SearchSort.ACUITY: lambda p: (
                acuity_rank[self._current_acuity(p)],
                p.name.casefold(),
                str(p.id),
            ),
            SearchSort.STATUS: lambda p: (
                p.admission_status.value,
                p.name.casefold(),
                str(p.id),
            ),
        }
        selected.sort(key=keys[sort])
        return tuple(
            SearchResult(
                p.id,
                p.mrn,
                p.name,
                p.species,
                p.admission_status,
                self._current_acuity(p),
                p.one_line_summary,
            )
            for p in selected
        )

    @classmethod
    def _matches_text(cls, patient: Patient, query: str) -> bool:
        if not query:
            return True
        values = [
            patient.mrn or "",
            patient.species,
            patient.breed or "",
            patient.one_line_summary,
            patient.blood_type or "",
            patient.code_status.value,
            patient.admission_status.value,
            patient.acuity.value,
        ]
        for day in patient.hospital_days:
            values.extend(
                (
                    day.calendar_date.isoformat(),
                    day.label or "",
                    day.acuity.value,
                    day.clinical_summary,
                    day.assessment,
                    day.treatment_changes,
                    day.physical_examination,
                    day.overnight_resident,
                    day.faculty,
                    day.sandbox_text,
                )
            )
            for task in day.tasks:
                values.extend(
                    (
                        task.title,
                        task.description,
                        task.assigned_to or "",
                        task.category.value,
                        task.bucket.value,
                    )
                )
            for problem in day.problem_list.problems:
                values.extend(
                    (
                        problem.title,
                        problem.description,
                        problem.assessment,
                        problem.plan,
                        problem.notes,
                    )
                )
            for device in day.instrumentation.devices:
                values.extend(
                    (
                        device.device_type.value.replace("_", " "),
                        device.anatomical_location,
                        device.size or "",
                        device.notes,
                        *device.complications,
                    )
                )
            for document in day.soap_documents:
                values.extend(
                    (
                        document.markdown_text,
                        document.subjective,
                        document.objective,
                        document.assessment,
                        document.plan,
                        document.author,
                    )
                )
        return cls._fuzzy_name_match(patient.name, query) or any(
            query in value.casefold() for value in values
        )

    def _matches_filters(self, patient: Patient, filters: SearchFilters) -> bool:
        if filters.status is not None and patient.admission_status is not filters.status:
            return False
        acuity = self._current_acuity(patient)
        if filters.acuity is not None and acuity is not filters.acuity:
            return False
        latest = patient.hospital_days[-1] if patient.hospital_days else None
        tasks = self._authoritative_tasks(patient)
        missing_today = patient.admission_status is AdmissionStatus.ADMITTED and (
            latest is None or latest.calendar_date != self._today()
        )
        open_todos = any(
            task.category is TaskCategory.CLINICAL
            and task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
            for task in tasks
        )
        pending_diagnostic = any(
            task.category is TaskCategory.DIAGNOSTIC
            and task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
            for task in tasks
        )
        if filters.missing_today and not missing_today:
            return False
        if filters.has_open_tasks and not any(
            t.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED} for t in tasks
        ):
            return False
        if filters.pending_diagnostic and not pending_diagnostic:
            return False
        return {
            SearchView.ALL_ACTIVE: True,
            SearchView.NEEDS_ATTENTION: (
                open_todos
                or pending_diagnostic
                or missing_today
                or acuity in {Acuity.CRITICAL, Acuity.UNSTABLE, Acuity.WATCHER}
            ),
            SearchView.NO_TODAY: missing_today,
            SearchView.PENDING_DIAGNOSTIC: pending_diagnostic,
            SearchView.OPEN_TODOS: open_todos,
            SearchView.CRITICAL_WATCHER: acuity
            in {Acuity.CRITICAL, Acuity.UNSTABLE, Acuity.WATCHER},
        }[filters.view]

    @staticmethod
    def _current_acuity(patient: Patient) -> Acuity:
        latest = patient.hospital_days[-1] if patient.hospital_days else None
        return latest.acuity if latest is not None else patient.acuity

    @staticmethod
    def _authoritative_tasks(patient: Patient) -> tuple[Task, ...]:
        newest: dict[UUID, Task] = {}
        for day in patient.hospital_days:
            for task in day.tasks:
                current = newest.get(task.lineage_id)
                if current is None or task.occurrence_number > current.occurrence_number:
                    newest[task.lineage_id] = task
        return tuple(newest.values())

    @staticmethod
    def _fuzzy_name_match(name: str, query: str) -> bool:
        normalized = name.strip().casefold()
        if query in normalized:
            return True
        query_tokens = query.split()
        name_tokens = normalized.replace("-", " ").split()
        if len(query_tokens) > 1 and all(
            any(query_token in name_token for name_token in name_tokens)
            for query_token in query_tokens
        ):
            return True
        iterator = iter(normalized)
        return bool(query) and all(character in iterator for character in query)
