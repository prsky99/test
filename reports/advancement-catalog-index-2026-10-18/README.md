# Fenced private lexical artifacts and bounded catalog shadow

2026-10-18 · v1.27 · actual scoped index, no operating Store/search/backend rollout.

Completed actual canonical artifact bodies, B-tree term postings, fenced atomic publication with existing outbox acknowledgement, exact AND/ID-ordered ASCII search and pure aggregate snapshot comparison. Current410 source/test/supporting files were frozen;401 prior files unchanged, one private outbox refactored, eight new Python files. Existing Store/collectors/frontend/SDK/requirements and server imports/routes remain unchanged. **This pilot requires no server restart.** Earlier v1.25 concurrent operating reflection remains unverified.

## Accepted evidence

**1,063 passed /116 new /0failure-error-skip**, one frozen affected32-module JUnit selection in91.41s. New cases are38core+43shadow+19independent+16PG; historical947/814/369/845/full2,878 and focused/RED/initial observations are not added. Existing projection/gateway/capability/runtime/usage/evaluation APIs, Chromium and local TLS are included. [JUnit](affected/regression.xml) · [log](affected/regression.log) · [case identities](test-reconciliation.json) · [source freeze](affected/source-freeze.json).

Actual SQLite/PostgreSQL14.22/psycopg3.3.6 passed22 strict checks in1960.112ms: body/posting/search equality, protocol/limit/current safety gates, removed terms, stale revision/model/lease, four atomic SQL fault boundaries per backend, real commit then injected lost acknowledgement, fresh read/reopen, tampered artifact/forged posting refusal and aggregate-only shadow. Private Unix-socket cluster stopped/removed; stderr empty; operating credentials not inherited. [Actual report](postgres-index-final.json).

Content66 source/maintenance files(not pages)/violations0, embedded HTML synchronized, legacy SDK/package11 and public4 unchanged. Eight new plus one modified Python compiled. New explicit private tables2; operating schema/routes/backend switches0. [Source checks](source-checks.json) · [all410 hashes](final-source-snapshot.json).

## Concrete security finding and review

Independent reviewers reproduced three encoded-credential cases which became searchable after decoding. Original3FAIL evidence remains [here](review-encoded-secret-reproduction.xml) and [independently here](index-projection-review-initial.xml). The fix normalizes combined HTML/percent encoding then reapplies public masking before tokenization. Final frozen review includes four encoded/mixed cases, raw secret/URL/email/tool omission and no provider/Registry call, forged self-consistent body refusal, persisted corruption, three accepted SQLite body/delete/posting failure boundaries and postcommit fresh-read recovery. [Independent review](independent-review.json). Initial observations remain separate in [verification](verification.json).

Final Bandit scope5 new/modified modules, raw **High0/Medium3/Low1**. Three source-owned fixed SQL construction sites and one synthetic unused private-trust password are reviewed, not suppressed or relabeled zero. [Scanner](static-final.json) · [triage](static-review.json). These selected checks are not certification of whole-platform vulnerability absence or a universal PII/secret detector.

## Explicit limits and next unit

The implemented search is ASCII2–32-character whole-word exact AND, at most128 unique document terms/8 query words/50 results, optional exact protocol and ascending resource ID. It is a declared portable B-tree lexical profile, not FTS5/BM25/sqlite-vec/vector/embedding/hybrid or recommendation relevance/latency parity. Artifacts remain private. Current coarse active/health/quarantine gates do not create execution/approval/quality evidence. Existing public recommendation/search behavior is unchanged.

Shadow compares only bounded supplied flat snapshots; source consistency/atomic capture, worker authority, artifact body/search quality and upstream truth are explicitly unassessed. It emits fixed aggregate counts, never raw IDs/keys/URLs/credentials/hash values, and never recomputes or adopts a legacy hash. Incomplete inputs retain null unassessed metrics. [Contract](../../docs/CATALOG_INDEX_ARTIFACTS.md).

Bounded AST inventory125 Python files/2726221bytes/4792 syntactic findings/122 unresolved SQL-call markers stayed within limits; this does not resolve every runtime receiver/transaction owner or establish migration completeness. [Inventory](storage-boundary-inventory.json).

Next: [observation ownership and consistent read-only capture/integration preparation](../../docs/CATALOG_INTEGRATION_PLAN.md). Actual legacy writers/search, full Store/auth/privacy/workflow/ledger/backend migration, operating cutover/replay/rollback and representative load/DR/HA remain gates. No operator server action, direct live DB write, provider/model execution, approval/grant or notification/marketing delivery occurred. G0/G1 remain open.
