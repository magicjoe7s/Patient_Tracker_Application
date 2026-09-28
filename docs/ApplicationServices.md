# Application Services

## Scope

Phase V introduces the UI-independent application layer. Services coordinate domain behavior and
the Phase IV unit of work; they do not import PySide6, SQLAlchemy records, or sessions. No new user
interface or legacy-data import behavior is part of this phase.

## Service Boundary

| Service | Responsibility |
|---|---|
| `PatientService` | Patient creation, identity correction, disposition, archive/purge, and durable active ordering |
| `HospitalDayService` | Day creation, navigation, clinical content, and problem/task/device carry |
| `ProblemService` | Ordered problem occurrences, forward lineage edits/status/removal, and history |
| `TaskService` | Task lifecycle, boards, occurrence lineage, and forward changes |
| `InstrumentationService` | Device placement, editing, discontinuation, and record correction |
| `SOAPService` | Canonical Markdown generation, targeted refresh, and conservative reverse mapping |
| `SandboxService` | Lossless day text plus explicit, idempotent checklist preview and extraction |
| `ClipboardService` | Exact chart/SOAP exports and post-copy day-owned EMR handoff state |
| `ReminderService` | Reminder rules, authoritative due queries, shown-state advancement, snooze, and hourly digests |
| `SearchService` | Canonical cross-day search, derived census filters, bins, and deterministic sorting |
| `SettingsService` | Validated device-local configuration updates and reset |
| `AutosaveCoordinator` | Debounce/retry lifecycle and application-facing failures |
| `BackupService` | Verified backup/restore orchestration and application-facing failures |
| `RecoveryService` | Debounced editor drafts, canonical fingerprints, and recovery lifecycle |

Services receive dependencies in their constructors. Clinical services receive a callable that
creates a `UnitOfWork`; therefore every mutation has an explicit transaction boundary and can be
tested without UI code. Persistence exceptions are translated into stable application exceptions.

`PatientService` keeps UUID identity immutable while allowing atomic MRN/species correction and
atomic replacement of the complete patient-owned summary. The latter supports clearing optional
MRN and blood-type values. MRN remains optional and uniquely constrained when present. Leaving the
active census normalizes manual order; creation and readmission append to that order. Purge is
rejected unless the patient is already archived.

`HospitalDayService` owns day acuity, timeline label, treatment changes, physical examination,
assessment, and clinical summary. Its explicit label replacement supports both setting and
clearing the optional note; these values never update the patient summary.

## Events and Commit Ordering

Events are metadata-only frozen values. They contain stable identifiers and operation names, not
clinical free text. A service publishes its event only after the unit-of-work context exits
successfully. Rollback or commit failure therefore cannot announce a state that was not stored.

`InProcessEventDispatcher` supports synchronous type-based subscriptions. The future presentation
composition root may bridge these events into Qt signals; services themselves remain unaware of
widgets and threads.

## Problem Carry and History

Each new problem starts a stable lineage with occurrence 1. Appending a latest hospital day creates
independent occurrences for unresolved, non-inactive problems in their displayed order; resolved
and inactive problems do not carry. Backdated days do not branch problem lineage.

Problem edits, resolution/reopening, and removal from a selected occurrence apply only to that
occurrence and later lineage members. Earlier hospital days remain immutable. Reordering is local
to the selected day, and SOAP assessment projection uses only that day's ordered active problems.

## Task Carry and History

Patient creation atomically creates today's ICU day 1. Hospital days are ordered by calendar date;
backdated insertion renumbers ICU ordinals while stable UUIDs remain unchanged. Appended days may
carry incomplete, carry-enabled task occurrences and active devices from the latest prior day. A
backdated insertion does not carry these objects because doing so could branch task lineage.

A carried task receives a new ID and retains the lineage ID, source task ID, and incremented
occurrence number. Existing target lineages are not duplicated. Edits, completion, and reopening
can be applied from a selected occurrence forward without rewriting earlier history.
Whole-lineage deletion is explicit and atomic.

Task metadata is stored in structured columns. The presentation boundary accepts the legacy compact
grammar (`!`, `!!`, `p:`, `b:`, `r:`, and `nocarry`) and routes To Do text containing POCUS or
point-of-care ultrasound language into the POCUS category. To Do, POCUS, Pending Diagnostic, and
Housekeeping remain distinct categories. `TaskService.board` derives immutable display rows from
the newest occurrence of every lineage across all hospital days. To Do and POCUS include admitted
patients, Pending Diagnostics additionally includes discharged and transferred patients, and
Housekeeping is cross-patient. `current_board` remains a compatibility projection over those rows.

Edits, completion, reopening, and category changes from a selected occurrence affect only that
occurrence and later members of its lineage. Omitting a carried pending diagnostic uses completed
occurrences as tombstones instead of deleting history. Confirmed lineage deletion remains the only
operation that removes every occurrence.

## Task Board and Focused Diagnostics

