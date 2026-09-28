
# DataModel.md

# ICU Patient Tracker Data Model

## Purpose

This document defines the canonical data model for the ICU Patient Tracker. It describes the clinical objects the application understands, their ownership, relationships, invariants, and lifecycle. It is intentionally independent of the database schema and user interface.

---

# Core Principles

- The data model represents the clinical workflow, not the database.
- Every piece of information has exactly one canonical owner.
- Derived information is calculated from canonical data whenever possible.
- Every object has a well-defined lifecycle and ownership.
- Hospital Day is the primary working context for clinicians.

---

# Object Hierarchy

```text
Application
│
├── ApplicationState
├── Settings
└── Patients
      │
      └── Patient
            │
            └── HospitalDay
                  ├── SOAPDocument
                  ├── Assessment
                  ├── PhysicalExam
                  ├── ClinicalSummary
                  ├── ProblemList
                  │     └── Problem
                  ├── Instrumentation
                  │     └── Device
                  ├── Tasks
                  │     └── Reminder
                  ├── TreatmentChanges
                  └── Sandbox
```

---

# Canonical Objects

## ApplicationState

Represents the current state of the running application.

Owns:
- Current patient
- Current hospital day
- Current selection
- Search/filter state
- Window layout
- Clipboard state
- Dirty state
- Autosave state

Only one ApplicationState exists.

---

## Patient

Represents one unique hospital patient.

### Identity

Each patient has a permanent unique identifier.

- An application-generated UUID is the immutable canonical identifier
- MRN is optional and must be unique when present
- Users do not create or edit the UUID directly
- Correcting an MRN never changes patient ownership or history
- Patient names are **not unique**
- Two patients may legitimately share the same name

### Typical attributes

- MRN
- Internal UUID
- Name
- Species
- Breed
- Sex
- Date of birth / Age
- Body weight
- Referring veterinarian
- Hospitalization status

### Owns

- Hospital Days

### Disposition lifecycle

The Python model stores canonical dispositions while the census retains the familiar labels:

| Census label | Canonical value |
|---|---|
| Active | Admitted |
| Home | Discharged |
| IMC | Transferred |
| Archived | Archived |
| Death | Deceased |

Active patients may move to Home, IMC, Archived, or Death. Home and IMC patients may be
readmitted or archived. Archived patients may be readmitted and are the only patients eligible for
permanent deletion. Death is terminal. Death, archive, and permanent deletion require explicit UI
confirmation. A readmitted or newly created patient joins the end of manual active order.

---

## HospitalDay

The HospitalDay is the primary working object within the application.

Nearly all clinician interaction occurs here.

Each HospitalDay belongs to exactly one Patient.

Hospital days are unique per patient and calendar date. They are displayed chronologically and
receive contiguous ICU ordinals beginning at one; inserting a backdated day safely renumbers the
timeline without changing stable day UUIDs. A newly created active patient receives today's first
day automatically.

Typical attributes:

- Date
- Hospital day number
- Attending service
- Status
- Code status
- Assigned clinician

Owns:

- SOAPDocument
- PhysicalExam
- Assessment
- ClinicalSummary
- ProblemList
- Instrumentation
- TreatmentChanges
- Tasks
- Sandbox
- EMR upload state

An appended day may carry unresolved problem occurrences, unfinished opted-in task occurrences,
active devices, overnight resident, and faculty from the latest prior day. A backdated insertion
does not branch carry-forward lineage.

`emr_uploaded` belongs to one hospital day, defaults to false, and becomes true only after a
successful SOAP clipboard handoff or an explicit user change. It is never inherited by another day.

---

## SOAPDocument

Lossless clinical Markdown document with conservative structured mappings.

Sections:

- Subjective
- Objective
- Assessment
- Plan

The full `markdown_text` is authoritative for user-authored formatting and unknown content. The four
structured fields remain available for explicit mappings and compatibility. Targeted refresh
changes only recognized regions; parsing never discards unrecognized text. Metadata includes
author, status, amendment identity, timestamps, and ordered problem references.

---

## PhysicalExam

Stores structured physical examination findings for a HospitalDay.

---

## Assessment

Stores the clinician's assessment for the day.

---

## ClinicalSummary

Stores the concise daily summary used for rounds and handoffs.

---

## ProblemList

Container for Problem objects.

Each Problem is independently editable.

Supports:

- Ordering
- Resolution
- Archiving
- Search
- Status changes

---

## Problem

Represents one active or historical medical problem.

Typical attributes:

- Description
- Status (active/resolved)
- Priority
- Date added
- Date resolved (optional)

