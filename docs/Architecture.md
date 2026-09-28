
# Architecture.md

# ICU Patient Tracker Architecture

## Purpose

This document defines the target software architecture for the Python implementation of the ICU Patient Tracker.

It describes how the application is organized, how components interact, and the architectural rules that govern future development. It intentionally describes the **ideal architecture**, not the legacy AutoHotkey implementation.

The architecture exists to support the Project Constitution. Whenever implementation choices conflict, the Constitution takes precedence.

---

# Architectural Goals

1. Preserve the clinician's workflow while modernizing the implementation.
2. Maintain a single, authoritative application state.
3. Keep business logic independent of the user interface.
4. Allow every window to function as another view of the same underlying data.
5. Maximize reliability, recoverability, and data integrity.
6. Minimize coupling between components.
7. Make future features easy to add without widespread refactoring.
8. Keep the architecture understandable by a new contributor within a short amount of time.

---

# Overall Architecture

```
Presentation Layer
│
├── Main Window
├── Patient Popup
├── Task Board
├── Patient Search
├── Analytics
├── Settings
└── Dialogs

        │
        ▼

Application Layer
│
├── ApplicationState
├── PatientService
├── HospitalDayService
├── TaskService
├── SOAPService
├── ReminderService
├── ClipboardService
├── SearchService
├── ImportExportService
├── SettingsService
└── UndoService

        │
        ▼

Domain Layer
│
├── Patient
├── HospitalDay
├── Task
├── Reminder
├── SOAPDocument
├── ProblemList
├── ClinicalSummary
├── Instrumentation
└── Settings

        │
        ▼

Persistence Layer
│
├── SQLite
├── Repository classes
├── Autosave
├── Backup
└── Import / Export
```

Application dependencies always flow downward.

---

# Physical Project Structure

```text
src/
└── icu_patient_tracker/
    ├── __init__.py
    ├── main.py
    ├── app/
    ├── ui/
    ├── widgets/
    ├── dialogs/
    ├── services/
    ├── domain/
    ├── persistence/
    ├── repositories/
    ├── resources/
    └── utils/

tests/
packaging/
scripts/
```

The package namespace prevents collisions with generic third-party package names while the
subpackages preserve the architectural boundaries described below. Tests remain outside the
production package. `packaging/` contains release-tool configuration, while `scripts/` contains
operator-invoked maintenance workflows; neither owns application state.

---

# Architectural Philosophy

The application is a real-time representation of the ICU, not a collection of forms.

Every window represents another view of the same application state.

No window owns data.

No window synchronizes with another window.

The application state is the single source of truth.

---

# Application State

The application owns exactly one ApplicationState object.

Responsibilities include:

- Current patient
- Current hospital day
- Current task
- Search state
- Filters
- Theme
- Window layout
- Dirty state
- Autosave status
- Clipboard status
- Selection state

Presentation components observe this state.

Application services modify this state.

Persistence serializes this state.

---

# Presentation Layer

Responsibilities:

- Display data
- Receive user input
- Emit user actions
- Observe application state

Presentation components never:

- Execute business logic
- Access SQLite directly
- Modify domain models directly

The implemented Phase VI presentation boundary, context ownership, event bridge, and panel extension
rules are documented in [PresentationArchitecture.md](PresentationArchitecture.md).

The read-only AutoHotkey reference audit and the approved method for translating behavior into this
architecture are documented in [ReferenceApplicationAnalysis.md](ReferenceApplicationAnalysis.md)
and [FeatureImplementationRoadmap.md](FeatureImplementationRoadmap.md).

---

# Application Services

All mutations occur through services.

Core services:

- PatientService
- HospitalDayService
- TaskService
- SOAPService
- ReminderService
- ClipboardService
- SearchService
- ImportExportService
- SettingsService
- UndoService

Services coordinate business logic, persistence, and state updates.

The implemented Phase V boundary is documented in
[ApplicationServices.md](ApplicationServices.md). Clinical services depend on repository/unit-of-work
protocols and publish metadata-only application events after successful commits. Autosave and backup
coordinators wrap the Phase IV infrastructure without introducing presentation dependencies.

---

# Domain Layer

Domain models represent clinical concepts rather than interface concepts.

Examples:

- Patient
- HospitalDay
- Task
- Reminder
- SOAPDocument
- ProblemList
- ClinicalSummary
- Instrumentation

Domain models contain validation and business rules but have no knowledge of widgets or persistence.

The Phase III implementation uses typed Python dataclasses as pure domain objects. Future
SQLAlchemy declarative models and mapping code belong in the persistence layer rather than in the
domain classes.

---

# Persistence Layer

SQLite is the permanent storage engine.

Repositories isolate database access from business logic.

Persistence responsibilities include:

- Saving
- Loading
- Autosave
- Backups
- Import/export
- Schema migration
- Recovery

The persistence implementation uses separate SQLAlchemy records and explicit domain mapping.
`PatientRepository` persists the complete patient aggregate, and `SqlAlchemyUnitOfWork` owns the
private session and transaction boundary. Formal Alembic revisions are the only supported schema
change mechanism. Operational details are documented in [Persistence.md](Persistence.md).

Derived values should be calculated rather than stored whenever practical.

---

# Event-Driven Architecture

Windows never communicate directly.

Instead:

1. User performs an action.
2. Service executes the change.
3. ApplicationState is updated.
4. An event/signal is emitted.
5. Interested views refresh themselves.

Example:

```
Edit Treatment
      ↓
SOAPService.update()
      ↓
TreatmentChanged Event
      ↓
Main Window refreshes
Patient Popup refreshes
Task Board refreshes
Search refreshes
```

This keeps windows independent while maintaining synchronization.

---

# Data Ownership

Every piece of data has exactly one owner.

Examples:

- Patient name → Patient
- Tasks → HospitalDay
- SOAP → SOAPDocument
- Theme → Settings
- Current selection → ApplicationState

Duplicate ownership is prohibited.

---

# Architectural Rules

1. UI never modifies models directly.
2. Every mutation passes through exactly one service.
3. UI never accesses SQLite.
4. Models never know about widgets.
5. Services never know about widgets.
6. Every window is another view of the same application state.
7. One source of truth exists for every piece of data.
8. Business logic never belongs inside widgets.
9. ApplicationState is the communication hub.
10. Persistence must remain replaceable.
11. Store canonical data; derive computed values when needed.
12. Design mutations so undo/redo can be added without major refactoring.

---

# Long-Running Operations

Operations such as autosave, searching, backup creation, imports, exports, and large database operations should execute asynchronously without blocking the UI.

Progress should be communicated through ApplicationState rather than direct widget manipulation.

---

# Future Scope

The architecture intentionally targets a single-user desktop application.

It is not optimized for:

- Multi-user collaboration
- Cloud-first workflows
- Web deployment
- Plugin ecosystems
- Enterprise-scale deployment

These goals should not influence architectural decisions unless the project scope changes.

---

# Success Criteria

A successful architecture:

- Preserves the established ICU workflow.
- Allows new windows to be added without modifying existing ones.
- Keeps business logic independent of the UI.
- Prevents duplicate data ownership.
- Supports reliable autosave and recovery.
- Enables future undo/redo.
- Remains understandable and maintainable over many years.
