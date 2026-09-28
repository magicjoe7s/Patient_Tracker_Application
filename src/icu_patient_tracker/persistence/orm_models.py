"""SQLAlchemy records kept separate from the clinical domain model."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from icu_patient_tracker.domain.enums import (
    Acuity,
    AdmissionStatus,
    ClinicalPriority,
    CodeStatus,
    DeviceStatus,
    DeviceType,
    DocumentStatus,
    HospitalDayStatus,
    ProblemStatus,
    ReminderScheduleType,
    ReminderStatus,
    ReproductiveStatus,
    Sex,
    SOAPDocumentType,
    SOAPUpdateType,
    TaskBucket,
    TaskCategory,
    TaskStatus,
)


def enum_values(enum_class: type[object]) -> list[str]:
    """Store stable StrEnum values instead of Python member names."""
    return [str(member.value) for member in enum_class]  # type: ignore[attr-defined]


class AwareDateTime(TypeDecorator[datetime]):
    """Round-trip timezone-aware ISO timestamps because SQLite drops timezone offsets."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Persisted timestamps must include timezone information.")
        return value.isoformat()

    def process_result_value(self, value: str | None, dialect: object) -> datetime | None:
        return datetime.fromisoformat(value) if value is not None else None


class Base(DeclarativeBase):
    """Declarative metadata root for the current persistence schema."""


class SyncTrackedRecord:
    """Server reconciliation metadata shared by synchronized clinical records."""

    server_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(AwareDateTime())


