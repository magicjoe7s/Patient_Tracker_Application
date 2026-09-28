# ICU Patient Tracker Software Specification

**Document status:** Current-state baseline  
**Prepared:** 2026-07-20  
**Implementation:** AutoHotkey v2  
**Persistence format:** Version 13

## 1. Purpose and Scope

This document specifies the ICU Patient Tracker as it is currently implemented. It covers the desktop application's purpose, design philosophy, data model, functional behavior, screens, dialogs, keyboard interaction, themes, settings, storage, integrations, non-functional characteristics, known gaps, and candidate areas for future development.

The specification is based on:

- `patient_tracker.ahk`: application shell, UI, patient and task operations, SOAP processing, analytics, commands, reminders, and integrations.
- `patient_tracker_workflow.ahk`: selection commits, day ordering and navigation, and reminder scheduling calculations.
- `patient_tracker_persistence.ahk`: versioned serialization, migrations, main/archive splitting, backups, recovery, and external-change detection.
- `theme_config.ahk`: shared typography, spacing, sizing, and base Warm theme tokens.
- `patient_tracker_data.txt`: active-patient data and persisted application settings.
- `patient_tracker_archive.txt`: non-active patient records.

This is a local workflow tool. The current implementation does not provide authentication, role-based access, encryption, a server API, or multi-user record locking.

## 2. Project Overview

The ICU Patient Tracker is an always-available desktop application for managing a veterinary ICU census and the clinical work associated with each patient and hospital day. It combines:

- Active census navigation and patient disposition tracking.
- Patient-level summary information.
- Date-ordered hospital-day records.
- To Do, POCUS, pending-diagnostic, and housekeeping task management.
- Structured charting fields and a generated/editable SOAP note.
- Fast clipboard export for EMR-side charting.
- Search, command-driven navigation, analytics, reminders, and a consolidated task board.
- Local recovery and Google Drive-oriented file synchronization safeguards.
- Launch integration with `Master Script - v2.ahk` for the tracker, ICU physical examination, and sick-patient workflows.

The primary operator is a clinician working repeatedly across multiple patients while other clinical or EMR windows are open. The application therefore prioritizes rapid switching, keyboard control, minimal navigation depth, persistent state, and compact auxiliary windows.

## 3. Design Philosophy

### 3.1 Clinical workflow first

The application organizes work around patient and hospital-day context. Selection changes commit the currently loaded record before another record is shown. The selected patient/day is the shared context for charting, tasks, SOAP, diagnostics, and reminders.

### 3.2 One source with multiple working surfaces

Structured charting, SOAP, the compact Patient Popup, diagnostics editor, task sidebar, and task board operate on the same in-memory records. Views are refreshed after mutations rather than maintaining independent data stores.

### 3.3 Preserve history while carrying work forward

New hospital days carry forward incomplete tasks and device information. Logical task IDs form lineages across days. Completing, reopening, or editing a task from a given day applies from that occurrence forward while earlier history remains intact. Explicit deletion removes the full lineage after confirmation.

### 3.4 Minimize data loss

The tracker uses delayed autosave, explicit Save Now, local recovery snapshots, backup copies, atomic replacement, audit logging, version migration backups, and modification-time checks before overwriting externally changed files.

### 3.5 Support keyboard and mouse equally

Primary actions have buttons, menu commands, keyboard shortcuts, or typed command equivalents. Focus-aware shortcuts preserve normal editing behavior where possible.

### 3.6 Progressive workspace density

The main window is responsive. It supports collapsible navigation, Charting/SOAP/Sandbox lower-panel modes, resize presets, an always-on-top compact editor, and automatic handoff to the Patient Popup below a monitor-relative size threshold.

### 3.7 Plain-text portability

Records are stored in UTF-8, line-oriented, versioned text files. Fields are percent-encoded so delimiters and newlines can be represented without requiring a database engine.

## 4. System Context and Modules

| Module | Responsibility |
|---|---|
| Main tracker | Application startup, all GUI construction, event handlers, patient/task operations, SOAP conversion, search, analytics, layout, clipboard, and Master Script messaging. |
| Workflow module | Safe context commits, date/day ordering, timeline display, reminder timestamps, due-time calculations, and reminder summaries. |
| Persistence module | Version-12 read/write, defaults, migrations, main/archive separation, backups, recovery snapshots, atomic writes, and external modification detection. |
| Theme module | Shared Aptos typography, spacing/sizing tokens, Warm palette, and native edit/list input coloring. |
| Master Script integration | Global `Shift+Alt+I` launcher/toggle, plus registered-window-message commands for ICU PE and sick-patient tools. |

The tracker runs as a single-instance persistent AutoHotkey v2 process. The tray menu exposes Show/Hide, Pin, Drive reload/upload actions, and Exit.

## 5. Domain Model

### 5.1 Application state

Application state contains:

- A map of patients keyed by an internal generated ID.
- Manual active-patient order.
- Global housekeeping task text.
- Current patient and hospital-day selection.
- Window, sidebar, filter, sort, theme, completion-filter, and pin preferences.
- Runtime-only search, popup, caret, reminder, dirty-state, and layout information.

