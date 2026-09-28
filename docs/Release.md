# Windows Release Process

## Supported artifact

The release pipeline produces a Windows x64 one-directory bundle. The directory is zipped for distribution so
Qt plugins, SQLAlchemy, SQLite, timezone data, themes, and Alembic migration files remain explicit
and inspectable. The application continues to store configuration, logs, backups, recovery state,
and the clinical database under the configured device-local paths; release artifacts never contain
clinical data.

Run the complete release pipeline from the repository root:

```powershell
.\scripts\build_release.ps1
```

The script installs the declared release extras, runs Ruff, strict mypy, and pytest, creates the
PyInstaller bundle, runs the packaged executable against
a unique disposable smoke directory, creates and verifies a ZIP with bounded retries for transient
Windows file locks, and writes its SHA-256 identity.

For a packaging-only iteration after the full checks have already passed:

```powershell
.\scripts\build_release.ps1 -SkipTests
```

Generated files are intentionally ignored by Git:

- `dist/ICU Patient Tracker/` — unpacked application;
- `dist/icu-patient-tracker-<version>-windows-x64.zip` — distributable archive;
- `dist/SHA256SUMS.txt` — archive identity;
- `build/` — disposable PyInstaller analysis and smoke-test work.

The versioned Windows ZIP and its matching `SHA256SUMS.txt` are the canonical distribution
artifacts. Development builds should not be distributed from alternate `dist-*` directories.

## Packaged smoke test

The executable accepts one maintenance-only command that never uses normal application data:

```powershell
& ".\dist\ICU Patient Tracker\ICU Patient Tracker.exe" `
  --smoke-test "$env:TEMP\icu-patient-tracker-release-check"
```

Use a new directory each time. The smoke test refuses prior artifacts, creates an isolated
configuration and SQLite database, applies every migration, verifies foreign keys, and performs a
graceful shutdown. On failure it writes `smoke-error.txt` in that disposable directory without
including clinical content.

## Clean-machine acceptance

Before distributing a release:

1. Copy the ZIP and `SHA256SUMS.txt` to a clean Windows x64 virtual machine.
2. Recalculate SHA-256 and compare it with the manifest.
3. Extract the entire directory; do not copy only the executable.
4. Run the packaged smoke test with a new temporary directory.
5. Launch `ICU Patient Tracker.exe` normally.
6. Verify dark/light themes, create a synthetic patient and hospital day, restart, create a backup,
   and restore that backup.
7. Confirm no AutoHotkey, Python, development repository, or network connection is required.
8. Remove the synthetic test data before approving the artifact.

## Optional integration decisions

| Candidate | Slice 18 decision | Reason |
|---|---|---|
| Master Script messages | Deferred adapter | Requires an approved Windows-message bridge and a working-copy launcher change. Reference files remain untouched. |
| Cloud-folder monitoring | Deferred | The application database is not a cloud synchronization artifact; conflict semantics need a separate design. |
| Global shortcuts | Implemented Windows adapter | `Shift+Alt+I` toggles the resident application, `Alt+Shift+T` toggles Task Board, and `Alt+Shift+R` opens diagnostic-result capture. Registration is best-effort and collisions are logged without blocking startup. |
| Tray behavior | Implemented | One shared tray icon owns Show/Hide, Task Board, main-window pinning, validated Exit, and privacy-safe reminder notifications. |
| Application icon | Implemented | The executable, Qt windows, taskbar, and system tray use the packaged multi-resolution icon. |
| Installer | Deferred | The verified ZIP remains the supported artifact until installation-location and upgrade behavior are approved. |
| Code signing | Deferred | Signing requires an owned certificate and protected release credentials. |
| Updates | Manual verified replacement | Automatic updates require a trusted distribution endpoint and rollback policy. |

Every deferred integration must remain an adapter that can be disabled without affecting clinical
workflows or storage.
