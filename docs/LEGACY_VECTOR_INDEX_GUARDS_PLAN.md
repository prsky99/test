# Current SQLite vector publication and coherent search guards

2026-10-18 · v1.31 · implemented/isolated verified; operating and semantic acceptance separate.

The original specification/gap analysis below is retained as historical rationale, not an outstanding second implementation queue. Implementation: `agent_market/legacy_vector_index.py` plus actual Store/Rag paths. Final affected run: 2011passed/199new/0failure-error-skip. [Evidence](../reports/advancement-legacy-vector-index-2026-10-18/README.md).

Actual bounds: five private tables; exact768 float32/cosine; supported squared norm1e-30..1e30; declared model/revision;90s lease;3attempts/60s backoff;50jobs per step;one request per claim. Sanitized corpus:name200/category200/description500. Tools/auth/raw connection payloads are excluded. Known quoted credentials, decoded URL/email/local paths are omitted/masked without universal secret/PII claims. Terminal GC:7days/max500 excluding current heads/provenance. Untagged old vectors stay unverified; model/recipe replacement is refused.

HTTP precedes the bounded read snapshot; KNN/provenance, ranks, final visibility filters and full Store rows use that snapshot. MVCC coherence is not absolute latest content at function return. Unknown native commits poison the handle and require fresh exact-job inspection, with no automatic replay. Tested sqlite-vec0.1.9 is pinned: upgraded schemas require the trusted extension for persisted triggers. Fresh no-extension FTS fallback does not imply upgraded-schema operation without the extension.

Integration also fixed genuine frontend cold-cache reentrant deadlock and persistent classifier rule revision8. Current curated535-case classification gates pass; this is not expert semantic quality. Readonly user-server smoke passed; new Redis and warm verification-refresh source still need the final user-controlled restart; no operating server/DB/model was managed.

## Historical paths and concrete gaps at specification time

The next unit is the existing full-schema SQLite Store and
[`RagPipeline.step`](../agent_market/gateway/rag.py), not the separate private
adapter/lexical artifact pilot. The latter already demonstrates useful fencing
and atomic acknowledgement rules, but it is neither this sqlite-vec consumer nor
FTS5/BM25/vector parity.

`step` selects active resources joined to `vec_outbox`, releases the Store lock,
requests embeddings, then deletes/replaces `vec_resources` and deletes outbox
rows by resource ID. It does not retain the selected enqueue identity, resource
generation, corpus digest, model identity or a claimed worker token. A newer
enqueue while embedding is outstanding can therefore be deleted by the old
completion. An old vector can replace a newer vector or be installed for a
resource that changed or was deactivated during the request. The enqueue time
and `reason` alone are not a durable revision or an ABA defense.

Each vector insertion catches its own exception and continues. The subsequent
resource-ID acknowledgement still runs, so a failed replacement can lose pending
work; an earlier successful `DELETE` can also leave no previous vector. The
existing code's sub-5ms transaction wording is not measured acceptance evidence.

The current corpus is name, category and the first500 description characters.
`record_usage` enqueues a vector update, but this recipe does not include tool
text. Category is a corpus field, while the registry's current vector enqueue
condition checks name/description changes. Those distinctions must be resolved
explicitly rather than claiming the vector contains the FTS tool corpus.

Backfill selects active IDs missing from `vec_resources`; an existing row has no
proof that it matches current source/model/recipe. `RagEngine.index_resources`
also writes vectors directly and must not remain a bypass. The automatic
collector path, admin background `/admin/api/rag/index`, direct helper and
backfill must all use the same publication boundary.

`hybrid_search` combines actual FTS5/BM25 and sqlite-vec KNN candidates with RRF.
Its dense branch currently lacks current source/model metadata. It filters
active/non-retired/non-quarantine IDs, but the later detail query does not repeat
those conditions. Merely protecting vector writes would not establish coherent
search reads or prevent an in-flight visibility change from returning an
excluded item.

## Historical implementation specification — completed in v1.31

Implement compatible Store helpers and a dedicated legacy-vector purpose. Reuse
the existing native SQLite writer lock and guarded savepoint behavior; reuse the
private catalog outbox's fencing principles rather than creating another generic
workflow queue. Do not attach vector work to a health/survey token or to a
workflow publication, deployment, notification or automation grant.

