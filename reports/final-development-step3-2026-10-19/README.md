# STEP 3 scoped source verification

The selected backend now composes the service, collector, workflow worker,
shared Ledger, storage observation and maintenance through one explicit backend.
PostgreSQL uses private DSN and stable workflow-root files; no implicit SQLite
fallback exists. The shipped image includes the optional native driver.

The migration lifecycle supports independently approved persistent activation
and current-state rollback with credential resealing and replay conservation.
SQLite source retirement commits with FULL durability before target activation.
Every table in the finite reviewed schema is materialized and fenced before
that commit, including previously absent optional domains used by stale raw
constructors. Interrupted target activation retains both stop boundaries until
a fresh independent review completes the same transfer.

Handoff checks all signed remote-task, evaluation-job, machine-event and Stripe
sandbox command histories. Active/unknown effects, changed terminal locators,
invalid signatures and inspection limits block transfer without rewriting state.
Retention keeps unknown effects, protected admissions, financial records and
authority tombstones, and retains research when signed job evidence is invalid.
Restore permanently blocks recovery policy/request and sandbox order authority.

## Actual scoped results

- `tests/test_application_store_migration.py`,
  `tests/test_application_runtime.py`,
  `tests/test_application_control_retention.py`, and
  `tests/test_phase2_restore_quarantine.py`, with `-k 'not actual'`:
  **65 passed, 2 deselected**. The deselected tests require the final canonical
  SQL catalog and are not reported as passes.
- `python -m scripts.rehearse_application_runtime_postgres --provisional-catalog`:
  **54/54 checks passed** on a disposable Unix-socket PostgreSQL cluster using
  the actual private-file connection factory and native psycopg driver.
  [Machine-readable receipt](native-provisional.json).
- The temporary cluster was removed. Operating database writes and external
  provider calls were both zero. No project server was started or restarted.

These are scoped, overlapping checks, not a deduplicated global test total.
The native receipt uses an explicitly provisional catalog built only in the
isolated child. The checked-in canonical catalog was not regenerated because
other source work is continuing. Final frozen-catalog native and integrated
security/browser acceptance remain pending that source freeze.

Representative deployment contention/load, independent operating ownership,
HA topology, operating RPO/RTO and real ingress cutover are external acceptance;
this synthetic cluster does not establish them.
