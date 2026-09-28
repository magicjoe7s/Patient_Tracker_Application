# ICU Patient Tracker

ICU Patient Tracker is a desktop application for veterinary ICU census management,
hospital-day charting, clinical tasks, SOAP notes, devices, reminders, search, analytics, and
optional synchronization between approved computers.

The supported application is the Python/PySide6 desktop release. Historical AutoHotkey material is
retained only as a migration and interface reference under [`docs/legacy`](docs/legacy/).

## Run the Windows application

For normal use, extract the complete release ZIP and run `ICU Patient Tracker.exe` from the
extracted `ICU Patient Tracker` directory. Do not copy the executable away from its `_internal`
directory.

Inside a development checkout, [Open ICU Patient Tracker.cmd](Open%20ICU%20Patient%20Tracker.cmd)
launches the current unpacked build from `dist/ICU Patient Tracker`.

Closing the main window hides the resident application. Use **Exit** from the system-tray menu for
a validated shutdown.

### Global shortcuts

| Shortcut | Action |
|---|---|
| `Shift+Alt+I` | Show or hide the application |
| `Alt+Shift+T` | Toggle the Task Board |
| `Alt+Shift+R` | Capture a diagnostic result for the selected patient day |

The in-app **Menu > Help / Shortcuts** window is the authoritative shortcut and command reference.

## Storage and safety

Application data is device-local under `%LOCALAPPDATA%\ICUPatientTracker` by default. This includes
the SQLite database, configuration, logs, backups, recovery data, and sync connection settings.
The current database revision is `0014_clinical_sync`.
On macOS, the corresponding location is `~/Library/Application Support/ICUPatientTracker`.

- Do not place the live SQLite database in a cloud-synchronized folder.
- Use **File > Create Backup** and **File > Restore Backup** for verified database protection.
- Unsaved editor text is captured in a device-local recovery snapshot.
- Release archives contain no clinical data.

## Synchronization

The current production synchronization path uses Supabase. Local work remains available offline;
saved changes are queued and synchronized in the background after a computer is paired. Conflicting
patient versions require an explicit local-or-server choice and are never silently merged.

See [Supabase setup](docs/SupabaseSetup.md) for device pairing and operating guidance and
[Sync architecture](docs/SyncArchitecture.md) for the security and data-flow design.

## Develop locally

Requirements: Windows and Python 3.12 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m icu_patient_tracker.main
```

Run the quality checks with:

```powershell
python -m ruff check src tests
python -m mypy src/icu_patient_tracker
python -m pytest -q
```

## Build the Windows release

```powershell
.\scripts\build_release.ps1
```

The release pipeline runs linting, strict type checking, tests, PyInstaller packaging, a disposable
packaged smoke test, ZIP creation, and SHA-256 generation. Its canonical user artifact is:

```text
dist/icu-patient-tracker-<version>-windows-x64.zip
```

Use `-SkipTests` only for packaging iteration after the same source state has already passed the
full checks. See [Windows release process](docs/Release.md) for clean-machine acceptance.

## Build the macOS release

The macOS application must be built on macOS. On an Apple Silicon Mac with Python 3.12 or newer:

```bash
bash scripts/build_macos.sh
```

This produces a native `.dmg`; signing and notarization require an Apple Developer identity. A
manual GitHub Actions workflow can also create an unsigned Apple Silicon test build. See the
[macOS release process](docs/macOSRelease.md) for compatibility, signing, and acceptance details.

Version tags matching `pyproject.toml` trigger the combined GitHub release workflow. It publishes
the verified Windows ZIP and Apple Silicon DMG together on the repository's Releases page.

## Project map

| Path | Purpose |
|---|---|
| `src/icu_patient_tracker/domain` | Clinical domain model and validation |
| `src/icu_patient_tracker/services` | Application workflows |
| `src/icu_patient_tracker/persistence` | SQLite repositories, migrations, backup, and recovery |
| `src/icu_patient_tracker/ui`, `dialogs`, `widgets` | PySide6 desktop presentation |
| `src/icu_patient_tracker/sync` | Production Supabase transport, authentication, and contracts |
| `tests` | Domain, persistence, service, sync, release, and UI verification |
| `deployment/supabase` | Supabase schema and verification scripts |
| `assets/design` | Non-runtime design masters, including the application-icon source |
| `docs` | Current architecture, operations, migration, and design documentation |
| `docs/legacy` | Historical AutoHotkey references and screenshots |

## Documentation

- [Architecture](docs/Architecture.md)
- [Data model](docs/DataModel.md)
- [Persistence](docs/Persistence.md)
- [Migration strategy](docs/MigrationStrategy.md)
- [Legacy import](docs/LegacyImport.md)
- [Supabase setup](docs/SupabaseSetup.md)
- [Sync architecture](docs/SyncArchitecture.md)
- [Release process](docs/Release.md)
- [UI style guide](docs/UIStyleGuide.md)

Historical documents describe the pre-Python application and are not operating instructions for
the current release.
