# Storage, recovery and load rehearsal

2026-10-18 · v1.23 isolated source implementation; no operating exercise or SLA.

The next batch extends reproducible isolated scenarios. It does not rebuild the
existing maintenance, backup, restoration or observation tools.

## Existing baseline to reuse

- `workflow_maintenance.py` already provides read-only preview and explicit idle
  batches of at most 20 runs, 14-day detailed-body compaction and 90-day event
  pruning. It preserves unknown outcomes, invalid proof, pending deliveries,
  run/idempotency IDs and replay tombstones. It does not automatically VACUUM.
- `workflow_backup.py` already provides online snapshots, checksums, private file
  permissions, new-path-only restore, paused runtime controls and quarantine.
  The private restored inventory and reapproval instructions already include
  SDK 1.2/1.3, public publication and independent automation state.
- `workflow_storage.py` already observes bounded read-only file/WAL/page and
  queue information. Missing/partial coverage is explicit. It does not measure
  contention or establish an operating SLA.
- Existing isolated regressions already cover unknown/delivery boundaries,
  restore revocation, retention holds, selected SIGKILL cases and 32 execution
  state tables in the PostgreSQL rehearsal. This does not implement the full
  Store/catalog/FTS/auth/collector/ledger adapter or a production migration.

## Implemented coherent unit

1. Build an explicit isolated scenario runner with bounded fixture sizes and a
   fixed seed. Populate completed, active, unknown, tampered and retained runs
   alongside current SDK/publication/automation authority and replay records.
   Use fresh temporary paths and synthetic inputs. Never default to the user
   database or start its collector/scheduler.
2. Reuse preview, then an explicitly requested idle batch. Verify semantic
   invariants before/after compaction: unknown/invalid evidence remains held,
   active work prevents maintenance, retained proofs remain signed, and lost
   bodies cannot become reusable callable or publication evidence.
3. Snapshot, restore to a new path and inspect the existing private inventory.
   Verify every applicable authority stays inactive and unresolved work stays
   unknown. Reapproval remains a fresh purpose-specific action; do not turn the
   inventory into bulk reactivation or resurrect old keys/grants.
4. Exercise bounded concurrent fixture SQL readers/writers and capture measured
   duration, busy/refusal counts, queue outcomes and file/WAL growth. If physical
   compaction is rehearsed, use only a disposable copied/restored database with
   controls paused. Preserve before/after integrity and replay checks. Clearly
   identify the environment, fixture scale and measurement limits.
5. Complete the runner, safe CLI/report outputs, failure cleanup, invariant and
   dynamic security tests, documentation and final source-frozen regression as
   one batch. Do not request a server restart for each internal layer.

The implementation is `agent_market.workflow_storage_rehearsal` and the explicit
CLI shim `scripts/rehearse_workflow_storage.py`. The fixture helper composes
current production contracts against a fresh synthetic Store without the
operating Runtime initializer, environment key loader, scheduler or worker
launcher. Mock MCP packets terminate in memory; synthetic signatures and approvals
are not provider-quality or expert evidence. The fixed seed controls scenario
layout; cryptographic IDs, timestamps and timings are intentionally not identical.

## Execution and output contract

Run only in a separate environment without an `AGENT_UPDATES_KEY` variable:

```sh
.venv/bin/python -B scripts/rehearse_workflow_storage.py --run --iterations 50 --readers 4 --writers 4 --report /absolute/existing-directory/new-report.json
```

`--run` is required. Iterations are 1–50, readers/writers each 1–4; defaults are
12/2/2. There is no database, server, input, seed or workspace argument. Each run
uses a new private temporary directory and a synthetic key. Presence of the
operating key variable causes a fixed refusal before workspace creation; its
value is not inspected or copied. Import/help/no-argument errors do not initialize
Store, create a workspace or recover queues.

The optional report must be a new file beneath existing nonsymlink directories.
It is opened exclusively with mode0600 and no overwrite. Errors do not echo paths,
arguments, keys, private references or stack traces. JSON stdout contains bounded
aggregate metrics and explicit invariants; failed or missing/nonboolean checks
cannot become a passing result. Normal and handled-failure cleanup is verified;
abrupt process termination is not a promise of automatic directory deletion.

## Scenarios and limits

- Completed runs and actual synthetic SDK1.2/1.3/publication/automation issuance
  and withdrawal are created through existing contracts. Active, bad-signature,
  pending-delivery and dispatched/expired unknown scenarios are explicit fixture
  fault injection. They never invoke an external recipient.
- Actual DurableRuns claim, second-owner refusal, stale fencing and dispatched
  recovery-to-unknown are checked separately from SQL contention. The load metric
  is not workflow-worker throughput or an end-to-end provider benchmark.
- A synthetic clock91days ahead exercises existing14/90day policies without
  forging historical provider proof. Active work blocks maintenance. After only
  the fixture's active scenario is settled, one body batch(limit20) and one
  metadata batch(limit1) execute. The latter prunes the earliest literal proof's
  authority/events while preserving valid public/SDK status capabilities for the
  immediate pre-restore check. Remaining eligible metadata is reported; this is
  bounded partial cleanup, not deletion of all aged records or a promise that
  expired status evidence stays readable indefinitely.
- Original attempt/idempotency/replay and real withdrawal tombstones survive.
  Unknown, invalid signatures and pending-delivery bodies remain held. Archived
  details cannot supply new publication, SDK execution preparation or comparison
  evidence through the actual loaders.
- Two new queued/prepared tasks are added after maintenance for the backup.
  Online backup and new-path restore reuse the existing private inventory.
  Revisions advance, controls/grants stay inactive, old previously valid read
  capabilities are refused, unfinished work/deliveries stay unknown, and no
  automatic reapproval or replay occurs. Restore inspection uses a read-only
  connection and performs no recovery or launch.
- Concurrent connections make bounded SQL counter updates and consistent
  snapshots. A separately held writer must produce a real busy refusal. Metrics
  include attempts, commits, busy/skipped work, measured attempt latencies,
  elapsed time, queue counts and DB/WAL allocation. File sizes are observations,
  not an atomic whole-system measurement.
- Physical checkpoint/VACUUM runs only on the disposable restored copy with all
  controls paused. Integrity and selected critical workflow/replay state are
  checked before/after. It never runs on the fixture source or an operating DB.
- Limits are cooperative: SQL busy20ms, load5seconds, existing backup/restore
  progress30seconds per copy and physical-compaction progress5seconds. There is
  no global hard deadline or guarantee against an operating-system stall.

No web mutation route, operating migration, new operating table or background
job is installed. The prior server-imported source and public/SDK assets are
preserved. These standalone tools require no additional server restart.

Final measured results, source hashes, initial findings and current affected
security/API/Chromium regressions are in the
[verification report](../reports/advancement-storage-rehearsal-2026-10-18/README.md).
Prior full-suite totals are historical evidence and are not added to this run.

Actual operating maintenance, fault injection, data retention deletion and
production cutover remain separately reviewed actions. Full PostgreSQL adapters,
cutover/rollback and HA need broader implementation and evidence after this
limited rehearsal. The next independent source unit is the
[explicit storage adapter foundation](POSTGRES_STORE_ADAPTER_PLAN.md). Actual
human quality evaluation and product provider integration remain independent
conditional tracks.
