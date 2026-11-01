# Atomic private catalog registry writer and revision-bound index intent

2026-10-18 · v1.26 · profiles `atomic-catalog-registry-v1` and
`revision-bound-catalog-index-v1`.

The separate writer implements one-resource registry commands and durable index
metadata on caller-owned SQLite/PostgreSQL adapters. It does not wire existing
Store, collectors, administrators, public registration or search to a new backend.
No operating schema, DSN, environment selector, server import or provider call is
added. Constructors initialize nothing. The explicit schema statements are for a
new supported private schema and isolated fixtures, not a migration script for an
operating database. The application Store remains SQLite.

## Input ownership and intentional compatibility differences

`RegistryUpsert` is immutable and private. Required fields are key, source, kind,
url, name, description and category. Optional fields are networks(tuple), integer
price_usdc, pay_to, method, details_json, call/payer counters, last_called and
caller-derived desc_lang/regions/auth_declared. These are registry-owned fields;
health, observed authentication, surveyed tool schemas, guides, trials and grade
payloads cannot be supplied by this command. No caller-selected SQL or field map
is accepted. No network/DNS lookup occurs: URL validation is syntactic storage
validation, not gateway SSRF admission or an execution authorization.

The profile rejects rather than truncates names over200 characters and
descriptions over2000. UTF-8 limits also apply: key512, source/category256,
URL4096, name800, description8000, payee256, method/language64, regions1024bytes.
IDs/revisions/counters use exact nonnegative signed64 integers without bool;
revision commands reserve the top value to avoid overflow. Times are explicit,
finite, nonnegative and below2^53, including observed_at=0. No implicit wall clock
or now-or-time fallback is used. Networks are at most32 bounded tokens, deduped
and sorted into the legacy comma-packed representation. Empty networks become
`,,`. Empty payee becomes null and nonempty payee is lowercase. Derived hints are
validated bounded values supplied by the caller; this writer does not infer text
constraints, validate registry price claims, convert currency or certify quality.

Timestamp inputs are trusted-caller UTC Unix seconds; fixtures use controlled
synthetic times. They are not authenticated external timestamps or authority
evidence. A live integration must supply and govern its own clock policy.

Details must be JSON object text, at most12288bytes before and after canonical
encoding. Duplicate keys, NUL/unpaired-surrogate strings, nonfinite numbers,
integers outside signed64, depth over12 and more than1024 visited values are
refused. JSON is canonicalized with sorted keys, ASCII escaping, compact
separators and no NaN. This intentionally differs from legacy implicit JSON
encoding, default=str and silent text truncation. A versioned content digest binds
the complete normalized registry command, including key and derived hints. The
new hash is not interchangeable with a legacy content_hash, cv_ fingerprint or
execution proof. Existing unversioned resources are refused, not silently
backfilled or recertified. Exact key equality is identity; a shared URL does not
merge two keys. Generated IDs use RETURNING and remain stable across updates;
PostgreSQL sequence gaps after aborted allocations are allowed.

`registry-text-corpus-v1` hashes kind, name, description and category. It excludes
usage-tool text, embedding output and index quality. A required explicit64hex
model_hash identifies the intended model/corpus implementation; no runtime model
is selected or contacted. This is not FTS/BM25/vector or Chat-ranking parity.

## One atomic write and durable request identity

`CatalogWriter(adapter, model_hash=...)` accepts the existing explicit adapter.
Its schema has a write-control row disabled by default. An authorized integrating
application would need to manage this control and its own real authorization;
the private Python control is not a public authentication boundary. Fixtures
explicitly enable it. A disabled/missing control refuses writes, including replay.
The PostgreSQL control row is locked FOR UPDATE; SQLite uses BEGIN IMMEDIATE.
This deliberately serializes this profile's registry writers, not a scalable
multi-writer performance claim. Direct legacy writers that bypass its ownership
are outside the supported profile.

`upsert(command, operation_id='co_'+32lowerhex, expected_revision=...,
observed_at=...)` owns one adapter transaction. Zero expected_revision is
create-only; positive values require the current catalog revision. A mismatch
commits an immutable conflict receipt, without modifying resource/index state.
Accepted writes return committed/new, changed or unchanged, resource ID and
revision. Fixed WriterError refusals distinguish invalid input, disabled writes,
unversioned resources, operation reuse, stale observation, revision conflict and
malformed state. Driver/commit errors retain StorageError certainty codes.

The operation fingerprint binds normalized command, expected revision, explicit
observation time and model hash. Same operation/same fingerprint returns the
original receipt with replayed=True, even after newer revisions. Different input
with a committed operation ID is refused. Both success and conflict receipts are
stable. No new operation ID, retry or reconnect is generated automatically.
Input/policy refusals that never commit a receipt are not durable accepted work.

