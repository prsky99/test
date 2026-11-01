# Catalog writes: migration contract and current behavior

2026-10-18 · design only · proposed private catalog write boundary.

This document records the current SQLite implementation and the acceptance gates
for a future catalog writer. It does not implement upserts, change the existing
Store, enable a PostgreSQL application backend or authorize a cutover. The
[catalog repository pilot](POSTGRES_CATALOG_REPOSITORY_PLAN.md) introduces a
separate, bounded read interface. Search, ingestion and all existing writers
continue to use their existing paths until separately migrated.

The source of truth for current behavior is
[`gateway/store.py`](../agent_market/gateway/store.py),
[`capability_registry.py`](../agent_market/capability_registry.py) and
[`gateway/rag.py`](../agent_market/gateway/rag.py). The following observations are
source analysis, not measurements of an operating database or provider.

During the read pilot's verification, two preexisting source files changed
concurrently outside that batch. The current Store skips invalid full-schema
normalization on ValueError/TypeError; a changed compact hash then clears the
full-schema fields, while an unchanged compact hash can retain the previous
full schema. The current capability survey also catches usage-record errors.
These separate edits are preserved, not attributed to the read pilot; their
operating reflection was not verified. The catalog acceptance run uses the
refrozen current source rather than the first run whose source changed.

## Identity, fields and private read results

`resources.key` has exact database uniqueness. Store upsert looks up this key; it
does not implement normalized URL uniqueness. Individual collectors can apply
their own duplicate rules. Two keys referring to the same URL are not
automatically the same resource under the Store contract.

`resources.id` is the persistent integer identity. FTS row IDs, vector row IDs,
health/history references, the persistent `ag_` association and `cv_` version
fingerprints depend on that identity. A migration must preserve IDs and existing
references rather than reinsert rows with newly allocated IDs. Existing
`first_seen` is preserved by an update; `last_seen` changes on each upsert.

`Store.resource(id)` returns `dict(row)` or `None`, without an activity, health or
authorization filter. It returns private original bindings and JSON stored as
text, rather than a public connection DTO. Fields can include original URLs,
authentication information, surveyed schemas and evaluation details. Use the
existing public projection boundary before exposing any catalog result. Neither
a raw resource dictionary nor its representation is safe public output.

New Store schemas declare `health_status` non-null with default `unknown`.
Imported or legacy SQL nulls, where present, are distinct from that string:
`NOT IN` does not include a null value. Nullable authentication and trial fields
also distinguish unknown from false. The read and write contracts must state
which values they preserve and which filters they apply. Do not normalize nulls
implicitly during migration.

Several list-like values use comma-delimited text, while details, tools, guides
and evaluation information use JSON text. The network encoder sorts and dedups
its input; its empty representation differs from the optional constraint packer.
There is no automatic JSONB, boolean, timezone or Decimal conversion contract.
Changing representation or JSON serialization can change stored hashes even
when decoded information appears equivalent.

## Current upsert and reset behavior

`upsert_resource` owns one Store transaction. `upsert_page` processes its input
page in one Store transaction and returns new/changed/unchanged counts. The
Store method itself does not impose a bounded page size or a strict typed input
schema. An explicit `now=0` is treated as absent by its current `now or time`
selection.

The registry content hash covers a JSON-encoded tuple containing source, kind,
URL, name truncated to 200 characters, description truncated to 2,000,
category, packed networks, price, lowercase payee, method, sorted-key details
JSON, call/payer counters and last-called time. It excludes the resource key,
observation times, active flag, health history, tool survey and execution
evidence. The outer serializer uses the current Python JSON defaults and
`default=str`; this is not a new strict canonical JSON standard.

For a new key, upsert allocates an ID, stores those values and derived
host/language/region/authentication hints, inserts FTS text and enqueues a vector
job. For an equal content hash, it only updates `last_seen` and sets `active=1`.
It does not rerun health checks, issue new quality evidence or refresh indexes.

For a changed hash, upsert preserves the ID and first-seen time while replacing
the registry fields and derived hints. It clears `cap_checked_at` and `eval_at`
for MCP/A2A resources, but leaves their historical payload fields in place. A
changed URL resets the current health status, failure streak, next-check state
and rolling health counters. An unchanged URL only receives the smaller reset
when its current state is retired. Other historical health fields are not
universally erased by these branches.

FTS and vector changes depend on the stored truncated name/description changing,
not merely on any content-hash difference. The initial and changed FTS inserts
use the original incoming name/description, although the base row stores their
truncated versions. Constraint extraction also receives the incoming text.
Changes beyond truncation can therefore have different consequences from changes
to the stored text. These are compatibility cases to review, not fixes shipped
by the read pilot.