### 5.2 Patient record

A patient record currently supports:

- Internal patient ID.
- Display name.
- Optional six-digit patient ID/MRN in runtime memory.
- Status: `Active`, `Home`, `IMC`, `Archived`, or `Death`.
- Acuity fallback: `Critical`, `Watcher`, or `Stable`.
- Code status: `CPR`, `DNR`, `DVM Discretion`, or `DNR Assist`.
- Blood type: blank, `DEA 1.1 +`, `DEA 1.1 -`, `Type A`, or `Type B`.
- Running problem list.
- One-line clinical summary.
- Legacy/patient-scope To Do, POCUS, and pending task fields.
- A map of hospital days and an ordered list of day keys.

### 5.3 Hospital-day record

Each hospital day supports:

- Date-based display label, optionally with a note such as `YYYY-MM-DD | postop`.
- Day-specific acuity in runtime memory.
- To Do, POCUS, and pending-diagnostic task lists.
- Treatment changes.
- Physical examination.
- Devices/lines.
- Legacy reminders text.
- Assessment/notes.
- Sandbox text.
- Overnight resident and faculty values parsed from SOAP.
- EMR-uploaded flag.
- SOAP mode flag and SOAP text.

Dates are normalized and sorted chronologically where a date token can be extracted. Older unparseable keys are retained after sortable dates.

### 5.4 Task record

Each task has:

- Stable logical task ID.
- Kind: To Do, POCUS, pending diagnostic, or housekeeping context.
- Text.
- Completion state.
- Priority: `routine`, `low`, `urgent`, or `critical`.
- Bucket: `today`, `overnight`, `discharge`, `followup`, or `diagnostic`.
- Carry-forward flag, defaulting to true.
- Optional reminder: interval minutes such as `60m`, or 24-hour clock time such as `14:30`.
- Reminder anchor and last-shown timestamps when applicable.

Task entry supports pipe-delimited suffixes such as:

```text
Recheck blood pressure | p:urgent | b:today | r:60m
Culture result | b:followup | nocarry
```

Leading `!` marks urgent and `!!` marks critical. Text recognized as POCUS is automatically routed from To Do into the POCUS category.

## 6. Functional Requirements

### 6.1 Patient Management

| ID | Current requirement |
|---|---|
| FR-PAT-001 | The system shall create a patient from a required name and an optional six-digit patient ID/MRN. |
| FR-PAT-002 | Creating a patient shall set status Active, acuity Stable, code status CPR, add the patient to active order, and create today's hospital day. |
| FR-PAT-003 | The system shall rename a selected patient. |
| FR-PAT-004 | The patient ID button shall copy an existing ID; Shift-click or a missing ID shall open ID editing. |
| FR-PAT-005 | The system shall set status to Active, Home, IMC, Archived, or Death. Death shall require confirmation. |
| FR-PAT-006 | Moving a patient out of Active shall remove it from active order. Reactivation shall restore it to active order. |
| FR-PAT-007 | The system shall archive one patient or all active patients matching a non-empty search, after confirmation. |
| FR-PAT-008 | Permanent purge shall be restricted to Archived patients and shall require confirmation. |
| FR-PAT-009 | Home and IMC patients shall be eligible for readmission to ICU through the command palette. Readmission shall reactivate the patient and create today's day if absent. |
| FR-PAT-010 | Active patients shall support manual drag reordering in the patient tree. Alternative sort modes shall be Name, Acuity, and Status. |
| FR-PAT-011 | The patient tree shall show acuity, disposition, abbreviated code status, open To Do and diagnostic counts, EMR status, and missing-today flags. |

### 6.2 Patient Information Management

| ID | Current requirement |
|---|---|
| FR-INF-001 | The patient summary shall edit acuity, code status, blood type, running problem list, and one-liner. |
| FR-INF-002 | Acuity shall be selectable and cycleable through Stable, Watcher, and Critical. |
| FR-INF-003 | A hospital day shall capture treatment changes, physical examination, devices/lines, assessment, SOAP, sandbox, task lists, and EMR-upload state. |
| FR-INF-004 | New day input shall require `YYYY-MM-DD`, optionally followed by a pipe and note. Duplicate dates for the same patient shall be rejected. |
| FR-INF-005 | Hospital days shall be presented chronologically with ICU ordinal, date/note, Today marker, and task-status badge. |
| FR-INF-006 | New hospital days shall carry forward incomplete carry-enabled To Do, POCUS, and pending tasks; devices/lines shall also carry forward. |
| FR-INF-007 | The latest day's overnight resident and faculty shall be available to SOAP generation and parsing. |
| FR-INF-008 | Copy Chart shall place treatment, examination, devices, and assessment text on the clipboard with patient/day context. |
| FR-INF-009 | Copy SOAP shall place SOAP text on the clipboard, mark the day uploaded to EMR, and minimize the main tracker. |

### 6.3 Task and Reminder Workflow

