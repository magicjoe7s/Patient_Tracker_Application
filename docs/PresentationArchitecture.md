# Presentation Architecture

## Structure and dependency direction

The `MainWindow` is one splitter-based desktop shell based on the approved legacy AutoHotkey
workspace composition. The compact left side groups patient/task navigation, actions, filters,
census status, and disposition controls. The right side keeps Patient Summary visible above the
selected-day workspace, with Charting, Problems, Tasks, SOAP, and Sandbox tabs. Structured devices
and lines are edited inside Charting rather than duplicated in a separate tab. This
layout preserves the legacy operator's visual hierarchy without moving state or business rules
out of the controller and service boundaries.

```text
MainWindow and focused widgets
            |
PresentationController + PresentationContext
            |
Application services
            |
Domain + repository protocols
            |
SQLAlchemy unit of work (composition root only)
```

`app/bootstrap.py` is the only desktop composition root. It creates configuration, logging,
database/migrations, event dispatcher, all services, autosave, Qt adapters, controller, and window.
Views never construct or import repositories, sessions, SQLAlchemy records, or the database manager.

## Responsibility map

| Component | Responsibility |
|---|---|
| `MainWindow` | Layout, menus/toolbars/actions, status surfaces, geometry, controlled close |
| `PresentationController` | User-intent translation, selected context, pending editor batch, service errors |
| `PresentationContext` | Sole patient/day/workspace/filter/loading/dirty/save-status state |
| `StableListModel` | Immutable display rows containing stable UUID identity roles |
| `QtEventAdapter` | Detachable application-event subscriptions and targeted Qt signals |
| `QtAutosaveAdapter` | One Qt timer polling the Phase V autosave coordinator |
| `QtReminderAdapter` | Once-per-minute due-count polling for the status bar |
| Panel widgets | Rendering, input collection, accessibility names, and user-intent emission |

## Selected-context sequence

The controller owns the selected patient UUID, selected hospital-day UUID, and a monotonically increasing
generation. Before changing either selection it flushes the shared pending-editor batch. A failed
flush leaves the old context active and dirty. On success, it updates context once and emits one
context signal; the day workspace then refreshes all dependent panels together.

SOAP, Sandbox, and charting editors record the generation they loaded. They refuse a save if it differs from
the current generation. Application events update navigation and affected lists, but a committed
day event does not reload in-progress editors. SOAP events likewise avoid replacing a dirty editor.
This prevents late or nested updates from cross-writing contexts.

## Events and errors

The framework-independent dispatcher emits metadata-only committed events. `QtEventAdapter`
subscribes once, converts event categories to typed Qt signals, and owns idempotent disconnectors.
Patient, day, problem, task, device, SOAP, settings, and persistence signals have targeted refresh
owners.

Widgets do not catch backend exceptions. The controller catches stable application exceptions,
logs technical context, and emits safe title/message pairs. The window uses status text plus a
warning dialog. Death, archive, permanent patient deletion, and full-lineage deletion use explicit
named confirmations. Permanent patient deletion is exposed only for an archived selection.

The census uses patient UUID roles independently of mutable names and MRNs. It provides the
Active/Home/IMC/Archived/Death views, Name/Acuity/Status sorts, manual active ordering, identity
correction, readmission, and lifecycle actions. New patients require a non-empty species; imported
`Unknown` species remains visibly correctable.

The census search is live and retains stable UUID selection while results change. Its disposition
control exposes Active, Home, IMC, Archived, Death, and all-bin scopes; a separate clinical filter
provides All Active, Needs Attention, No Today, Pending DX, Open To-Dos, and Critical/Watcher.
Search and filter rules remain in `SearchService`, not widgets.

The hospital-day timeline uses day UUIDs independently of mutable labels and chronological
position. Entries show ICU ordinal, formatted date, optional note, and a Today marker. Previous and
next navigation wrap at timeline boundaries. Every direct selection, relative navigation, new-day
operation, and patient change flushes pending editors first; a failed flush restores the visible
timeline selection to the unchanged context.

The Patient Summary tab edits only patient-owned name, species, MRN, acuity, code status, blood
type, one-line summary, and the selected day's running problems. Copy MRN writes the canonical MRN
to the clipboard and minimizes the window. The Daily Charting tab is an AM-owned workspace with a
two-column grid for Pertinent Exam Findings, diagnostic tests and editable linked results,
Treatment Changes, and structured Devices, followed by a full-width Assessment editor. Legacy
day-owned `clinical_summary` data remains preserved but is no longer exposed as an additional
Charting editor. Diagnostic tasks and their linked results now provide the user-facing diagnostic
workflow.
Both editors retain the context generation they loaded; stale editors refuse to save, and committed
patient/day events refresh clean affected views without replacing an in-progress editor.

