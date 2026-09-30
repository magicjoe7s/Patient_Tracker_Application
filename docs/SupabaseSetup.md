# Automatic sync with Supabase

The configured project is `vykqrhuqohmpxstudtto`. The application includes its
public URL, publishable key, workspace ID and the four registered device IDs.
These are public routing identifiers, not privileged database credentials.

## Connect each computer once

1. Use the updated app on the laptop first. Click **Sync: Set up** at the bottom.
2. Select **Laptop**, enter the tracker Auth email/password you created, and click
   **Connect and remember login**. This starts uploading the local patient records.
3. Wait for **Sync: Synced** before setting up the other computers.
4. On the work computer, desktop, and ER computer, install the same updated app, choose the
   matching device name and sign in with the same tracker account.

You do not need to configure SQL or paste Supabase keys on each computer.
Use a separate local app database on each machine. Do not copy the laptop's paired
SQLite database, sync connection file or credential store to another machine.
Starting with an empty database on the other computers lets sync download the
laptop's records. Existing independent records are preserved; matching patient
IDs with different contents may require conflict review. Different IDs are not
silently merged based on name or MRN.

The tracker login is separate from the Supabase dashboard login. Windows
Credential Manager stores a refresh token on each computer; the app does not save
the password in configuration, logs or its database. Access tokens refresh in the
background. **Forget login on this computer** removes its local saved session.

## Everyday behavior

The app opens from local SQLite without waiting for a network connection. After
saving, it schedules a background sync after 1.5 seconds; it also checks for
remote changes every 15 seconds while running, including when minimized to tray.
Timing depends on connectivity and pending local edits. **Sync now** requests an
immediate check. **Pause syncing** keeps edits local until resumed.

Changes and deletions remain queued offline and survive restart. Only changed
patients are uploaded, with their complete patient/day/notes/tasks/SOAP graph.
An immutable operation ID makes a lost response safe to retry. Network requests
run on a worker thread; SQLite reconciliation and view refresh run on the GUI
thread after pending edits have saved.

If two devices change the same patient before syncing, neither version silently
wins. Click the sync status and **Review conflicts** to compare readable versions.
Choose the complete local or server version; this is patient-level conflict
resolution, not automatic field merging. Both versions are retained in local
conflict history. Further edits can cause another review.

A patient snapshot above approximately 900 KB is kept locally and requires
attention rather than being partially uploaded. Unknown formats and invalid
server responses stop reconciliation without advancing the download cursor.
Sync is separate from the existing local backup system. A database restore or
server rollback may require pairing/cursor repair; automatic re-pairing is not
implemented.

## Deployed migrations and verification (2026-09-07)

- `001_sync.sql`: private RLS tables, atomic version-checked push, idempotent
  receipts, ordered paginated pull, membership and device authorization.
- `002_authorize_owner.sql`: the owner and original three devices were authorized with
  explicit user approval. Authenticated users can execute RPCs only; functions
  still check the registered account/device. Anonymous access remains revoked.
- `authorize_er_device.sql`: adds the separately identified ER computer without
  changing or revoking the original three device registrations.
- `003_clinical_sync.sql`: adds the versioned patient snapshot type while preserving
  those access restrictions. Applied successfully to the live project.
- `verify_clinical_sync.sql`: passed in live PostgreSQL using fabricated records
  inside a rolled-back transaction. Tests three device identities, retries,
  stale-write conflicts, batch rollback, deletion, pagination and access denial.

Local tests additionally exercise complete domain snapshots, separate SQLite
files for multiple devices, offline edits, lost responses, conflict resolution,
deletions, credential refresh and background-thread callbacks.
These tests do not claim three physical computers or the owner's authenticated
HTTPS login have been tested. The final live sign-in requires the owner to enter
the tracker password in the app. No actual patient data was uploaded during the
SQL verification. No paid infrastructure was added.
