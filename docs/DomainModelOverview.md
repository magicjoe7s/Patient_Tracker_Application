# Clinical Domain Model Overview

## Purpose

The Phase III domain layer defines the persistence-independent clinical vocabulary of the ICU
Patient Tracker. Models are typed Python dataclasses with explicit validation and lifecycle
methods. They do not import PySide6, SQLAlchemy, repositories, or services.

SQLAlchemy persistence models and mapping code remain a separate future concern. This preserves
the architecture's downward dependency direction and prevents database details from becoming
clinical rules.

## Principal Relationships

```text
Patient (application-generated UUID is the stable identifier)
└── 0..* HospitalDay (UUID; calendar-date working context)
    ├── 1 ProblemList
    │   └── 0..* Problem
    ├── 1 Instrumentation
    │   └── 0..* Device
    ├── 0..* Task
    │   └── 0..1 Reminder
    └── 0..* SOAPDocument

ApplicationState
└── references selected identifiers only; owns no clinical record
```

Ownership is enforced when an entity enters an aggregate collection. Child entities carry the
owning patient UUID and hospital-day UUID so invalid cross-patient or cross-day assignments fail at
the domain boundary.

## Important Decisions

### Patient identity

An application-generated UUID is the canonical, stable patient identifier. The user never creates
or edits it. MRN is an optional, unique secondary identifier and may be added or corrected later
without changing patient ownership or history. Names are required but are not unique. New patients
require species; the explicit `Unknown` value is reserved for legacy import and can be corrected.

### Hospital-day definition

A hospital day is a calendar-date working context. Its `calendar_date` must match the local date
represented by its timezone-aware `start_at`. `day_number` is admission-relative, starts at one,
and must be unique within a patient.

### Problem ownership

Each hospital day owns exactly one `ProblemList`, and every `Problem` belongs to exactly one list.
The same problem object is not shared between hospital days. Future carry-forward behavior must
copy or explicitly link problems without creating duplicate canonical ownership.

### Device retention

Each hospital day owns one `Instrumentation` collection. Marking a device removed records a
clinical removal timestamp and retains history. `delete_record()` is a distinct operation reserved
for correcting an erroneous record; authorization and confirmation belong in a future service.

### Tasks and reminders

A `Task` is required work and always belongs to a patient hospital day. A `Reminder` is only a
notification and is owned by one task. Completing or dismissing a reminder does not automatically
complete its task; future services will coordinate that workflow explicitly.

Each task occurrence has its own UUID plus a stable `lineage_id`. Carried occurrences reference
the preceding task through `source_task_id`, increment `occurrence_number`, and retain an explicit
`carry_forward` preference. Persistence preserves this metadata; Phase V services implement
the carry-forward workflow.

### SOAP immutability

SOAP sections remain separate fields. A finalized document cannot be edited in place. Amendments
are new draft documents that reference the immutable source document and receive their own UUID.

### Application state

`ApplicationState` contains only transient selection, workspace, filters, and dirty state. It
references clinical records by identifier and never owns them.

## Validation Conventions

- All required text is trimmed and must remain non-empty.
- Persistent child objects use UUID identifiers.
- Clinical and audit timestamps must include timezone information.
- End, removal, resolution, completion, and finalization times must respect relevant ordering rules.
- Constrained clinical states use `StrEnum` values.
- Invalid transitions, duplicates, missing members, and relationship violations raise focused
  domain exceptions.
- Collections expose tuples or copies so callers cannot bypass membership rules.

## Deferred Decisions

The following decisions require workflow or persistence design beyond Phase III:

- Cross-day problem continuity semantics.
- Detailed patient admission-status transition policy, including readmission episodes.
- Whether later workflows need truly global housekeeping tasks outside a hospital day.
- User and role identity models for task assignment and SOAP authorship.
- Extension policy for uncommon device types beyond `DeviceType.OTHER`.
- Service-layer authorization and confirmation for permanent record deletion.
- SQLAlchemy table design, mapping, cascade behavior, and migration strategy.
- Serialization and external interchange formats.
- Scheduling, delivery, and task-coordination behavior for reminders.