| ID | Current requirement |
|---|---|
| FR-TSK-001 | The selected-day task workspace shall expose separate To Do, POCUS, and Pending lists with completion checkboxes and open counts. |
| FR-TSK-002 | Users shall add, edit, delete, complete, and reopen tasks from the selected-day sidebar. Double-click shall edit. |
| FR-TSK-003 | Editing or changing completion shall preserve a logical task ID and update matching carried occurrences from the acted-on day forward. |
| FR-TSK-004 | Deleting a task shall require confirmation and remove every carried occurrence in its lineage. |
| FR-TSK-005 | Completed tasks may be hidden independently for To Do, POCUS, Pending, and Housekeeping. |
| FR-TSK-006 | The system shall maintain a global Housekeeping list outside patient/day scope. |
| FR-TSK-007 | The task board shall show each logical task once using its newest authoritative occurrence. |
| FR-TSK-008 | The task board's Pending pane shall include Active, Home, and IMC follow-up diagnostics. To Do and POCUS targets shall be Active patients. |
| FR-TSK-009 | Pending diagnostics shall support a free-form summary editor using `[ ]` and `[x]` lines. Removed carried items shall be recorded as completed tombstones so they do not reappear. |
| FR-TSK-010 | Unchecked Markdown checklist lines in Sandbox shall be convertible into day To Do/POCUS tasks during save. |
| FR-REM-001 | To Do and POCUS tasks shall support interval and fixed-time reminders. Pending and housekeeping tasks do not currently generate timed alerts. |
| FR-REM-002 | The system shall poll timed reminders once per minute and show up to three due alerts in a tray notification. |
| FR-REM-003 | The system shall generate an hourly digest when open work exists and open the task board with due, pending, follow-up, urgent, and aggregate information. |
| FR-REM-004 | An hourly digest may be snoozed for five minutes. |

### 6.4 SOAP and Clinical Workflow

| ID | Current requirement |
|---|---|
| FR-SOAP-001 | Each hospital day shall have an independently editable SOAP document and a SOAP-mode flag. |
| FR-SOAP-002 | Empty SOAP content shall be initialized from a clinical template containing hospitalization header, code status, clinical trend, one-liner, problem list, examination, diagnostics, treatment, instrumentation, ins/outs, assessment, recommendations, and staff attribution. |
| FR-SOAP-003 | Structured fields shall autofill their mapped SOAP sections without replacing unrelated SOAP sections. |
| FR-SOAP-004 | SOAP edits shall reverse-synchronize problem list, one-liner, diagnostics, treatment, AM physical examination, devices, AM assessment, overnight resident, and faculty where recognized. |
| FR-SOAP-005 | Pending diagnostics shall preserve entered diagnostic results when the structured pending list refreshes the SOAP section. |
| FR-SOAP-006 | Devices such as urinary catheters, drains, and chest tubes shall add or retain relevant output rows in Ins/Out. |
| FR-SOAP-007 | Refresh SOAP shall rebuild all mapped sections from the current structured charting values. |
| FR-SOAP-008 | The Patient Popup shall expose SOAP and Sandbox editors for the same selected patient/day and mirror content with the main editors. |
| FR-SOAP-009 | The popup shall support patient navigation, compact/full modes, SOAP/Sandbox switching, caret restoration per patient/day, and return to the main window. |

### 6.5 Search, Filters, Commands, and Navigation

| ID | Current requirement |
|---|---|
| FR-NAV-001 | The left sidebar shall switch between patient navigation and selected-day task management. |
| FR-NAV-002 | Patient filtering shall support All Active, Needs Attention, No Today, Pending DX, Open To-Dos, and Critical/Watcher. |
| FR-NAV-003 | Sidebar search shall match name, status, acuity, code status, blood type, problem list, one-liner, tasks, dates, charting, SOAP, and Sandbox content. |
| FR-NAV-004 | Show bins shall include Home, IMC, Archived, and Death records in applicable tree/search views. |
| FR-NAV-005 | The Patient Search popup shall filter live, cycle results, select with or without closing, rename a result, and mass-archive active matches. |
| FR-NAV-006 | Selection changes shall commit the currently loaded record and queue persistence before loading the destination. |
| FR-NAV-007 | The command palette shall support patient/day selection, new patient/day, readmission, task creation, status changes, patient navigation, SOAP/popup/Sandbox, save/copy/pin, task board, hide/show completed, and focus commands. |
| FR-NAV-008 | The lower workspace shall switch among Charting, SOAP, and Sandbox panels. |

### 6.6 Analytics

| ID | Current requirement |
|---|---|
| FR-ANA-001 | Analytics shall report total and active census plus counts by status. |
| FR-ANA-002 | Analytics shall report active-patient acuity distribution, average ICU days, patients with pending diagnostics, and patients missing today's entry. |
| FR-ANA-003 | Analytics shall report top logical pending diagnostics, top active-patient problem-list terms, and a Needs Attention list. |
| FR-ANA-004 | Analytics shall be refreshable, copyable to the clipboard, resizable, and read-only. |

### 6.7 External Integration

