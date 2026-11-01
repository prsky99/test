# Read-only workflow storage observations

2026-10-18 · `workflow-storage-observation-v1`.

`python -m agent_market.workflow_storage --db <existing-database>` observes an
existing SQLite database through a short separate `mode=ro` connection with
`query_only=ON`. The administrator endpoint is
`GET /admin/api/workflows/storage`, restricted to a current highest administrator
and returned with `Cache-Control: no-store`. There is no mutation endpoint.

The response includes database/WAL/shared-memory file sizes, SQLite page size,
allocated/free page bytes and bounded run/outbox/manual-delivery state counts.
Unknown execution outcomes are counted separately from terminal status. Raw run
IDs, inputs, private filesystem names and underlying exception text are omitted.
Stored unrecognized status labels are aggregated as `other`, not displayed.

One SQLite read snapshot supplies available queue counts. Filesystem sizes are a
separate observation and are explicitly nontransactional. A 50 ms lock wait and
250 ms progress budget bound ordinary database work; OS scheduling and filesystem
operations are not a hard real-time guarantee. Interrupted, missing or busy
sections are marked unavailable instead of reported as fabricated zero counts.
This does not measure lock contention, historical growth, application latency or
complete telemetry coverage. Physical bytes can exceed currently allocated pages
because WAL and reusable pages are reported separately.

Inspection never initializes a Store, schema, key or execution runtime, recovers a
queue, changes application records, checkpoints/truncates WAL, runs VACUUM or
applies retention. Ordinary SQLite WAL reader-lock/shared-memory coordination can
still occur; `mode=ro` is not an assertion that no transient shared-memory bytes
are touched. No `immutable=1` shortcut is used to hide committed WAL data.

Maintenance remains the separate explicit idle bounded workflow-retention tool.
Observation does not approve cleanup, compaction, PostgreSQL cutover or HA.
CLI exit status is 2 if the database cannot be observed; partial sections remain
visible in the JSON coverage declaration.
