# Explicit storage adapter foundation — delivered scope

2026-10-18 · v1.24 source/isolated foundation complete; no operating migration or cutover.

The current execution-state PostgreSQL rehearsal covers 32 selected tables. The
disposable SQLite storage rehearsal exercises current retention and restore
contracts. Neither replaces the application Store or establishes production
capacity, availability, RPO or RTO.

The foundation below is implemented and isolated-verified. The new low-level
contract is separate from the legacy application Store, whose PostgreSQL backend
remains unsupported. [Contract](STORAGE_ADAPTER_CONTRACT.md) ·
[verification](../reports/advancement-storage-adapter-2026-10-18/README.md).

## Delivered coherent source unit

1. Inventory the actual storage entry points and SQLite-specific SQL. Include
   `Store.tx/query`, direct `_db/_lock` users, schema initializers and nested
   commits. Identify row mapping, generated IDs, placeholders, conflict handling,
   transaction ownership, cancellation and retry semantics before choosing an
   adapter contract. Do not rewrite arbitrary SQL through string substitution.
2. Add an explicit, opt-in adapter boundary and isolated contract tests. Preserve
   the current SQLite default and public/API/SDK behavior. Selecting an
   unsupported backend must fail closed; it must not silently fall back or create
   another database. Keep database URLs, passwords and raw driver errors out of
   public responses and reports.
3. Validate transactions, concurrent compare-and-set, rollback, generated IDs,
   null/numeric/time/text round trips and current idempotency/authority checks
   against disposable databases. Use fixed identifiers and bound parameters.
   Add PostgreSQL integration only through an explicitly isolated local cluster
   with no operating DSN, credentials or network listener.
4. Document supported and unsupported subsystems, then freeze source and run the
   affected security, API/browser and compatibility regressions once. Keep the
   design, machine plan, verification artifacts and existing Canvas consistent.

## Subsequent implementation and operating gates

- Catalog/resource/search: current Store combines FTS search, ranking inputs,
  usage/schema/evaluation/health histories, reports and workflow definitions.
  PostgreSQL search behavior, indexes and ranking must be specified and tested;
  copying selected execution tables does not cover these functions.
- Identity and privacy: administrator sessions/roles, visitor requests,
  notification preferences, destination verification, consent and credential
  sealing need their existing boundaries preserved. Restore must not revive
  withdrawn rights or expose keys.
- Execution and ledger: ownership/fencing/deadlines, checkpoint signatures,
  outbox/manual-delivery uncertainty and replay tombstones need transactional
  parity. Ledger holds/settlements/refunds require independent accounting
  contracts; this adapter work does not enable payments or advertising.
- Migration: use reviewed, bounded exports, row/count/hash reconciliation and
  explicit write ownership. Avoid uncontrolled dual writes. Back up and rehearse
  both cutover and rollback before any operating change; preserve unresolved
  external effects as unknown.
- Capacity and disaster recovery: select representative scale and failure cases,
  measure actual behavior, and define operating targets from evidence. A local
  synthetic run cannot certify HA, uninterrupted service or production RPO/RTO.

Actual operating migration, maintenance application, credential changes and
activation remain separately reviewed actions. The user's terminal server stays
under the user's control. Real human quality evidence and actual product-provider
integration are independent conditional tracks, not prerequisites for this
storage boundary work.

Current status: [remaining work](REMAINING_WORK_BATCHES.md) and
[platform design](PLATFORM_ADVANCEMENT_DESIGN.md).

Next independent source unit: [catalog repository pilot](POSTGRES_CATALOG_REPOSITORY_PLAN.md).