| ID | Current requirement |
|---|---|
| FR-INT-001 | `Master Script - v2.ahk` shall launch or show/hide the tracker through `Shift+Alt+I`. |
| FR-INT-002 | ICU PE and sick buttons shall send registered Windows messages to a running Master Script instance. |
| FR-INT-003 | If Master Script is not running, the tracker shall attempt to start it and retry the command. |
| FR-INT-004 | Drive actions shall offer explicit local-to-Drive overwrite and Drive-to-local reload directions, each with overwrite confirmation where data loss is possible. |

## 7. Screens and Interactions

### 7.1 Main: ICU Patient Tracker

The resizable main window contains:

| Region | Components | Interaction |
|---|---|---|
| Sidebar mode selector | Patients and Tasks tabs | Switches between census navigation and selected-day task work. |
| Patient actions | New Patient, New Day, collapse, Drive | Creates records, changes layout, or opens sync actions. |
| Find and filters | Search, clear, popup search, Show bins, view filter, sort | Filters the tree and controls patient visibility/order. Enter in sidebar search selects the first match. |
| Tracker status | Census/task metrics, saved state, reminder overview, selected summary | Read-only operational state. |
| Patient tree | Patient roots and hospital-day children | Selects context; active roots may be manually reordered. |
| Status actions | Home, IMC, Act, Death, Menu | Changes disposition or opens the command hub. |
| Selected-day tasks | To Do/POCUS/Pending tabs, Hide Completed, Add/Edit/Delete, Pending Summary, Task Board | Manages lineage-aware tasks. |
| Patient overview | Name, patient ID, Task Board, Save Now, status, acuity, code status, blood type, problem list, one-liner, EMR flag | Edits patient and selected-day metadata. |
| Panel selector | Charting, SOAP, Sandbox | Selects the lower workspace in the current single-panel layout. |
| Charting workspace | Day navigation, reminders, treatment, examination, devices, assessment, Copy Chart, Refresh SOAP | Edits structured day information and drives SOAP mapping. |
| SOAP workspace | SOAP editor and Copy SOAP | Direct SOAP editing and EMR clipboard workflow. |
| Sandbox workspace | Free-text editor and Pop out | Per-day scratch work and task extraction. |

Closing the main window exits through the normal save path. Escape hides the window without exiting.

### 7.2 Patient Popup

An always-on-top tool window used beside the EMR. It provides Main, SOAP/Sandbox mode controls, compact/full mode, previous/next active patient, patient/day header, and the active editor. Showing it hides the main window. Closing, Escape, or Main commits edits and restores the main tracker.

### 7.3 Patient Search

An always-on-top search field and result list. Empty search initially shows all patients allowed by Show bins. Typing filters live. Arrow keys or search-specific shortcuts cycle. Enter selects and closes; Ctrl+Enter selects and remains open; F2 renames; Ctrl+Shift+Enter archives all active matches after confirmation. If opened from the Patient Popup, focus returns there.

### 7.4 Pending Diagnostics

A focused multi-line editor for a selected patient/day. Other tracker windows are temporarily hidden and restored on close. Changes save on focus loss or close, preserve task IDs where possible, complete omitted carried tasks, propagate edits forward, update SOAP diagnostics, and refresh derived task views.

### 7.5 ICU Tracker Task Board

A resizable always-on-top 2x2 dashboard:

- Pending Diagnostics + Follow-up.
- All Patients To Do.
- POCUS.
- Housekeeping.

Each pane has Hide Completed and Add/Edit/Delete controls. Checking changes completion; double-clicking a patient-scoped row selects its patient/day. Refresh updates all panes. When opened for the hourly digest, a Snooze button and digest summary are shown.

### 7.6 Tracker Menu / Shortcuts

A resizable, read-only help window generated from application text. It links to the typed command palette and can be hidden with Close or Escape.

### 7.7 ICU Tracker Analytics

A resizable read-only report window with Refresh, Copy, and Close controls. The report is recalculated from current in-memory records whenever opened or refreshed.

## 8. Dialog and Notification Inventory

| Dialog/notification | Trigger and behavior |
|---|---|
| Google Drive Sync | Drive button; chooses Send Local Data to Drive, Replace Local Data from Drive, or Cancel. |
| New ICU Patient | New Patient; collects name and optional six-digit ID/MRN and validates the ID. |
| Patient ID | Add ID or Shift-click ID; validates a six-digit value. |
| Add Hospital Day | New Day; accepts date plus optional note and rejects invalid/duplicate dates. |
| Rename | Rename action/F2; edits patient name. |
| To Do / POCUS / Pending input | Add/Edit task; accepts text plus priority, bucket, reminder, and carry suffixes. Empty edit invokes deletion behavior. |
| Task Board target picker | Board Add for patient-scoped work; chooses an eligible patient/latest day and task specification. |
| Pending Diagnostics | Edit Pending Summary; full multi-line diagnostic checklist editor. |
| Command Palette | Ctrl+K; displays examples and accepts one typed command. |
| Readmit To ICU | `readmit` without a query; prompts for a Home/IMC patient. |
| Recover Draft | Startup with a valid recovery file; offers to restore unsaved patient/day edits. |
| Reload Tracker Data | Manual Drive reload with dirty state; confirms discarding local unsaved edits. |
| Overwrite Drive Data | Forced save while an external change is detected; confirms replacing the newer disk copy. |
| Archive Patient | Archive action; confirms non-destructive archival. |
| Mass Archive | Search Ctrl+Shift+Enter; previews matching names and confirms batch archival. |
| Death Status | Death action; confirms deceased/euthanized status. |
| Confirm Purge | Permanent purge of an Archived record; warns that it cannot be undone. |
| Delete Task Lineage | Task delete; confirms removal of all carried copies. |
| Validation/error messages | Missing selection, missing Master Script, invalid ID/date, duplicate day, empty SOAP, missing target, unknown command/status/focus, or launch/message failure. |
| Reminder tray notification | Once-per-minute scan; displays up to three due To Do/POCUS items and a remaining count. |
| Tooltip | Copying patient ID briefly reports the copied value. |

