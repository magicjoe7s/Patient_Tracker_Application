# Reference Application Analysis

## Purpose

This document records the Phase VII read-only analysis of the supplied AutoHotkey ICU Patient
Tracker. The reference application defines established workflow behavior, but it does not define
the architecture of the Python application. The Python project constitution, architecture, data
model, and coding standards remain authoritative for implementation quality and boundaries.

The migration policy is:

- Preserve clinically meaningful rules, outcomes, and safety checks.
- Preserve historical data without inventing clinical identifiers or facts.
- Reimplement behavior through the Python domain, service, repository, and presentation layers.
- Do not translate AutoHotkey functions line by line or reproduce its global-state architecture.
- Resolve documented conflicts explicitly before changing the canonical Python model.

## Reference Baseline

The following files were inspected in place and were not modified or copied into the project.
SHA-256 fingerprints make the analyzed baseline reproducible.

| File | Role | SHA-256 |
|---|---|---|
| `patient_tracker.ahk` | UI shell and most application behavior; 553 functions | `573BC6E93FE1A524320074709EC72A1E306758B9CA36DA37D39631178DC9D17E` |
| `patient_tracker_workflow.ahk` | Selection, day ordering, navigation, and reminder calculations | `8AD157427A1AE25A8DB6AEEE57429D384E7F375A63C0F3B4CF9D631208CC0560` |
| `patient_tracker_persistence.ahk` | Versioned text persistence, backup, recovery, and conflict checks | `F714550342E3064ED2857E7D093AB688D6AA0507BBD2EBF2D611F3519D3C5BA2` |
| `docs/legacy/AutoHotkey-Application-Specification.md` | Historical behavioral specification | `7705D93852FCF8978E086633495136AEB3DC2274E220107DD9ED063CED97E990` |
| `patient_tracker_data.txt` | Version-13 active records and settings | `CAABD0A438CEC2A4E4B277F0AA3C33941D151A719870E0E1D839663A54931BC3` |
| `patient_tracker_archive.txt` | Version-13 non-active records | `743777478A24A2888D77DF9658D744A88CBC67DCA806DB6F95ED697228E1493A` |
| `README.md` | General AutoHotkey-folder inventory | `65256B712BCE531AF150B5AA06BB781008F4348DA75EF1C4B79ECC0F698E9D09` |
| `theme_config.ahk` | Shared Warm-theme tokens and native input coloring | `ADEB1BCCE8CF128A62A9EE1F137D4CD4759755DAA1022E94A8B2057AD0CD59CF` |
| `Master Script - v2.ahk` | Global tracker launcher and ICU PE/sick-tool message receiver | `3E06DB7EEBCA6BA3F92C42DC9B7D5351D26F32A7406D6A0E3EDB525B62AF462D` |

The supplied specification is retained under `docs/legacy` as the stable legacy behavioral
baseline.

The two initially missing dependencies were subsequently supplied and inspected. `theme_config.ahk`
defines the documented Aptos typography and Warm palette. `Master Script - v2.ahk` registers the
`PT_OPEN_ICUPE` and `PT_OPEN_SICK` Windows messages and handles them by opening its existing ICU PE
and sick-patient tools. Its `Shift+Alt+I` launcher specifically searches for an AutoHotkey GUI class
and launches `.ahk` paths, so it cannot discover or toggle the Qt application without a future
compatibility adapter. The reference files remain read-only.

## Sensitive-Data Handling

The two text data files may contain identifying and clinical information. Analysis was limited to
record types, field counts, versions, status counts, and identifier-quality statistics. Patient
names, identifiers, notes, and clinical text must not be copied into source control, tests, logs,
documentation, screenshots, or bug reports.

Before importer development, a synthetic or irreversibly deidentified version-13 fixture is
required. Production import must run against a copied database and copied source files first.

## Structural Data Audit

Both supplied files use the current version-13, UTF-8, pipe-delimited, percent-encoded format.

| File | Patients | Hospital days | Statuses | Invalid/missing six-digit MRNs |
|---|---:|---:|---|---:|
| Active/settings | 4 | 10 | Active: 4 | 4 |
| Archive | 239 | 371 | Home: 114; IMC: 62; Archived: 32; Death: 31 | 211 |
| **Total** | **243** | **381** | | **215** |

All patient rows have 14 fields and all day rows have 18 fields, which is consistent with version
13. No duplicate groups were found among the valid six-digit MRNs. The high missing-MRN count is a
blocking identity issue for the current Python model, which requires MRN as the aggregate and
repository key.

## Reference Behavior Inventory

### Patient and census

- Generated internal identity plus optional six-digit MRN.
- Name, status, acuity, code status, blood type, one-liner, and running problem list.
- Active, Home, IMC, Archived, and Death dispositions.
- Manual active order and Name/Acuity/Status sorts.
- Readmission, archive, mass archive, and archive-only permanent purge.
- Census labels derived from acuity, code, tasks, EMR state, and missing-today state.