class PatientRecord(SyncTrackedRecord, Base):
    """Stored patient aggregate root."""

    __tablename__ = "patients"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    mrn: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    species: Mapped[str] = mapped_column(String(128), nullable=False)
    breed: Mapped[str | None] = mapped_column(String(128))
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, native_enum=False, values_callable=enum_values), nullable=False
    )
    reproductive_status: Mapped[ReproductiveStatus] = mapped_column(
        Enum(ReproductiveStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    estimated_age_years: Mapped[float | None] = mapped_column(Float)
    body_weight_kg: Mapped[float | None] = mapped_column(Float)
    one_line_summary: Mapped[str] = mapped_column(Text, nullable=False)
    code_status: Mapped[CodeStatus] = mapped_column(
        Enum(CodeStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    blood_type: Mapped[str | None] = mapped_column(String(64))
    acuity: Mapped[Acuity] = mapped_column(
        Enum(Acuity, native_enum=False, values_callable=enum_values), nullable=False
    )
    admission_status: Mapped[AdmissionStatus] = mapped_column(
        Enum(AdmissionStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    active_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    hospital_days: Mapped[list[HospitalDayRecord]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="HospitalDayRecord.day_number",
    )


class HospitalDayRecord(SyncTrackedRecord, Base):
    """Stored calendar-date hospitalization context."""

    __tablename__ = "hospital_days"
    __table_args__ = (
        UniqueConstraint("patient_id", "calendar_date", name="uq_hospital_day_date"),
        UniqueConstraint("patient_id", "day_number", name="uq_hospital_day_number"),
        UniqueConstraint("id", "patient_id", name="uq_hospital_day_owner"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    patient_id: Mapped[UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    status: Mapped[HospitalDayStatus] = mapped_column(
        Enum(HospitalDayStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    acuity: Mapped[Acuity] = mapped_column(
        Enum(Acuity, native_enum=False, values_callable=enum_values), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(255))
    treatment_changes: Mapped[str] = mapped_column(Text, nullable=False)
    physical_examination: Mapped[str] = mapped_column(Text, nullable=False)
    assessment: Mapped[str] = mapped_column(Text, nullable=False)
    clinical_summary: Mapped[str] = mapped_column(Text, nullable=False)
    overnight_resident: Mapped[str] = mapped_column(String(255), nullable=False)
    faculty: Mapped[str] = mapped_column(String(255), nullable=False)
    sandbox_text: Mapped[str] = mapped_column(Text, nullable=False)
    emr_uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    patient: Mapped[PatientRecord] = relationship(back_populates="hospital_days")
    problem_list: Mapped[ProblemListRecord] = relationship(
        back_populates="hospital_day", cascade="all, delete-orphan", single_parent=True
    )
    instrumentation: Mapped[InstrumentationRecord] = relationship(
        back_populates="hospital_day", cascade="all, delete-orphan", single_parent=True
    )
    tasks: Mapped[list[TaskRecord]] = relationship(
        back_populates="hospital_day",
        cascade="all, delete-orphan",
        order_by="TaskRecord.ordering_position",
    )
    soap_documents: Mapped[list[SOAPDocumentRecord]] = relationship(
        back_populates="hospital_day",
        cascade="all, delete-orphan",
        order_by="SOAPDocumentRecord.created_at",
    )


class ProblemListRecord(SyncTrackedRecord, Base):
    """Stored one-to-one problem collection for a hospital day."""

    __tablename__ = "problem_lists"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    hospital_day_id: Mapped[UUID] = mapped_column(
        ForeignKey("hospital_days.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    hospital_day: Mapped[HospitalDayRecord] = relationship(back_populates="problem_list")
    problems: Mapped[list[ProblemRecord]] = relationship(
        back_populates="problem_list",
        cascade="all, delete-orphan",
        order_by="ProblemRecord.ordering_position",
    )


class ProblemRecord(SyncTrackedRecord, Base):
    """Stored ordered clinical problem."""

    __tablename__ = "problems"
    __table_args__ = (
        UniqueConstraint("problem_list_id", "ordering_position", name="uq_problem_order"),
        ForeignKeyConstraint(
            ["source_problem_id"],
            ["problems.id"],
            name="fk_problem_source",
            ondelete="SET NULL",
        ),
        UniqueConstraint("problem_list_id", "lineage_id", name="uq_problem_lineage_day"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    problem_list_id: Mapped[UUID] = mapped_column(
        ForeignKey("problem_lists.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProblemStatus] = mapped_column(
        Enum(ProblemStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    priority: Mapped[ClinicalPriority] = mapped_column(
        Enum(ClinicalPriority, native_enum=False, values_callable=enum_values), nullable=False
    )
    identified_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    assessment: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    ordering_position: Mapped[int] = mapped_column(Integer, nullable=False)
    lineage_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_problem_id: Mapped[UUID | None] = mapped_column(Uuid)
    occurrence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    problem_list: Mapped[ProblemListRecord] = relationship(back_populates="problems")
    source_problem: Mapped[ProblemRecord | None] = relationship(
        remote_side="ProblemRecord.id", foreign_keys=[source_problem_id]
    )


class InstrumentationRecord(SyncTrackedRecord, Base):
    """Stored one-to-one device collection for a hospital day."""

    __tablename__ = "instrumentations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    hospital_day_id: Mapped[UUID] = mapped_column(
        ForeignKey("hospital_days.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    hospital_day: Mapped[HospitalDayRecord] = relationship(back_populates="instrumentation")
    devices: Mapped[list[DeviceRecord]] = relationship(
        back_populates="instrumentation",
        cascade="all, delete-orphan",
        order_by="DeviceRecord.ordering_position",
    )


class DeviceRecord(SyncTrackedRecord, Base):
    """Stored medical-device placement history."""

    __tablename__ = "devices"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    instrumentation_id: Mapped[UUID] = mapped_column(
        ForeignKey("instrumentations.id", ondelete="CASCADE"), nullable=False
    )
    device_type: Mapped[DeviceType] = mapped_column(
        Enum(DeviceType, native_enum=False, values_callable=enum_values), nullable=False
    )
    anatomical_location: Mapped[str] = mapped_column(String(255), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    size: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    complications: Mapped[str] = mapped_column(Text, nullable=False)
    ordering_position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    instrumentation: Mapped[InstrumentationRecord] = relationship(back_populates="devices")


class TaskRecord(SyncTrackedRecord, Base):
    """Stored task occurrence with stable cross-day lineage metadata."""

    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_task_id"], ["tasks.id"], name="fk_task_source", ondelete="SET NULL"
        ),
        UniqueConstraint("hospital_day_id", "lineage_id", name="uq_task_lineage_day"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    hospital_day_id: Mapped[UUID] = mapped_column(
        ForeignKey("hospital_days.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    priority: Mapped[ClinicalPriority] = mapped_column(
        Enum(ClinicalPriority, native_enum=False, values_callable=enum_values), nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[TaskCategory] = mapped_column(
        Enum(TaskCategory, native_enum=False, values_callable=enum_values), nullable=False
    )
    bucket: Mapped[TaskBucket] = mapped_column(
        Enum(TaskBucket, native_enum=False, values_callable=enum_values), nullable=False
    )
    source: Mapped[str | None] = mapped_column(String(255))
    lineage_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_task_id: Mapped[UUID | None] = mapped_column(Uuid)
    occurrence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    carry_forward: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ordering_position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    hospital_day: Mapped[HospitalDayRecord] = relationship(back_populates="tasks")
    source_task: Mapped[TaskRecord | None] = relationship(
        remote_side="TaskRecord.id", foreign_keys=[source_task_id]
    )
    reminder: Mapped[ReminderRecord | None] = relationship(
        back_populates="task", cascade="all, delete-orphan", single_parent=True
    )
    diagnostic_result: Mapped[DiagnosticResultRecord | None] = relationship(
        back_populates="task", cascade="all, delete-orphan", single_parent=True
    )


class DiagnosticResultRecord(SyncTrackedRecord, Base):
    """Stored lossless result linked one-to-one with a diagnostic task."""

    __tablename__ = "diagnostic_results"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    result_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    task: Mapped[TaskRecord] = relationship(back_populates="diagnostic_result")


class ReminderRecord(SyncTrackedRecord, Base):
    """Stored notification state for one task."""

    __tablename__ = "reminders"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    trigger_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_type: Mapped[ReminderScheduleType] = mapped_column(
        Enum(ReminderScheduleType, native_enum=False, values_callable=enum_values), nullable=False
    )
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    fixed_time: Mapped[time | None] = mapped_column(Time)
    anchor_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    snoozed_until: Mapped[datetime | None] = mapped_column(AwareDateTime())
    dismissed_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    last_shown_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    task: Mapped[TaskRecord] = relationship(back_populates="reminder")


class SOAPDocumentRecord(SyncTrackedRecord, Base):
    """Stored structured SOAP document and immutable audit state."""

    __tablename__ = "soap_documents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    hospital_day_id: Mapped[UUID] = mapped_column(
        ForeignKey("hospital_days.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[SOAPDocumentType] = mapped_column(
        Enum(SOAPDocumentType, native_enum=False, values_callable=enum_values), nullable=False
    )
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    update_type: Mapped[SOAPUpdateType] = mapped_column(
        Enum(SOAPUpdateType, native_enum=False, values_callable=enum_values), nullable=False
    )
    subjective: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    assessment: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, values_callable=enum_values), nullable=False
    )
    amends_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("soap_documents.id", ondelete="SET NULL")
    )
    finalized_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    hospital_day: Mapped[HospitalDayRecord] = relationship(back_populates="soap_documents")
    amends_document: Mapped[SOAPDocumentRecord | None] = relationship(
        remote_side="SOAPDocumentRecord.id", foreign_keys=[amends_document_id]
    )
    problem_links: Mapped[list[SOAPProblemReferenceRecord]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="SOAPProblemReferenceRecord.ordering_position",
    )


class SOAPProblemReferenceRecord(Base):
    """Ordered reference from a SOAP document to a problem in its aggregate."""

    __tablename__ = "soap_problem_references"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("soap_documents.id", ondelete="CASCADE"), primary_key=True
    )
    problem_id: Mapped[UUID] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True
    )
    ordering_position: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[SOAPDocumentRecord] = relationship(back_populates="problem_links")
    problem: Mapped[ProblemRecord] = relationship()


class SyncDeviceRecord(Base):
    """Stable identity and pull cursor for this local installation."""

    __tablename__ = "sync_devices"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_pull_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(AwareDateTime())


class SyncOutboxRecord(Base):
    """Durable idempotent mutation waiting to be pushed to the server."""

    __tablename__ = "sync_outbox"

    operation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    base_server_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)


class SyncConflictRecord(Base):
    """Preserved local and server values for explicit clinician resolution."""

    __tablename__ = "sync_conflicts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_outbox.operation_id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    local_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    server_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    server_version: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(32))
    resolved_at: Mapped[datetime | None] = mapped_column(AwareDateTime())


class ClinicalSyncRecord(Base):
    """Latest durable local revision, including deletion after the patient is removed."""

    __tablename__ = "clinical_sync"
    patient_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    local_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    synced_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    server_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    operation_revision: Mapped[int | None] = mapped_column(Integer)


class SyncStateRecord(Base):
    """Singleton local account/workspace and synchronization status."""

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_devices.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_push_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    last_pull_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    status: Mapped[str] = mapped_column(String(32), nullable=False)
