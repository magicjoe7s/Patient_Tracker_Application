# Feature-by-Feature Implementation Roadmap

## Working Agreement

The AutoHotkey application is a behavioral reference, not a code template. We will implement one
bounded feature slice at a time. No slice starts until its rules and acceptance examples are
approved. No following slice starts until the current slice passes its automated and manual gates.

Every feature uses the same cycle:

1. Extract its reference rules and edge cases.
2. Decide which behavior to preserve, intentionally change, or omit.
3. Write acceptance criteria and synthetic examples.
4. Add or amend domain rules only when required.
5. Add service behavior and persistence migrations through existing boundaries.
6. Add the smallest useful PySide6 surface.
7. Add unit, service, persistence, and GUI tests appropriate to the change.
8. Run all project gates and perform the feature's manual test.
9. Update traceability documentation and create one focused Git commit.

Common completion commands:

```powershell
python -m ruff format --check src tests
python -m ruff check src tests
python -m mypy src
python -m pytest
.\scripts\build_release.ps1
```

## Stage 0: Approve the Migration Contract

This is a decision stage, not feature code.

Approve:

- internal UUID plus optional unique MRN;
- explicit legacy status and code-status mapping;
- day-owned problem history with carry-forward presentation;
- lossless SOAP Markdown plus conservative structured mappings;
- explicit `unknown` species for legacy import;
- one-time read-only import rather than ongoing text-file synchronization;
- deidentified characterization fixtures only.

**Exit gate:** amend the authoritative model documents and record approved decisions before schema
or service changes.

## Slice 1: Identity and Legacy Parser Foundation (implemented)

**Goal:** represent patients without inventing MRNs and prove that version-13 text can be parsed
without writing to the database.

Preserve:

- stable legacy internal identity;
- optional six-digit MRN semantics;
- non-unique patient names;
- strict percent decoding and record versions.

Implement:

- canonical patient UUID and optional unique MRN;
- Alembic migration and repository/service identity changes;
- read-only version-13 parser returning typed import records;
- dry-run counts and non-sensitive validation diagnostics;
- synthetic fixtures for main, archive, missing MRN, encoded delimiters, and malformed rows.

Exclude:

- production import commit;
- any mutation of supplied text files;
- UI beyond a developer-facing dry-run command if needed.

**Acceptance:** all existing records can be structurally accounted for; missing MRNs remain missing;
rerunning a dry run changes nothing.

## Slice 2: Patient Census and Disposition Lifecycle (implemented)

**Goal:** reproduce the safe census workflow through the current architecture.

Preserve:

- create, rename, status, readmit, archive, archive-only purge, and death confirmation rules;
- active order and Name/Acuity/Status sorting;
- Home/IMC/Archived/Death bins.

Intentionally change:

- use explicit dialogs and services instead of encoded button/shift-click behavior where clearer;
- require species for new patients while allowing imported `unknown` values to be reviewed.

**Acceptance:** status transitions and ordering survive restart; irreversible operations confirm;
duplicate names work; optional MRNs remain uniquely constrained when present.

## Slice 3: Hospital-Day Creation, Timeline, and Carry Forward (implemented)

**Goal:** establish the daily context used by every later clinical feature.

Preserve:

- creation of today's first day for a new active patient;
- `YYYY-MM-DD | note` input behavior;
- duplicate-date rejection;
- chronological ordering, ICU ordinal, Today marker, and previous/next navigation;
- commit-before-selection-change;
- explicit carry-forward rules.

Initially carry only the canonical task and device objects already supported by the application
layer. Later slices add problem and staff carry-forward behavior as those workflows are completed.

**Acceptance:** outgoing unsaved edits cannot cross-write into the selected destination; day order and
labels survive restart.

## Slice 4: Patient Summary and Daily Charting (implemented)

**Goal:** complete the primary structured workspace before SOAP automation.

Preserve:

- patient name, species, MRN, acuity, code status, blood type, one-liner;
- day acuity plus AM treatment changes, pertinent examination, Diagnostic Summary, structured
  devices, and assessment; the persistence field historically named `clinical_summary` backs the
  user-facing Diagnostic Summary;
