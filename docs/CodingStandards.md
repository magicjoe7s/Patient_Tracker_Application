
# CodingStandards.md

# ICU Patient Tracker Coding Standards

## Purpose

This document defines the coding philosophy and implementation standards for the ICU Patient Tracker. Its goal is to keep the codebase maintainable, predictable, and aligned with the project's clinical workflow.

---

# Core Philosophy

The primary objective is not to write clever code.

The objective is to write code that remains understandable and trustworthy years after it is written.

Core principles:

- Code is read more often than it is written.
- Explicit is better than clever.
- Clinical correctness outweighs optimization.
- Reliability outweighs elegance.
- Simplicity is preferred whenever possible.

---

# Development Priorities

When making implementation decisions, optimize in this order:

1. Clinical correctness
2. Workflow efficiency
3. Reliability
4. Maintainability
5. Performance
6. Code elegance

---

# Python Standards

- Target the current supported Python 3 release for the project.
- Use type hints throughout the codebase.
- Prefer `pathlib` over string paths.
- Use `datetime` objects instead of custom date handling.
- Use `Enum` for constrained values.
- Avoid global variables.
- Favor composition over inheritance.

---

# Project Structure

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
```

All production modules live inside the `icu_patient_tracker` package namespace.
Tests live at the repository root and mirror production boundaries when practical.

Each module should have a single, well-defined responsibility.

---

# Naming Conventions

Classes

- Patient
- HospitalDay
- SOAPDocument
- PatientService
- TaskRepository

Functions

- Verb-first names
- Examples:
    - create_patient()
    - update_weight()
    - generate_summary()

Variables

- Descriptive names
- Avoid abbreviations unless universally understood

Constants

- UPPER_CASE

Private members

- Leading underscore

---

# Classes

Classes should:

- Have one responsibility.
- Be small and cohesive.
- Be easy to understand independently.

Large "god objects" should be avoided.

---

# Functions

Functions should:

- Do one thing.
- Have a single clear purpose.
- Be short whenever practical.
- Avoid hidden side effects.

If a function requires extensive comments to explain its logic, consider simplifying or splitting it.

---

# Type Hints

Type hints are required for:

- Public functions
- Services
- Repositories
- Domain models
- Public methods

---

# Documentation

Docstrings should explain intent rather than restating the implementation.

Comments should explain *why*, not *what*.

Remove obsolete comments promptly.

---

# Error Handling

Never use:

```python
except:
```

Always catch explicit exceptions.

User-facing errors should:

- Explain what happened.
- Explain what was protected.
- Suggest the next action.

---

# Logging

Unexpected failures should be logged.

Silent failures are prohibited.

Logging should provide enough context to diagnose issues without exposing unnecessary implementation details.

---

# User Interface Rules

Widgets are responsible only for presentation.

Widgets must not:

- Modify domain models directly.
- Execute SQL.
- Perform business logic.
- Access repositories directly.

Widgets receive user input and delegate work to services.

---

# Services

Services own business logic.

Services are responsible for:

- Validation
- State changes
- Coordinating repositories
- Emitting events
- Updating ApplicationState

All mutations pass through services.

---

# Domain Models

Domain models represent clinical concepts.

Models:

- Do not know about widgets.
- Do not know about SQLite.
- Do not know about services.

Models may contain validation and domain-specific behavior.

---

# Repositories

Repositories are the only components that communicate with SQLite.

Responsibilities:

- Load
- Save
- Query
- Delete

Repositories do not contain business logic.

---

# Event-Driven Communication

Components communicate through ApplicationState and events.

Avoid direct communication between windows.

Adding a new view should not require modifying existing views.

---

# Complexity Budget

Every class begins with a complexity budget of zero.

When a class gains unrelated responsibilities, split it into smaller classes.

Prefer many focused classes over a few very large classes.

---

# Testing Philosophy

Test business logic rather than presentation.

Priority:

1. Services
2. Domain models
3. Repositories
4. UI behavior

Automated tests should focus on clinical workflows and data integrity.

---

# Refactoring Rule

Leave the code cleaner than you found it.

Small improvements made consistently prevent long-term code degradation.

---

# Clinical Workflow Rule

Never sacrifice workflow efficiency for architectural purity.

If an implementation improves developer convenience but slows clinicians, it should be reconsidered.

---

# Explicit Over Clever

Prefer readable, purpose-specific code over generic abstractions.

Good:

```python
patient_service.update_weight(patient_id, weight)
```

Avoid unnecessary generic interfaces such as:

```python
entity_service.update(entity_type, entity_id, field_name, value)
```

Clarity is preferred over brevity.

---

# Definition of Success

A successful codebase is:

- Predictable
- Readable
- Easy to modify
- Easy to test
- Resistant to bugs
- Aligned with clinical workflow
- Understandable by a new contributor with minimal onboarding
