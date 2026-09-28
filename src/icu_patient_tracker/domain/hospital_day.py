"""Calendar-based hospital-day aggregate and relationship boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from icu_patient_tracker.domain.enums import Acuity, HospitalDayStatus
from icu_patient_tracker.domain.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidStateTransitionError,
    RelationshipError,
)
from icu_patient_tracker.domain.instrumentation import Instrumentation
from icu_patient_tracker.domain.problem_list import ProblemList
from icu_patient_tracker.domain.reminder import Reminder
from icu_patient_tracker.domain.soap_document import SOAPDocument
from icu_patient_tracker.domain.task import Task
from icu_patient_tracker.domain.validation import (
    require_enum,
    require_text,
    require_uuid,
    validate_audit_timestamps,
    validate_timestamp_order,
)


@dataclass(slots=True)
class HospitalDay:
    """A calendar-date ICU working context owned by exactly one patient."""

    patient_id: UUID
    calendar_date: date
    day_number: int
    start_at: datetime
    end_at: datetime | None = None
    status: HospitalDayStatus = HospitalDayStatus.OPEN
    acuity: Acuity = Acuity.UNKNOWN
    label: str | None = None
    treatment_changes: str = ""
    physical_examination: str = ""
    assessment: str = ""
    clinical_summary: str = ""
    overnight_resident: str = ""
    faculty: str = ""
    sandbox_text: str = ""
    emr_uploaded: bool = False
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _problem_list: ProblemList = field(init=False, repr=False)
    _instrumentation: Instrumentation = field(init=False, repr=False)
    _tasks: list[Task] = field(default_factory=list, repr=False)
    _soap_documents: list[SOAPDocument] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.patient_id = require_uuid(self.patient_id, "patient_id")
        self.id = require_uuid(self.id, "id")
        self.status = require_enum(self.status, HospitalDayStatus, "status")
        self.acuity = require_enum(self.acuity, Acuity, "acuity")
        if self.label is not None:
            self.label = require_text(self.label, "label")
        if self.day_number < 1:
            raise DomainValidationError("day_number must be at least 1.")
        validate_timestamp_order(self.start_at, self.end_at, "start_at", "end_at")
        validate_audit_timestamps(self.created_at, self.updated_at)
        if "\n" in self.overnight_resident or "\n" in self.faculty:
            raise DomainValidationError("SOAP staff attribution must be a single line.")
        if not isinstance(self.emr_uploaded, bool):
            raise DomainValidationError("emr_uploaded must be a boolean.")
        if self.calendar_date != self.start_at.date():
            raise DomainValidationError(
                "calendar_date must match the local calendar date of start_at."
            )
        if self.status is HospitalDayStatus.CLOSED and self.end_at is None:
            raise DomainValidationError("A closed hospital day requires end_at.")
        if self.status is HospitalDayStatus.OPEN and self.end_at is not None:
            raise DomainValidationError("An open hospital day cannot have end_at.")
        self._problem_list = ProblemList(self.patient_id, self.id)
        self._instrumentation = Instrumentation(self.patient_id, self.id)

        initial_tasks = list(self._tasks)
        initial_documents = list(self._soap_documents)
        self._tasks.clear()
        self._soap_documents.clear()
        for task in initial_tasks:
            self.add_task(task)
        for document in initial_documents:
            self.add_soap_document(document)

    @property
    def problem_list(self) -> ProblemList:
        """Return the sole problem list owned by this hospital day."""
        return self._problem_list

    @property
    def instrumentation(self) -> Instrumentation:
        """Return the sole instrumentation record owned by this hospital day."""
        return self._instrumentation

    @property
    def tasks(self) -> tuple[Task, ...]:
        """Return tasks in insertion order."""
        return tuple(self._tasks)

    @property
    def reminders(self) -> tuple[Reminder, ...]:
        """Derive reminders from their canonical owning tasks."""
        return tuple(task.reminder for task in self._tasks if task.reminder is not None)

    @property
    def soap_documents(self) -> tuple[SOAPDocument, ...]:
        """Return SOAP documents in creation order."""
        return tuple(sorted(self._soap_documents, key=lambda document: document.created_at))

    def add_task(self, task: Task) -> None:
        """Attach a task with matching patient and hospital-day ownership."""
        self._validate_child(task.patient_id, task.hospital_day_id, "Task")
        if any(existing.id == task.id for existing in self._tasks):
            raise DuplicateEntityError(f"Task {task.id} is already attached.")
        self._tasks.append(task)
        self._touch()

    def add_reminder(self, reminder: Reminder) -> None:
        """Attach a reminder to its existing task and expose it through this day."""
        self._validate_child(reminder.patient_id, reminder.hospital_day_id, "Reminder")
        task = self.get_task(reminder.task_id)
        task.attach_reminder(reminder)
        self._touch()

    def add_soap_document(self, document: SOAPDocument) -> None:
        """Attach a unique SOAP document with matching ownership."""
        self._validate_child(document.patient_id, document.hospital_day_id, "SOAP document")
        if any(existing.id == document.id for existing in self._soap_documents):
            raise DuplicateEntityError(f"SOAP document {document.id} is already attached.")
        self._soap_documents.append(document)
        self._touch()

    def get_task(self, task_id: UUID) -> Task:
        """Return a task by stable identifier."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        raise EntityNotFoundError(f"Task {task_id} is not attached to this hospital day.")

    def remove_task(self, task_id: UUID) -> Task:
        """Remove one explicit task occurrence from this hospital day."""
        task = self.get_task(task_id)
        self._tasks.remove(task)
        self._touch()
        return task

    def close(self, end_at: datetime | None = None) -> None:
        """Close an open hospital day with a valid end timestamp."""
        if self.status is HospitalDayStatus.CLOSED:
            raise InvalidStateTransitionError("Hospital day is already closed.")
        closing_time = end_at or datetime.now(UTC)
        validate_timestamp_order(self.start_at, closing_time, "start_at", "end_at")
        self.status = HospitalDayStatus.CLOSED
        self.end_at = closing_time
        self._touch()

    def assign_day_number(self, day_number: int) -> None:
        """Assign the chronological ICU ordinal within the owning patient."""
        if day_number < 1:
            raise DomainValidationError("day_number must be at least 1.")
        if self.day_number != day_number:
            self.day_number = day_number
            self._touch()

    def update_clinical_content(
        self,
        *,
        acuity: Acuity | None = None,
        treatment_changes: str | None = None,
        physical_examination: str | None = None,
        assessment: str | None = None,
        clinical_summary: str | None = None,
    ) -> None:
        """Update day-owned structured text without SOAP formatting concerns."""
        if acuity is not None:
            self.acuity = require_enum(acuity, Acuity, "acuity")
        if treatment_changes is not None:
            self.treatment_changes = treatment_changes
        if physical_examination is not None:
            self.physical_examination = physical_examination
        if assessment is not None:
            self.assessment = assessment
        if clinical_summary is not None:
            self.clinical_summary = clinical_summary
        self._touch()

    def update_soap_staff(self, *, overnight_resident: str, faculty: str) -> None:
        """Replace day-owned SOAP attribution with normalized single-line values."""
        resident = " ".join(overnight_resident.split())
        faculty_name = " ".join(faculty.split())
        self.overnight_resident = resident
        self.faculty = faculty_name
        self._touch()

    def update_sandbox(self, sandbox_text: str) -> None:
        """Replace the day-owned Markdown scratch space without interpreting it."""
        self.sandbox_text = sandbox_text
        self._touch()

    def set_emr_uploaded(self, uploaded: bool) -> None:
        """Record whether this day's SOAP has been handed off to the EMR."""
        if not isinstance(uploaded, bool):
            raise DomainValidationError("uploaded must be a boolean.")
        self.emr_uploaded = uploaded
        self._touch()

    def replace_label(self, label: str | None) -> None:
        """Set or clear the optional day note used by the timeline."""
        self.label = require_text(label, "label") if label is not None else None
        self._touch()

    def _validate_child(self, patient_id: UUID, hospital_day_id: UUID, label: str) -> None:
        if patient_id != self.patient_id:
            raise RelationshipError(f"{label} belongs to a different patient.")
        if hospital_day_id != self.id:
            raise RelationshipError(f"{label} belongs to a different hospital day.")

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"HospitalDay(id={self.id!r}, patient_id={self.patient_id!r}, "
            f"day_number={self.day_number}, status={self.status.value!r})"
        )