The consolidated board owns no clinical state. Each row contains display context and a canonical
`Task` snapshot, while every mutation delegates to the existing forward-lineage service methods.
Completing the newest occurrence hides the lineage instead of exposing an earlier open occurrence.
Task events refresh the selected-day task panel, all four board panes, and the focused diagnostics
editor. Row activation flushes pending editors before changing shared patient/day context.

## SOAP Synchronization

SOAP documents retain the complete canonical Markdown alongside four compatibility mappings.
`CanonicalSOAPMapper` is a pure parser/renderer: it generates the supplied ICU `#INPUT#` template
with the selected and following calendar dates, preserves its section
order, refreshes only explicitly selected regions, retains diagnostic results, derives device
Ins/Out rows, and extracts only recognized fields. Unknown headings and unrelated text remain
unchanged. Exact-count problem/diagnostic mappings update their selected and later lineage
occurrences; ambiguous cardinality leaves structured collections untouched. Overnight resident and
faculty are day-owned and carry on appended days. The daytime resident comes from device-local
settings. Pre-Slice-8 documents are initialized once on first open.

## Sandbox Extraction

`SandboxService` saves day-owned Markdown without interpreting or rewriting it. Preview scans only
unchecked checklist rows, applies the shared compact task grammar, routes POCUS work, and excludes
duplicates already present in Clinical or POCUS tasks. Extraction requires selected source line
numbers and the exact previewed text, rejects stale previews, persists tasks and optional reminders
atomically, and leaves the Sandbox unchanged.

## Clipboard and EMR Handoff

`ClipboardService` depends on a minimal plain-text writer port rather than PySide6. MRN copy writes
the selected patient's canonical MRN and rejects an absent MRN; the presentation layer performs
the requested post-copy minimization. Chart export
retains the reference patient/date header and section order and normalizes output to CRLF for
external-editor compatibility. SOAP export preserves the entire canonical document. Empty SOAP or
clipboard failure is reported without changing clinical state; only a successful SOAP copy marks
its owning day uploaded. The Qt adapter is supplied by the composition root, and no keystrokes,
window discovery, or direct EMR automation occurs.

## Reminder Scheduling

Reminder specifications persist their rule:

- Absolute: one timezone-aware trigger.
- Interval: positive minutes and a timezone-aware anchor.
- Fixed time: one local wall-clock time; the next occurrence is calculated from the injected clock.

Only the newest task occurrence in each lineage is authoritative. Due queries include actionable
To Do and POCUS reminders, exclude completed/cancelled tasks and inactive patients, and sort by
trigger then ID. Successful presentation records `last_shown_at`; interval rules advance from the
actual display time, fixed-time rules advance to the next wall-clock occurrence, and absolute rules
are dismissed. Reminder snooze state is persistent. The hourly in-app digest summarizes due
reminders, pending diagnostics, long-term follow-up, urgent work, and aggregate open counts. The
wall clock is injected so every calculation is deterministic without Qt timers.

## Search, Filters, and Bins

`SearchService` performs case-insensitive canonical-content matching across patient identity and
summary fields plus every hospital day's charting, problems, tasks, devices, SOAP Markdown, and
Sandbox Markdown. Patient names additionally support the characterized token and subsequence fuzzy
matching. Empty queries retain all records in the selected disposition bin.

The six derived views are All Active, Needs Attention, No Today, Pending DX, Open To-Dos, and
Critical/Watcher. They use the latest hospital-day acuity and newest authoritative task occurrence
per lineage. No Today applies only to admitted patients. Home, IMC, Archived, and Death remain
explicit disposition bins. Manual, name, acuity, and status sorts use UUID as the final tie-break,
so duplicate names remain deterministic.

## Settings Ownership

Current settings are device-local and stored by `ConfigManager`. Theme, logging, database/backup
paths, retention, autosave timing, user preferences, and reserved future settings are not clinical
records and do not enter patient aggregates.

## Operational Analytics

`AnalyticsService` is a read-only application service. It loads canonical patient aggregates and
returns an immutable `AnalyticsSnapshot`; it never persists calculated totals. Current acuity and
problem terms come from the newest hospital day, while pending diagnostics are selected from the
newest occurrence of each task lineage. A clock and narrow clipboard writer are injected so report
generation and export remain deterministic and independent of PySide6.

The fixed-format report preserves the characterized census, acuity, average-day, pending,
missing-today, top-term, and Needs Attention sections. Copying exports the supplied snapshot rather
than silently recalculating it, so the text matches what the operator reviewed.

## Recovery and Reviewed Restore

`RecoveryService` stages text-only editor values for one stable patient/day context and delegates
atomic JSON replacement to `RecoveryStore`. It fingerprints the canonical editor values that were
loaded, using sorted JSON and SHA-256 rather than file timestamps. Startup recovery compares those
fingerprints against current canonical projections. Conflicted drafts require explicit additional
approval and are still loaded only into unsaved editors.

`BackupService.inspect` returns a verified immutable descriptor containing path, size, and SHA-256.
The restore use case accepts that reviewed descriptor, rejects content changed after review,
creates a pre-restore safety snapshot, releases pooled connections, atomically replaces the local
SQLite database, and reinitializes the same database lifecycle. Failure after connection release
also reinitializes the preserved active database.
