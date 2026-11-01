# Current Store observation generation guards

2026-10-18 · v1.30 · source implemented; isolated acceptance recorded in the linked report.

The existing SQLite Store and real health/MCP/A2A/auth collectors now share a
pre-work generation fence. This integrates the current 67-field Store; it is not
activation of the separate private PostgreSQL/catalog repository or copy importer.

## Reservation and application

`Store.observation_guard(id, owner, expected_resource=row)` reserves an owner
sequence under native `BEGIN IMMEDIATE` before external work. It compares the
actual current resource with the snapshot used for that work. The private frozen
token carries resource ID, owner, generation, sequence, start time, bounded snapshot
hash and a random per-Store issuer. It is an internal concurrency ticket, never a
public authentication credential or execution/quality attestation.

Two separate metadata tables retain generations and health/survey/auth/evaluation
owner heads. They do not add fields to `resources.*` or public projections.
Generations survive resource deletion; reinsertion increments the previous fence,
so an A→B→A change or ID reuse cannot revive an old token. The trigger covers the
30 selected registry/binding/schema fields and additional capability/auth check,
health-status and trial dependencies. `last_seen` refreshes and scheduling-only
`next_check_at` leases do not change binding generations. A health-status change
conservatively fences in-flight assessments; unrelated owner clocks otherwise
remain independent. A reservation is durable even if its external work fails:
latest-started tracked work wins, and an older result is discarded rather than
rebound to a freshly loaded resource.

`Store.observation_transaction(token)` takes the native writer lock and requires
the same issuer, resource generation/hash, latest reserved sequence, unused
sequence and nondecreasing owner completion time. It holds that lock across the
complete local result bundle, including schema, authentication, quality, FTS,
vector intent and Registry evidence writes. External HTTP stays outside it.
Nested `Store.tx()` calls use savepoints inside this context instead of committing
the parent. A failed nested operation poisons the whole bundle even if a caller
catches its exception. Accepted SQL, failed savepoint release and outer exceptions
roll back the logical bundle and owner consumption. An error after commit is
uncertain: this Store handle refuses further guarded observation work; it never retries
the provider or automatically reapplies the token. A fresh Store cannot use the
old issuer. This is not a proof of exactly-once provider execution.

## Ownership and freshness

Supported existing `record_health`, `record_capability`, `record_auth`,
`record_usage`, `record_evaluation`, auth signals and scavenger writes retain their
call signatures. Unguarded compatible writes advance their owner head, invalidating
older tracked work. Arbitrary direct SQL is not thereby converted into a guarded
observation API. The generation trigger detects selected dependency changes,
including direct binding SQL; it does not establish provenance for every legacy
writer or timestamp. Existing transactions outside guarded bundles keep their
legacy nesting behavior.

Health reachability/history does not create callability evidence or approvals.
Observed authentication retains the discovery handoff; a successful unauthenticated
connection probe preserves an already known tool-level authentication requirement.
Provider quotes use an
explicit registry upsert/hash path rather than silently changing a registry amount
under an old hash. Existing machine quote behavior is preserved; no price copy is
added to Chat. Survey failure retains prior payload/history but clears quality
freshness and eligibility. Every survey application advances the dependency fence,
including repeated failure, so an earlier standalone evaluation cannot restore
freshness. A successful tracked survey without a complete schema clears the old
full schema even when its compact tools hash is unchanged. A legacy unguarded
same-compact caller retains its deliberately supported old schema behavior.
A pure assessment computation failure may preserve a valid survey as an explicit
review-required result: old assessment history remains, freshness/eligibility are
cleared, quarantine is never weakened, and no new grade is counted. SQL or Registry
persistence failure still aborts the entire result bundle.
Removing the last tool rebuilds FTS from registry name/description and enqueues a
new vector intent; obsolete tool terms no longer remain searchable. Immutable
version/evidence/approval records are preserved rather than rewritten or imported
as new success. Synthetic tests do not represent provider or expert quality.

## Collector coverage

- Health single/batch checks, result-dependent postponement, retired scavenger
  revival/failure. Initial scheduling claims remain separate from observations.
- MCP capability/usage/trial Registry/evaluation, including atomic storage failure
  handling; A2A card/category/discovered MCP/auth/usage/evaluation bundles.
- Auth discovery success/failure and static MCP/x402 evaluation.
- Tokens are captured after per-host waits and before the actual external work;
  stale snapshots can be refused before any provider request. `accepted`, `stale`,
  `postponed` and `record_error` distinguish persisted observations from discarded
  or scheduling-only results. These counters are operational diagnostics only.

## Verification and release boundary

[Batch evidence](../reports/advancement-legacy-observation-guards-2026-10-18/README.md)
records genuine pre-fix failures, full-schema SQLite faults, native accepted SQL
rollback, real mocked-transport collector flows, API/Chromium/TLS regressions and
unaltered SDK/frontend contracts. Exact source hashes and independent concurrent
changes are recorded separately. This is a bounded affected suite, not whole
platform vulnerability certification, operating provider execution, a Redis
cluster test, or full PostgreSQL Store/authority migration.

The user controls the terminal server. No operating server or database was changed
by this batch. These server-imported source changes require **one user-controlled
restart at the batch end**; normal Store initialization installs the two private
metadata tables/triggers. Authenticated operating acceptance, worker drain,
representative load/DR/HA and G0/G1 remain open. No manual operating migration or
backend switch is performed here.

Next independent source unit:
[current vector index publication and acknowledgement guards](LEGACY_VECTOR_INDEX_GUARDS_PLAN.md).
[Owned-copy proof](CATALOG_COPY_CONTRACT.md) ·
[cutover requirements](CATALOG_CUTOVER_CONTRACT.md) ·
[remaining order](REMAINING_WORK_BATCHES.md).