- clear patient-level versus day-level ownership.

**Acceptance:** each field persists under its canonical owner, refreshes all open views through
events, and remains unchanged when navigating unrelated patients/days.

## Slice 5: Running Problem Workflow (implemented)

**Goal:** preserve a usable running problem list while retaining daily history.

Preserve:

- ordered problem presentation;
- add, edit, reorder, resolve/reopen, and remove behavior;
- SOAP problem-list projection.

Intentionally change:

- replace the reference's patient-level free-text list with structured day-owned problems;
- carry unresolved problems forward with lineage rather than overwrite history.

**Acceptance:** historical days remain unchanged after later edits, carried problems retain lineage,
and the latest day presents the current running list.

## Slice 6: Task Categories, Entry Grammar, and Lineage (implemented)

**Goal:** complete To Do, POCUS, Pending Diagnostic, and Housekeeping semantics.

Preserve:

- `!`/`!!`, `p:`, `b:`, `r:`, and `nocarry` parsing;
- automatic POCUS routing;
- stable lineage and forward-only edit/complete/reopen behavior;
- confirmed full-lineage deletion;
- independent hide-completed preferences;
- omitted carried-diagnostic tombstones.

Intentionally change:

- store metadata as structured columns rather than encoded text suffixes;
- use a dedicated UI editor in addition to accepting the compact grammar.

**Acceptance:** reference examples produce the same structured result; earlier occurrences never
change during forward mutations; restart retains lineage.

## Slice 7: Reminder Notifications and Digest

**Status:** Implemented.

**Goal:** expose the already structured reminder rules as reliable desktop behavior.

Preserve:

- interval and fixed-time reminders for To Do and POCUS;
- newest-authoritative-occurrence rule;
- one-minute due polling, up-to-three alert summary, hourly digest, and five-minute snooze.

Intentionally change:

- use Qt/platform notification adapters behind a service boundary;
- keep scheduling calculations testable without timers or GUI objects.

**Acceptance:** deterministic clock-based tests cover due, future, shown, snoozed, completed, and
restart cases; notifications contain no more identifying information than the approved policy.

## Slice 8: Canonical SOAP Template and Round-Trip Mapping

**Status:** Implemented.

**Goal:** preserve the clinical SOAP workflow without destructive text rewriting.

Preserve:

- template sections and staff attribution fields;
- targeted structured-to-SOAP refresh;
- conservative reverse synchronization;
- unrelated-section preservation;
- diagnostic-result retention;
- device-derived Ins/Out rows;
- literal `#INPUT#` traversal.

Intentionally change:

- remove hard-coded clinician names and source them from settings;
- implement parsing and rendering as focused, tested services rather than widget handlers.

**Acceptance:** golden synthetic documents round-trip without losing unrecognized text; targeted
refresh changes only its mapped section; every legacy SOAP rule has a characterization test.

## Slice 9: Sandbox and Checklist Extraction

**Status:** Implemented.

**Goal:** add the day-owned working area without making it a second source of truth.

Preserve:

- per-day free text;
- Markdown-friendly paste behavior;
- extraction of unchecked checklist rows into To Do/POCUS work;
- `#INPUT#` traversal where applicable.

Intentionally change:

- task extraction is an explicit preview-and-confirm action rather than an invisible side effect of
  every save.

**Acceptance:** extraction is idempotent, existing tasks are not duplicated, and Sandbox text remains
unchanged unless the user explicitly edits it.

## Slice 10: Clipboard and EMR Handoff

**Status:** Implemented.

**Goal:** support safe transfer to the external medical record without embedding EMR automation.

Preserve:

- Copy Chart formatting;
- Copy SOAP formatting;
- day-level uploaded flag after confirmed copy;
- visible upload state.

Intentionally change:

- isolate clipboard access in `ClipboardService`;
- make minimize-after-copy a preference rather than hidden business logic.