The Charting refresh action first saves those AM-owned fields, then updates only their recognized
SOAP regions. Nested mapping replaces the AM exam and AM assessment blocks while retaining PM
content. Recommendations, Ins/Out narrative, overnight attribution, and unknown Markdown remain
SOAP-owned and are not overwritten by Charting refresh.

## Autosave and shutdown

Text changes register one saver per editor with the controller and mark the Phase V coordinator
dirty. The single Qt timer polls that coordinator. A flush invokes the current charting/SOAP savers
as one selection-stable batch. Dirty state clears only after every saver succeeds. Failures pause
automatic retry, remain visible, and keep callbacks pending. Close is rejected if the batch cannot
be persisted. Geometry, Qt window state, and splitter sizes are then stored as device-local user
preferences through `SettingsService`.

The task panel provides To Do, POCUS, Pending Diagnostic, and Housekeeping category views. Each
category has an independent device-local hide-completed preference. The structured add/edit dialog
exposes category, priority, bucket, and carry-forward controls, while add also accepts the compact
reference grammar. Automatic POCUS routing changes the visible category without encoding metadata
into the stored title. Diagnostic omission records forward-only completed occurrences; full-lineage
deletion remains separately confirmed.

The problem panel presents the selected day's explicit order and provides structured add/edit,
resolve/reopen, forward removal, and local reorder actions. Edit and lifecycle buttons state their
forward scope. Each action uses problem lineage identity, so changing a later day cannot overwrite
an earlier occurrence. The Patient Summary running-problem editor reconciles one title per line
through the same lineage-aware service and confirms forward removals. SOAP refresh projects the
selected day's ordered active problems.

## Theme, shortcuts, and accessibility

`ThemeManager` applies packaged dark or light QSS application-wide. Panels do not carry private
color rules. Immutable definitions in `ActionRegistry` generate every main-window `QAction`, menu
placement, toolbar entry, shortcut, typed-command alias, usage row, and Help entry. Registry
construction rejects duplicate action names, aliases, and shortcuts. `MainWindow.execute_command`
translates parsed intent through existing controller/widget boundaries; the parser owns no clinical
logic. Standard editing shortcuts are deliberately not registered, so focused Qt editors retain
native copy, cut, paste, selection, undo, redo, and word editing.

`CommandPaletteDialog` provides filtered registry-derived usage suggestions. `GeneratedHelpDialog`
renders the registry at display time, eliminating hard-coded help drift. Keyboard actions cover
patient/day navigation, task entry, popup and task-board access, clinical focus targets, pinning,
sidebar visibility, and resize presets. Lists and editors retain accessible names and visible focus.

The SOAP workspace uses one canonical `QPlainTextEdit`, not four competing section editors. A new
day without SOAP text is initialized with the supplied ICU `#INPUT#` template. A
mapping selector requests focused service refreshes for the header, one-liner, problem list, AM
exam, diagnostics, treatment, instrumentation/Ins-Out, AM assessment, or staff attribution. Tab and
Shift+Tab traverse literal `#INPUT#` tokens without deleting them. Saving first persists the exact
Markdown and then applies conservative recognized mappings through `SOAPService`; widgets contain
no parsing rules.

The Sandbox workspace persists the selected day's text exactly. Paste handling only normalizes
line endings, tabs, trailing whitespace, and common flattened Markdown boundaries. Task creation is
a separate preview dialog: only confirmed unchecked checklist rows are created, duplicates are
excluded across Clinical and POCUS tasks, stale previews are rejected, and the source text is never
rewritten. Previous/next controls traverse literal `#INPUT#` tokens.

Copy Chart and Copy SOAP flush pending editors before reading canonical persisted values.
`ClipboardService` owns deterministic formatting and calls a narrow Qt clipboard adapter. A
successful SOAP copy marks only the selected day uploaded; failures do not change the marker. The
workspace displays the state as a checkbox, badge, and timeline suffix. Optional minimization after
SOAP copy is device-local configuration, not clinical or service-layer behavior.

## Reminder presentation and privacy

