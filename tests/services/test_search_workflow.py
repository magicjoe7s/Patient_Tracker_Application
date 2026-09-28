"""Slice 11 canonical search, derived-filter, bin, and ranking tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from types import TracebackType

from icu_patient_tracker.domain.enums import Acuity, AdmissionStatus, TaskCategory
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.sandbox_service import SandboxService
from icu_patient_tracker.services.search_service import (
    SearchFilters,
    SearchService,
    SearchSort,
    SearchView,
)
from icu_patient_tracker.services.soap_service import SOAPService
from icu_patient_tracker.services.task_service import TaskService

TODAY = date(2026, 7, 22)
NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)


def test_derived_views_and_disposition_bins_are_deterministic(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients_today = PatientService(factory, now=lambda: NOW)
    patients_yesterday = PatientService(factory, now=lambda: NOW - timedelta(days=1))
    days = HospitalDayService(factory)
    tasks = TaskService(factory)
    search = SearchService(factory, today=lambda: TODAY)

    critical = patients_today.create(name="Critical", species="Canine")
    days.update(critical.id, critical.hospital_days[0].id, acuity=Acuity.CRITICAL)
    todo = patients_today.create(name="Todo", species="Canine")
    tasks.create(todo.id, todo.hospital_days[0].id, title="Call owner")
    diagnostic = patients_today.create(name="Diagnostic", species="Feline")
    tasks.create(
        diagnostic.id,
        diagnostic.hospital_days[0].id,
        title="Review culture",
        category=TaskCategory.DIAGNOSTIC,
    )
    patients_yesterday.create(name="Missing", species="Canine")
    patients_today.create(name="Quiet", species="Feline")
    home = patients_today.create(name="Home DX", species="Canine")
    tasks.create(
        home.id,
        home.hospital_days[0].id,
        title="Review biopsy",
        category=TaskCategory.DIAGNOSTIC,
    )
    patients_today.change_status(home.id, AdmissionStatus.DISCHARGED)

    def names(
        view: SearchView,
        status: AdmissionStatus | None = AdmissionStatus.ADMITTED,
    ) -> set[str]:
        return {
            result.name for result in search.search(filters=SearchFilters(status=status, view=view))
        }

    assert names(SearchView.NO_TODAY) == {"Missing"}
    assert names(SearchView.OPEN_TODOS) == {"Todo"}
    assert names(SearchView.PENDING_DIAGNOSTIC) == {"Diagnostic"}
    assert names(SearchView.CRITICAL_WATCHER) == {"Critical"}
    assert names(SearchView.NEEDS_ATTENTION) == {
        "Critical",
        "Todo",
        "Diagnostic",
        "Missing",
    }
    assert names(SearchView.ALL_ACTIVE) == {
        "Critical",
        "Todo",
        "Diagnostic",
        "Missing",
        "Quiet",
    }
    assert names(SearchView.PENDING_DIAGNOSTIC, AdmissionStatus.DISCHARGED) == {"Home DX"}


def test_search_finds_cross_day_soap_and_sandbox_and_archived_records(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: NOW - timedelta(days=1))
    days = HospitalDayService(factory)
    soap = SOAPService(factory)
    sandbox = SandboxService(factory)
    search = SearchService(factory, today=lambda: TODAY)
    patient = patients.create(mrn="A-100", name="Bellatrix", species="Canine")
    old_day = patient.hospital_days[0]
    document = soap.create(patient.id, old_day.id, author="Dr. Search")
    soap.save_markdown(
        patient.id,
        old_day.id,
        document.id,
        "# Historical SOAP\nRare transfusion reaction",
    )
    sandbox.save(patient.id, old_day.id, "Owner mentioned hidden medication")
    days.create(patient.id, start_at=NOW)
    patients.change_status(patient.id, AdmissionStatus.ARCHIVED)

    archived = SearchFilters(status=AdmissionStatus.ARCHIVED)
    assert [result.name for result in search.search("transfusion reaction", filters=archived)] == [
        "Bellatrix"
    ]
    assert [result.name for result in search.search("hidden medication", filters=archived)] == [
        "Bellatrix"
    ]
    assert [result.name for result in search.search("bltrx", filters=archived)] == ["Bellatrix"]


def test_duplicate_names_use_stable_uuid_tie_break_and_empty_query_respects_sort(
    database_manager: DatabaseManager,
) -> None:
    factory = database_manager.unit_of_work
    patients = PatientService(factory, now=lambda: NOW)
    search = SearchService(factory, today=lambda: TODAY)
    first = patients.create(mrn="B2", name="Bella", species="Canine")
    second = patients.create(mrn="A1", name="Bella", species="Feline")
    patients.create(mrn="C3", name="Alfie", species="Canine")

    results = search.search(
        "",
        filters=SearchFilters(status=AdmissionStatus.ADMITTED),
        sort=SearchSort.NAME,
    )

    assert [result.name for result in results] == ["Alfie", "Bella", "Bella"]
    bella_ids = [result.patient_id for result in results if result.name == "Bella"]
    assert bella_ids == sorted((first.id, second.id), key=str)


class _SearchRepository:
    def __init__(self, patients: tuple[Patient, ...]) -> None:
        self._patients = patients

    def list(self) -> tuple[Patient, ...]:
        return self._patients


class _SearchUnitOfWork:
    def __init__(self, patients: tuple[Patient, ...]) -> None:
        self.patients = _SearchRepository(patients)

    def __enter__(self) -> _SearchUnitOfWork:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exception_type, exception, traceback
        return False


def test_in_memory_search_remains_interactive_above_expected_census_size() -> None:
    population = tuple(
        Patient(
            name=f"Patient {index:04d}",
            species="Canine",
            one_line_summary="needle" if index == 1_999 else "routine",
            active_order=index,
        )
        for index in range(2_000)
    )
    service = SearchService(  # type: ignore[arg-type]
        lambda: _SearchUnitOfWork(population), today=lambda: TODAY
    )

    started = perf_counter()
    results = service.search("needle", filters=SearchFilters(status=AdmissionStatus.ADMITTED))
    elapsed = perf_counter() - started

    assert [result.name for result in results] == ["Patient 1999"]
    assert elapsed < 1.0
