"""Read-only Slice 15 operational analytics tests."""

from datetime import UTC, datetime, timedelta

from icu_patient_tracker.domain.enums import Acuity, AdmissionStatus, TaskCategory
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.analytics_service import (
    AnalyticsService,
    format_analytics_report,
)
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.problem_service import ProblemService
from icu_patient_tracker.services.task_service import TaskService

START = datetime(2026, 7, 20, 8, tzinfo=UTC)
REPORT_TIME = datetime(2026, 7, 22, 12, tzinfo=UTC)


class RecordingWriter:
    """Capture the narrow clipboard port without requiring Qt."""

    def __init__(self) -> None:
        self.text = ""

    def set_text(self, text: str) -> None:
        self.text = text


def test_snapshot_is_deterministic_and_uses_authoritative_current_state(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: START)
    days = HospitalDayService(factory)
    problems = ProblemService(factory)
    tasks = TaskService(factory)
    writer = RecordingWriter()
    analytics = AnalyticsService(factory, writer, now=lambda: REPORT_TIME)

    bella = patients.create(name="Bella", species="Canine")
    bella_first = bella.hospital_days[0]
    problems.add(bella.id, bella_first.id, title="Sepsis, AKI")
    tasks.create(
        bella.id,
        bella_first.id,
        title="CBC",
        category=TaskCategory.DIAGNOSTIC,
    )
    tasks.create(
        bella.id,
        bella_first.id,
        title="Culture!",
        category=TaskCategory.DIAGNOSTIC,
    )
    bella_today = days.create(bella.id, start_at=START + timedelta(days=2))
    days.update(bella.id, bella_today.id, acuity=Acuity.CRITICAL)
    culture = next(task for task in bella_today.tasks if task.title == "Culture!")
    tasks.complete(bella.id, culture.id, at=REPORT_TIME)

    milo = patients.create(name="Milo", species="Feline", acuity=Acuity.WATCHER)
    milo_day = milo.hospital_days[0]
    problems.add(milo.id, milo_day.id, title="Sepsis")
    tasks.create(
        milo.id,
        milo_day.id,
        title=" cbc ",
        category=TaskCategory.DIAGNOSTIC,
    )
    patients.create(name="Nova", species="Canine")

    for name, status in (
        ("Home", AdmissionStatus.DISCHARGED),
        ("IMC", AdmissionStatus.TRANSFERRED),
        ("Archived", AdmissionStatus.ARCHIVED),
        ("Deceased", AdmissionStatus.DECEASED),
    ):
        patient = patients.create(name=name, species="Unknown")
        patients.change_status(patient.id, status)

    first = analytics.snapshot()
    second = analytics.snapshot()

    assert first == second
    assert first.total_patients == 7
    assert first.active_count == 3
    assert {row.status: row.count for row in first.status_counts} == {
        AdmissionStatus.ADMITTED: 3,
        AdmissionStatus.TRANSFERRED: 1,
        AdmissionStatus.DISCHARGED: 1,
        AdmissionStatus.DECEASED: 1,
        AdmissionStatus.ARCHIVED: 1,
    }
    assert {row.acuity: row.count for row in first.acuity_counts} == {
        Acuity.UNKNOWN: 1,
        Acuity.STABLE: 0,
        Acuity.WATCHER: 1,
        Acuity.UNSTABLE: 0,
        Acuity.CRITICAL: 1,
    }
    assert first.average_icu_days == 1.3
    assert first.pending_active_count == 2
    assert first.missing_today_count == 2
    assert [(row.term, row.count) for row in first.top_pending_diagnostics] == [("cbc", 2)]
    assert [(row.term, row.count) for row in first.top_problem_terms] == [
        ("sepsis", 2),
        ("aki", 1),
    ]
    assert first.needs_attention == (
        "Milo (no entry today)",
        "Nova (no entry today)",
        "Bella (1 pending)",
        "Milo (1 pending)",
    )

    report = format_analytics_report(first)
    assert "ICU Tracker Analytics - 2026-07-22 12:00" in report
    assert "- Status split: Active 3 | Home 1 | IMC 1 | Archived 1 | Death 1" in report
    assert "- Acuity split: Unselected 1 | Stable 0 | Watcher 1 | Unstable 0 | Critical 1" in report
    assert "- cbc (2)" in report
    assert analytics.copy_report(first) == report.replace("\n", "\r\n")
    assert writer.text == report.replace("\n", "\r\n")


def test_empty_snapshot_and_report_have_explicit_zero_state(
    database_manager: DatabaseManager,
) -> None:
    writer = RecordingWriter()
    analytics = AnalyticsService(
        database_manager.unit_of_work,
        writer,
        now=lambda: REPORT_TIME,
    )

    snapshot = analytics.snapshot()
    report = format_analytics_report(snapshot)

    assert snapshot.total_patients == 0
    assert snapshot.active_count == 0
    assert snapshot.average_icu_days == 0.0
    assert snapshot.top_pending_diagnostics == ()
    assert snapshot.top_problem_terms == ()
    assert snapshot.needs_attention == ()
    assert report.count("- none") == 3
