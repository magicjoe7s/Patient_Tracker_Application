# ICU Patient Tracker Project Constitution

## Purpose

This document defines the immutable principles that guide development of
the ICU Patient Tracker.

The Functional Specification describes **what** the application does.

The Architecture describes **how** it is implemented.

This document describes **how engineering decisions should be made
whenever multiple valid solutions exist.**

If any future implementation conflicts with these principles, these
principles take precedence unless intentionally revised.

------------------------------------------------------------------------

# Core Mission

The ICU Patient Tracker exists to facilitate clinical documentation
outside of the electronic medical record (EMR) in a busy veterinary ICU.

Its purpose is to allow clinicians to maintain **accurate, organized,
and comprehensive patient records despite limitations of the hospital
EMR.**

The application is not intended to replace the EMR. Instead, it serves
as the clinician's primary workspace throughout the day and minimizes
friction when transferring information into the official medical record.

------------------------------------------------------------------------

# Project Priorities

Whenever tradeoffs exist, priorities are resolved in this order:

1.  Clinical workflow speed
2.  Reliability and data integrity
3.  Flexibility and adaptability
4.  Performance
5.  Ease of maintenance
6.  User interface aesthetics
7.  Feature richness

Lower priorities should never compromise higher priorities.

------------------------------------------------------------------------

# Clinical Workflow First

The workflow is the product.

The software exists to support clinicians---not the other way around.

If a technically elegant solution slows clinicians during a busy ICU
shift, it is the wrong solution.

Engineering should adapt to workflow rather than forcing clinicians to
adapt to engineering.

------------------------------------------------------------------------

# Preserve Workflow

The AutoHotkey implementation represents years of iterative refinement.

The goal of the rewrite is **not** to redesign the workflow.

Instead:

-   Preserve the workflow.
-   Preserve muscle memory where practical.
-   Reduce unnecessary clicks.
-   Modernize the interface.
-   Improve maintainability.
-   Improve reliability.

The Python application should feel immediately familiar to existing
users while providing a cleaner, more polished experience.

------------------------------------------------------------------------

# Feature Philosophy

New functionality should only be added when it produces a meaningful
improvement to the clinical workflow.

Every proposed feature should answer:

> **How does this make caring for patients easier?**

If that question cannot be answered clearly, the feature should not be
implemented.

------------------------------------------------------------------------

# Data Entry Philosophy

**Clinicians should never be required to enter the same information
twice.**

Every piece of clinical information should have **one canonical
location** where it is entered.

The software is responsible for propagating that information everywhere
else it is needed.

Synchronization should be automatic whenever possible while remaining
transparent and understandable.

Duplicate data entry increases workload, introduces inconsistency, and
should be treated as a design failure.

------------------------------------------------------------------------

# Loeb's Laws of Software

1.  Never risk patient data for convenience.
2.  The fastest correct workflow is usually the best workflow.
3.  Reduce clinician cognitive load whenever possible.
4.  Maintain a single source of truth for every piece of data.
5.  Every click must justify its existence.
6.  Software should behave predictably.
7.  Optimize for the common workflow rather than uncommon edge cases.
8.  Automation should assist clinicians, never obscure what happened.
9.  The application must function completely offline.
10. The application should be trusted enough to use during the busiest
    ICU shift of the year.

------------------------------------------------------------------------

# Reliability Principles

-   Data loss is unacceptable.
-   Whenever uncertainty exists, preserve data rather than risk
    deletion.
-   Saving should be automatic whenever practical.
-   Recovery should always be possible.
-   Failures should fail safely.

------------------------------------------------------------------------

# User Interface Principles

-   Maximize information density without increasing cognitive burden.
-   The interface should feel calm, predictable, and professional.
-   Visual polish should never compromise efficiency.
-   Whitespace should improve readability rather than imitate consumer
    software.

------------------------------------------------------------------------

# Keyboard First

Every common workflow should be executable from the keyboard.

Mouse interactions should remain intuitive but should never be the only
way to perform frequent tasks.

------------------------------------------------------------------------

# Automation Philosophy

Automation should eliminate repetitive work.

Automation should never remove clinician awareness.

Automatic actions should always be understandable and reversible
whenever practical.

------------------------------------------------------------------------

# Simplicity

Choose the simplest implementation that satisfies the workflow.

Avoid unnecessary abstraction, frameworks, and complexity.

Simple code is easier to understand, debug, and trust.

------------------------------------------------------------------------

# Extensibility

Design the application so new clinical tools can be added without
restructuring the existing system.

Future modules should integrate naturally into the architecture rather
than requiring widespread modification.

------------------------------------------------------------------------

# Decision Hierarchy

When multiple implementations satisfy the requirements, choose the
option that best satisfies this order:

1.  Clinical workflow
2.  Reliability
3.  Maintainability
4.  Performance
5.  Elegance

------------------------------------------------------------------------

# Things We Will Not Optimize For

-   Mobile devices
-   Touch-first interfaces
-   Web browsers
-   Cloud-first workflows
-   Multiple simultaneous users
-   Enterprise deployment
-   Visual novelty

------------------------------------------------------------------------

# Definition of Success

A successful release is one in which an experienced ICU clinician can
perform an entire shift faster, with fewer missed tasks, fewer
documentation errors, and greater confidence than when using the
AutoHotkey version.