All tracker-owned input and message dialogs temporarily lower a pinned owner so the dialog is not hidden behind it, then restore pin state.

## 9. Keyboard Shortcuts

AutoHotkey notation is translated below into user-facing key names. Unless marked global or popup-specific, shortcuts require the main tracker to be active.

### 9.1 Main tracker

| Shortcut | Action |
|---|---|
| Ctrl+N | New patient. |
| Ctrl+D | Add pending diagnostic for selected day. |
| Ctrl+Shift+D | New hospital day. |
| Alt+N | New hospital day. |
| Ctrl+T | Add To Do for selected day. |
| Ctrl+S | Save current edits. |
| Ctrl+Z | Undo in focused edit control. |
| Ctrl+Y or Ctrl+Shift+Z | Redo in focused edit control. |
| Ctrl+P | Toggle Patient Popup. |
| Alt+S | Toggle SOAP mode for selected day. |
| Ctrl+V or Shift+Insert | Context-aware paste; Sandbox paste receives Markdown/flattened-text formatting. |
| Ctrl+Delete | Delete the next word in an editable field. |
| Ctrl+F | Open Patient Search. |
| Ctrl+Shift+I | Previous hospital day. |
| Ctrl+Shift+K | Next hospital day. |
| Ctrl+Alt+1 | Small resize preset. |
| Ctrl+Alt+2 | Medium resize preset. |
| Ctrl+Alt+3 | Large resize preset. |
| Ctrl+Alt+0 | Fit active monitor. |
| Ctrl+Alt+A | Open Analytics. |
| Ctrl+Alt+H | Toggle all hide-completed preferences. |
| Ctrl+Alt+L | Collapse/expand patient sidebar. |
| Ctrl+Alt+P | Toggle always-on-top pin. |
| Ctrl+Alt+T | Open Task Board. |
| Ctrl+K | Open typed Command Palette. |
| Ctrl+G or F3 | Next current search result. |
| Ctrl+Shift+G or Shift+F3 | Previous current search result. |
| F2 | Rename selected patient. |
| Tab / Shift+Tab | Move through workflow fields or `#INPUT#` tokens. |
| Alt+P | Focus Problem List or its SOAP section. |
| Alt+E | Focus Physical Exam or its SOAP section. |
| Alt+T | Focus Treatment or its SOAP section. |
| Alt+A | Focus Assessment or its SOAP section. |
| CapsLock+Alt+J | Previous active patient. |
| CapsLock+Alt+L | Next active patient. |

### 9.2 Patient Popup

| Shortcut | Action |
|---|---|
| Ctrl+N or Alt+N | New patient. |
| Ctrl+S | Save popup edits. |
| Ctrl+F | Open Patient Search. |
| Ctrl+P | Close/toggle popup. |
| Ctrl+Shift+S | Switch to Sandbox. |
| Ctrl+Shift+O | Switch to SOAP. |
| Alt+M | Toggle compact/full size. |
| Alt+S | Toggle SOAP/Sandbox editor. |
| Ctrl+T | Add To Do. |
| Ctrl+D | Add pending diagnostic. |
| Tab / Shift+Tab | Move among `#INPUT#` tokens, then return to editor. |
| CapsLock+Alt+J / CapsLock+Alt+L | Previous/next active patient. |
| Shift+Alt+I | Refocus popup editor while the popup is visible. |

### 9.3 Patient Search

| Shortcut | Action |
|---|---|
| Up / Down | Previous/next visible match. |
| Ctrl+J / Ctrl+Shift+K | Next/previous visible match. |
| Enter | Select and close. |
| Ctrl+Enter | Select and keep search open. |
| Ctrl+Shift+Enter | Archive all active matches after confirmation. |
| F2 | Rename highlighted patient. |
| Escape | Close and return focus. |

### 9.4 Task Board and global launcher

| Scope | Shortcut | Action |
|---|---|---|
| Task Board | Ctrl+T | Add To Do. |
| Task Board | Ctrl+D | Add pending diagnostic. |
| Task Board | Ctrl+H | Add housekeeping task. |
| Global while tracker runs | Alt+Shift+T | Toggle Task Board. |
| Master Script global | Shift+Alt+I | Launch/show/hide Patient Tracker. |

