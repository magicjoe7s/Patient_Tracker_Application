"""Representative non-sensitive domain graphs used by persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.enums import DeviceType, SOAPDocumentType
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task


def make_representative_patient(mrn: str | None = "123456") -> Patient:
    """Build two hospital days containing every persisted Phase III child type."""
    patient = Patient("Bella", "Canine", mrn=mrn, breed="Mixed", body_weight_kg=12.5)
    first_start = datetime(2026, 7, 20, 7, tzinfo=UTC)
    second_start = first_start + timedelta(days=1)
    first_day = HospitalDay(patient.id, first_start.date(), 1, first_start)
    second_day = HospitalDay(patient.id, second_start.date(), 2, second_start)

    hypotension = Problem(patient.id, first_day.id, "Hypotension", assessment="Fluid responsive")
    anemia = Problem(patient.id, first_day.id, "Anemia", plan="Trend PCV/TS")
    first_day.problem_list.add(hypotension)
    first_day.problem_list.add(anemia)
    first_day.problem_list.reorder([anemia.id, hypotension.id])

    catheter = Device(
        patient.id,
        first_day.id,
        DeviceType.PERIPHERAL_IV_CATHETER,
        "Left cephalic",
        first_start,
        size="20 ga",
    )
    urinary_catheter = Device(
        patient.id,
        first_day.id,
        DeviceType.URINARY_CATHETER,
        "Urinary bladder",
        first_start + timedelta(hours=1),
    )
    urinary_catheter.mark_removed(first_start + timedelta(hours=8))
    first_day.instrumentation.add(catheter)
    first_day.instrumentation.add(urinary_catheter)

    original_task = Task(
        patient.id,
        first_day.id,
        "Recheck blood pressure",
        description="Doppler measurement",
    )
    original_task.complete()
    reminder = Reminder(
        original_task.id,
        patient.id,
        first_day.id,
        first_start + timedelta(hours=2),
        "Blood pressure recheck due",
    )
    first_day.add_task(original_task)
    first_day.add_reminder(reminder)

    carried_task = Task(
        patient.id,
        second_day.id,
        original_task.title,
        lineage_id=original_task.lineage_id,
        source_task_id=original_task.id,
        occurrence_number=2,
    )
    second_day.add_task(carried_task)

    document = SOAPDocument(
        patient.id,
        first_day.id,
        SOAPDocumentType.DAILY,
        "Dr. Rivera",
        subjective="Resting comfortably",
        objective="HR 100 bpm",
        assessment="Perfusion improved",
        plan="Continue monitoring",
        problem_ids=(anemia.id, hypotension.id),
    )
    document.finalize()
    first_day.add_soap_document(document)
    amendment = document.create_amendment("Dr. Chen")
    amendment.update_sections(plan="Continue monitoring; corrected dose")
    amendment.finalize()
    first_day.add_soap_document(amendment)

    patient.add_hospital_day(first_day)
    patient.add_hospital_day(second_day)
    return patient
