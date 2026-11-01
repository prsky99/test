# Fenced private lexical artifacts and bounded catalog shadow

2026-10-18 · v1.27 · explicit private adapter/fixture implementation.
No operating catalog, search, schema or backend is switched by these modules.

## Materialized contract

`agent_market/catalog_index.py` implements `CatalogIndex.build`, `publish`,
`artifact` and `search`. `ARTIFACT_SCHEMA` is explicit caller-owned DDL; imports
and constructors open no database and create no tables. The existing atomic
writer and outbox remain the only registry/revision and index claim boundaries.
The outbox's old `complete` method still acknowledges metadata only; it does not
claim that an actual artifact exists.

The new artifact contains canonical ASCII JSON with exactly profile, resource ID,
revision, raw corpus hash, declared model/recipe hash, kind and sorted unique
terms. Its SHA-256 binds the complete document. The separate raw corpus hash
continues to bind `registry-text-corpus-v1` plus kind/name/description/category;
it must never be confused with the sanitized artifact digest. The model hash
names the lexical recipe and Unicode word-boundary version, not an embedding
model, provider execution, quality grade or authority attestation. Future recipe
changes require an explicit new identity and new revision-bound work.

The recipe projects the selected public fields through `public_agent` without a
Store, normalizes HTML/percent encoding in three bounded combined passes, applies
public credential/visitor-token masking again, removes HTTP/WebSocket URLs and
email spans, and extracts English ASCII whole words starting with a letter and
containing 2–32 letters/digits. It lowercases and deduplicates terms. It refuses
more than128 terms instead of silently truncating. Canonical JSON is limited to
12KiB. URL, auth, details, connection bindings and tool payloads are not corpus
fields. Known credentials and contact/connection spans are tested exclusions;
this is not a universal detector for unlabeled secrets, personal names, arbitrary
encodings, hostnames without schemes or multilingual meaning. The artifacts and
API remain private.

SQLite and PostgreSQL use the same bounded lexical posting table and B-tree
lookup, rather than FTS5/BM25, sqlite-vec, stemming, semantic vectors or hybrid
ranking. A query accepts1–8 ASCII words, up to256 characters, uses exact AND
membership, optional exact A2A/MCP/x402 kind, ascending stable resource ID and a
limit1–50. Repeated words collapse after the input-word bound. The result is only
private ID/revision/kind/matched terms. Existing public recommendation ranking,
fresh verification and protocol selection remain unchanged.

## Atomicity, recovery and reads

Build reads the current revision/corpus/model and creates a bounded proposal
outside the write transaction. Publish validates document/recipe/scope, reuses the
existing head lock and exact job/worker/token/fence/lease checks, recomputes the
bounded expected projection, and commits job acknowledgement, metadata, actual
artifact body and complete term replacement in one adapter transaction. There is
no file/vector write outside that transaction and no provider/model/network task
inside it. A stale or superseded worker cannot replace a newer artifact, clear its
terms or acknowledge newer pending work. Advancing the head immediately hides
older artifacts even before replacement; deleted terms are removed on publish.

A storage error rolls back all those mutations. A commit acknowledgement failure
remains `commit_unknown`, poisons that adapter and is never automatically retried.
A fresh connection inspects the durable job/artifact before any caller decision;
replaying the consumed claim cannot rematerialize it. Failure/lease/reclaim retain
the existing outbox states; no automatic worker, retry loop or server task is
installed.

Read/search join the current writer revision, single active head, indexed job,
projection hash and artifact identity. They validate the canonical body and
recompute the expected sanitized document from the current bounded source row.
Search additionally checks actual query membership in that document, so forged
postings cannot create a false positive. Current active status, healthy/reachable
health and non-quarantine status are checked on every search. These coarse gates
do not constitute execution permission, fresh callable evidence, contract success
or recommendation eligibility. The existing gateway still supplies those checks.
Malformed or oversized selected rows fail closed rather than return raw data.
The adapter's result limits remain effective; this pilot establishes no operating
latency, throughput, recall, relevance or whole-Store search parity guarantee.

## Read-only shadow comparison

`catalog_shadow.compare_snapshots(source, candidate, expected_model_hash=...)`
accepts explicit flat tuple/dict snapshots only. It opens no database, path,
network, Store or configuration and mutates neither input. Bounds are100 resources,
500 rows per metadata kind,1000 total rows,2MiB per snapshot,16KiB per scalar,
64 fields per row and50000 cells. Invalid input returns fixed incomplete status
and null unassessed metrics, with no partial success claim.

The report contains only fixed aggregate fields. It compares stable IDs/keys,
first/last observation times, activity, registry normalization and observation
ownership, then checks proposed hash/corpus/model/revision/head/current job and
projection intent. Stored legacy hashes are compared as stored; they are never
recomputed, rewritten or adopted. Expected profile replacement is distinguished
from other stored-hash differences. Empty snapshots are explicitly labeled.
Completeness means bounded analysis completed, not source equivalence or cutover
readiness. Atomic source capture, worker/lease authority, artifact body/search
quality, upstream truth and unselected legacy fields are explicitly unassessed.

## Verification and remaining gates

[Final evidence](../reports/advancement-catalog-index-2026-10-18/README.md)
records actual disposable SQLite/PostgreSQL execution, stale revision/model/lease
and fence refusal, artifact/posting corruption, rollback and commit uncertainty,
privacy regression and affected browser/API/TLS checks. An encoded-credential
failure was reproduced before the post-normalization redaction fix; both failed
and accepted evidence are retained.

v1.28 delivers [private observation ownership and repeatable capture](CATALOG_OBSERVATION_CONTRACT.md)
and [explicit cutover requirements](CATALOG_CUTOVER_CONTRACT.md). Existing writers
and search still require reviewed supported mapping and operating integration. This implementation does not launch a worker, open an operating database,
activate PostgreSQL, adopt unversioned rows, certify legacy evidence or change
public frontend/SDK behavior. Full Store/auth/privacy/workflow/ledger migration,
representative load, DR/HA and G0/G1 remain separate.

[Writer/outbox](CATALOG_ATOMIC_WRITER.md) ·
[observed legacy write contract](CATALOG_WRITE_MIGRATION_CONTRACT.md) ·
[remaining work](REMAINING_WORK_BATCHES.md).