New resources start with revision1, active1 and unknown health. Updates retain ID
and first_seen. A successful new observation, including equal normalized content,
advances revision, keeps last_seen monotonic and reactivates the resource.
An older observed_at is refused even when a matching revision was supplied.
Equal content touches only last_seen/active in the resource row; changed content
replaces registry-owned columns and invalidates capability/evaluation timestamps.
Historical grade/schema/guide/trial payloads and observation times remain raw
facts, not fresh evidence. URL/kind changes or changed retired entries reset the
specified current health state, streak/next-check and rolling counters, while
preserving historical last check/success and separate observed-auth/schema data.
A kind change now receives the same reset; all changed kinds clear cap/eval
stamps. These are explicit conservative profile differences, not silent Store
compatibility. Future live integration must review the binding of retained survey
and credential hints before routing execution.

The resource, catalog revision/hash/profile, deletion of current
capability_eligibility, current index head/job intent and receipt commit together.
Every accepted command invalidates that current cache and enqueues the new
revision, including equal corpus observations. This is deliberately conservative
and can cause extra reindex work. Immutable agent/version/approval/evidence
history is not rewritten or deleted, and no Registry.current, real test result or
callable status is created. Missing required tables or an index enqueue error
roll back the resource mutation too. No atomic multi-resource/page API is supplied;
legacy upsert_page migration remains gated.

## Commit certainty and reconciliation

A failed commit acknowledgement propagates commit_unknown and makes the adapter
unusable, even when rollback also fails. It is not returned as conflict or proof
that no write occurred. No internal retry occurs. A fresh trusted connection can
call `reconcile(operation_id)` to read the committed receipt, or explicitly
resubmit the same exact operation after appropriate reconciliation/ownership
checks. An absent receipt is only a statement-time observation and does not prove
that an in-flight commit can never become visible. Never create a new request ID
and blindly repeat an uncertain write. Receipts/tombstones have no automatic GC
in this pilot; future retention must preserve replay/conflict certainty.

## Index work ownership and stale completion

The writer calls `enqueue(session, resource_id, revision, corpus_hash,
model_hash, now)` inside its own transaction. The outbox never opens an inner
transaction or commits independently. Jobs bind all four identity values and
have deterministic IDs. There is one current active model/head per resource.
Advancing revision supersedes older jobs across models; reusing a revision with
different corpus/model is refused. Historical projection rows may remain stored,
but reads expose only a matching current head and indexed job.

`CatalogIndexOutbox.claim(worker_id, now=..., lease_seconds=1..60)` atomically
claims pending/expired work. Worker IDs have a bounded source-safe alphabet;
claims bind job/resource/revision/corpus/model, owner, random token, increasing
fence and exact lease end. Expired claims can be reclaimed with a new token/fence.
There is no heartbeat or automatic external computation in this profile.

`complete(claim, projection_hash, now=...)` locks and checks the current head and
then verifies every claim dimension, state and unexpired lease. Job acknowledgement
and indexed hash metadata commit together. A stale/superseded worker cannot
publish an older projection or acknowledge newer pending work. Model changes are
covered by the same current-resource boundary. `fail` accepts only index_failed,
invalid_projection or worker_cancelled; failed work stays visible with its error
until superseded by a later revision, without claiming success or automatically retrying. A future operator
retry policy must issue a deliberate supported new job/revision.

The returned states indexed/failed/stale_claim/superseded are fixed private data;
repr omits record/claim values. `indexed_projection(resource_id, model_hash)` is
current hash metadata only. **No actual FTS table, vector, embedding, artifact
body or model output is written or verified.** A projection hash is not a search
quality certificate. Future consumers must materialize their real artifact and
acknowledge it atomically under the same revision fence, with validation before
publication. External computation stays outside DB transactions.

v1.27 adds a separate [actual lexical artifact consumer](CATALOG_INDEX_ARTIFACTS.md)
which reuses the same-session acknowledgement and materializes body/postings
atomically. The existing `complete` method remains metadata only. Legacy
FTS/vector/search and operating application integration remain separate gates.

## Verification and remaining migration gates

Disposable fixtures exercise SQLite/PostgreSQL row semantics and actual
concurrent same-key creation/update, stale revisions, idempotent requests,
registry/observation field ownership, rollback after accepted SQL, current-cache
invalidation/history preservation, lost commit acknowledgement and explicit
reconciliation, stale model/lease/fence completions and private/public projection.
Native driver timeouts and safe private PostgreSQL lifecycle are reused. No
operator server or database is started, stopped or changed.

The [observed legacy write contract](CATALOG_WRITE_MIGRATION_CONTRACT.md) remains
source analysis. The new supported profile does not resolve all direct Store
writers, health/survey/evidence transaction ownership, full schema migration,
index/search engines, FTS/tokenization parity, public authorization, operating
cutover/rollback or representative capacity/DR/HA. Existing execution kill
switches/grants and privacy/marketing permissions are not inherited or altered.
See the current verification report and [remaining order](REMAINING_WORK_BATCHES.md).

v1.28 adds a separate [private observation/capture boundary](CATALOG_OBSERVATION_CONTRACT.md)
for explicitly supported health/survey/evaluation fields. This is not migration
of the existing Store/collector writers or all observation/auth/trial domains.
