# R&D design refinement — 2026-10-19

Design revision: **RND-2026-10-19-r1 / 2.0-draft.3**. Product baseline remains **v1.39**.

The supplied R&D proposal was compared with existing implementation and primary research/official protocol sources. The current main and phase-two designs, structured plans, remaining-work sequence and two existing Canvas artifacts were updated together. No product implementation or deployment was performed.

## Result

- Retained the nine current `POST139R-01~09` execution entries. Fifteen research subcontracts map into those entries; RQ tags and historical AC/R/N/B IDs do not introduce another execution queue.
- Made `P2-01-TYPED-EVIDENCE` the next source owner of a common lineage contract. Evaluation, monitoring, routing and later contribution analysis reference the same run/node/attempt evidence.
- Reused the typed executor, evaluation worker, execution journal, durable receiver, SDK2/BFF and TEST_UNIT ledger. Each subcontract records the new delta, one owner/artifact identity, source dependencies, actual-acceptance dependencies, entry/exit/stop conditions and validation focus.
- Added Action-MR/oracle/discrete reliability experiments, observable Dual-Clock shadow, narrowly gated early stopping and reviewed replanning. Unknown external outcomes never become automatic replay, provider replacement or another payment.
- Kept existing server-side SDK authority as the baseline; client private fields/freeze are optional robustness changes. Separated HMAC delivery acceptance from conditional new public asymmetric receipts and from quality/business/payment evidence.
- Separated protocol authorization, commitment, claim, settlement, finality, refund and payout. Real contractual settlement remains last; synthetic conformance preparation does not authorize money.
- Corrected current v1.38 planning/baseline wrappers to v1.39 while retaining historical records. Research percentages, a mismatched paper citation, funding qualifications and unsupported performance/security/financial guarantees are explicitly qualified.

## Validation

[verification.json](verification.json): **32/32 design consistency checks passed**. Package IDs, artifact ownership, dependency DAG, exact queue/cache equality, local Markdown links/anchors, actual reused paths, attachment digest and product-input immutability were checked.

[canvas-compile.json](canvas-compile.json): both existing Canvas artifacts compiled with zero warnings. Inline plans match final JSON originals. This is syntax/data consistency verification, not a new browser/runtime acceptance claim.

[final-independent-review.json](final-independent-review.json): no unresolved findings. One nonexistent reused-module reference was corrected and rechecked. The independent review covers the recorded document hashes; final Canvas synchronization is covered separately.

All **649** inputs in the accepted v1.39 source/test manifest remain unchanged. Historical **483** pytest cases, **63** native contracts and **22** restart-read samples were not rerun or added to these design checks. No secure-coding or dynamic product suite was repeated for documentation-only changes. Future source batches still require relevant secure-coding, isolated API/browser, native-parity and restore checks before closure.

No operating server probe/restart, database mutation, provider call, notification, payment, public Workspace activation or advertisement occurred. No additional user-server restart is needed. Actual IdP/provider/independent-evaluator/receiver/payment/operating-recovery acceptance remains dependent on designated targets. Official funding attachment eligibility was not fully reviewed and remains an application-time check.

## Authoritative artifacts

- [R&D supplement](../../docs/PLATFORM_RND_REFINEMENT.md)
- [Canonical research subcontracts](../../docs/platform-rnd-refinement.json)
- [Current single work sequence](../../docs/REMAINING_WORK_BATCHES.md)
- [Main design](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md)
- [Phase-two design](../../docs/PLATFORM_ADVANCEMENT_PHASE2_DESIGN.md)
- [Research/version audit](reliability-source-audit.json)
- [Protocol/security audit](protocol-security-source-audit.json)
- [Initial reuse comparison](reuse-gap-review.json): historical alias proposals only; the canonical subcontract file controls final mapping.

Source work and actual acceptance have separate gates. Prepare administrator/CI and environment ownership alongside common typed evidence; then reuse that evidence for MR/oracle and milestone shadow while auditing only necessary SDK gaps. Use one designated environment for actual quality/login/SDK/delivery/recovery acceptance. Promote narrow routing/intervention only with evidence, expand intent/long-task/own-agent profiles by demand, and leave real contractual settlement last. Do not require every research package or full PostgreSQL/HA before a narrow read pilot.