1. Define one versioned canonical corpus function shared by ordinary indexing,
   backfill, direct helper admission and final source verification. Keep the
   initial field set and bounds explicit. Any privacy projection, normalization,
   truncation policy or addition of tool text is a recipe change with its own
   identity; do not silently reuse old vectors. Keep raw source fingerprints
   distinct from the sanitized text actually sent for embedding.
2. Define a server-owned model descriptor: declared model identifier/revision,
   dimension, float representation, distance metric and corpus/recipe version.
   Capture it before the request and compare it again on completion. A mutable
   model tag or dimension match alone is not proof of identical weights. If no
   immutable model digest is available, describe the identity as declared, not
   independently verified. Do not fetch model weights/registries to invent one.
3. Add the smallest persistent metadata needed for a single current head,
   immutable job identity, claim token/fence/lease and committed vector provenance.
   Keep legacy `vec_outbox` producer/count compatibility deliberate. Use a shared
   enqueue helper inside the producer's transaction, with a fresh job identity
   and monotonic source generation. Do not derive identity from a wall-clock
   timestamp or rebind an old resource-ID job to a newly loaded row.
4. Cover all supported producers: registry new/change, category-only changes,
   usage enqueue, deactivation/deletion, backfill and admin/direct indexing.
   Maintain an explicit inventory of remaining direct SQL aliases. Until they
   are covered, fail closed on unrepresentable work and do not claim every
   possible operating writer is fenced.
5. Route claim, completion, search freshness and reconciliation through those
   helpers. Preserve supported public/API envelopes, while distinguishing
   committed, stale/superseded, failed and unavailable work in private counters.
   Only committed vector publications count as indexed.

The concrete metadata schema/API should be agreed before editing the consumer.
An implementation can maintain a current head, immutable job records and a small
vector provenance record beside the existing virtual table. It need not replace
the Store or the private `catalog_index_*` tables. Old vectors with no matching
provenance are explicitly unverified, not automatically adopted as current.

## Claim, external work and atomic completion

Claim a bounded batch in a short native writer transaction. Fix the resource
identity/incarnation, monotonic generation, exact current corpus and recipe
digest, model descriptor, immutable job ID, worker token, fence and lease before
external work. A registry/corpus or required binding generation changing A→B→A
must still invalidate the original claim. Do not advance a stale claim to the
latest generation after embedding returns. Backfill must first obtain a current
job/head, rather than bypassing the outbox because no vector exists.

Run the embedding request outside DB transactions. Keep request size, batch
size, vector dimension and response size bounded. Refuse missing/extra/reordered
responses when their association with the claimed inputs cannot be established.
Validate every vector before writes: exact length, finite numeric non-boolean
values, representable finite float32 values and a defined nonzero cosine vector.
Do not silently pad, truncate, coerce or accept NaN/infinity/overflow.

For each completion, reacquire the writer lock and verify the current head,
generation, source identity, active state, canonical source digest, recipe/model,
job ID, worker token/fence and unexpired lease. Recompute the bounded expected
corpus under that lock. A changed source, model, job, lease or removed resource
must cause zero vector/provenance/acknowledgement writes for the old claim.

Publish vector replacement, its serialized-vector hash/provenance and the exact
job acknowledgement in one actual transaction. Delete a compatibility outbox row
only when it still names that same current job; never acknowledge by resource
ID alone. A stale worker must neither replace a current vector nor erase a newer
pending request. A SQL error after deletion/insertion must restore the previous
vector and leave pending work intact. Do not catch persistence errors and then
commit a partial result bundle. If batches use independent per-job transactions,
report the committed/stale/failed split explicitly.

Lease expiry/reclaim must advance the fence, retain unambiguous outcomes and
exclude a zombie completion. Define bounded retry/backoff for failed computation
separately from ambiguous DB commit acknowledgement. `commit_unknown` must not
trigger an automatic re-publication or resource-ID delete: use a fresh connection
to inspect the exact durable job, vector hash and provenance first. Do not claim
exactly-once embedding calls or infer permission for billable remote computation
from a local retry mechanism.

## Search freshness and public boundaries

Only dense candidates whose current head/job, source generation/corpus,
recipe/model and committed provenance agree may contribute a dense rank. A source
or model change must hide its older vector immediately, even before replacement.
Inactive/deleted, retired and quarantined resources remain excluded under the
existing policy. Recheck the same visibility and freshness rules for returned
detail rows in one bounded read snapshot. Keep FTS and vector freshness separate;
a stale dense hit is not permission to label an unrelated lexical hit as dense.