### 9.5 Current help-text discrepancies

The generated in-app help currently describes `Ctrl+Shift+J / Ctrl+Shift+L` for patient navigation, but the registered handlers require `CapsLock+Alt+J / CapsLock+Alt+L`. It also describes `Ctrl+Backspace` for word deletion, while the registered handler is `Ctrl+Delete`. This specification records the implemented bindings.

## 10. Typed Command Palette

Supported commands and aliases include:

- `help`, `h`, or `?`.
- `np` or `new patient`.
- `nd` or `new day`.
- `todo` or `new todo`.
- `readmit` or `readmit <patient query>`.
- `p <patient query>` or `patient <patient query>`.
- `day <date or label>`.
- `status active|home|imc|archive|death`.
- `next`, `prev`, or `previous`.
- `soap` or `toggle soap`.
- `popup`, `soap popup`, `sandbox popup`, or `popup sandbox`.
- `save`, `copy`, or `copy soap`.
- `pin` or `toggle pin`.
- `tasks`, `task board`, or `board`.
- `hide done`, `hide completed`, `show done`, or `show completed`.
- `focus search|problem|todo|pocus|pending|treatment|exam|devices|assessment|soap|tree`.

Commands are executed after the modal input dialog closes. Unknown commands show an error and direct the user back to help.

## 11. Themes and Visual System

### 11.1 Available themes

| Theme | Characteristics |
|---|---|
| Clinical Blue | Default. Cool neutral background, white surfaces, dark text, blue navigation/primary accents, green success, amber warning, and red error/critical states. |
| Warm | Original shared palette. Eggshell background, cream surfaces, warm charcoal text, brick-red critical accent, and hunter-green success accent. |

Theme selection is available under Menu > Theme and is persisted. The application updates the main window and created auxiliary windows at runtime, including input/list background and text colors.

### 11.2 Shared visual tokens

- Font family: Aptos.
- Base size: 10; header 12; helper 9; hero 18.
- General padding: 10; small 5; large 15.
- Nominal button height: 32.
- Input height: 28.
- Nominal border radius token: 6, although native AutoHotkey controls determine actual rendering.
- Semantic colors: navigation, primary, selected, success, warning, error, and critical.

### 11.3 Acuity and status visualization

Clinical acuity is displayed through text badges and semantic colors. Tree labels add concise operational flags such as code status, open task counts, pending-diagnostic counts, EMR state, and missing-today state.

## 12. Settings and Preferences

### 12.1 Persisted settings

The following are stored in `patient_tracker_data.txt`:

| Setting | Values/default |
|---|---|
| Window position and size | `winX`, `winY`, `winW`, `winH`; default 1270x780. Off-screen saved positions are rejected and recentered. |
| Main window pin | Boolean; default off. |
| Show bins | Boolean; default off. |
| Sidebar mode | Patients or Tasks; default Patients. |
| Selected task category | To Do, POCUS, or Pending; default To Do. |
| Left sidebar collapsed | Boolean; default false. |
| Hide completed | Independent booleans for To Do, POCUS, Pending, and Housekeeping; defaults true. |
| Sort mode | Manual, Name, Acuity, or Status; default Manual. |
| Theme | Clinical Blue or Warm; default Clinical Blue. |
| Sidebar filter | One of the six defined patient filters; default All Active. |
| Active order | Ordered list of active patient internal IDs. |
| Housekeeping | Global normalized task list. |

### 12.2 Runtime/session settings

Current selection, sidebar search text, Charting/SOAP/Sandbox lower-panel selection, popup compact mode, caret locations, search results, reminder queues, and transient scroll/layout state are not serialized as durable settings.

## 13. Data Storage and Persistence

### 13.1 File locations

| Path | Purpose |
|---|---|
| `A_ScriptDir\patient_tracker_data.txt` | Version-13 settings plus Active patient records. |
| `A_ScriptDir\patient_tracker_archive.txt` | Version-13 Home, IMC, Archived, and Death patient records. |
| `%AppData%\PatientTracker\patient_tracker_data.txt.bak` | Backup of active/settings file. |
| `%AppData%\PatientTracker\patient_tracker_archive.txt.bak` | Backup of archive file. |
| `%AppData%\PatientTracker\patient_tracker_recovery.txt` | Unsaved current patient/day recovery snapshot. |
| `%AppData%\PatientTracker\patient_tracker_recovery.txt.bak` | Last cleared recovery snapshot. |
| `%AppData%\PatientTracker\patient_tracker_audit.log` | Timestamped audit events. |
| `%AppData%\PatientTracker\*.v11` | One-time pre-migration copies when task IDs are upgraded from a pre-version-12 format. |
| `%AppData%\PatientTracker\*.v12` | One-time copies of the live and archive files before the version-13 patient ID/day-acuity migration. |

### 13.2 Serialization contract

