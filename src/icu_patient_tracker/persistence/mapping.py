"""Explicit conversion between pure domain aggregates and SQLAlchemy records."""

from __future__ import annotations

import json
from uuid import UUID

from icu_patient_tracker.domain.device import Device
from icu_patient_tracker.domain.diagnostic_result import DiagnosticResult
from icu_patient_tracker.domain.hospital_day import HospitalDay
from icu_patient_tracker.domain.instrumentation import Instrumentation
from icu_patient_tracker.domain.patient import Patient
from icu_patient_tracker.domain.problem import Problem
from icu_patient_tracker.domain.problem_list import ProblemList
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.persistence.orm_models import (
    DeviceRecord,
    DiagnosticResultRecord,
    HospitalDayRecord,
    InstrumentationRecord,
    PatientRecord,
    ProblemListRecord,
    ProblemRecord,
    ReminderRecord,
    SOAPDocumentRecord,
    SOAPProblemReferenceRecord,
    TaskRecord,
)


def patient_to_record(patient: Patient) -> PatientRecord:
    """Convert a complete patient aggregate into a detached ORM graph."""
    record = PatientRecord(
        id=patient.id,
        mrn=patient.mrn,
        name=patient.name,
        species=patient.species,
        breed=patient.breed,
        sex=patient.sex,
        reproductive_status=patient.reproductive_status,
        date_of_birth=patient.date_of_birth,
        estimated_age_years=patient.estimated_age_years,
        body_weight_kg=patient.body_weight_kg,
        one_line_summary=patient.one_line_summary,
        code_status=patient.code_status,
        blood_type=patient.blood_type,
        acuity=patient.acuity,
        admission_status=patient.admission_status,
        active_order=patient.active_order,
        created_at=patient.created_at,
        updated_at=patient.updated_at,
        hospital_days=[hospital_day_to_record(day) for day in patient.hospital_days],
    )
    tasks_by_id = {
        task.id: task for hospital_day in record.hospital_days for task in hospital_day.tasks
    }
    for task in tasks_by_id.values():
        if task.source_task_id is not None:
            try:
                task.source_task = tasks_by_id[task.source_task_id]
            except KeyError as error:
                raise ValueError(
                    f"Task {task.id} references source task {task.source_task_id} "
                    "outside the patient aggregate."
                ) from error
    documents_by_id = {
        document.id: document
        for hospital_day in record.hospital_days
        for document in hospital_day.soap_documents
    }
    for document in documents_by_id.values():
        if document.amends_document_id is not None:
            try:
                document.amends_document = documents_by_id[document.amends_document_id]
            except KeyError as error:
                raise ValueError(
                    f"SOAP document {document.id} references source document "
                    f"{document.amends_document_id} outside the patient aggregate."
                ) from error
    return record


def hospital_day_to_record(hospital_day: HospitalDay) -> HospitalDayRecord:
    """Convert a hospital-day aggregate and every owned child record."""
    problem_list_record = problem_list_to_record(hospital_day.problem_list)
    document_records = [
        soap_document_to_record(document) for document in hospital_day.soap_documents
    ]
    problems_by_id = {problem.id: problem for problem in problem_list_record.problems}
    for document in document_records:
        for reference in document.problem_links:
            try:
                reference.problem = problems_by_id[reference.problem_id]
            except KeyError as error:
                raise ValueError(
                    f"SOAP document {document.id} references problem "
                    f"{reference.problem_id} outside its hospital day."
                ) from error
    return HospitalDayRecord(
        id=hospital_day.id,
        patient_id=hospital_day.patient_id,
        calendar_date=hospital_day.calendar_date,
        day_number=hospital_day.day_number,
        start_at=hospital_day.start_at,
        end_at=hospital_day.end_at,
        status=hospital_day.status,
        acuity=hospital_day.acuity,
        label=hospital_day.label,
        treatment_changes=hospital_day.treatment_changes,
        physical_examination=hospital_day.physical_examination,
        assessment=hospital_day.assessment,
        clinical_summary=hospital_day.clinical_summary,
        overnight_resident=hospital_day.overnight_resident,
        faculty=hospital_day.faculty,
        sandbox_text=hospital_day.sandbox_text,
        emr_uploaded=hospital_day.emr_uploaded,
        created_at=hospital_day.created_at,
        updated_at=hospital_day.updated_at,
        problem_list=problem_list_record,
        instrumentation=instrumentation_to_record(hospital_day.instrumentation),
        tasks=[
            task_to_record(task, ordering_position)
            for ordering_position, task in enumerate(hospital_day.tasks)
        ],
        soap_documents=document_records,
    )


