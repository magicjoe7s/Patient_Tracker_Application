# Database Migration Strategy

## Scope

The Python application uses Alembic as the only mechanism for persistent SQLite schema changes.
The current schema revision is `0010_emr_upload_state`.

This strategy applies to the Python SQLite database. Importing the legacy AutoHotkey version-13
text files is a separate future workflow and is not part of Phase IV.

## Revision Policy

Every schema change requires all of the following in the same change set:

1. A new ordered Alembic revision.
2. Matching SQLAlchemy record changes.
3. Upgrade tests, including representative earlier-revision data when data conversion is involved.
4. Round-trip repository tests for affected domain values.
5. Documentation of the new current revision and operational impact.

Application code must never issue ad hoc `CREATE TABLE` or `ALTER TABLE` statements during normal
startup. A new database and an existing supported database both reach the current schema through
Alembic.

## Startup and Version Safety

Application bootstrap calls `DatabaseManager.initialize()`. Initialization:

1. Inspects the recorded Alembic revision.
2. Rejects a revision not present in the packaged migration history.
3. Applies ordered upgrades through Alembic.
4. Verifies connectivity and SQLite foreign-key enforcement.

An unsupported future revision raises `UnsupportedSchemaVersionError` before any migration runs.
The application must not stamp, overwrite, or silently reinterpret that database.

## Commands

Use the configured database path from the application configuration:

```powershell
python -m icu_patient_tracker.persistence.migration_manager current
python -m icu_patient_tracker.persistence.migration_manager upgrade
python -m icu_patient_tracker.persistence.migration_manager downgrade 0001_initial_domain
```

Downgrade is an explicit maintenance operation. It should be used only when the target revision's
data loss is understood and a verified backup exists. Revision `0002_task_lineage` can downgrade by
dropping the added lineage and ordering columns; this necessarily discards those newer values.

## Current Revision History

| Revision | Purpose |
|---|---|
| `0001_initial_domain` | Creates the Phase III clinical tables and relationships. |
| `0002_task_lineage` | Adds task lineage, occurrence, carry-forward metadata, and explicit task/device ordering. |
| `0003_application_services` | Adds patient/day summaries, task buckets, and durable reminder schedule specifications required by Phase V services. |
| `0004_patient_uuid_identity` | Replaces MRN primary identity with generated patient UUIDs and makes MRN an optional unique secondary identifier. |
| `0005_chronological_day_numbers` | Normalizes existing hospital-day numbers into chronological, contiguous ICU ordinals. |
| `0006_problem_lineage` | Adds problem lineage, source occurrence, and occurrence-number metadata. |
| `0007_reminder_shown_state` | Adds the last successful reminder-display timestamp. |
| `0008_canonical_soap` | Adds lossless SOAP Markdown and day-owned overnight resident/faculty attribution. |
| `0009_day_sandbox` | Adds lossless, day-owned Sandbox Markdown. |
| `0010_emr_upload_state` | Adds the day-owned SOAP-to-EMR handoff marker. |

The `0001 → 0002` upgrade initializes each existing task's lineage from its stable task ID and
preserves all existing clinical rows.

The `0002 -> 0003` upgrade supplies conservative defaults for existing rows (`stable`, `full_code`,
`today`, and `absolute`) while retaining all prior clinical and task data.

The `0003 -> 0004` upgrade generates one UUID for every existing patient and rewrites hospital-day
ownership to that UUID without changing clinical content. Downgrade is rejected if any patient has
no MRN because the older schema cannot represent that state losslessly.

The `0004 -> 0005` data migration temporarily moves day numbers outside their positive range, then
assigns chronological ordinals without violating the per-patient uniqueness constraint. Downgrade
retains the safe chronological order because the former creation order is not stored.

The `0005 -> 0006` upgrade initializes every existing problem as occurrence 1 of a lineage derived
from its existing UUID. No clinical content or ordering is changed. Downgrade drops only the newer
lineage metadata and retains every stored problem occurrence.

The `0006 -> 0007` upgrade adds nullable `last_shown_at` state. Existing schedules and statuses are
unchanged, and existing reminder rows begin with no recorded display.

The `0007 -> 0008` upgrade adds empty, non-null Markdown and staff fields without interpreting
existing clinical text. A pre-Slice-8 SOAP document receives canonical Markdown once when first
opened; non-empty Markdown is never replaced by this upgrade path.

The `0008 -> 0009` upgrade adds an empty, non-null Sandbox text field to every hospital day.
Existing clinical values and SOAP Markdown are unchanged.

The `0009 -> 0010` upgrade adds a non-null `emr_uploaded` flag defaulting to false. It records only
the handoff state for its owning hospital day and does not alter SOAP or charting content.

## Legacy AutoHotkey Data

The legacy version-13 text format remains an external source format. Slice 1 provides a strict,
read-only parser and non-sensitive dry-run report. A future import service will:

- Read legacy files without modifying them.
- Parse into transfer objects rather than SQLAlchemy rows.
- Validate and report all rejected or ambiguous records.
- Construct current domain aggregates.
- Persist accepted aggregates through the unit of work.
- Commit the import atomically only after validation succeeds.
- Preserve an import report and a verified pre-import backup.

No import tables or production import commit are included in Slice 1.
