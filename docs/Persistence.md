# Persistence Operations

## Architecture

The persistence layer stores pure Phase III domain objects in SQLite through separate SQLAlchemy
record classes and explicit mapping functions. Domain modules do not import SQLAlchemy, and public
repository contracts do not expose sessions, queries, rows, or SQL concepts.

`PatientRepository` is the primary aggregate repository. A patient is loaded and saved with every
owned hospital day, problem list, problem, instrumentation record, device, task occurrence,
reminder, SOAP document, and ordered SOAP problem reference. This avoids repositories for internal
tables that cannot exist independently.

Application configuration remains JSON-backed. Transient `ApplicationState`, Qt objects, window
state, dirty state, digest-window state, and runtime notification delivery are not stored in the
clinical database. Reminder schedule, snooze, status, and last successful display are durable.

## Database Location and Configuration

The default files are below `%LOCALAPPDATA%\ICUPatientTracker`:

```text
config.json
patient_tracker.sqlite3
logs/
backups/
recovery.json
recovery.json.bak
```

The configuration file controls:

- `database_path`
- `backup_directory`
- `backup_retention_count` (default `10`)
- `autosave_debounce_seconds` (default `0.7`)
- `autosave_retry_seconds` (default `5.0`)

Database, backup, temporary, WAL, shared-memory, and log files are excluded by `.gitignore`.

## SQLite Settings

Every application-managed connection enables:

- Foreign-key enforcement.
- WAL journal mode.
- Normal synchronous mode.
- A 5-second SQLite busy timeout, in addition to the connection timeout.
- Connection health checks before pooled connection reuse.

The application is designed for one local process. These settings do not add multi-user or merge
support.

## Tables and Relationships

| Table | Ownership |
|---|---|
| `patients` | Aggregate root keyed by an application-generated UUID; optional MRN is unique when present. |
| `hospital_days` | Many per patient; date/day number are unique, and SOAP overnight/faculty attribution is day-owned. |
| `problem_lists` | Exactly one per hospital day. |
| `problems` | Ordered children of one problem list. |
| `instrumentations` | Exactly one per hospital day. |
| `devices` | Ordered current or historical children of instrumentation. |
| `tasks` | Ordered hospital-day occurrences with stable lineage metadata. |
| `reminders` | Zero or one per task. |
| `soap_documents` | Lossless Markdown plus structured mappings and amendment references. |
| `soap_problem_references` | Ordered links from SOAP documents to problems. |
| `alembic_version` | Formal schema revision. |

Foreign keys and delete cascades prevent orphan child records. Permanent patient deletion is
available only as an explicit repository operation; future services must provide authorization and
confirmation appropriate to clinical workflow.

## Transactions and Repositories

Use a unit of work for every persistence operation:

```python
with database.unit_of_work() as unit_of_work:
    unit_of_work.patients.add(patient)
```

The context commits completely on success and rolls back completely on failure. Repositories in one
unit share the same private session. Sessions are always closed when the context exits. Reusing the
same unit in a competing nested transaction is rejected explicitly.

Public failures use persistence exceptions such as `RecordNotFoundError`,
`DuplicateIdentityError`, `ConstraintViolationError`, and `TransactionError`; raw SQLAlchemy
exceptions do not cross the repository boundary.

## Database Initialization and Migrations

Application startup initializes or upgrades the configured database automatically through formal
Alembic revisions. The current revision is `0010_emr_upload_state`.

See [MigrationStrategy.md](MigrationStrategy.md) for commands, revision policy, downgrade limits,
future-schema protection, and the deferred legacy-import boundary.

## Autosave Primitives

`AutosaveController` is a scheduler-independent persistence primitive:

- Dirty changes reset one monotonic debounce deadline.
- Rapid changes coalesce into one save operation.
- `poll()` flushes only when due.
- `save_now()` and `shutdown()` synchronously flush pending work.
- A failed save keeps dirty state, exposes `AutosaveError`, and pauses automatic retries.
- `schedule_retry()` resumes only after an explicit recovery decision.

The controller creates no threads and imports no PySide6 code. The Phase V autosave coordinator connects it to
application mutations, `ApplicationState`, and an event-loop timer. The supplied save callable must
use a unit of work so each autosave is transactional.

## Backup and Restore

Backups use SQLite's online backup API; a live database is never copied with a naive filesystem
copy. A backup is first written to a temporary file, checked with SQLite `quick_check`, checked for
a supported Alembic revision, and only then atomically published.

Create or verify a backup:

```powershell
python -m icu_patient_tracker.persistence.backup create
python -m icu_patient_tracker.persistence.backup verify "C:\path\to\backup.sqlite3"
```

Restore a backup:

```powershell
python -m icu_patient_tracker.persistence.backup restore "C:\path\to\backup.sqlite3"
```

Restore behavior:

1. Verify the candidate without changing active data.
2. Create and verify a timestamped `pre_restore` backup of the active database.
3. Restore the candidate into a temporary database and verify it again.
4. Close active pooled connections and checkpoint WAL data.
5. Atomically replace the active database.

A corrupt or unsupported candidate never replaces the active database. Backup and restore events
are logged without recording SOAP text or other clinical content.

GUI restoration first inspects the candidate and records its SHA-256 content identity. The final
confirmed restore must match that identity both before and after preparing the candidate, so a file
changed after operator review cannot silently replace the active database. The database lifecycle
is reopened after either successful replacement or a post-disposal failure.

The default retention is ten timestamped backups. Oldest ordinary backups are removed after a new
verified backup is published. The candidate and pre-restore snapshot are protected during restore,
even if this temporarily exceeds the configured count.

## Unsaved Editor Recovery

Recovery is device-local and separate from canonical SQLite records. Patient Summary, Daily
Charting, SOAP, and Sandbox editors stage text fields for one patient/day UUID context. After 900 ms
the service writes one versioned JSON snapshot through a temporary file and atomic replacement.
Successful clinical save archives the snapshot as `recovery.json.bak` and removes the active marker.

Each editor entry includes a SHA-256 fingerprint of the canonical values it originally loaded. At
startup, current values are compared by content—not modification time. A matching draft may be
loaded into unsaved editors after confirmation. A mismatch requires a second warning, and even an
approved conflicted draft remains unsaved until the operator explicitly saves it. Missing contexts
and invalid snapshots are retained for manual review rather than interpreted best-effort.

The SQLite database is single-device application storage. Cloud-folder watching, automatic external
replacement, and record-level merging are intentionally not implemented. External databases may
enter only through reviewed restore; legacy records use the separately approved one-time importer.

## Testing

Run all isolated persistence and migration tests:

```powershell
python -m pytest tests/persistence
```

Run all project quality gates:

```powershell
python -m ruff format --check src tests
python -m ruff check .
python -m mypy
python -m pytest
```

Tests use temporary directories and synthetic records only. They do not access developer or
production clinical data.
