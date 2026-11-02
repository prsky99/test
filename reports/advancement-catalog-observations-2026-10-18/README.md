# Owned catalog observations and consistent read-only capture

2026-10-18 · v1.28 · private supported profile, no operating writer/backend cutover.

Completed typed health/survey/evaluation owners, monotonic per-owner/retained clocks and revision CAS, atomic cache/index invalidation/owner receipt, native read-only repeatable capture, aggregate comparison and explicit integration/rollback gates. All410 prior source/test/support files remain unchanged; eight new Python files bring the frozen scope to418. No server imports/routes, operating schema, Store/collector/frontend/SDK/requirements or backend selectors changed. **No server restart is required for this unit.** Earlier v1.25 concurrent live reflection remains unverified.

## Accepted evidence

**1,175 passed /112 new /0failure-error-skip**, one frozen affected36-module selection in80.18s. New37core+37capture+22independent+16PG; historical1,063/947/814/369/845/full2,878 and initial/focused/RED runs are not added. Existing projection/gateway/capability/runtime/usage/evaluation APIs, Chromium and local TLS are included. [JUnit](affected/regression.xml) · [log](affected/regression.log) · [unique cases](test-reconciliation.json) · [source freeze](affected/source-freeze.json).

Actual SQLite/PostgreSQL14.22/psycopg3.3.6 passed23 strict applicable contracts in1577.246ms. Includes independent owner clocks, survey/evaluation freshness, unchanged registry/corpus/model/immutable history, current eligibility/index invalidation, four connections/one CAS winner per backend, six accepted-SQL rollback boundaries per backend, real commit then lost acknowledgement/fresh reconciliation, paused-write inspection, actual writer interleaving during repeatable capture and aggregate cross-backend comparison. Private Unix-socket cluster stopped/removed, stderr empty, inherited operating PG credentials excluded. [Actual CLI report](postgres-observations.json). These small contracts establish no operating throughput/HA or source clock attestation.

NewPython8 compile; content66 source/maintenance files(not pages)/violations0; embedded HTML synchronized; legacy SDK/package11 and public4 unchanged. New private tables2, operating tables/routes/backend switches0. [Source checks](source-checks.json) · [all418 hashes](final-source-snapshot.json).

## Concrete fixes and security scope

Two independent failures showed successful/failed surveys leaving prior evaluation freshness active; [original2RED](review-evaluation-freshness-reproduction.xml) retained. Root also reproduced a retained survey timestamp without a new owner head allowing an older assessment; [original1RED](retained-survey-reproduction.xml) retained. The fix tombstones eval_at without changing grade/history/owner clock, and enforces both survey-head and retained-stamp dependencies. Final cases cover those fixes and7independent accepted-SQL faults, native SQLite CAS and actual postcommit fresh-read/replay. [Independent review](independent-review.json).

Capture's initial harness wrongly treated the fixed limit label resources as leaked data; its assertion was narrowed to SQL/driver/private-value leakage, with initial failure and full37-case final rerun preserved. It was not a product defect. All initial artifacts are enumerated separately in [verification](verification.json).

Final Bandit4newmodules raw **High0/Medium5/Low1**. Five fixed source-owned SQL construction sites and one synthetic unused local-trust password were independently reviewed, not suppressed or relabeled zero. [Raw scanner](static-final.json) · [triage](static-review.json). These selected static/dynamic checks do not certify whole-platform vulnerability absence.

## Deliberate supported limits

Owners are trusted private inputs; no actual provider provenance, clock attestation, execution/approval/independent quality evidence, trial/auth/commercial update or legacy random retirement/scheduling behavior is supplied. Registry ID/first-last sighting/hash/corpus/model and immutable histories remain intact. Owner-clock receipts store raw private bounded canonical payloads, not public DTOs or encrypted secret storage. [Ownership contract](../../docs/CATALOG_OBSERVATION_CONTRACT.md).

Capture reads selected44resource fields and4index metadata tables only, at most100resources/500metadata-kind/1000totalrows/2MiB,16KiBscalar; driver decoding happens before adapter bounds and no CPU/latency guarantee is made. Unsafe schema/shadows/isolation/limits return no raw partial capture. Each source is individually read-only/repeatable, never an atomic shared cross-DB instant. Owner clocks/journal/authority, artifact body/search quality, all legacy fields and upstream truth are unassessed. Aggregate output contains no raw URLs/credentials/keys/hash values.

Bounded AST inventory128 Python files/2761123bytes/4792syntactic findings/122unresolved SQL-call markers is not full runtime receiver/transaction or migration coverage. [Inventory](storage-boundary-inventory.json).

Next: [owned-copy migration rehearsal](../../docs/CATALOG_COPY_REHEARSAL_PLAN.md) under [explicit integration/cutover gates](../../docs/CATALOG_CUTOVER_CONTRACT.md). Operating legacy writers/search, full Store/FTS/vector/auth/privacy/workflow/ledger migration, reviewed source/target/cutover/rollback, representative load/DR/HA and real people/provider acceptance remain separate. Operator server actions/live DB writes/provider-model tasks/approvals/grants/notifications/advertising0; G0/G1 remain open.