Each daily problem occurrence has its own UUID plus a stable lineage UUID, optional source-problem
UUID, and occurrence number. Only unresolved and non-inactive problems carry to an appended day.
Forward mutations never rewrite an earlier hospital day.

---

## Instrumentation

Container for active devices.

Owns Device objects.

---

## Device

Represents one piece of instrumentation.

Examples:

- Urinary catheter
- Jugular catheter
- Arterial catheter
- Chest tube
- Nasogastric tube

Typical attributes:

- Type
- Placement date/time
- Location
- Status
- Notes

---

## Task

Represents one actionable clinical task.

Typical attributes:

- Title
- Description
- Priority
- Due time
- Status
- Completion time

Each Task belongs to exactly one HospitalDay.

Each stored task occurrence has its own UUID. A stable lineage UUID, optional source-task UUID,
occurrence number, and carry-forward preference preserve cross-day task history without sharing
object ownership between hospital days.

Task category, priority, bucket, and carry-forward behavior are stored as structured values rather
than title suffixes. The implemented clinical categories distinguish To Do (`clinical`), POCUS,
Pending Diagnostic (`diagnostic`), and Housekeeping. Completing an omitted carried diagnostic
preserves a historical tombstone; it is not deleted from prior or current hospital days.

---

## Reminder

Represents reminder behavior associated with a Task.

The persisted rule records its trigger, schedule type, interval or fixed-time parameters, lifecycle
status, snooze/terminal timestamps, and nullable `last_shown_at`. A carried task owns a new reminder
identity with the same actionable rule. Only the newest task occurrence in a lineage may notify.

---

## TreatmentChanges

Structured record of treatment modifications during the day.

---

## Sandbox

Lossless, day-owned Markdown working space for notes that are not yet part of the permanent record.
Saving never creates tasks. An explicit preview-and-confirm operation can create validated Clinical
or POCUS tasks from unchecked checklist rows without changing the Sandbox text.

---

## Settings

Application-wide configuration.

Examples:

- Theme
- Autosave
- Backup settings
- User preferences

---

# Relationships

```text
Patient
    1
    │
    └──────────< HospitalDay

HospitalDay
    1
    ├──────────1 SOAPDocument
    ├──────────1 Assessment
    ├──────────1 PhysicalExam
    ├──────────1 ClinicalSummary
    ├──────────1 ProblemList
    ├──────────1 Instrumentation
    ├──────────1 TreatmentChanges
    ├──────────1 Sandbox
    └──────────< Task

ProblemList
    └──────────< Problem

Instrumentation
    └──────────< Device

Task
    └──────────0..1 Reminder
```

---

# Invariants

These rules must always hold.

- Every Patient is uniquely identified by an application-generated UUID.
- MRN is optional and unique when present.
- Patient names are not unique.
- Every HospitalDay belongs to exactly one Patient.
- Every Task belongs to exactly one HospitalDay.
- Every Problem belongs to exactly one ProblemList.
- Every Device belongs to exactly one Instrumentation collection.
- Every canonical object has one owner.
- Objects may not exist without their parent.

---

# Canonical vs Derived Data

## Canonical (stored)

- Patient
- HospitalDay
- SOAPDocument
- Assessment
- PhysicalExam
- ClinicalSummary
- Problem
- Device
- Task
- Reminder
- TreatmentChanges
- Sandbox
- Settings

## Derived (calculated)

- Dashboard statistics
- Open task counts
- Search results
- Filtered patient lists
- Reminder queues
- Timeline summaries
- Analytics
- Status indicators

Derived data should never become the source of truth.

Operational analytics are calculated on demand from patient aggregates. Current acuity and problem
terms use the newest hospital day; pending diagnostics use the newest task occurrence per lineage.
Analytics snapshots are transient presentation values and require no database table or migration.

---

# Data Ownership

Every datum exists in exactly one location.

The application references canonical objects rather than duplicating values.

Duplicate ownership is considered an architectural error.

---

# Design Goals

- Mirror real clinical workflows.
- Keep the HospitalDay as the primary interaction point.
- Preserve a single source of truth.
- Support future undo/redo.
- Support reliable synchronization across all views.
- Keep the model independent of persistence and UI.

---

# Implementation Overview

The implemented Phase III relationships, validation conventions, lifecycle decisions, and
deferred questions are documented in [DomainModelOverview.md](DomainModelOverview.md).

## Slice 4 Field Ownership

Patient-owned summary fields are name, species, optional unique MRN, patient acuity, code status,
optional blood type, and one-line summary. Hospital-day-owned charting fields are day acuity,
optional timeline label, treatment changes, physical examination, assessment, clinical summary,
and devices. Editing one owner never copies values into the other; UUID identity selects both
records independently of mutable display fields.