`deactivate_unseen` marks matching active rows inactive, removes their queued
vector work and attempts to remove their vectors. It retains the resource row,
FTS text and histories; vector deletion errors are caught by the current method.
An active row or an unchanged registry hash is not proof of safe callability.

## Health, survey and execution evidence stay separate

`record_health` appends a health check and updates resource status, failure
streak, scheduling, rolling counters and optional observed authentication/price.
Failure preserves a historical last-success time. Observed price can update
without recomputing the registry content hash. Reachability is a health
observation, not a successful tool execution or a semantic contract test.

Capability, authentication, usage and evaluation methods are separate writers.
In particular, `record_usage` stores compact and optional full tool schemas,
their hashes, guides and trial information. A compact schema change without a
new full schema clears the old full-schema fields. Compact hash equality affects
the usage timestamp/change history behavior. A legacy `trial_ok` flag or an
evaluation grade must not be promoted into modern execution evidence.

When extracted tool text is nonempty, usage recording rebuilds FTS from stored
name/description plus that text and queues vector work. Empty tool text does not
clear previous FTS tool text in that method. Constructor backfills and missing
FTS synchronization are additional paths with their own text sources. Therefore
index parity requires cases for new rows, changed descriptions, tool additions,
tool removal and backfill, rather than a row-count comparison alone.

The connection registry maintains three different concepts:

- The registry content hash describes an ingestion snapshot, including some
  usage counters. It is not a connection binding or schema fingerprint.
- `version_parts` fingerprints connection/authentication bindings, selected
  guide/card fields, tools, schema completeness and protocol profile. The
  resulting immutable `cv_` ID also binds the resource ID. Persistent `ag_`
  references are stored separately; they are not recomputed from a URL.
- Version-bound transport, execution and contract observations record their own
  outcome, scope, timestamps and expiry. Approval, current execution eligibility
  and contract evidence have distinct requirements. A successful old version
  does not certify a changed one.

`Registry.current` can insert missing agent/version records. It is not a pure
read helper and must not be called inside a future transaction on the assumption
that it cannot write or commit. Current evidence recording and its eligibility
cache update also use separate Store transactions; do not describe them as one
existing atomic catalog/evidence write.

The current SQLite invalidation trigger removes `capability_eligibility` after
specified changes to URL, kind, tool hashes, authentication info/observation,
activity, health, usage guide or details. It does not delete historical versions,
approvals or evidence. Its field list is not identical to the binding fingerprint
inputs; for example, the binding includes declared authentication. The future
writer must reconcile both dependency sets explicitly. Trigger presence is not
proof that every direct update invalidates every dependent view.

## Existing transaction, search and index limits

`Store.tx` shares one connection under a reentrant lock and uses the connection
context rather than savepoints. A nested successful context can commit outer
writes; a nested failing context can roll them back. `Store.query` is a general
SQL execution helper, not an enforced read-only operation. The new
[adapter contract](STORAGE_ADAPTER_CONTRACT.md) deliberately does not change these
legacy semantics.

Resource changes, FTS changes and vector enqueue statements in `_upsert` share
its transaction, but that fact does not make arbitrary nested Store helpers a
safe future unit of work. Store construction also performs schema work,
backfills and initialization. It is not a read-only repository opener.

`Store.search` combines FTS BM25 hits, optional hybrid candidates and category
fallback rows. FTS has no explicit resource-ID tie break. Hybrid IDs are fetched
through an unordered `IN` query before merging; category fallback orders by
payer count with no explicit ID tie break. Its filters and order differ from
Chat's final recommendation ranking. A deterministic bounded read pilot must
declare its own filters/order, and must not claim FTS, hybrid search or
recommendation-ranking parity.

`vec_outbox` currently coalesces work by resource ID with replacement, without a
catalog revision or embedding-model revision. `RagPipeline.step` reads rows,
computes embeddings outside the writer lock, then writes vectors and deletes
queued IDs in a later transaction. It does not compare a claimed revision when
acknowledging work. Per-row vector write errors are caught, while the outbox-ID
deletion still runs. A stale worker can therefore lack the information required
to distinguish its job from a newer enqueue. This is a migration requirement,
not a claim that the current implementation has been changed.

The vector corpus uses name, category and a bounded description; it is not the
same corpus as FTS tool text. FTS5 tokenization/vocabulary, sqlite-vec distance,
embedding model/dimensions, generated row IDs and SQL conflict semantics each
need an explicit replacement contract. Do not translate them by string-rewriting
SQLite SQL or silently treat an unavailable index as equivalent success.

## Required future atomic write unit

