# Legacy Interface Fidelity

## Baseline

The AutoHotkey files and the screenshots captured on July 20, 2026 are the approved visual and
workflow baseline until a newer reference set is supplied. Reference files and screenshots remain
read-only inputs; the Python application does not execute or modify them.

## Implemented composition

- Compact Patients/Tasks navigation at the top of the census sidebar.
- Patients and selected-day Tasks now switch in place within the left sidebar.
- Grouped Actions, Filters, and Status regions.
- Live Active, Home, IMC, and visible-census counts.
- Compact Home, IMC, Active, Death, and Menu disposition controls.
- Patient Summary remains visible above the selected hospital-day workspace.
- Patient Summary includes Add ID, Task Board, Save Now, Copy MRN, One Liner, a Canine/Feline
  selector, and an editable running problem list. Imported `Unknown` species remains available until
  the user corrects it.
- Compact previous/next day controls and legacy-oriented Charting and SOAP tab labels.
- Charting gives the reference treatment, examination, and devices/lines fields the full workspace;
  AM Charting presents Pertinent Exam Findings, Diagnostic Summary, Treatment Changes, Devices,
  and Assessment. Devices are not duplicated in a second tab, and PM narrative remains SOAP-owned.
- SOAP initializes with the supplied ICU `#INPUT#` template when the selected day has no document.
- The popup uses the compact Main, S, SB, Min, previous, next, and pin control vocabulary. Its
  collapsed form is a small draggable strip; non-editing surfaces can drag the window.
- Qt text fields retain native text and input-method handling. AutoHotkey expansions should send
  literal text (for example, AutoHotkey v2 `SendText`) or paste clipboard text; simulated modifier
  keystrokes can collide with application shortcuts and produce missing or altered characters.
- Find Patient opens a dedicated keyboard-first live-search tool window.
- The bottom Menu button opens the registry-generated tracker menu; the modern menu bar and toolbar
  remain implemented but start hidden.
- Existing Python Problems, Tasks, Devices, backup, recovery, and safety behavior remains
  accessible rather than being removed for visual similarity.

## Remaining comparison work after the historical-reference pass

- Review final light/dark colors, spacing, and font metrics on a real Windows display.
- Reconcile exact task counters, table columns, and row-checkbox appearance with the updated
  reference set.
- Compare the command/help wording and any new dialogs against the updated reference set.
- Replace historical assumptions when the newer AutoHotkey source and screenshots arrive.

Pixel dimensions are not frozen because Windows scaling and the forthcoming reference update may
change them. Workflow position, terminology, keyboard access, and information hierarchy are the
primary fidelity requirements.
