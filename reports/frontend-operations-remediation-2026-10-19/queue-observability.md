# Queue progress and operational recording remediation

Implemented source changes only. The user-managed service was not started, stopped, restarted, or probed, and the operational database was not opened for writes, rebuilt, or checkpointed. Existing unrelated working-tree changes were preserved.

## Vector queue

`agent_market/legacy_vector_index.py` now excludes inactive, deleted, retired, quarantined, and stale-generation heads before applying the claim candidate limit. It terminalizes a bounded set of obsolete heads and scans at most fifty current candidates to bypass stale source/corpus/descriptor bindings without starving later eligible work. The returned claim count remains bounded by the caller's limit. Queue-order and head-lookup indexes support this path; they are installed only when normal store initialization runs after deployment.

The fix retains model pinning, resource snapshots, generation checks, source/corpus hashes, leases, fence tokens, provenance verification, exact outbox acknowledgment, and commit-uncertainty behavior. A stale caller snapshot does not retire a current otherwise-eligible job. Ineligible queue intent is never promoted into verified vector provenance.

New regressions cover inactive, deleted, quarantine, retired, stale generation, each of three stale binding hashes, more obsolete rows than the cleanup bound, and stale caller snapshots. The original publication/fencing/rollback/uncertainty suites also pass. The older pre-remediation reproduction artifact remains a record of the original failure; its assertion that the pipeline stays idle is intentionally no longer true after this fix.

## Buffered operational metadata

`agent_market/observability.py` now retains a bounded FIFO of sanitized, idempotent post-start metadata actions when a short independent write cannot finish. It buffers selection/dispatch/result/completion metadata, never provider calls, workflow execution, user task input, or message payloads. Starts remain best effort so a failed start cannot create an orphan observation later without a usable identity.

- Capacity: 256 metadata actions; maximum age: 60 seconds.
- Flush bound: 32 actions and a 0.1-second loop budget, with the existing per-write lock timeout.
- No retry thread is created. Existing journal activity, the existing five-second workflow scheduler tick, the scheduler fallback, and the authenticated admin snapshot trigger bounded drains.
- Shutdown attempts a final drain, closes recording, and counts/discards remaining buffered metadata. No callback can retry business execution.
- Observed dispatch/completion timestamps are captured when the event occurs, not when its buffered write is flushed.
- FIFO recovery and idempotent SQL preserve `unknown` after a dispatched timeout and retain late results as metadata. Even expired dispatch metadata cannot make a known dispatched timeout look undispatched.
- Journal initialization checks for an existing transaction before schema initialization, preventing an implicit commit of a caller's business transaction. Existing independent-writer and native transaction boundaries remain intact.

## Admin API

`GET /admin/api/observations` remains authenticated superadmin-only and `Cache-Control: no-store`. It flushes before opening its read snapshot and adds the following `recording` fields:

`process_local`, `enabled`, `closed`, `complete`, `pending_writes`, `dropped_writes`, `write_failures`, `flushed_writes`, `oldest_pending_seconds`.

These counters describe this process's instrumented metadata writer. They reset with a new process and do not retrospectively count historical omissions or other workers. Overall `coverage_complete` stays false because uninstrumented paths, retention pruning, and historical outages remain outside this journal's knowledge. A pending or dropped action keeps the process recording status incomplete; later recovery does not hide already-dropped metadata. A database-only snapshot without a live journal reports unavailable process counters explicitly.

## Validation

Final isolated runs:

1. Recovery, vector progress, all native vector lifecycle/fencing/pipeline/store-edge tests, and task-update security: **189 passed** in 26.44 seconds.
2. Source coverage, SQLite POSIX lock safety, and operational observability: **27 passed, 1 deselected** in 6.73 seconds.
3. Admin trace dialog browser regressions: **2 passed** in 6.98 seconds. The first sandboxed Chromium launch could not register its macOS Mach port; the same isolated tests passed after automatic approval allowed an external-sandbox run. All browser requests were routed to an isolated test app, without an HTTP listener or production access.
4. `compileall` for the changed implementation and new tests passed.

The one initially deselected existing test was `test_notification_sender_records_acceptance_without_contact_or_permission_data`. Its fixture was subsequently updated to record real isolated registry execution evidence, and the test passed unchanged (1 passed in 1.82 seconds). Purpose/evidence verification was not weakened. Earlier selective results are transitional; the final integrated suite includes this test.

Security checks for this scope include parameterized SQL inspection, stale-generation/provenance/fence regressions, no-commit and actual SQLite writer-contention tests, bounded memory/expiry/drain tests, late-result uncertainty tests, authenticated admin API/filter/no-store/privacy tests, and isolated browser tests. A later focused Bandit run used temporary tooling without changing project dependencies; its six medium B608 findings and manual triage are documented in `secure-coding-review.md`. This was not a complete repository security/dependency audit or a live production security assessment.

## Activation and remaining limits

These changes require the user to restart their existing Python service to load the updated code. No live queue drain or deployment was performed. After an authorized restart, confirm fresh eligible claims and indexed provenance, oldest eligible pending age, and process recording counters. The in-memory metadata retry buffer is best effort, can lose pending data on abrupt process termination or after its bounded expiry, and does not claim durable delivery or recipient receipt.