**Acceptance:** exact synthetic golden outputs pass; empty-content and clipboard errors are handled;
copying one day never changes another day's upload state.

## Slice 11: Search, Filters, and Bins

**Status:** Implemented.

**Goal:** reproduce fast patient discovery across canonical content.

Preserve:

- live search across approved patient/day/task/problem/SOAP/Sandbox fields;
- All Active, Needs Attention, No Today, Pending DX, Open To-Dos, and Critical/Watcher filters;
- Home, IMC, Archived, and Death bins;
- manual/name/acuity/status sort behavior.

**Acceptance:** deterministic ranking/filter fixtures cover duplicate names, empty searches, archived
records, and cross-day content; performance remains interactive at and above the supplied data size.

## Slice 12: Pending Diagnostics and Consolidated Task Board

**Status:** Implemented.

**Goal:** add derived working surfaces without introducing duplicate state.

Preserve:

- focused pending-diagnostic summary editing;
- newest authoritative task occurrence per lineage;
- Pending, To Do, POCUS, and global Housekeeping panes;
- eligible-patient status rules;
- row activation back to patient/day context.

**Acceptance:** board values are derived from repositories/services, mutations update all views by
events, and no board-owned clinical data exists.

Implementation notes:

- To Do and POCUS rows are limited to admitted patients; Pending Diagnostics also includes
  discharged (Home) and transferred (IMC) patients; Housekeeping is a global cross-patient view.
- Only the newest occurrence in each task lineage is shown, including when that occurrence is
  completed, so an older open occurrence can never reappear as current work.
- Structured add/edit/complete/reopen/delete operations mutate canonical tasks and publish the
  existing metadata-only task events. The focused diagnostics editor uses the selected patient/day.
- Double-clicking a board row atomically flushes pending editors and selects its owning patient/day.
- No migration was required because the board introduces no persistence or duplicate clinical state.

## Slice 13: Patient Popup and Responsive Workspace

**Status:** Implemented.

**Goal:** support side-by-side work with an external EMR.

Preserve:

- same patient/day context as the main window;
- SOAP/Sandbox modes, previous/next active patient, compact/full mode, caret restoration, and return
  to main;
- optional always-on-top behavior.

Intentionally change:

- use shared presentation context and services rather than mirroring widget contents.

**Acceptance:** edits in either surface are immediately visible in the other; closing or switching
context safely flushes pending edits; no popup owns clinical state.

Implementation notes:

- Main-window and popup editors hand off through the controller's pending-save boundary, then reload
  canonical SOAP/Sandbox values; the main window is hidden while the popup is active.
- Previous/next wraps through the admitted census and selects the destination's latest hospital day.
- SOAP and Sandbox selections are remembered in memory per patient/day/mode and clamped safely when
  text changes. They are intentionally not durable settings.
- Compact mode collapses the popup to its patient header; full mode restores the active editor.
  Always-on-top is user-toggleable and defaults on.
- `Ctrl+P`, `Ctrl+Shift+S`, `Ctrl+Shift+O`, `Alt+M`, Escape, and explicit Main controls cover the
  characterized popup workflow. A small visible main workspace hands off automatically when a day
  is selected, and returning disarms repeated handoff until the window is enlarged again.
- Failed saves leave the popup and context open. No migration was required because the popup owns
  only transient presentation state.

## Slice 14: Command Palette, Shortcuts, and Generated Help

**Status:** Implemented.

**Goal:** restore fast keyboard operation without repeating the reference's help drift.

Preserve:

- documented patient/day/task/status/navigation/focus commands and aliases;
- common keyboard workflows.

Intentionally change:

- define actions once and generate menus, shortcuts, command registrations, and help from one
  registry;
- avoid overriding normal editor shortcuts when focus is in a text control.

**Acceptance:** command parsing and action dispatch are unit tested; generated help matches every
registered shortcut; keyboard-only smoke tests cover the primary workflow.

Implementation notes:

- Immutable `ActionDefinition` records drive `QAction` labels, menus, toolbar placement, shortcut
  sequences, command aliases, usage text, and generated Help from one validated registry.
