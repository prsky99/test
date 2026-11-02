# Atomic private catalog writer and revision-bound index intent

2026-10-18 · v1.26 · private single-resource profile; no operating Store/index migration.

The planned coherent unit is complete: strict typed registry upsert, stable ID/revision/CAS, durable operation receipts, atomic current-cache invalidation/index intent, fenced metadata completion, actual SQLite/PostgreSQL concurrency/failure verification and scoped security/API/browser regression. Existing394 source/test/supporting bytes remain unchanged; eight Python files are new. **This pilot itself needs no server restart.** Earlier v1.25 concurrent Store/survey live reflection remains unverified; this turn did not introduce new drift or perform operator-server actions.

## Accepted frozen evidence

**947 passed /133 new /0failure-error-skip**, one frozen affected28-module selection in79.28s. New cases belong only to four newly added modules(52core+47outbox+18independent+16PG); historical814/369/845/full2,878 and focused/initial runs are not added. Includes existing public/private projection, gateway/authority APIs, Chromium/TLS, read/adapter and runtime/usage/evaluation compatibility. [JUnit](affected/regression.xml) · [log](affected/regression.log) · [case identities](test-reconciliation.json).

All402 source/test/supporting hashes stayed frozen; prior394 bytes unchanged. NewPython8 compiled, content66 source/maintenance files(not pages)/violations0, HTML synchronized, SDK11/public4 unchanged. Seven tables belong to the explicit disposable/private schema only; new operating tables/routes/backend switches0. [Source checks](source-checks.json) · [hashes](final-source-snapshot.json).

Actual final PostgreSQL14.22(version140022)/psycopg3.3.6 passed22 strict checks in1525.019ms. Each backend uses four connections for fresh same-key creation and existing-key CAS update races, with one winner, stable identity and matching receipts. A real commit is followed by an injected acknowledgement exception; a separate connection reconciles the durable result and explicit same-op replay adds no new logical write. Private Unix-only cluster stopped/removed, stderr empty, no inherited operating PG credentials. [Actual report](postgres-writer-final.json). These small contracts are not operating throughput/HA or gap-free sequence guarantees.

## Concrete findings and security

A root source review corrected nonfinite JSON being converted to null before the command tests were run; no failing test artifact is claimed for that pre-test correction. Root's strict refusal cases now cover NaN/infinities, duplicate keys, oversized/deep JSON and exact numeric/time domains.

A concrete outbox model-change reproduction failed: per-model heads left an old model projection eligible after a newer model/revision. The corrected profile has one current active model/head per resource, refuses different model/corpus at the same revision, supersedes older jobs across models and hides old projections. The original failing [reproduction](outbox-model-race-initial.xml), earlier model-separation assumption and final scoped tests are retained, not counted as additional successes. [Independent writer review](independent-review.json) covers eight accepted-SQL failure boundaries and complete logical rollback, excluding native sequence counters.

Raw Bandit scope is four new modules **High0/Medium5/Low1**, errors0. Four B608 warnings compose trusted registry column/placeholder lists; one reads a fixed function-local fixture table/order allowlist. All values are separate bound parameters, with no request-selected identifier/clause. The B106 password is synthetic unused local-trust fixture data. No suppressions or raw0 claim. [Raw scan](static-final.json) · [independent triage](static-review.json). This is not whole-platform vulnerability certification.

## Delivered behavior and intentional differences

[The contract](../../docs/CATALOG_ATOMIC_WRITER.md) separates strict normalized registry fields from observation-owned payloads and legacy hash/truncation rules. A schema-default disabled write control is explicitly enabled only in fixtures; it is not a public authentication scheme. PG control-row locking and SQLite BEGIN IMMEDIATE serialize this profile's writers. Different exact keys are not merged by URL. Explicit observed_at0 is valid, last_seen never moves backwards, ID/first_seen remain stable and generated IDs use RETURNING.

A single transaction commits the resource, revision/hash profile, current eligibility deletion, current index head/job and immutable success/conflict receipt. Equal content still advances revision/intent; exact operation replay returns the original result without another mutation. Different payload/preconditions under a used ID are refused. Immutable agent/version/approval/evidence history and raw observation/schema/grade payloads remain; they do not become fresh verification. Unversioned legacy rows are refused rather than silently adopted. The new writer does not implement legacy atomic page batches or every Store/reset/constraint behavior.

Mid-write faults at eight independent accepted-SQL boundaries and four native fixture boundaries per backend roll back the logical unit. Commit uncertainty stays commit_unknown, disables the adapter and performs no automatic retry/reconnect. A missing reconciled receipt is only a current observation; it cannot prove an in-flight commit will never appear. Model/corpus/revision, owner/token/fence/lease prevent a stale index worker from publishing or acknowledging newer work. Failures remain fixed terminal states and are not silently retried.

**Indexed projections are hash metadata only.** No actual FTS/vector, embedding, model computation or artifact body is materialized. No search ranking, factual/provider quality or full Store compatibility is inferred. Caller-supplied clocks/model declarations and private Python connections are trusted inputs, not externally attested time or public authorization. Existing public projection still hides bindings/secrets and preserves independent citations; commands/results/claims have private repr and are not public DTOs.

The current bounded static inventory scans122 Python files/2690589bytes/4792 syntactic findings with122 unresolved SQL-call markers. Source hashes match; no operating DB/config/network or source SQL/value output. It does not resolve every runtime receiver/alias/transaction owner or establish migration completeness. [Inventory](storage-boundary-inventory.json).

## Operating limits and next batch

This batch changes no Store/collector/server/frontend/SDK/dependency source and adds no server import/route/schema. No new operating UI/API acceptance or direct live DB writes/provider/model tasks/approvals/grants/notifications/marketing occurred. Prior v1.25 concurrent-source live reflection remains a separate unknown; previous v1.22 authenticated UI evidence remains historical. All new faults, SQL changes and PG lifecycle actions are isolated synthetic fixtures.

Next: [fenced actual index artifacts and read-only catalog shadow reconciliation](../../docs/CATALOG_INDEX_CONSUMER_PLAN.md). Legacy single write ownership, collectors/admin/public registration/health/survey/evidence integration, actual FTS/vector/search parity, full Store/auth/privacy/workflow/ledger migration, operating cutover/rollback/representative capacity/DR/HA and real human/provider acceptance/R-07/AC-08/G0/G1 remain separate. [Design](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md) · [remaining order](../../docs/REMAINING_WORK_BATCHES.md).