v1.26 implements a separate strict single-resource [writer and metadata outbox](CATALOG_ATOMIC_WRITER.md). The requirements below remain migration acceptance gates for legacy application writers, full observation ownership and actual indexes; they are not all delivered by that private profile:

1. Define a bounded typed command and a versioned normalization/hash profile.
   Specify exact key identity, field ownership, nulls, finite numbers, UTC times,
   text limits, JSON encoding and error results. Preserve historical hashes;
   do not recanonicalize stored rows during reads. Any intentional departure from
   the current reset/index quirks needs explicit review and compatibility cases.
2. Own one explicit adapter session and transaction. Validate current authority
   and expected resource revision under that ownership before mutation. Do not
   nest legacy `Store.tx`, run a Store initializer or call a helper that can
   independently commit. Use trusted dialect-specific statements and bound
   values; generated IDs require an explicit `RETURNING` contract.
3. Commit the resource mutation, derived constraints and prescribed reset state,
   version/eligibility invalidation, and required search-index or durable
   index-job intent together. A catalog revision/CAS policy must prevent a stale
   ingestion snapshot from overwriting newer survey or health fields. Separate
   writers need explicit field ownership rather than full-row replacement.
4. Preserve immutable connection versions, approval/evidence chronology,
   execution certainty and withdrawal/replay tombstones. Real health/execution
   observations remain separate scoped commands with actual timestamps and
   version checks. A migration, retained signed projection, grade or index rebuild
   must never invent successful provider execution or recertify factual accuracy.
5. Compute embeddings and other external work outside the database transaction.
   Bind jobs to resource ID, catalog/corpus revision and model revision. Apply
   and acknowledge only the still-matching revision; stale completion must not
   overwrite a newer vector or delete a newer enqueue. Failed writes must retain
   retryable work or an explicit failed state. Reads still recheck current
   resource/policy eligibility independently of stale index hits.
6. Return an explicit committed/conflict/refused/uncertain result. A failed
   commit acknowledgement is `commit_unknown`, not proof that nothing changed.
   Use durable operation identity and reconciliation before retrying; do not
   allocate another resource or blindly replay a partly acknowledged batch.

The dependency review must cover registry text/category/network changes;
URL/kind/authentication binding changes; compact/full schema and guide changes;
activity/health changes; observed prices/counters; and direct administrative
patches. Each group needs its own hash/version/index/invalidation expectations.
Not every field belongs in every hash, and not every observation should reset
registry first-seen state or rewrite an unrelated schema.

## Migration and verification gates

Before routing any existing write path to a new repository:

- Inventory all catalog writers, including collector registration/detail
  updates, health/capability/auth/usage/evaluation recording, admin registration
  edits and activity controls, frontend registration handling, constructor
  backfills and vector workers. Moving `_upsert` alone does not establish single
  write ownership. The bounded AST inventory is an aid, not a resolved call graph.
- Pin new/equal/changed upserts, stable IDs/first-seen, counter-only changes,
  URL and retired resets, long text, empty networks/constraints, nullable flags,
  full-schema loss, removed tool text and direct writer invalidation. Identify
  consciously versioned behavior changes rather than hiding them in migration.
- Verify SQLite/PostgreSQL row/null/scalar/JSON/hash/time/unique-conflict behavior
  with disposable fixtures. Include batch rollback, generated IDs, concurrent
  same-key ingestion, stale revision refusal, health/survey interleaving and
  commit-uncertainty reconciliation. Do not use native cursor rowcounts or
  `lastrowid` as an assumed portable contract.
- Inject failures between resource, derived-state and job writes. Test that a
  stale embedding cannot acknowledge a newer job, a failed index write keeps
  work visible and deactivated rows cannot become callable from stale indexes.
  FTS/vector search ordering and tokenization require separate acceptance tests.
- Preserve private original bindings internally while testing existing public
  redaction/projection independently. Confirm changed versions invalidate current
  eligibility without deleting history or restoring withdrawn authority. An
  imported success, stale approval or legacy trial flag must not become fresh
  callable/contract evidence.
- Reconcile snapshot identities, counts and declared hashes before cutover.
  Use read-only shadow checks first, then a reviewed single write-owner boundary
  with an explicit stop/rollback plan. Do not add automatic dual writes, a hidden
  backend environment switch or silent SQLite fallback. Backup/restore must keep
  its separate fail-closed quarantine and authority-revocation behavior.

All acceptance work must use isolated synthetic data and explicitly supported
connections. Full Store compatibility, operating data migration, search/FTS,
credential/admin/privacy state, workflows/ledger, representative load, DR and HA
remain separate scopes. This design requires no user server operation and makes
no operating PostgreSQL, security-certification or provider-quality claim.