- The parser normalizes whitespace/case, resolves exact aliases before argument prefixes, reports
  missing required arguments, and preserves optional readmission prompting.
- Commands cover patient/day selection, readmission, disposition, active-patient navigation, task
  entry, SOAP/popup modes, save/copy, task board, completed visibility, and workflow focus targets.
- Main-window pin, sidebar visibility, and resize presets are registered actions. The pin preference
  uses existing device-local settings; no clinical or database state was added.
- Patient navigation uses `Ctrl+Shift+J/L` consistently in both the live binding and generated help,
  intentionally eliminating the characterized CapsLock/help discrepancy.
- Standard text copy/cut/paste/select-all/undo/redo shortcuts are absent from the action registry and
  remain native to focused Qt editors. No migration was required.

## Slice 15: Analytics

**Status:** Implemented.

**Goal:** provide read-only operational summaries derived from canonical data.

Preserve:

- census/status/acuity counts;
- average ICU days, pending diagnostics, missing-today, top terms, and Needs Attention;
- refresh and approved clipboard export.

**Acceptance:** reports are deterministic for fixed fixtures, contain no stored duplicate totals,
and handle an empty database.

Implementation notes:

- `AnalyticsService` creates one immutable snapshot from canonical patient aggregates; there is no
  analytics table, cache, or schema migration.
- Active acuity and problem terms use each patient's newest hospital day. Pending diagnostics use
  only the newest occurrence of each task lineage, so an older open occurrence cannot reappear
  after its carried successor is completed or cancelled.
- Fixed status/acuity order and count-descending, term-ascending ranking make reports deterministic.
  Missing-today rows precede pending-diagnostic rows in Needs Attention, preserving the reference
  behavior where one patient can have both reasons.
- The resizable read-only dialog supports explicit refresh and clipboard copy, is registered in the
  shared action/command/help system, and refreshes while visible after canonical domain events.
- Service and headless Qt tests cover populated and empty projections, lineage semantics, exact
  report export, action dispatch, clipboard output, and live refresh.

## Slice 16: Recovery, Backup Restore, and External Conflict Policy

**Status:** Implemented.

**Goal:** meet or exceed the reference's protection against loss without imitating whole-file text
synchronization.

Preserve:

- autosave flush on navigation/exit;
- recoverable draft behavior;
- rotating backups;
- explicit confirmation before destructive restore/overwrite;
- visible save and recovery status.

Intentionally change:

- use SQLite-consistent backup/restore and transaction rules;
- define cloud synchronization as a separate future integration;
- do not use modification time as a record-level merge mechanism.

**Acceptance:** forced-failure tests prove rollback; backup restore is tested using copied temporary
databases; interrupted-edit recovery never overwrites a newer committed record silently.

Implementation notes:

- Patient Summary, Daily Charting, SOAP, and Sandbox editors stage one versioned recovery snapshot
  for their stable patient/day UUID context. A UI-independent service owns the 900 ms debounce and
  an atomic JSON store owns temporary replacement and last-cleared `.bak` retention.
- Each entry records a SHA-256 fingerprint of the canonical values originally loaded. Startup
  recovery compares current canonical values and requires a second warning when they differ.
  Recovery populates unsaved editors for review; it never writes clinical records automatically.
- A successful coordinated save archives and clears the recovery marker. A failed close explicitly
  flushes the staged recovery snapshot before the application refuses shutdown.
- Create Backup and Restore Backup are registered File actions and typed commands. Restore verifies
  a selected SQLite candidate before confirmation, binds the confirmation to its SHA-256 identity,
  creates a verified pre-restore safety backup, replaces atomically, and reopens the shared database
  lifecycle. A candidate changed after review is rejected.
- Forced replacement-failure tests prove the original database remains readable after pooled
  connections reopen. Restart tests prove interrupted drafts stay unsaved until explicit approval.
- No schema migration was required. The local SQLite database is not a cloud synchronization
  artifact; future sync/import adapters must use explicit content identities and conflict policy.