def problem_list_to_record(problem_list: ProblemList) -> ProblemListRecord:
    """Convert an ordered clinical problem collection."""
    return ProblemListRecord(
        id=problem_list.id,
        hospital_day_id=problem_list.hospital_day_id,
        created_at=problem_list.created_at,
        updated_at=problem_list.updated_at,
        problems=[problem_to_record(problem) for problem in problem_list.problems],
    )


def problem_to_record(problem: Problem) -> ProblemRecord:
    """Convert one clinical problem."""
    return ProblemRecord(
        id=problem.id,
        title=problem.title,
        description=problem.description,
        status=problem.status,
        priority=problem.priority,
        identified_at=problem.identified_at,
        resolved_at=problem.resolved_at,
        assessment=problem.assessment,
        plan=problem.plan,
        notes=problem.notes,
        ordering_position=problem.ordering_position,
        lineage_id=problem.lineage_id,
        source_problem_id=problem.source_problem_id,
        occurrence_number=problem.occurrence_number,
        created_at=problem.created_at,
        updated_at=problem.updated_at,
    )


def instrumentation_to_record(
    instrumentation: Instrumentation,
) -> InstrumentationRecord:
    """Convert a device collection while preserving insertion order explicitly."""
    return InstrumentationRecord(
        id=instrumentation.id,
        hospital_day_id=instrumentation.hospital_day_id,
        created_at=instrumentation.created_at,
        updated_at=instrumentation.updated_at,
        devices=[
            device_to_record(device, ordering_position)
            for ordering_position, device in enumerate(instrumentation.devices)
        ],
    )


