# Catalog repository pilot — delivered read scope

2026-10-18 · v1.25 private read pilot verified; no operating PostgreSQL rollout.

The explicit adapter, static source inventory and private PostgreSQL DB-API
contract are completed foundation units. Do not rebuild them. The application
Store remains SQLite and its complete PostgreSQL backend is unsupported.

Implemented: the bounded selected read contract and isolated verification.
Atomic write behavior below is designed, not implemented.
[Read contract](CATALOG_REPOSITORY_CONTRACT.md) ·
[write migration contract](CATALOG_WRITE_MIGRATION_CONTRACT.md) ·
[verification](../reports/advancement-catalog-repository-2026-10-18/README.md).

## Delivered coherent read/design unit

1. Use the frozen inventory to define a private catalog repository contract for
   resource identity lookup, bounded batch lookup, counts and explicit filters.
   Include result types, nulls, ordering, limits, current activity/health fields
   and private original bindings. Preserve stable public projection behavior.
2. Implement fixed SQLite/PostgreSQL statement variants through the new session
   boundary, with matching bounded synthetic schemas and tests. Keep search/FTS
   ranking out of parity claims until tokenization, language, normalization,
   ordering and index maintenance have explicit acceptance cases.
3. Design resource upsert/content-hash/version invalidation and related FTS/vector
   outbox effects as one atomic write contract before migrating them. Preserve
   current schema/credential/health/quality evidence; do not silently recertify
   old versions, replace upstream URLs or backfill invented success.
4. Exercise row/transaction/conflict/rollback/CAS and public redaction semantics
   on disposable SQLite and private Unix-socket PostgreSQL fixtures. Include
   injection-like bound text, role/projection and stale-version tests. Freeze and
   run affected security/API/browser compatibility once; update all design views.

There is no operating DSN, environment backend toggle, automatic dual write or
silent fallback. Introduce any future opt-in application wiring only after its
supported repository scope is explicit; unsupported subsystems must remain gated.

## Broader remaining work

Search/FTS and collection/evaluation histories, administrator/visitor/privacy
state, credential sealing, workflow execution and separate ledger invariants need
deliberate repositories and schema migrations. A resource read/write pilot does
not establish complete Store compatibility. Use verified snapshots/count/hash
reconciliation and reviewed write ownership for future cutover/rollback. Actual
operating maintenance, representative capacity/DR and HA remain separate gates.

The user controls the terminal server. Independent human-quality evidence and
actual approved product-provider integration continue as conditional tracks.

[Adapter contract](STORAGE_ADAPTER_CONTRACT.md) ·
[remaining batches](REMAINING_WORK_BATCHES.md) ·
[platform design](PLATFORM_ADVANCEMENT_DESIGN.md).

Next: [atomic catalog writer](POSTGRES_CATALOG_WRITER_PLAN.md).