- Files are UTF-8 plain text.
- Records use `TYPE|field|field...` lines.
- Current format is `VERSION|13`.
- Main file begins with window/settings records; archive declares `FILE_ROLE|ARCHIVE`.
- User data is UTF-8 percent-encoded, preserving pipes, percent signs, and newlines.
- Patient records and day records are independent lines joined by internal IDs.
- Version 13 appends the normalized six-digit patient ID/MRN to each `PATIENT` record and normalized day-specific acuity to each `DAY` record without shifting older field indexes.
- Tasks are normalized checkbox lines with metadata suffixes and stable IDs.
- Older formats are parsed with compatibility branches and upgraded on load/save.
- During version-12 migration, patient ID is recovered from a six-digit value in the patient name when available. Day acuity is inferred from SOAP Clinical Trend (`Unstable`, `Watcher`, or `Stable`), then falls back to patient acuity and finally Stable.

### 13.3 Save and recovery behavior

- Field edits mark the application dirty and normally queue autosave after approximately 700 ms.
- Recovery snapshots are queued after approximately 900 ms while editing a valid patient/day.
- Save first commits the active UI context into memory.
- Writes use a temporary file under `%AppData%\PatientTracker`, copy the old destination to its backup, then replace the destination.
- Successful save clears the recovery file, updates known modification times, clears dirty state, and records the save time.
- Exiting commits current values, saves, and releases native theme resources.

### 13.4 External/Drive change behavior

- A silent watcher checks external file changes separately from autosave and no more often than every 15 minutes.
- If an external change is found while there are no dirty or pending local edits, the tracker automatically reloads it and attempts to retain the current patient/day selection.
- Save compares current file modification times with the last known values.
- A newer/replaced/deleted external file blocks an ordinary overwrite and marks an external reload pending.
- Manual reload may discard unsaved local edits only after confirmation.
- Forced local-to-Drive save requires confirmation before overwriting an externally newer copy.
- Conflict detection is modification-time based; there is no record-level merge.

### 13.5 Audit events

The audit log currently records task reminder display, patient creation, hospital-day creation, rename, status change, readmission, archive, and purge actions. It is append-only in normal operation and contains timestamps plus action/detail text.

## 14. Non-Functional Requirements and Current Characteristics

### 14.1 Reliability and integrity

| ID | Requirement/current mechanism |
|---|---|
| NFR-REL-001 | The application shall commit the current record before patient/day navigation. |
| NFR-REL-002 | Persistent writes shall retain a backup and use temporary-file replacement. |
| NFR-REL-003 | The application shall offer recovery of a valid unsaved draft at startup. |
| NFR-REL-004 | External file changes shall prevent silent overwrite. |
| NFR-REL-005 | Destructive archive, death, purge, lineage-delete, mass-archive, reload, and forced-overwrite actions shall use confirmation where implemented. |
| NFR-REL-006 | Version migrations affecting task identity shall preserve version-11 backups. |

### 14.2 Performance and responsiveness

| ID | Requirement/current mechanism |
|---|---|
| NFR-PERF-001 | Ordinary field changes shall update memory immediately and defer disk writes through short timers. |
| NFR-PERF-002 | Drive checks shall be separated from autosave and rate-limited to 15 minutes. |
| NFR-PERF-003 | Search shall update interactively over in-memory data. |
| NFR-PERF-004 | Derived task boards and analytics shall be computed on demand from in-memory records. |

The current implementation performs linear scans over patients, days, and text. This is appropriate for a personal ICU census but has no explicit scale target or benchmark.

### 14.3 Usability and accessibility

| ID | Requirement/current mechanism |
|---|---|
| NFR-USE-001 | Common clinical actions shall be reachable by mouse and keyboard. |
| NFR-USE-002 | The main window shall remain usable from a 760x520 minimum and adapt to monitor work area. |
| NFR-USE-003 | Saved windows shall be restored only when a meaningful area remains visible on a monitor. |
| NFR-USE-004 | Compact popup and responsive handoff shall support concurrent EMR work. |
| NFR-USE-005 | Current save, reminder, selected-patient, task-count, EMR, and acuity state shall be visibly indicated. |

The application uses native controls and keyboard focus, but it has no documented screen-reader test, high-contrast test, color-blindness validation, or full keyboard accessibility test.

### 14.4 Security and privacy

| ID | Current characteristic |
|---|---|
| NFR-SEC-001 | Data is stored as readable local/Drive text and readable local backups. |
| NFR-SEC-002 | Access control relies entirely on Windows account, filesystem, and Drive permissions. |
| NFR-SEC-003 | There is no application login, encryption at rest, automatic data expiry, or redaction/export policy. |
| NFR-SEC-004 | The audit log is not tamper-evident and does not identify individual application users. |

Because the stored content may contain clinical and identifying information, deployment policy should explicitly define acceptable storage, synchronization, retention, and device-access controls.

### 14.5 Maintainability and compatibility

- AutoHotkey v2 is explicitly required.
- Shared responsibilities are partially separated into workflow, persistence, and theme modules.
- Persistence uses a version marker and compatibility parsing.
- UI and domain behavior remain concentrated in a large main script, increasing regression risk for cross-cutting changes.
- No tracker-specific automated test files are present in the project inventory.
- The Master Script and tracker depend on exact window titles, registered message names, and expected relative paths.