### Hospital day and daily charting

- Calendar-date day key with optional display note and chronological ICU ordinal.
- Duplicate calendar dates rejected per patient.
- Treatment, physical examination, devices, assessment, Sandbox, SOAP, tasks, staff, acuity, and
  EMR-upload state.
- New days carry incomplete carry-enabled tasks, devices, and SOAP staff values forward.
- Outgoing context is committed before patient or day navigation.

### Tasks and diagnostics

- To Do, POCUS, Pending Diagnostic, and global Housekeeping surfaces.
- Stable lineage identity across carried day occurrences.
- Forward-only edit, completion, and reopen behavior from the acted-on occurrence.
- Confirmed lineage deletion and pending-diagnostic tombstones.
- Priority, bucket, carry preference, interval reminder, and fixed-time reminder metadata.
- Compact text-entry grammar, including `!`, `!!`, `p:`, `b:`, `r:`, and `nocarry`.
- Task board presents only the newest authoritative occurrence of each lineage.

### SOAP and Sandbox

- One editable, template-initialized SOAP document per day.
- Structured-to-SOAP targeted updates preserve unrelated sections.
- Recognized SOAP sections reverse-synchronize structured values.
- Diagnostic results are retained when the pending checklist changes.
- Device changes maintain associated Ins/Out rows.
- `#INPUT#` tokens support keyboard traversal.
- Sandbox is day-owned free text and can contribute unchecked Markdown tasks during save.

### Navigation and auxiliary surfaces

- Patient sidebar, task sidebar, day timeline, live search, search popup, and command palette.
- Compact always-on-top SOAP/Sandbox patient popup with caret restoration.
- Pending Diagnostics editor, four-pane Task Board, help window, and analytics report.
- Mouse and keyboard access for common operations.

### Reliability

- Delayed autosave and explicit Save Now.
- Temporary-file replacement and previous-copy backups.
- Unsaved-draft recovery snapshot.
- Main/archive separation.
- Modification-time conflict detection for externally replaced files.
- Confirmation for destructive or overwrite operations.
- Audit entries for selected patient, day, task, and reminder actions.

### External behavior

- Clipboard exports for charting and SOAP.
- Copy SOAP marks the day uploaded and minimizes the tracker.
- Optional filesystem synchronization behavior described as Google Drive synchronization.
- Windows-message integration with a separate AutoHotkey master script.

### Verified legacy theme contract

- Aptos font with base, helper, header, and hero sizes of 10, 9, 12, and 18.
- Eggshell shell, cream surfaces, warm charcoal text, white native input surfaces.
- Brick-red primary and hunter-green secondary accents.
- Shared padding and nominal control-height tokens.

These are behavioral/design references, not a requirement to reproduce native AutoHotkey rendering.
The centralized Qt theme manager remains the implementation boundary.

## Current Python Coverage and Gaps

| Area | Current state | Phase VII finding |
|---|---|---|
| Application boundaries | Implemented | Keep. Reference global state must not cross into Python architecture. |
| Patient CRUD/status | Partial | UUID identity, optional MRN, correction, lifecycle confirmations, readmission, bins, sorts, and UI reorder are implemented; mass archive and legacy import remain later work. |
| Patient identity | Implemented | Generated UUID identity and optional unique MRN preserve all characterized legacy records. |
| Hospital days | Implemented | Automatic first day, strict input, chronological ordinals, safe navigation, and task/problem/device/staff carry use stable day context. |
| Patient summary | Implemented | Patient-owned fields have a dedicated editor; species is required for new records and legacy records may import as correctable `Unknown`. |
| Daily charting | Implemented | Day-owned acuity, note, treatment, examination, assessment, clinical summary, and devices remain isolated by stable patient/day UUID context. |
| Problems | Implemented/intentional change | Ordered daily problem occurrences carry unresolved lineages forward; edits, resolve/reopen, and removal preserve earlier history, and SOAP projects the active ordered list. |
| Tasks | Implemented | Structured To Do, POCUS, Pending Diagnostic, and Housekeeping categories preserve compact grammar, reminder tokens, forward-only lineage mutations, diagnostic tombstones, independent filters, and global latest-day board projection. |
| Devices | Implemented | Structured lifecycle, day carry-forward, SOAP instrumentation projection, and loss-preserving Ins/Out rows are implemented. |
| Reminders | Implemented | To Do/POCUS rules use newest occurrences, minute polling, privacy-safe platform alerts, persistent shown/snooze state, and an in-app hourly digest. |
| SOAP | Implemented/intentional change | Full canonical Markdown is stored losslessly; targeted mappings, conservative reverse sync, staff settings/carry, diagnostic retention, device Ins/Out, and input-token traversal are characterized. |
| Sandbox | Implemented/intentional change | Day-owned text is lossless; unchecked checklist extraction requires an idempotent preview and confirmation instead of occurring silently on save. |
| EMR upload state | Implemented | Successful SOAP copy or an explicit user control updates only the selected day's visible marker. |
| Search/filter | Implemented/intentional change | Canonical cross-day fields, fuzzy names, six derived views, five disposition scopes, and four deterministic sorts are implemented inline; the separate legacy popup is deferred to the shared command surface. |
| Task Board/diagnostics | Implemented/intentional change | Four derived panes enforce newest-lineage and disposition rules, canonical mutations refresh all open surfaces, and row activation restores patient/day context. Focused diagnostics use structured task editing rather than destructive raw-checklist reconciliation. |
| Popup/compact layout | Implemented/intentional change | Shared-context SOAP/Sandbox handoff, active-patient navigation, per-context caret memory, compact/full mode, pinning, safe return, and responsive activation are implemented without mirrored clinical state. |
| Commands/shortcuts/help | Implemented/intentional change | One validated registry generates actions, menus, shortcuts, command aliases, palette suggestions, and Help. Patient navigation consistently uses Ctrl+Shift+J/L, and native text-editing shortcuts remain unclaimed. |
| Analytics | Implemented | A deterministic read-only snapshot derives reference census, acuity, ICU-day, newest-lineage pending diagnostic, current problem-term, missing-today, and Needs Attention metrics without persisted totals. |
| Clipboard | Implemented/intentional change | Chart/SOAP plain-text exports use an isolated adapter; minimize-after-copy is a setting and no EMR automation is embedded. |
| Recovery/conflict | Implemented/intentional change | Debounced UUID-context editor drafts recover into unsaved review state with canonical content fingerprints; reviewed SQLite restore uses SHA-256 binding and a pre-restore safety backup. Cloud-folder watching and mtime-based replacement are intentionally excluded. |
| Legacy import | Missing | A strict, report-producing version-13 importer is required. |
| External AHK integration | Reference verified; Python missing | Message names and launcher behavior are known; keep compatibility isolated and optional. |