def device_to_record(device: Device, ordering_position: int) -> DeviceRecord:
    """Convert one device, encoding its immutable complication sequence as JSON."""
    return DeviceRecord(
        id=device.id,
        device_type=device.device_type,
        anatomical_location=device.anatomical_location,
        placed_at=device.placed_at,
        status=device.status,
        removed_at=device.removed_at,
        size=device.size,
        notes=device.notes,
        complications=json.dumps(device.complications),
        ordering_position=ordering_position,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


def task_to_record(task: Task, ordering_position: int) -> TaskRecord:
    """Convert one task occurrence and its optional reminder."""
    return TaskRecord(
        id=task.id,
        hospital_day_id=task.hospital_day_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        due_at=task.due_at,
        completed_at=task.completed_at,
        assigned_to=task.assigned_to,
        category=task.category,
        bucket=task.bucket,
        source=task.source,
        lineage_id=task.lineage_id,
        source_task_id=task.source_task_id,
        occurrence_number=task.occurrence_number,
        carry_forward=task.carry_forward,
        ordering_position=ordering_position,
        created_at=task.created_at,
        updated_at=task.updated_at,
        reminder=reminder_to_record(task.reminder) if task.reminder is not None else None,
        diagnostic_result=(
            diagnostic_result_to_record(task.diagnostic_result)
            if task.diagnostic_result is not None
            else None
        ),
    )


def diagnostic_result_to_record(result: DiagnosticResult) -> DiagnosticResultRecord:
    """Convert one task-owned diagnostic result."""
    return DiagnosticResultRecord(
        id=result.id,
        task_id=result.task_id,
        result_text=result.result_text,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )


def reminder_to_record(reminder: Reminder) -> ReminderRecord:
    """Convert one task notification."""
    return ReminderRecord(
        id=reminder.id,
        task_id=reminder.task_id,
        trigger_at=reminder.trigger_at,
        message=reminder.message,
        schedule_type=reminder.schedule_type,
        interval_minutes=reminder.interval_minutes,
        fixed_time=reminder.fixed_time,
        anchor_at=reminder.anchor_at,
        status=reminder.status,
        snoozed_until=reminder.snoozed_until,
        dismissed_at=reminder.dismissed_at,
        completed_at=reminder.completed_at,
        last_shown_at=reminder.last_shown_at,
        created_at=reminder.created_at,
        updated_at=reminder.updated_at,
    )


def soap_document_to_record(document: SOAPDocument) -> SOAPDocumentRecord:
    """Convert one structured document and ordered problem references."""
    return SOAPDocumentRecord(
        id=document.id,
        hospital_day_id=document.hospital_day_id,
        document_type=document.document_type,
        author=document.author,
        update_type=document.update_type,
        subjective=document.subjective,
        objective=document.objective,
        assessment=document.assessment,
        plan=document.plan,
        markdown_text=document.markdown_text,
        status=document.status,
        amends_document_id=document.amends_document_id,
        finalized_at=document.finalized_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        problem_links=[
            SOAPProblemReferenceRecord(
                problem_id=problem_id,
                ordering_position=ordering_position,
            )
            for ordering_position, problem_id in enumerate(document.problem_ids)
        ],
    )


def patient_from_record(record: PatientRecord) -> Patient:
    """Rehydrate a complete patient aggregate without changing persisted timestamps."""
    patient = Patient(
        name=record.name,
        species=record.species,
        id=record.id,
        mrn=record.mrn,
        breed=record.breed,
        sex=record.sex,
        reproductive_status=record.reproductive_status,
        date_of_birth=record.date_of_birth,
        estimated_age_years=record.estimated_age_years,
        body_weight_kg=record.body_weight_kg,
        one_line_summary=record.one_line_summary,
        code_status=record.code_status,
        blood_type=record.blood_type,
        acuity=record.acuity,
        admission_status=record.admission_status,
        active_order=record.active_order,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
    for hospital_day_record in record.hospital_days:
        patient.add_hospital_day(hospital_day_from_record(hospital_day_record, record.id))
    patient.updated_at = record.updated_at
    return patient


def hospital_day_from_record(record: HospitalDayRecord, patient_id: UUID) -> HospitalDay:
    """Rehydrate one hospital-day aggregate and restore all owned collections."""
    hospital_day = HospitalDay(
        patient_id=patient_id,
        calendar_date=record.calendar_date,
        day_number=record.day_number,
        start_at=record.start_at,
        end_at=record.end_at,
        status=record.status,
        acuity=record.acuity,
        label=record.label,
        treatment_changes=record.treatment_changes,
        physical_examination=record.physical_examination,
        assessment=record.assessment,
        clinical_summary=record.clinical_summary,
        overnight_resident=record.overnight_resident,
        faculty=record.faculty,
        sandbox_text=record.sandbox_text,
        emr_uploaded=record.emr_uploaded,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
    hospital_day._problem_list = problem_list_from_record(record.problem_list, patient_id)
    hospital_day._instrumentation = instrumentation_from_record(record.instrumentation, patient_id)
    for task_record in record.tasks:
        hospital_day.add_task(task_from_record(task_record, patient_id))
    for document_record in record.soap_documents:
        hospital_day.add_soap_document(soap_document_from_record(document_record, patient_id))
    hospital_day.updated_at = record.updated_at
    return hospital_day


def problem_list_from_record(record: ProblemListRecord, patient_id: UUID) -> ProblemList:
    """Rehydrate an ordered problem collection."""
    result = ProblemList(
        patient_id=patient_id,
        hospital_day_id=record.hospital_day_id,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        _problems=[
            problem_from_record(problem, patient_id, record.hospital_day_id)
            for problem in record.problems
        ],
    )
    result.updated_at = record.updated_at
    return result


def problem_from_record(record: ProblemRecord, patient_id: UUID, day_id: UUID) -> Problem:
    """Rehydrate one clinical problem."""
    return Problem(
        patient_id=patient_id,
        hospital_day_id=day_id,
        title=record.title,
        description=record.description,
        status=record.status,
        priority=record.priority,
        identified_at=record.identified_at,
        resolved_at=record.resolved_at,
        assessment=record.assessment,
        plan=record.plan,
        notes=record.notes,
        ordering_position=record.ordering_position,
        lineage_id=record.lineage_id,
        source_problem_id=record.source_problem_id,
        occurrence_number=record.occurrence_number,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def instrumentation_from_record(record: InstrumentationRecord, patient_id: UUID) -> Instrumentation:
    """Rehydrate current and historical medical devices."""
    result = Instrumentation(
        patient_id=patient_id,
        hospital_day_id=record.hospital_day_id,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        _devices=[
            device_from_record(device, patient_id, record.hospital_day_id)
            for device in record.devices
        ],
    )
    result.updated_at = record.updated_at
    return result


def device_from_record(record: DeviceRecord, patient_id: UUID, day_id: UUID) -> Device:
    """Rehydrate one medical device and its complication sequence."""
    decoded_complications = json.loads(record.complications)
    if not isinstance(decoded_complications, list) or not all(
        isinstance(item, str) for item in decoded_complications
    ):
        raise ValueError(f"Device {record.id} has invalid complication data.")
    return Device(
        patient_id=patient_id,
        hospital_day_id=day_id,
        device_type=record.device_type,
        anatomical_location=record.anatomical_location,
        placed_at=record.placed_at,
        status=record.status,
        removed_at=record.removed_at,
        size=record.size,
        notes=record.notes,
        complications=tuple(decoded_complications),
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def task_from_record(record: TaskRecord, patient_id: UUID) -> Task:
    """Rehydrate one task occurrence and attach its optional reminder."""
    task = Task(
        patient_id=patient_id,
        hospital_day_id=record.hospital_day_id,
        title=record.title,
        description=record.description,
        status=record.status,
        priority=record.priority,
        due_at=record.due_at,
        completed_at=record.completed_at,
        assigned_to=record.assigned_to,
        category=record.category,
        bucket=record.bucket,
        source=record.source,
        lineage_id=record.lineage_id,
        source_task_id=record.source_task_id,
        occurrence_number=record.occurrence_number,
        carry_forward=record.carry_forward,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
    if record.reminder is not None:
        task.attach_reminder(reminder_from_record(record.reminder, patient_id, record))
        task.updated_at = record.updated_at
    if record.diagnostic_result is not None:
        task.attach_diagnostic_result(
            diagnostic_result_from_record(record.diagnostic_result, patient_id, record)
        )
        task.updated_at = record.updated_at
    return task


def diagnostic_result_from_record(
    record: DiagnosticResultRecord, patient_id: UUID, task_record: TaskRecord
) -> DiagnosticResult:
    """Rehydrate one task-owned diagnostic result."""
    return DiagnosticResult(
        patient_id=patient_id,
        hospital_day_id=task_record.hospital_day_id,
        task_id=record.task_id,
        result_text=record.result_text,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def reminder_from_record(
    record: ReminderRecord, patient_id: UUID, task_record: TaskRecord
) -> Reminder:
    """Rehydrate one task notification."""
    return Reminder(
        task_id=record.task_id,
        patient_id=patient_id,
        hospital_day_id=task_record.hospital_day_id,
        trigger_at=record.trigger_at,
        message=record.message,
        schedule_type=record.schedule_type,
        interval_minutes=record.interval_minutes,
        fixed_time=record.fixed_time,
        anchor_at=record.anchor_at,
        status=record.status,
        snoozed_until=record.snoozed_until,
        dismissed_at=record.dismissed_at,
        completed_at=record.completed_at,
        last_shown_at=record.last_shown_at,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def soap_document_from_record(record: SOAPDocumentRecord, patient_id: UUID) -> SOAPDocument:
    """Rehydrate one structured SOAP document and ordered problem references."""
    return SOAPDocument(
        patient_id=patient_id,
        hospital_day_id=record.hospital_day_id,
        document_type=record.document_type,
        author=record.author,
        update_type=record.update_type,
        subjective=record.subjective,
        objective=record.objective,
        assessment=record.assessment,
        plan=record.plan,
        markdown_text=record.markdown_text,
        problem_ids=tuple(link.problem_id for link in record.problem_links),
        status=record.status,
        amends_document_id=record.amends_document_id,
        finalized_at=record.finalized_at,
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
