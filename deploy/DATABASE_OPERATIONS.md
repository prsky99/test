# SQLite maintenance

The gateway and public frontend share the configured `GATEWAY_DB`. Do not run
another collector or gateway against an unintended database while investigating
an incident. Confirm the database opened by the listening process; a recovered
file with a different filename does not change an existing connection.

## Safe startup

The gateway reserves both configured listening ports before opening storage or
starting collectors. A port collision exits with an explicit error and releases
all reservations. It does not silently start the frontend on a different port.
Stop the existing gateway gracefully before restarting with the same settings.

On macOS, the command-line entry point checks Python's linked SQLite version.
If it predates the WAL-reset fix and a patched Homebrew SQLite is installed,
the entry point probes it in a child process and re-executes Python with that
library selected. Existing application settings are preserved. This does not
replace Python packages or install software. Other platforms should use a
distribution build containing the upstream WAL-reset fix.

The fix is available in SQLite 3.51.3 and later, and the 3.44.6 and 3.50.7
backports. See [SQLite WAL-reset documentation](https://www.sqlite.org/wal.html#walreset).

## Permission and lock safety

SQLite owns the descriptors for an existing database, WAL, and shared-memory
file. Never open and close these files merely to change permissions: on POSIX,
closing an unrelated database descriptor can release the process's SQLite locks.
The permission helper uses a no-follow metadata operation and retains mode 600.
Only initial creation uses an exclusive raw descriptor, before SQLite connects.
See [SQLite's POSIX lock explanation](https://www.sqlite.org/howtocorrupt.html#posix_advisory_locks_canceled_by_a_separate_thread_doing_close_).

## Preservation and validation

- Use SQLite's online backup API for a live database. Restrict the destination
  directory to mode 700 and backup files to mode 600.
- A raw filesystem snapshot requires all writers to be stopped; preserve the
  database and its matching WAL together. Never delete or mix WAL files to make
  an error disappear, and never replace a database held open by a process.
- Run `PRAGMA quick_check` on a consistent snapshot, then `integrity_check`
  when checking index consistency. Large databases may take several minutes.
- Verify the affected record, schemas, row counts, and application reads before
  considering a recovered copy usable. A successful backup operation alone does
  not prove that the source was healthy.
- Keep damaged originals. Recovery can lose records or constraints; restore to
  a separate file and validate it before a controlled, offline replacement.

References: [safe backup methods](https://www.sqlite.org/howtocorrupt.html#backup_or_restore_while_a_transaction_is_active)
and [SQLite recovery guidance](https://www.sqlite.org/recovery.html).

## Workflow execution snapshots (R-05)

Use the explicit `agent_market.workflow_backup` CLI for an online snapshot and
restoration to a **new** path. It verifies integrity/checksums and preserves a
local encryption key in private storage (environment-managed keys stay outside
the export). Restoration quarantines unfinished/pending outcomes, pauses runtime
controls/schedules, invalidates old deployment/delivery/destination/event/session
and active task-update authorization, and never automatically replays old work.
Do not replace a live database or run the source and restored clone as active
executors. See [the implementation contract](../docs/DURABLE_WORKFLOWS.md).


## v1.10 bounded retention and restored inventory

Use the explicit workflow maintenance CLI in [operations hardening](../docs/WORKFLOW_OPERATIONS_HARDENING.md) after current schema initialization. Preview is read-only and does not recover or poll the execution queue; apply compacts at most twenty old known-terminal runs and preserves replay/unknown evidence. Do not expect immediate SQLite file shrinking or automatic VACUUM. A new-path restore writes `<database>.restored-inventory.json` at 0600 with limited prior IDs/states and reapproval steps; it never reenables old keys or pending deliveries. Latest execution/routing/operations PostgreSQL rehearsal is 27 tables, including budget/reconciliation/manual delivery/retention state. Complete Store/FTS/auth/collector adaptation and production cutover remain unimplemented.