`QtReminderAdapter` owns the one-minute timer and a small platform-notification boundary. Reminder
calculations remain in the application service. OS notifications contain only a generic maximum-
three reminder summary and overflow count; they never contain patient names, MRNs, day labels, or
task text. Full clinical context is rendered only in the non-modal in-application hourly digest.
The digest supports a five-minute snooze, while the status bar provides an in-app fallback when a
system tray is unavailable.

## Resident desktop shell

The production composition root acquires a device-local process lock before opening SQLite. A
second launch sends an activation message to the existing process and exits without constructing a
second application runtime. The resident process owns one tray icon shared by reminder delivery and
shell controls. Escape and ordinary main-window close requests flush pending editors and hide the
workflow; the tray Exit action uses the existing validated shutdown path.

On Windows, a narrow native adapter registers `Shift+Alt+I` for application visibility,
`Alt+Shift+T` for the always-on-top Task Board, and `Alt+Shift+R` for diagnostic-result capture.
Registration failures are non-fatal so operating-
system shortcut collisions cannot prevent access to clinical data. Tests and maintenance roots do
not enable the desktop adapter.

## Task board presentation

`TaskBoardDialog` contains Pending Diagnostics, To Do, POCUS, and global Housekeeping panes backed
only by immutable service projections. Its structured actions update canonical task lineages, and
the shared event adapter refreshes every open task surface. Double-click navigation uses the shared
presentation context after a successful pending-editor flush. `PendingDiagnosticsDialog` is a
focused selected-day editor over the same canonical task data, not a copied checklist.

## Patient Popup and responsive handoff

`PatientPopup` is a transient Qt tool window over the shared `PresentationController`. Opening it
flushes the main editor, loads canonical selected-day SOAP and Sandbox Markdown, and hides the main
window. Returning, closing, Escape, or patient navigation flushes through the same pending-save
boundary; a failure keeps the popup visible and preserves context. Event refreshes never replace the
popup's unsaved generation.

The popup retains only session-local mode, compact/pin state, and caret selections keyed by stable
patient/day UUIDs. It does not own clinical data. Previous/next uses the admitted census and shared
context. Its compact form is a fixed small strip that can be dragged from its background or labels;
editor and button input remains interactive. The main window schedules a responsive handoff below its compact threshold only while the
handoff is armed, preventing an immediate reopen after the operator explicitly returns to Main.

## Analytics dialog

`AnalyticsDialog` is a resizable, read-only view over one immutable service snapshot. Refresh asks
the controller for a replacement snapshot, Copy exports that same reviewed snapshot, and canonical
domain events refresh the dialog only while it is visible. The dialog contains no calculation,
repository access, clinical mutation controls, or duplicated state beyond its transient snapshot.
Its menu, toolbar, shortcut, command aliases, and Help entry come from `ActionRegistry`.

## Recovery and restore presentation

On startup, `MainWindow` offers a valid recovery snapshot once. It restores the stable patient/day
context, compares canonical editor fingerprints, and requires additional approval for conflicts.
Accepted values are routed through each panel's narrow recovery projection and ordinary dirty/save
boundary; no widget writes directly to persistence and recovery never auto-saves clinical data.

Create Backup and Restore Backup are registry-generated File actions. Restore uses a native file
selector, displays the verified filename, size, and SHA-256 prefix, defaults confirmation to No,
and refreshes all canonical views only after the database has been replaced and reopened.

## Adding a panel

1. Confirm the use case already has an application-service boundary; add a focused service and
   regression tests if it does not.
2. Add an immutable stable-ID presentation row/model only when a list is required.
3. Add a focused widget that calls controller intent methods, never repositories or domain mutation.
4. Give the panel one context-refresh owner and one targeted event-refresh owner.
5. Register pending text through the controller instead of creating another autosave timer.
6. Add isolated UI tests and extend the restart workflow only when the panel persists clinical data.

## Testing

Tests use `QT_QPA_PLATFORM=offscreen` and temporary configuration/database paths.

```powershell
python -m pytest tests/ui -q
python -m pytest -q
python -m ruff check src tests
python -m mypy src/icu_patient_tracker
```

## Deferred external adapters

Direct EMR automation, Master Script message compatibility, Drive integration, and pixel-level
legacy matching remain intentionally unimplemented. Release packaging, controlled legacy import,
and the resident shell do not add presentation ownership or bypass service boundaries.
