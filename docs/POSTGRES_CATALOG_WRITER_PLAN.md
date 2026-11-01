# Atomic catalog writer and revision-bound index intent — delivered private scope

2026-10-18 · v1.26 private source/isolated verification complete; no operating cutover.

The explicit adapter and bounded private catalog read repository are completed
foundation units. Reuse them and the observed [write migration contract](CATALOG_WRITE_MIGRATION_CONTRACT.md).
Do not reimplement read pagination or label the low-level driver a full Store.

Implemented as a separate strict single-resource profile with metadata-only index intent.
Legacy application writer migration and actual index engines remain gated.
[Contract](CATALOG_ATOMIC_WRITER.md) ·
[verification](../reports/advancement-catalog-writer-2026-10-18/README.md).

## Delivered coherent private implementation unit

1. Define bounded typed registry upsert commands, stable exact key/ID/first-seen
   rules, explicit field ownership and a versioned normalization/content-hash
   policy. Pin new/equal/changed/counter/URL/retired/schema-null behavior and mark
   intentional departures from legacy quirks before enabling application writes.
2. Implement a private SQLite/PostgreSQL writer on a single explicit session with
   operation identity, expected revision/CAS, committed/conflict/refused results
   and conservative commit_unknown reconciliation. Preserve immutable evidence
   history and invalidate current eligibility without fabricating provider tests.
3. Atomically record the mutation, required derived/reset state and revision-bound
   search/index work intent. Use durable corpus/model revisions and stale-worker
   acknowledgement checks; failed or superseded work must not delete newer jobs.
   External embeddings stay outside the transaction. Search/tokenization parity
   and an actual replacement FTS/vector engine remain separate gates.
4. Exercise concurrent same-key and stale updates, health/survey field ownership,
   rollback at each write boundary, idempotent operation replay, unknown commit,
   retained evidence and index-job stale completion using disposable SQLite and
   private PostgreSQL. Run affected API/browser/security compatibility once after
   freezing source; synchronize design, reports and remaining work together.

This unit adds no operating DSN, backend environment switch, automatic dual write
or silent fallback. Wiring an existing collector or administrator writer requires
an explicit supported unit of work, shadow reconciliation and a reviewed single
write-owner/rollback plan. Full Store/search/auth/privacy/workflow/ledger migration,
operating data cutover, representative capacity/DR and HA remain separate.

[Read contract](CATALOG_REPOSITORY_CONTRACT.md) ·
[remaining batches](REMAINING_WORK_BATCHES.md) ·
[platform design](PLATFORM_ADVANCEMENT_DESIGN.md).

Next: [fenced index artifacts and shadow reconciliation](CATALOG_INDEX_CONSUMER_PLAN.md).
