# Bounded private catalog read repository

2026-10-18 · v1.25 · source pilot `bounded-catalog-read-v1`.

This separate repository reads a declared subset of catalog columns through the
explicit SQLite/PostgreSQL adapter. It does not initialize a schema, migrate
records, replace Store, add routes, change public projection or enable an operating
PostgreSQL backend. The current terminal server continues to use its original
SQLite Store. There is no DSN, environment backend toggle, automatic dual write,
retry or fallback in the repository.

## Private data and API

`CatalogRepository(adapter)` accepts only an explicit SQLiteAdapter or
PostgresAdapter. Caller-owned connection/exclusive-use and transaction certainty
rules follow the [adapter contract](STORAGE_ADAPTER_CONTRACT.md). No source
configuration, environment credentials, driver or database is opened at import.

`get(id, expected_hash=None)` returns a private CatalogResource or None.
`get_by_key(key)` uses exact database text equality; a key is not a normalized
upstream URL. IDs are positive signed64 integers, without bool or float coercion.
An optional lowercase64hex expected_hash is compared to the observed registry
content_hash in the same query result; missing/mismatch reports stale_resource.
It is not a connection version, execution authorization, freshness guarantee after
the read, or proof of a successful call. Missing resources without a precondition
return None. Legacy hash strings are retained as raw data rather than recertified.

`batch(ids)` accepts an exact tuple of at most50 identities. Repeated IDs collapse
to their first occurrence. Its found tuple follows that input order; missing
contains absent identities in first-occurrence order. An empty batch returns empty
results, including the same session/thread lifetime checks. SQL uses a fixed50-slot
bound statement, padded with null, never interpolated identities or SQL fragments.

`list(filters=CatalogFilter(), limit=50, after_id=0)` uses ascending ID keyset
pagination, with limit1..50. `count(filters=...)` counts the whole matching set,
independently of a list cursor. This is a separate read ordering contract, not
FTS/BM25/vector ranking, newest recommendation order or complete Store.search
compatibility. A new helper call starts a new transaction, so separate pages or
counts do not promise a shared point in time.

CatalogFilter supports optional exact kind(a2a/mcp/x402), category, source,
active(exact bool), health_status(unknown/healthy/reachable/failing/down/retired)
and inclusive min_last_seen. None omits a filter. It does not request SQL NULL;
unknown is a literal status and NULL remains distinct. Time inputs must be finite,
nonnegative and below2^53. Category/source filter text is at most256 UTF-8 bytes.
No raw WHERE, ORDER BY, role/tenant override or execution/approval action is exposed.

`with repository.snapshot() as view:` groups these reads under one read-only
transaction. SQLite requires read_uncommitted=0 and uses its ordinary deferred
read snapshot beginning with the first data read; the caller controls journal
and shared-cache policy. A function-form PRAGMA probe fails closed if an ordinary
main/TEMP table shadows its name. It never changes read_uncommitted. See the
official [SQLite isolation](https://www.sqlite.org/isolation.html) and
[PRAGMA function](https://www.sqlite.org/pragma.html#pragma_read_uncommitted) contracts.
PostgreSQL must
already have a session default of REPEATABLE READ or SERIALIZABLE. The first
read-only probe checks the actual transaction isolation and refuses other modes
with isolation_required. It does not silently claim READ COMMITTED is repeatable,
alter a caller's defaults, retry a failed transaction, or make the two databases'
lock/performance behavior identical. PostgreSQL's default statement snapshots and
repeatable snapshots are described in the official [isolation documentation](https://www.postgresql.org/docs/14/transaction-iso.html)
and [client defaults](https://www.postgresql.org/docs/14/runtime-config-client.html#GUC-DEFAULT-TRANSACTION-ISOLATION).
A view expires on context exit and is bound to its creating thread. Finish the
context successfully before relying on a committed transaction result.

## Selected row contract and limits

The28 explicit columns are identity(id/key/source/kind), original url, name,
description, category, active, first_seen/last_seen, health_status/last_check_at/
last_ok_at, eval_score/eval_grade/eval_security/eval_at, content_hash,
auth_declared/auth_observed/auth_info, details, usage_tools/usage_full_tools,
usage_full_hash/usage_tools_hash and usage_guide.

The record is immutable and its repr omits values. `as_private_dict()` returns a
fresh private mapping, not a public DTO. JSON is raw text: null, empty text, empty
array text and malformed JSON remain distinct. No tools schema, version row,
callability, health, quality or authorization is synthesized. Inactive, down or
quarantined records are not silently excluded from identity lookups; callers must
apply purpose-specific safety and relevance policies elsewhere. No Registry or
public_agent(store=...) is called, since those may create version data.

Text is checked without truncation: key512bytes, source/category256, URL4096,
name1024, description8192, hash text256, evaluation labels64, and each selected
JSON/text payload16384. Scalars preserve null and zero. Active/auth values accept
only0/1 integers, with nullable auth; health may be NULL for an imported/legacy
row. Eval score is nullable0..100; known timestamps are finite nonnegative values
below2^53. Malformed/unsupported rows fail with invalid_record, rather than
returning a partial/truncated agent. No unrestricted Store.resource parity is
claimed: its other columns, large schemas and unbounded legacy values remain
outside this profile.

The underlying adapter additionally bounds each result to1000rows/1MiB after
native driver decoding. A50-row list/batch can still exceed the payload limit and
fail explicitly. Count may scan many rows; no production CPU/memory/latency or
query-plan guarantee is implied. Read fixtures use their own statement/lock
budgets. Missing schema or driver/connection errors retain fixed StorageError
codes; CatalogError uses fixed request/record/stale/session/thread/isolation codes,
without SQL, raw values, connection addresses or driver diagnostic text.

Public compatibility tests feed equivalent selected metadata through the existing
`public_agent(..., resource=raw, store=None)` projection and compare canonical
URLs, redaction, schema constraints and citations. This does not make every private
field a publishable public field or prove parity for unselected metadata. No new
public serialization API is added.

## Verification and next unit

Disposable SQLite and private Unix-socket PostgreSQL fixtures cover bound
injection-like text, null/empty semantics, filtering/order/bounds, snapshot
concurrency/lifetime, stale hash, native read-only and private/public separation.
A write CAS/rollback probe exercises trusted synthetic fixture SQL, not a catalog
write API or migrated collector. The rehearsal accepts only explicit --run and no
operator connection/database/path. Its established cluster harness creates a fresh
private cluster, strips inherited libpq configuration and stops it before removal.
It preserves a possibly live private fixture on failed shutdown.

[Write migration contract](CATALOG_WRITE_MIGRATION_CONTRACT.md) specifies observed
Store behavior and the required future atomic resource/revision/invalidation/index
outbox transition. A separate strict [atomic writer](CATALOG_ATOMIC_WRITER.md) now implements a declared private subset; the observed contract remains the migration requirements for legacy writers and actual indexes.
Full Store/FTS/vector/evidence/credential/visitor/workflow/ledger migration,
application wiring, reviewed cutover/rollback and operating capacity/DR/HA remain
separate. [Remaining batches](REMAINING_WORK_BATCHES.md).
