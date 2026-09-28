# Cross-device synchronization

## Current implementation

The supported production synchronization path is the desktop application's Supabase adapter. Each
Windows computer retains its own SQLite database under `%LOCALAPPDATA%\ICUPatientTracker`; devices
exchange versioned patient snapshots through authenticated Supabase RPC calls. The SQLite file is
never synchronized through Google Drive, OneDrive, Dropbox, or a network share.

The implementation includes:

- local schema revisions `0013_sync_foundation` and `0014_clinical_sync`;
- stable device and workspace identity;
- a durable transactional outbox;
- immutable operation IDs for safe retries;
- ordered pull cursors and deletion tombstones;
- Windows Credential Manager storage for refresh tokens;
- background Qt network work with GUI-thread reconciliation;
- explicit patient-level conflict review; and
- offline-first startup and editing.

See [Supabase setup](SupabaseSetup.md) for pairing instructions and deployed-schema verification.

## Data flow

```text
local save
  -> patient snapshot and outbox operation commit together
  -> background worker pushes queued operations
  -> Supabase validates workspace, device, identity, and base version
  -> client pulls ordered changes after its saved cursor
  -> GUI thread saves pending edits, applies remote changes, and refreshes views
```

A failed request leaves local work queued. A response is accepted only when operation identities,
change ordering, and cursor progression match the synchronization contract.

## Conflict policy

Concurrent changes to the same patient never use silent last-write-wins behavior. The server keeps
the accepted version, while the losing local operation and server payload are retained in local
conflict history. The user must choose the complete local or server patient version.

Automatic field-level merging is intentionally unsupported because narrative clinical data cannot
be safely combined without proving that edits are independent.

## Security boundary

- Every request uses HTTPS.
- Supabase authentication establishes the user session.
- Row-level security and RPC checks enforce account, workspace, and device authorization.
- The desktop application contains only public project routing information.
- Passwords are never written to configuration, logs, or the clinical database.
- Refresh tokens are stored in Windows Credential Manager.
- Routine errors never include clinical payloads, credentials, or raw server response bodies.

Deployment must still comply with the hospital's privacy, security, retention, backup, and vendor
approval policies.

## Local versus synchronized data

Synchronized:

- versioned patient snapshots and deletion state;
- operation and change identities needed for conflict-safe replication.

Device-local:

- SQLite cache and WAL files;
- configuration and logs;
- recovery snapshots and verified backups;
- refresh tokens and device pairing state.

Backup/restore remains separate from synchronization. Restoring a database or rolling back the
server may require deliberate cursor or pairing repair.

## Non-goals

- Synchronizing the SQLite file itself.
- Giving the desktop client administrator or service-role credentials.
- Silent conflict resolution.
- Synchronizing device-local recovery snapshots.
- Supporting the retired synthetic HTTP or standalone FastAPI/PostgreSQL rehearsal servers.
