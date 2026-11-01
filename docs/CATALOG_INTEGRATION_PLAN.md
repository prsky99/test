# Catalog observation ownership and capture — delivered private scope

2026-10-18 · v1.28 private source/isolated verification complete; no operating cutover.

The explicit adapter, bounded registry reader/writer, revision-bound outbox,
materialized lexical artifacts and pure aggregate shadow comparison are completed
private units. Reuse them. The next dependency is ownership of legacy observations
and trustworthy source capture, rather than another index/queue implementation.

Implemented bounded private health/survey/evaluation observations and native
read-only capture; legacy auth/commercial/trial/retirement/full-Store integration
remain unsupported gates. [Contract](CATALOG_OBSERVATION_CONTRACT.md) ·
[cutover requirements](CATALOG_CUTOVER_CONTRACT.md) ·
[verification](../reports/advancement-catalog-observations-2026-10-18/README.md).

## Delivered coherent private implementation unit

1. Review actual health, survey/tool schema, usage and evaluation write paths and
   pin each field's owner, monotonic observation timestamp, stale-writer behavior,
   and effects on current callability/approval caches and corpus/model revision.
   Preserve immutable evidence and legacy first-seen/identity. A newer observation
   must not be overwritten by an older worker; an unrelated health result must
   not claim registry/contract/quality authority.
2. Implement an explicitly scoped private typed observation writer and isolated
   adapter contracts for supported cases. Couple affected current-cache/index
   invalidation atomically to accepted changes. Keep unsupported owners explicit;
   do not infer broad Store parity, replay successful evidence or silently adopt
   unversioned rows. Reuse durable operation receipts/commit-uncertainty rules.
3. Add bounded read-only snapshot capture for caller-owned disposable/copied sources
   and the supplied shadow comparison. Validate schema, consistent capture and
   limits, emit aggregate findings only, and keep unfinished scans visibly
   incomplete. CLI inputs must not accidentally connect to the operating DB or
   inherited PostgreSQL credentials, and must never instantiate mutating Store
   initialization. Read-only refusal is preferable to an unsafe fallback.
4. Define an explicit source-to-target integration/cutover contract: writer
   exclusion or journal boundary, stable-ID/version mapping, model/index rebuild,
   incremental reconciliation, quiescence and rollback without resurrecting
   revoked authority or exposing provider bindings. Actual operating activation
   requires concrete target/source ownership and reviewed procedures; do not add
   hidden environment switches or automatic dual writes.
5. Freeze the complete unit and verify two-backend observation races, stale
   timestamps, rollback/commit uncertainty, privacy, affected API/browser/TLS and
   existing writer/index compatibility. Update design, evidence and remaining
   order once; operating restart is only needed if server-imported source changes.

Operating full-Store/FTS/vector/auth/privacy/workflow/ledger migration, DSN rollout,
production replay, actual provider/independent quality acceptance and representative
load/DR/HA remain gates. A source design or synthetic fixture is not completion
of those gates.

[Delivered artifacts](CATALOG_INDEX_ARTIFACTS.md) ·
[legacy ownership contract](CATALOG_WRITE_MIGRATION_CONTRACT.md) ·
[platform design](PLATFORM_ADVANCEMENT_DESIGN.md) ·
[remaining order](REMAINING_WORK_BATCHES.md).

Next: [owned-copy migration rehearsal](CATALOG_COPY_REHEARSAL_PLAN.md).
