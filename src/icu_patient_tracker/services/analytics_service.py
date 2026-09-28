"""Deterministic, read-only operational analytics derived from canonical records."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    ProblemStatus,
    TaskCategory,
    TaskStatus,
)
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.services.clipboard_service import ClipboardWriter
from icu_patient_tracker.services.common import ServiceBase, UnitOfWorkFactory
from icu_patient_tracker.services.exceptions import ClipboardServiceError


@dataclass(frozen=True, slots=True)
class StatusCount:
    status: AdmissionStatus
    count: int


@dataclass(frozen=True, slots=True)
class AcuityCount:
    acuity: Acuity
    count: int


@dataclass(frozen=True, slots=True)
class TermCount:
    term: str
    count: int


@dataclass(frozen=True, slots=True)
class AnalyticsSnapshot:
    """One immutable current-state report with no independent persistence."""

    generated_at: datetime
    total_patients: int
    active_count: int
    status_counts: tuple[StatusCount, ...]
    acuity_counts: tuple[AcuityCount, ...]
    average_icu_days: float
    pending_active_count: int
    missing_today_count: int
    top_pending_diagnostics: tuple[TermCount, ...]
    top_problem_terms: tuple[TermCount, ...]
    needs_attention: tuple[str, ...]


class AnalyticsService(ServiceBase):
    """Compute and export current operational summaries without mutating clinical data."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        writer: ClipboardWriter,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(unit_of_work_factory)
        self._writer = writer
        self._now = now or (lambda: datetime.now().astimezone())

    def snapshot(self) -> AnalyticsSnapshot:
        generated_at = self._now()
        with self._unit_of_work_factory() as unit_of_work:
            patients = unit_of_work.patients.list()
        active = tuple(
            sorted(
                (p for p in patients if p.admission_status is AdmissionStatus.ADMITTED),
                key=lambda patient: (
                    patient.active_order if patient.active_order is not None else 1_000_000,
                    patient.name.casefold(),
                    str(patient.id),
                ),
            )
        )
        statuses = Counter(patient.admission_status for patient in patients)
        acuities = Counter(self._current_acuity(patient) for patient in active)
        pending_terms: Counter[str] = Counter()
        problem_terms: Counter[str] = Counter()
        pending_names: list[str] = []
        missing_names: list[str] = []
        today = generated_at.date()

        for patient in active:
            open_diagnostics = tuple(
                task
                for task in self._authoritative_tasks(patient)
                if task.category is TaskCategory.DIAGNOSTIC
                and task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
            )
            for task in open_diagnostics:
                term = _normalize_term(task.title)
                if term:
                    pending_terms[term] += 1
            if open_diagnostics:
                pending_names.append(f"{patient.name} ({len(open_diagnostics)} pending)")
            if not any(day.calendar_date == today for day in patient.hospital_days):
                missing_names.append(patient.name)
            latest = patient.hospital_days[-1] if patient.hospital_days else None
            if latest is not None:
                for problem in latest.problem_list.problems:
                    if problem.status in {ProblemStatus.RESOLVED, ProblemStatus.INACTIVE}:
                        continue
                    for raw_term in re.split(r"[,;\n]+", problem.title):
                        term = _normalize_term(raw_term)
                        if term:
                            problem_terms[term] += 1

        needs_attention = tuple(
            [f"{name} (no entry today)" for name in missing_names] + pending_names
        )
        active_count = len(active)
        total_days = sum(len(patient.hospital_days) for patient in active)
        return AnalyticsSnapshot(
            generated_at=generated_at,
            total_patients=len(patients),
            active_count=active_count,
            status_counts=tuple(
                StatusCount(status, statuses[status]) for status in AdmissionStatus
            ),
            acuity_counts=tuple(AcuityCount(acuity, acuities[acuity]) for acuity in Acuity),
            average_icu_days=round(total_days / active_count, 1) if active_count else 0.0,
            pending_active_count=len(pending_names),
            missing_today_count=len(missing_names),
            top_pending_diagnostics=_top_terms(pending_terms, 5),
            top_problem_terms=_top_terms(problem_terms, 10),
            needs_attention=needs_attention,
        )

    def copy_report(self, snapshot: AnalyticsSnapshot | None = None) -> str:
        report = format_analytics_report(snapshot or self.snapshot())
        exported = report.replace("\n", "\r\n")
        try:
            self._writer.set_text(exported)
        except Exception as error:
            raise ClipboardServiceError(
                "The analytics report could not be copied. Please try again."
            ) from error
        return exported

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


def format_analytics_report(snapshot: AnalyticsSnapshot) -> str:
    """Render the characterized fixed-order, read-only analytics report."""
    status = {row.status: row.count for row in snapshot.status_counts}
    acuity = {row.acuity: row.count for row in snapshot.acuity_counts}
    lines = [
        f"ICU Tracker Analytics - {snapshot.generated_at:%Y-%m-%d %H:%M}",
        "",
        "Census",
        f"- Total patients: {snapshot.total_patients}",
        f"- Active census: {snapshot.active_count}",
        (
            "- Status split: "
            f"Active {status[AdmissionStatus.ADMITTED]} | "
            f"Home {status[AdmissionStatus.DISCHARGED]} | "
            f"IMC {status[AdmissionStatus.TRANSFERRED]} | "
            f"Archived {status[AdmissionStatus.ARCHIVED]} | "
            f"Death {status[AdmissionStatus.DECEASED]}"
        ),
        "",
        "Active Patient Metrics",
        (
            "- Acuity split: "
            f"Unselected {acuity[Acuity.UNKNOWN]} | "
            f"Stable {acuity[Acuity.STABLE]} | "
            f"Watcher {acuity[Acuity.WATCHER]} | "
            f"Unstable {acuity[Acuity.UNSTABLE]} | "
            f"Critical {acuity[Acuity.CRITICAL]}"
        ),
        f"- Average ICU days (active): {snapshot.average_icu_days:.1f}",
        (
            "- Active patients with pending diagnostics: "
            f"{snapshot.pending_active_count}/{snapshot.active_count}"
        ),
        f"- Active patients without an entry for today: {snapshot.missing_today_count}",
        "",
        "Top Logical Pending Diagnostics",
        *_format_terms(snapshot.top_pending_diagnostics),
        "",
        "Top Problem List Terms (active patients)",
        *_format_terms(snapshot.top_problem_terms),
        "",
        "Needs Attention Today",
        *(f"- {item}" for item in snapshot.needs_attention),
    ]
    if not snapshot.needs_attention:
        lines.append("- none")
    return "\n".join(lines)


def _normalize_term(value: str) -> str:
    normalized = re.sub(r"[^\w\s\-/]", "", value.strip().casefold())
    return " ".join(normalized.split())


def _top_terms(counter: Counter[str], limit: int) -> tuple[TermCount, ...]:
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return tuple(TermCount(term, count) for term, count in ordered[:limit])


def _format_terms(rows: tuple[TermCount, ...]) -> tuple[str, ...]:
    return tuple(f"- {row.term} ({row.count})" for row in rows) or ("- none",)
