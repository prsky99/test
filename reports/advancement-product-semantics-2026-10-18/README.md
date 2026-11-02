# Product semantics v2 — source and isolated verification

2026-10-18 · v1.22 · contract `products.compare.v2` · inspector `product-semantics-v2`.

One coherent batch adds bounded product identity/variant, exact typed units, declared currency/price basis, source and UTC evidence, explicit missing/partial handling, private schema/API/native inspector and strict explicit v2 approval/test boundaries. It preserves v1 and existing news/docs execution, one-alternative policy, public frontend and all SDK package bytes.

## Actual scope

- Seven bounded dimensions and exact decimal factors distinguish SI/decimal storage from binary storage. Original quantities, declarations and monetary evidence remain visible. Different dimensions/currencies/bases/observation instants do not silently compare. No FX, per-unit price division, implicit rounding, missing-to-zero, truth/expert grade or winner is produced.
- The ten-code project currency allowlist does not claim complete ISO4217/minor-unit validation. Retrieval is at most24h old; evidence may precede retrieval by24h (up to48h before inspection). Exact UTC instants, not their spelling, determine temporal compatibility. Unknown product attributes, tax/shipping and real identity/source accuracy remain outside this bounded contract.
- Offline input/output samples are never saved or used as live callable/contract evidence. No DNS/source fetch, provider/model call, execution, approval, publication or grant occurs in inspection. Metadata approval counts are not provider readiness. Current-active highest-admin, same-origin/CSRF, strict duplicate/nonfinite/size/depth/node validation, fixed private errors and no-store apply.
- Existing explicit private v2 approval and live tests remain separate: exact full/compact selected tool/schema/hints, current real execution proof and version/approval consistency. V2 approval rechecks current role under a SQLite writer lock. Raw browser JSON is preserved on both sample and explicit v2 test routes so duplicate/escaped-equivalent keys reach strict server rejection. Existing v1 routes and data retain their behavior.
- Product compiler, product fallback/cascade, public product comparison and SDK integration remain disabled pending actual current providers, reviewed semantics and separate permission. No arbitrary pasted sample is shown as a retained signed product execution.

## Verification

**2,878 passed / failure,error,skip0** in the final source-frozen broad selection of 137 modules (1051.78s). **Unique latest 2,878; 263 new against v1.21**. Focused suites overlap this run and are not added. [JUnit](broad/regression.xml) · [log](broad.log) · [case reconciliation](test-reconciliation.json).

All 372 scoped application/test/supporting-source hashes remained frozen. Public content66 source/maintenance files (not pages),0violations; embedded HTML synchronized. Eleven SDK/package and four main/public-connection sources are byte-identical to v1.21. Five Python modules compile and public3/admin1 inline scripts parse. [Source checks](source-checks.json) · [hashes](final-source-snapshot.json).

Bandit scope is five Python modules: **High0 / Medium14 / Low16**. Every flagged code excerpt matches the retained input baseline, all in existing administrator code; new core/service and changed contract/registry modules have0 findings. This scope differs from earlier reports. [Scan](bandit-final.json) · [individual triage](static-triage.json). Static and isolated dynamic tests are not proof of whole-platform absence of vulnerabilities or real provider quality.

Independent tests cover hostile Decimal/default contexts, exact arithmetic/original preservation, explicit temporal/currency/basis mismatches, typed bounds, missing/partial, multicast/private/credential URLs without DNS, literal XSS, sessions/late responses/logout, duplicate/escaped JSON keys, role withdrawal and actual isolated gateway/contract execution. The broad suite also revalidates existing durability/unknown, release/SDK/automation/restore and PG state-rehearsal behavior; no new DB table or full PostgreSQL adapter is introduced.

## Findings and retained observations

Initial actual isolated ManagedGateway v2 integration failed because the generic credential redactor correctly masks the field `key`. Only the new, undeployed contract was renamed to `criterion_id`; shared masking/projection and v1 were preserved. Failed malformed provider output cannot become input-only success. Known platform invocation gateway URLs cannot masquerade as original evidence sources.

Independent review also closed raw UI duplicate-key loss on both new inspection and existing v2 explicit-test inputs, legacy system-token role-label reliance, guarded approval-write concurrency, inherited multicast address classification, and mutable global/default decimal-context effects. The final semantic review also reproduced distinct submicrosecond timestamps collapsing to one inherited datetime value; v2 now refuses unsupported precision (at most six fractional digits), preserving v1. The initial broad run was interrupted early, retained as broad-interrupted-before-time-guard and excluded from pass totals. The complete broad run reported here uses the final frozen source. Evidence of initial observations is preserved rather than relabeled as final passes. Early core test code also used the wrong existing `dataset` column (correct `dataset_version`); a hidden native-option Playwright disabled-state assertion was replaced with its actual DOM property after confirming the product state. The independent writer-lock test initially used a separate in-memory database; only its fixture was corrected to a disposable file Store before proving the second connection was writer-locked. Immediate-scroll screenshot capture was settled for two animationframes after verifying the sticky Close control hit-test.

[Observed initial suites](verification.json) · [frozen schema/unit/currency snapshot](core-contract-snapshot.json) · [inspector screenshot](admin-product-inspector.png) · [normalized sample screenshot](admin-product-normalized-sample.png). Screenshots show fabricated isolated test samples, not operating product facts.

## Operating limits and next work

After user restart/refresh, authenticated v1.21 automation dialog/profile code and normal workflow screen were present; storage anonymous GET403/no-store, public list200/no-store and missing release404/no-store. No operating approval, provider/model task, publication/deployment/automation grant, run or delivery was created. New product v2 backend/UI requires one batch-end user restart and authenticated acceptance. [Read-only observations](restart-readonly.json).

No user-server operation, direct operating DB mutation, actual provider/model task, operating approval/grant or notification/marketing send was performed. Isolated fixture servers/Chromium and PG processes are verification only. One user terminal restart and administrator refresh is needed for new Python. Thereafter safe inspection can be accepted without inventing provider evidence.

Next independent source batch: reuse the existing retention, backup, quarantined restore and private inventory tools in a bounded reproducible mixed-purpose load/recovery/disposable-compaction rehearsal. [Next batch plan](../../docs/STORAGE_DR_LOAD_REHEARSAL_PLAN.md). Actual expert/source/access/pre-run allocation, approved operating product integration, full Store/catalog/FTS/auth/collector/ledger PostgreSQL adapter/cutover/HA and organization/ledger/support remain separate. Full R-07/AC-08/G0/G1 are open. [Contract](../../docs/WORKFLOW_PRODUCT_SEMANTICS.md) · [remaining batches](../../docs/REMAINING_WORK_BATCHES.md).
