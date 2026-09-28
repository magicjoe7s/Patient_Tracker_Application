"""Hospital-day calendar rule, ownership, and lifecycle tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from icu_patient_tracker.domain.enums import HospitalDayStatus, SOAPDocumentType
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
    RelationshipError,
)
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task


def make_day() -> HospitalDay:
    start = datetime(2026, 7, 20, 7, tzinfo=UTC)
    return HospitalDay(uuid4(), start.date(), 1, start)


def test_hospital_day_creates_required_owned_collections() -> None:
    hospital_day = make_day()

    assert hospital_day.status is HospitalDayStatus.OPEN
    assert hospital_day.problem_list.hospital_day_id == hospital_day.id
    assert hospital_day.instrumentation.hospital_day_id == hospital_day.id
    assert hospital_day.tasks == ()
    assert "day_number=1" in repr(hospital_day)


def test_hospital_day_enforces_calendar_and_timestamp_rules() -> None:
    start = datetime(2026, 7, 20, 7, tzinfo=UTC)
    with pytest.raises(DomainValidationError, match="calendar_date"):
        HospitalDay(uuid4(), (start + timedelta(days=1)).date(), 1, start)
    with pytest.raises(DomainValidationError, match="day_number"):
        HospitalDay(uuid4(), start.date(), 0, start)


def test_hospital_day_closes_once() -> None:
    hospital_day = make_day()
    end = hospital_day.start_at + timedelta(hours=12)
    hospital_day.close(end)

    assert hospital_day.status is HospitalDayStatus.CLOSED
    assert hospital_day.end_at == end
    with pytest.raises(InvalidStateTransitionError):
        hospital_day.close(end)


def test_hospital_day_connects_tasks_reminders_and_documents() -> None:
    hospital_day = make_day()
    task = Task(hospital_day.patient_id, hospital_day.id, "Recheck blood pressure")
    reminder = Reminder(
        task.id,
        hospital_day.patient_id,
        hospital_day.id,
        hospital_day.start_at + timedelta(hours=2),
        "Recheck due",
    )
    document = SOAPDocument(
        hospital_day.patient_id, hospital_day.id, SOAPDocumentType.DAILY, "Dr. Rivera"
    )
    hospital_day.add_task(task)
    hospital_day.add_reminder(reminder)
    hospital_day.add_soap_document(document)

    assert hospital_day.tasks == (task,)
    assert hospital_day.reminders == (reminder,)
    assert hospital_day.soap_documents == (document,)


def test_hospital_day_rejects_children_from_other_contexts() -> None:
    hospital_day = make_day()
    with pytest.raises(RelationshipError):
        hospital_day.add_task(Task(uuid4(), hospital_day.id, "Wrong patient"))
    with pytest.raises(RelationshipError):
        hospital_day.add_task(Task(hospital_day.patient_id, uuid4(), "Wrong day"))