## Required Decisions

The decisions below were approved for Slice 1 on 2026-07-20.

### Decision 1: patient identity

**Approved:** add an automatically generated immutable UUID as canonical identity and make MRN optional but
unique when present. Retain the legacy internal ID only as import provenance, not as the new primary
key.

Why: this preserves all 243 records without fabricating MRNs, permits legitimate MRN correction,
and keeps duplicate names valid. It requires an intentional amendment to `DataModel.md`, repository
interfaces, foreign keys, services, migrations, and tests.

Rejected default: generating fake six-digit MRNs. A generated value would look clinically real and
misrepresent missing source information.

### Decision 2: vocabulary mapping

**Approved:** map dispositions as follows while retaining user-facing labels:

| Reference | Python meaning |
|---|---|
| Active | Admitted |
| Home | Discharged |
| IMC | Transferred |
| Archived | Archived |
| Death | Deceased |

Extend code-status vocabulary so `DVM Discretion` and `DNR Assist` are not silently collapsed into
one generic value. Preserve unknown source values as reported import errors rather than guessing.

### Decision 3: problem-list ownership

**Approved:** retain day ownership in the Python domain and carry unresolved problems into a
new day with explicit lineage. Present the latest list as the running problem list. This preserves
the workflow while improving historical fidelity and maintaining one canonical owner.

### Decision 4: SOAP representation

**Approved:** preserve a lossless canonical Markdown document alongside recognized structured
sections and mapping metadata. Parsing must be conservative: unrecognized text remains untouched.
The current four-section-only representation is insufficient for lossless import of the reference
template.

### Decision 5: legacy species

**Approved:** import records without source species as explicit `Unknown`. Display that value and
allow later correction. New-patient workflows continue to require species. Never infer species from
names, blood types, or clinical text.

### Decision 6: synchronization scope

**Approved:** treat legacy text files as a one-time import source. Do not maintain bidirectional
SQLite/text synchronization. Keep backup/restore separate from cloud-provider synchronization.

## Import Safety Contract

The eventual importer must:

1. Accept explicit main and archive paths and never edit either source file.
2. Verify supported version and file role before parsing records.
3. Decode fields strictly and report line-numbered validation failures without logging clinical text.
4. Produce a dry-run report with counts, warnings, and proposed mappings.
5. Preserve a source fingerprint and legacy identity for idempotency and provenance.
6. Import into one database transaction and roll back on a rejected record.
7. Detect a repeated import and refuse duplicates unless an explicit supported resume mode exists.
8. Back up the target database before a production import.
9. Reconcile all imported totals and statuses after commit.
10. Require user confirmation between dry run and commit.

## Rule Precedence

When sources disagree, use this order:

1. Project Constitution and explicit user decisions.
2. Current Python architecture and canonical data-model documentation.
3. Reference specification for observable behavior.
4. Characterization tests derived from the AutoHotkey implementation.
5. Legacy data format for import compatibility only.
6. Incidental AutoHotkey implementation details.

Any intentional behavior change must be recorded in the feature's acceptance criteria instead of
being hidden inside implementation code.
