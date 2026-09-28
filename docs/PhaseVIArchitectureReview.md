# Phase VI Architecture Stability Review

## Scope and result

The Phase II-V code and tests were reviewed before clinical presentation work began. Domain modules
do not import PySide6 or SQLAlchemy. Services do not import Qt. Repository protocols expose complete
patient aggregates, while concrete SQLAlchemy sessions remain private to the persistence unit of
work. Service mutation events are published after unit-of-work context exit, autosave retains dirty
state after failure, reminder time is injectable, search ordering is deterministic, and task/SOAP
behavior is independently testable.

No UI module needs direct repository, SQLAlchemy record, or session access. The required dependency
direction can therefore remain presentation -> services -> domain/repository protocols ->
persistence.

## Findings

| Classification | Finding | Resolution |
|---|---|---|
| Blocking | Problems had domain and persistence support but no mutation service. | Add a focused `ProblemService`, application events, domain edit method, and regression tests. |
| Blocking | Instrumentation had domain and persistence support but no mutation service. | Add a focused `InstrumentationService`, application events, domain edit method, and regression tests. |
| Blocking | Bootstrap constructed only database/theme and an empty window. | Extend the existing bootstrap into the sole composition root for dispatcher, services, adapters, coordinator, and window. |
| Important, non-blocking | The event dispatcher could subscribe but not disconnect. | Return an idempotent disconnect callback so the Qt adapter has deterministic lifetime ownership. |
| Important, non-blocking | SOAP document discovery is aggregate-oriented rather than a dedicated read DTO. | Presentation coordinator reads documents returned by `HospitalDayService`; all mutations remain in `SOAPService`. |
| Deferred improvement | Read services currently return detached domain aggregates rather than immutable presentation DTOs for every panel. | Qt models copy stable identifiers and display values. Broader read-model work is deferred until measured scale or Phase VII needs justify it. |
| Deferred improvement | Ordinary local service calls are synchronous. | Retain the simple synchronous path for the expected personal ICU dataset; backup/restore UI remains deferred. |

## Lower-layer modifications authorized by the review

Only the two missing mutation services, their minimal domain edit methods, two event types, and event
unsubscription are changes below the presentation layer. They close concrete UI-boundary defects;
they do not redesign persistence or introduce new clinical rules.
