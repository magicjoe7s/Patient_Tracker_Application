"""Database-backed Slice 8 SOAP Markdown and synchronization workflows."""

from datetime import UTC, datetime, timedelta

from icu_patient_tracker.domain.enums import Acuity, CodeStatus, TaskCategory, TaskStatus
from icu_patient_tracker.persistence.database import DatabaseManager
from icu_patient_tracker.services.events import RecordingEventPublisher
from icu_patient_tracker.services.hospital_day_service import HospitalDayService
from icu_patient_tracker.services.patient_service import PatientService
from icu_patient_tracker.services.problem_service import ProblemService
from icu_patient_tracker.services.soap_service import SOAPService
from icu_patient_tracker.services.task_service import TaskService

START = datetime(2026, 7, 22, 8, tzinfo=UTC)


def test_lossless_markdown_reverse_mapping_and_staff_carry_survive_restart(
    database_manager: DatabaseManager,
) -> None:
    publisher = RecordingEventPublisher()
    factory = database_manager.unit_of_work
    patients = PatientService(factory, publisher, now=lambda: START)
    days = HospitalDayService(factory, publisher)
    problems = ProblemService(factory, publisher)
    tasks = TaskService(factory, publisher)
    soap = SOAPService(factory, publisher)
    patient = patients.create(name="Bella", species="Canine")
    day = patient.hospital_days[0]
    problem = problems.add(patient.id, day.id, title="Anemia")
    diagnostic = tasks.create(
        patient.id,
        day.id,
        title="CBC",
        category=TaskCategory.DIAGNOSTIC,
    )
    document = soap.create(
        patient.id,
        day.id,
        author="Dr. Author",
        daytime_resident="Dr. Day",
    )
    edited = (
        document.markdown_text.replace("**One Liner:** #INPUT#", "**One Liner:** Improving")
        .replace(
            "## **Problem list**\n1. #INPUT#",
            "## **Problem list**\n1. Regenerative anemia\n   - PCV improved to 28%",
        )
        .replace(
            "**Diagnostic Summary**\n- #INPUT#",
            "**Diagnostic Summary**\n- CBC: mild anemia",
        )
        .replace("**AM:**\n- #INPUT#", "**AM:**\n- HR 100 bpm", 1)
        .replace(
            "*Overnight ICU Resident:* #INPUT#",
            "*Overnight ICU Resident:* Dr. Night",
        )
        .replace("*Faculty:* #INPUT#", "*Faculty:* Dr. Faculty")
    )
    edited += "\n\n## Custom material\nPreserve  two spaces  exactly."

    saved = soap.save_markdown(patient.id, day.id, document.id, edited)

    assert saved.markdown_text == edited
    loaded_patient = patients.get(patient.id)
    loaded_day = days.get(patient.id, day.id)
    assert loaded_patient.one_line_summary == "Improving"
    assert loaded_day.physical_examination == "HR 100 bpm"
    assert loaded_day.clinical_summary == "CBC: mild anemia"
    assert loaded_day.overnight_resident == "Dr. Night"
    assert loaded_day.faculty == "Dr. Faculty"
    assert loaded_day.problem_list.problems[0].id == problem.id
    assert loaded_day.problem_list.problems[0].title == "Regenerative anemia"
    assert loaded_day.problem_list.problems[0].description == "PCV improved to 28%"
    assert loaded_day.tasks[0].id == diagnostic.id
    assert loaded_day.tasks[0].title == "CBC"
    assert loaded_day.tasks[0].status is TaskStatus.PENDING
    assert loaded_day.soap_documents[0].markdown_text == edited

    patients.update_summary(patient.id, code_status=CodeStatus.DNR_ASSIST)
    days.update(patient.id, day.id, acuity=Acuity.CRITICAL)
    next_day = days.create(patient.id, start_at=START + timedelta(days=1))
    assert next_day.acuity is Acuity.UNKNOWN
    next_soap = soap.create(patient.id, next_day.id, author="Dr. Author")
    assert "**Code Status:** DNR with assist" in next_soap.markdown_text
    assert "**Clinical Trend:** #INPUT#" in next_soap.markdown_text
    assert next_day.overnight_resident == "Dr. Night"
    assert next_day.faculty == "Dr. Faculty"


def test_soap_problem_list_additions_reconcile_into_structured_list(
    database_manager: DatabaseManager,
) -> None:
    publisher = RecordingEventPublisher()
    factory = database_manager.unit_of_work
    patients = PatientService(factory, publisher, now=lambda: START)
    problems = ProblemService(factory, publisher)
    soap = SOAPService(factory, publisher)
    patient = patients.create(name="Milo", species="Feline")
    day = patient.hospital_days[0]
    problems.add(patient.id, day.id, title="Anemia")
    document = soap.create(patient.id, day.id, author="Dr. Author")
    edited = document.markdown_text.replace(
        "## **Problem list**\n1. #INPUT#",
        "## **Problem list**\n1. Anemia\n2. New ambiguous problem",
    )

    soap.save_markdown(patient.id, day.id, document.id, edited)

    loaded = patients.get(patient.id)
    assert [problem.title for problem in loaded.hospital_days[0].problem_list.problems] == [
        "Anemia",
        "New ambiguous problem",
    ]
    assert loaded.hospital_days[0].soap_documents[0].markdown_text == edited
