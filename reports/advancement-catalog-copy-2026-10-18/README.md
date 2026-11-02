# Explicit owned-copy catalog migration rehearsal

2026-10-18 · v1.29 · named prospective subset; no operating import/cutover.

Completed exact source/target column checks, unsupported-domain gate, held source protocol fence, stable sparse IDs/keys/times/NULLs, stored legacy hash provenance, prospective revisions/baseline owner clocks, actual fenced artifacts and recovery/replay. Existing418 sources remain unchanged; six new Python files bring frozen scope to424. No server import/route, operating schema, Store/collector/frontend/SDK/requirements or backend switch changed. **This unit needs no restart.** Earlier v1.25 concurrent operating reflection remains unverified.

## Accepted frozen evidence

**1,290 passed /115new /0failure-error-skip**, one frozen affected39-module selection in85.89s. New74source+25independent+16PG cases; historical1,175/1,063/947/814/369/845/full2,878 and focused/initial/RED runs are not added. Existing projection/gateway/capability/runtime/usage/evaluation APIs, Chromium and local TLS are included. [JUnit](affected/regression.xml) · [log](affected/regression.log) · [unique cases](test-reconciliation.json) · [freeze](affected/source-freeze.json).

Actual SQLite/PostgreSQL14.22/psycopg3.3.6 passed24 strict applicable conditions in2139.349ms. Actual source→new target per backend; sparse ID7/41 and later new typed ID>41; legacy/proposed hashes and owner tombstones; no authority restoration; seven accepted-SQL logical rollback stages per backend; real commit then lost acknowledgement/fresh receipt; exact replay/refusal of changed source/populated target; source protocol writer exclusion; reopened capture/actual artifacts/search. Private Unix-socket cluster stopped/removed, stderr0, inherited operating PG credentials excluded. [Final actual CLI](postgres-copy-final.json). Sequence allocation is explicitly nontransactional; row rollback is not sequence rollback or gap-free allocation.

All424 source hashes held fixed, prior418 unchanged/new6 compiled. Content66source/maintenance files(not pages)/violations0, embedded HTML synchronized, SDK11/public4 unchanged. Two private target provenance tables/four synthetic source tables, new operating tables/routes0. [Source checks](source-checks.json) · [hashes](final-source-snapshot.json).

## Concrete fixes and security

Preserved authentic failures for hidden extra source metadata/control rows, duplicate manifest and target control cardinality, known credential patterns including a generic text field, mutable cached source bypass, and actual target affinity converting stored original hash or ID. Reused reproductions are not summed as distinct findings/test totals. The fix validates all declared column sets/cardinalities, refuses known credential-bearing text, reloads actual held source data and validates each actual INSERT RETURNING tuple before committing. [Independent review](independent-review.json) · [initial/final artifact inventory](verification.json).

Bandit3newmodules raw **High0/Medium14/Low1**. Fixed source-owned schema/column/table lists and fixture queries14, synthetic unused local-trust password1 were independently reviewed, not suppressed or relabeled zero. [Scanner](static-final.json) · [triage](static-review.json). Scoped checks are not whole-platform vulnerability certification.

## Supported scope and unassessed gates

The source is an explicit44-column/four-table synthetic profile, not all67 known operating resource fields or all Store tables. Seven excluded domains require declared zero; nonzero/unknown refuses import. A zero declaration is not a full operating inventory. Original hash/NULL is preserved separately from prospective strict hash. Baseline heads refer to copy receipts and mappings, not invented observation/execution/evidence/approval rows. Target remains disabled; no authority/session/grant/eligibility is restored.

SQLite BEGIN IMMEDIATE provides an actual writer reservation. PostgreSQL sourcecontrol row locks only cooperating writers. Source data rows are unchanged, but its reservation transaction is not native read-only; cross-DB atomicity/all-runtime-writer exclusion are explicitly false. Known credential detection is bounded and conservative, not a universal secret/PII detector. Source epoch5→revision6 is declared fixture mapping; synthetic old-generation and invalid-token tests are not proof that actual operating worker leases were drained. [Contract](../../docs/CATALOG_COPY_CONTRACT.md).

Bounded AST inventory130Python/2795856bytes/4792syntactic findings/122unresolved SQL markers is not all runtime receiver/transaction or full migration coverage. [Inventory](storage-boundary-inventory.json).

Next: [current Store/collector observation generation guards](../../docs/LEGACY_OBSERVATION_GUARDS_PLAN.md). Actual full67-field/subsystem mapping, operating source/target writer inventory, authentication/privacy/ledger/FTS/vector, operator cutover/rollback and representative load/DR/HA remain gates. No operating server/DB action, provider/model task, approval/grant, notification or advertising occurred; G0/G1 remain open.
