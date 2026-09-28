"""Controlled clinical vocabulary shared by domain models."""

from enum import StrEnum


class Sex(StrEnum):
    """Recorded biological sex when known."""

    FEMALE = "female"
    MALE = "male"
    INTERSEX = "intersex"
    UNKNOWN = "unknown"


class ReproductiveStatus(StrEnum):
    """Recorded reproductive status when known."""

    INTACT = "intact"
    SPAYED = "spayed"
    NEUTERED = "neutered"
    UNKNOWN = "unknown"


class AdmissionStatus(StrEnum):
    """Patient-level hospitalization state."""

    ADMITTED = "admitted"
    TRANSFERRED = "transferred"
    DISCHARGED = "discharged"
    DECEASED = "deceased"
    ARCHIVED = "archived"


class CodeStatus(StrEnum):
    """Patient-level cardiopulmonary resuscitation directive."""

    FULL_CODE = "full_code"
    DO_NOT_RESUSCITATE = "do_not_resuscitate"
    DVM_DISCRETION = "dvm_discretion"
    DNR_ASSIST = "dnr_assist"
    LIMITED = "limited"
    UNKNOWN = "unknown"


class Acuity(StrEnum):
    """Clinical attention level used for patient and hospital-day summaries."""

    UNKNOWN = "unknown"
    STABLE = "stable"
    WATCHER = "watcher"
    UNSTABLE = "unstable"
    CRITICAL = "critical"


class HospitalDayStatus(StrEnum):
    """Whether a hospital-day working context remains open."""

    OPEN = "open"
    CLOSED = "closed"


class ClinicalPriority(StrEnum):
    """Shared urgency vocabulary for problems and tasks."""

    ROUTINE = "routine"
    LOW = "low"
    URGENT = "urgent"
    CRITICAL = "critical"


class ProblemStatus(StrEnum):
    """Observed clinical trajectory of a problem."""

    ACTIVE = "active"
    IMPROVING = "improving"
    WORSENING = "worsening"
    STATIC = "static"
    RESOLVED = "resolved"
    INACTIVE = "inactive"


class DeviceType(StrEnum):
    """Common ICU device categories; OTHER preserves legitimate uncommon devices."""

    PERIPHERAL_IV_CATHETER = "peripheral_iv_catheter"
    CENTRAL_VENOUS_CATHETER = "central_venous_catheter"
    URINARY_CATHETER = "urinary_catheter"
    FECAL_FOLEY = "fecal_foley"
    ARTERIAL_CATHETER = "arterial_catheter"
    FEEDING_TUBE = "feeding_tube"
    CHEST_TUBE = "chest_tube"
    ABDOMINAL_DRAIN = "abdominal_drain"
    SUBCUTANEOUS_DRAIN = "subcutaneous_drain"
    OXYGEN_DELIVERY = "oxygen_delivery"
    OTHER = "other"


class DeviceStatus(StrEnum):
    """Placement lifecycle for a medical device."""

    ACTIVE = "active"
    REMOVED = "removed"


class TaskStatus(StrEnum):
    """Execution state of required work."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DEFERRED = "deferred"


class TaskCategory(StrEnum):
    """Source grouping for clinical and administrative work."""

    CLINICAL = "clinical"
    POCUS = "pocus"
    DIAGNOSTIC = "diagnostic"
    ADMINISTRATIVE = "administrative"
    HOUSEKEEPING = "housekeeping"


class TaskBucket(StrEnum):
    """Workflow destination for a task occurrence."""

    TODAY = "today"
    OVERNIGHT = "overnight"
    DISCHARGE = "discharge"
    FOLLOW_UP = "follow_up"
    DIAGNOSTIC = "diagnostic"


class ReminderStatus(StrEnum):
    """Notification lifecycle independent of task completion."""

    PENDING = "pending"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReminderScheduleType(StrEnum):
    """Persisted rule used to calculate reminder trigger times."""

    ABSOLUTE = "absolute"
    INTERVAL = "interval"
    FIXED_TIME = "fixed_time"


class SOAPDocumentType(StrEnum):
    """Clinical purpose of a SOAP document."""

    ADMISSION = "admission"
    DAILY = "daily"
    PROGRESS = "progress"
    DISCHARGE = "discharge"


class SOAPUpdateType(StrEnum):
    """Whether a document is original or supplements a finalized document."""

    ORIGINAL = "original"
    AMENDMENT = "amendment"
    CORRECTION = "correction"


class DocumentStatus(StrEnum):
    """Editability and audit state of a SOAP document."""

    DRAFT = "draft"
    FINALIZED = "finalized"
    AMENDED = "amended"


class Workspace(StrEnum):
    """Top-level transient workspace selection."""

    CENSUS = "census"
    CHARTING = "charting"
    SOAP = "soap"
    TASKS = "tasks"