## Slice 17: Production Legacy Import

**Status:** Implemented; real-source dry run completed, intended-database import awaiting manual
staging review and explicit approval.

**Goal:** migrate approved reference records into SQLite once all destination semantics exist.

Preserve:

- all supported version-13 patient/day/task/SOAP/settings content;
- statuses, dates, source identities, ordering, and historical relationships;
- an immutable audit of source fingerprints and import results without clinical text.

Workflow:

1. Back up the repository, database, and source files.
2. Run parser dry run and review every warning.
3. Import into a copied staging database.
4. Reconcile counts and inspect a deidentified sample manually.
5. Run the full suite and restart test.
6. Only then import into the intended local database.

**Acceptance:** totals reconcile, repeated import cannot duplicate records, source files retain their
original hashes, and rollback leaves the target unchanged on failure.

Implementation notes:

- The v13 parser now decodes normalized task metadata and every recognized setting while keeping
  terminal reports free of patient identifiers and clinical text.
- Import requires the exact pair of reviewed SHA-256 fingerprints, an explicit target, and an
  explicit backup directory. Non-empty targets and repeated source pairs are rejected.
- Generated UUIDs own all Python aggregates. A non-clinical audit stores source hashes, result
  counts, and hashed legacy-to-target identities; clinical text is never written to the audit.
- Patients, days, tasks, reminders, SOAP Markdown, problems, devices, and the audit marker commit in
  one SQLAlchemy transaction, followed by persisted table-count reconciliation and a second source
  hash check.
- The current real source pair validates as 253 patients and 395 hospital days. It has only been
  mapped in memory; no intended application database was modified.
- Global housekeeping and presentation-only settings remain explicit review items because the
  current domain has no global task owner and Python preferences must not be silently overwritten.

## Slice 18: Optional External Integrations and Release Readiness

**Status:** Release foundation and the approved resident-shell adapter are implemented; remaining
environment-specific integrations are separately scoped.

**Goal:** decide which environment-specific conveniences belong in the Python product.

Candidates:

- Master Script launch/message compatibility;
- cloud-folder monitoring;
- tray menu and global shortcuts (implemented as an optional composition-root adapter);
- installer, application icon, signed executable, and update approach.

These are optional and must remain adapters around the application. The reference Master Script
contract is now known: it receives `PT_OPEN_ICUPE` and `PT_OPEN_SICK` registered Windows messages,
and its `Shift+Alt+I` handler searches for an AutoHotkey GUI before launching an `.ahk` path. A Qt
compatibility solution must not require editing the supplied reference files. It may use a separate
launcher adapter or a deliberately approved change to a working copy later.

**Acceptance:** optional adapters can be disabled without affecting clinical workflows or storage;
the packaged application passes a clean-machine installation and smoke test.

Implementation notes:

- A PyInstaller one-directory Windows bundle includes Qt plugins, themes, timezone data, and the
  filesystem Alembic environment and revisions required for first-run database creation.
- `scripts/build_release.ps1` runs quality gates, builds Python artifacts and the executable,
  executes an isolated binary-level smoke test, creates a versioned ZIP, and records SHA-256.
- The packaged smoke path refuses reused artifacts and never opens the configured application
  database. It verifies migrations, SQLite foreign keys, and graceful shutdown.
- The locally built executable passed the packaged smoke test. A clean Windows virtual-machine
  acceptance remains a manual release gate.
- Master Script message compatibility, cloud monitoring, installer/icon work, signing, and
  automatic updates remain separately approved adapter work. Global shortcuts and the resident tray
  launcher are implemented without modifying any reference file.

## Per-Slice Approval Template

Before starting a slice, answer:

1. Which listed reference behaviors must be preserved exactly?
2. Which behaviors should intentionally change?
3. What synthetic examples demonstrate success?
4. What is explicitly out of scope?
5. Does the slice require schema migration or legacy-data conversion?
6. What manual workflow will the user perform to accept it?

The implementation report for each slice will list changed files, migrations, tests, manual steps,
known limitations, and the recommended Git commit message.
