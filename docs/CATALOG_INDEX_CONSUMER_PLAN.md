# Fenced index artifacts and catalog shadow — delivered private scope

2026-10-18 · v1.27 private source/isolated verification complete; no operating rollout.

The adapter, bounded catalog reader, strict atomic writer and revision-bound
index metadata are completed units. Reuse their contracts; do not replace them
with another queue, recompute legacy hashes during reads or label a metadata hash
an implemented search index.

Implemented as actual bounded ASCII lexical bodies/postings plus pure aggregate
supplied-snapshot comparison. Legacy FTS/BM25/vector/search parity is not established.
[Contract](CATALOG_INDEX_ARTIFACTS.md) ·
[verification](../reports/advancement-catalog-index-2026-10-18/README.md).

## Delivered coherent private implementation unit

1. Define bounded versioned corpus/artifact inputs and exact model/schema identity.
   Preserve private bindings outside public/search payloads. Specify text/tool
   inclusion, normalization, language, dimensions, numeric bounds and artifact
   digests. Keep provider/model computation outside the database transaction.
2. Add a trusted materialization path that validates the actual artifact and
   publishes it together with the current-head/job acknowledgement under the
   existing revision/model/token/fence boundary. A standalone file or vector
   written before an unchecked acknowledgement is not an atomic index publish.
   Interrupted or superseded work must not replace newer artifacts or delete
   newer jobs. Reuse explicit failure/uncertainty states and immutable receipts.
3. Implement a deliberately scoped SQLite index consumer and a declared
   PostgreSQL counterpart or explicit unsupported gate. Pin corpus/tokenization,
   removed-tool handling, NULL/empty data and deterministic result ordering.
   Do not claim parity with all legacy FTS5/sqlite-vec/BM25/hybrid behavior from
   matching counts or synthetic embeddings. No operating embedding model is
   required or invoked for isolated contract/security verification.
4. Build a bounded read-only reconciliation view for explicit synthetic snapshots
   comparing stable resource IDs/keys, legacy versus proposed normalization,
   registry/observation ownership and required corpus/version/invalidation intent.
   Report aggregate differences without original URLs, credentials or raw data.
   It must not mutate or silently adopt unversioned operating resources.
5. Exercise stale worker/model completion, artifact failure, rollback/commit
   uncertainty, restart/recovery, privacy/projection and affected API/browser/TLS
   compatibility in isolated fixtures. Freeze once and update source evidence,
   design and remaining work as one completed batch.

Routing collectors, admin/public registration, health/survey/evidence updates or
existing search to these components requires explicit supported write ownership,
reviewed normalization changes and snapshot/cutover/rollback procedures. No hidden
DSN/environment selector, automatic dual write, unsupported backend fallback or
old evidence recertification is allowed. Full Store/FTS/vector/auth/privacy/
workflow/ledger migration and representative operating load/DR/HA remain separate.

[Atomic writer](CATALOG_ATOMIC_WRITER.md) ·
[observed migration contract](CATALOG_WRITE_MIGRATION_CONTRACT.md) ·
[remaining order](REMAINING_WORK_BATCHES.md) ·
[platform design](PLATFORM_ADVANCEMENT_DESIGN.md).

Next: [observation ownership and consistent capture](CATALOG_INTEGRATION_PLAN.md).