## 15. Known Current Gaps and Constraints

These are observed implementation facts, not proposed features:

1. **Legacy patient ID recovery:** version-12 data did not store the separate patient ID/MRN. Migration can recover it only when a six-digit value is present in the patient name; otherwise it must be re-entered once and is then retained by version 13.
2. **Legacy day-acuity recovery:** version-12 data did not store day acuity. Migration uses the SOAP Clinical Trend when available, then patient acuity and Stable; manually altered or absent SOAP headers can limit historical accuracy. New version-13 changes are retained exactly.
3. **Help shortcut drift:** in-app help lists two bindings that differ from the registered handlers, as documented in section 9.5.
4. **No merge synchronization:** Drive conflict protection supports choosing one complete copy; it cannot merge concurrent edits.
5. **Plain-text sensitive data:** live, archive, backup, recovery, and audit content are unencrypted.
6. **Single-user/single-process model:** there is no shared server state, record locking, user identity, or permissions model.
7. **Hard-coded SOAP attribution:** the generated template contains a fixed daytime ICU resident name rather than a user/configuration value.
8. **Reminder persistence model:** reminder metadata is embedded in normalized task text; hourly snooze and runtime reminder queue state are not durable across restart.
9. **No formal automated verification:** no permanent tracker-specific unit, integration, migration, or UI test suite is currently maintained.

## 16. Future Feature Placeholders

The following are candidate extension areas and are not current requirements. Each should receive a priority, owner, acceptance criteria, migration impact, and release target before implementation.

### FUT-001: Formal schema validation and migration tooling

- Maintain a schema manifest for every persisted setting and clinical field.
- Add permanent round-trip fixtures for current and historical formats.
- Validate migration backups and rollback before each schema release.
- Refuse unsupported future versions rather than interpreting them as legacy data.

### FUT-002: Configurable clinician and SOAP templates

- Move daytime resident, staff defaults, section names, and template text into settings.
- Support named templates without invalidating existing notes.
- Add template preview and migration behavior.

### FUT-003: Safer data governance

- Optional encryption at rest for live, archive, backup, recovery, and audit files.
- Configurable retention and purge policy.
- Redacted export and backup review tools.
- User-visible storage-location and synchronization status.

### FUT-004: Multi-device merge and conflict review

- Replace whole-file overwrite decisions with record-level comparison.
- Present patient/day/task conflicts with timestamps and source device.
- Preserve both copies before merge.

### FUT-005: Structured settings screen

- Theme, default sort/filter, resize behavior, reminder cadence, autosave intervals, clinician identity, storage paths, and Drive behavior.
- Reset-to-default and export/import settings.
- Distinguish device-local settings from synchronized clinical data.

### FUT-006: Advanced reminders and scheduling

- Persistent snooze/dismiss actions.
- Reminder editor controls instead of suffix-only entry.
- Date-specific, recurring, and escalation rules.
- Dedicated reminder history and acknowledgment state.

### FUT-007: Reporting and export

- Filtered census report.
- Patient timeline and handoff export.
- CSV/JSON/PDF output with explicit privacy controls.
- Date-range analytics and trends instead of current snapshot-only analytics.

### FUT-008: Clinical workflow extensions

- Medication, fluid, nutrition, device, and procedure structures where free text is insufficient.
- Handoff ownership and shift transitions.
- Configurable disposition workflow.
- Attachments or links to external records without embedding protected data unnecessarily.

### FUT-009: Test and release framework

- Unit tests for task parsing/lineage, date parsing, SOAP round-trip mapping, search, and analytics.
- Persistence round-trip and version-migration fixtures.
- Recovery and external-conflict integration tests.
- Automated GUI smoke tests for main, popup, search, diagnostics, board, help, and analytics surfaces.
- Release checklist covering backup restore and Master Script integration.

### FUT-010: Accessibility and UI consistency

- Resolve help/shortcut discrepancies automatically from one shortcut registry.
- Screen-reader labels and tab-order audit.
- High-contrast and color-independent status indicators.
- Configurable font size and density.

## 17. Acceptance Baseline for the Current Product

A current build is functionally acceptable when:

1. It launches under AutoHotkey v2 and loads both active and archive files without error.
2. A patient and today's day can be created, edited, saved, restarted, and reloaded with all fields that are actually serialized intact.
3. Patient/day navigation commits outgoing edits and does not cross-write records.
4. Task carry-forward, completion, reopen, edit, and deletion behave consistently across lineage occurrences.
5. Structured charting refreshes mapped SOAP sections and recognized SOAP edits reverse-sync without changing unrelated sections.
6. Search, filters, task board, diagnostics editor, analytics, popup, themes, and keyboard commands open and act on the correct context.
7. A simulated unsaved draft can be recovered and a simulated external file modification blocks an ordinary save.
8. Main and archive writes produce usable backups and retain version markers.
9. Master Script `Shift+Alt+I`, ICU PE, and sick-patient integrations reach the expected windows.
10. Known gaps in section 15 are either accepted for the release or resolved through a new persistence version and updated specification.