Retain the existing FTS/BM25/RRF behavior unless a separately tested compatibility
decision changes it. A fake vector test establishes storage/search invariants,
not semantic relevance, multilingual recall, recommendation quality or a vector
engine's parity with the private ASCII lexical index.

Embedding corpus is a separate outbound data purpose. Use only the declared
bounded fields and existing privacy protections; exclude credentials, visitor
profiles, raw connection/auth/tool payloads and private diagnostics. Test known
encoded credentials and source/connection URL boundaries. Do not promise a
universal secret/PII detector. Keep endpoint/model configuration server-owned;
do not add client-selected embedding URLs, model downloads or arbitrary extension
loading paths.

Public Chat's one-agent ranking, explicit/default protocol behavior, managed
gateway projection, English copy, metadata and privacy/payment-display rules
remain unchanged. Preserve public workflow, publication, SDK1.0/admin1.1,
literal SDK1.2 and connected SDK1.3 purpose/API/asset contracts. Do not enable RAG
answer generation in public Chat or expose model names, raw vectors, corpus,
paths, tokens or provider endpoints through public results. Native admin search
remains authenticated; the existing public Chat bypass of RAG generation must
remain covered by regression tests.

## Isolated acceptance and security evidence

Use fresh full-schema SQLite fixtures with synthetic admin bootstrap data and
explicit fake embedding injection. No project server, operating DB, actual
embedding/generation model, inherited credential or network listener is needed.
Use the installed trusted sqlite-vec extension and real virtual-table SQL for
the required dense/search checks; mocking the database or silently skipping a
missing extension does not satisfy that acceptance. Report an unavailable
dependency separately.

Required adversarial scenarios are:

- Delay fake embeddings while a second Store/SQLite connection changes source,
  category, schema/binding where relevant, active state or resource incarnation.
  Include exact A→B→A changes and identical enqueue timestamps with distinct jobs.
- Reserve/reclaim from two workers and finish the old worker last. Assert the
  new vector/head survives and the new pending job is not acknowledged.
- Submit malformed vectors, wrong batch counts/dimensions, booleans, zero cosine
  vectors and nonfinite/float32-overflow values. Assert no previous vector loss
  and no false successful acknowledgement.
- Inject errors after actual vector deletion/insertion, provenance write and job
  acknowledgement. Assert whole logical-state rollback. Inject acknowledgement
  failure after an actual commit, then reopen and reconcile without another
  embedding call or automatic replay.
- Exercise backfill and direct helper paths, category-only changes, deleted or
  deactivated resources, untagged old vectors, repeated jobs and model-descriptor
  mismatch. Test actual KNN/RRF reads with stale dense terms hidden and final
  visibility filters intact; include SQL-like query text and source privacy cases.
- Run relevant Store/collector/RAG/admin API regressions plus affected public
  browser/security/TLS and content/HTML/SDK invariants after one source freeze.
  Preserve initial failing evidence and identify fixture/harness corrections.

Reports should contain fixed aggregate counts, measured durations, exact native
SQLite/extension scope and explicit unavailable checks. Exclude raw corpus,
vectors, URLs, secrets, paths and unrestricted exception text. No synthetic score
or test count is an expert quality grade, production capacity result or security
certification.

## Separate follow-up gates

This source batch is a fenced legacy SQLite consumer/read integration. Actual
embedding service availability/response behavior and semantic evaluation require
their own approved provider/data run. A model replacement or dimension/recipe
migration requires an explicit new identity, isolated index/rebuild strategy,
coverage and relevance review, operator approval and rollback point; it is not
silently activated by changing a tag or reusing the old virtual table.

Whole-Store PostgreSQL wiring, legacy authority/ledger/privacy migration,
operating source ownership, worker drain, representative load/DR/HA and operator
cutover/rollback remain separate. The user controls their terminal-run server.
Do not stop/restart it during development; if this next implemented batch changes
loaded server source, request one restart only after its full review/verification.
This planning document itself requires no restart.

[Collector guard plan](LEGACY_OBSERVATION_GUARDS_PLAN.md) ·
[private fenced lexical artifacts](CATALOG_INDEX_ARTIFACTS.md) ·
[owned-copy contract](CATALOG_COPY_CONTRACT.md) ·
[cutover gates](CATALOG_CUTOVER_CONTRACT.md).
