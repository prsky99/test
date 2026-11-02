# R-07 recorded paired comparison — v1.12

2026-10-18 · read-only comparison source implementation; authenticated live acceptance remains separate.

## Restart observation and implemented work

The user restarted the server. Read-only checks observed listener PID 64849 started `Sun Oct 18 10:34:11 2026`, local Home/admin UI HTTP 200 with CSP and expected prior composer UI markers. Anonymous maintenance/fallback-control and existing composer generation/publication calls returned 403. The live fallback switch remained off with zero policies. These checks confirm basic reachability and access refusal, not authenticated functionality or full G0/G1. Evidence: [restart observations](restart-readonly.json).

The next R-07 unit is a formal recorded comparison/evaluation interface. The workflow menu's **Compare completed tests** dialog compares two completed administrator tests of different compiled agents with the same contract and identical input, including the exact news period. It verifies snapshot, node binding, stored execution authority/principal and checkpoint signatures/scope; evaluates output contracts at the signed observation time; and separately reports current definition/approval equality and present eligibility.

The view displays recorded node latency, result/distinct-source counts, partial status, source hosts/titles/timestamps/document versions and news dates, plus source overlap. Failure/unknown/missing certainty/evidence do not become successful results or zero-quality scores. There is no automatic winner, factual-accuracy claim, relevance grade, evidence promotion, publication or new model/provider invocation. This is recorded evaluation, not active paired-call orchestration or an expert benchmark.

The new evaluator uses a consistent read-only SQLite connection (scoped savepoint for memory stores), bound SQL IDs, bounded metadata/definition/checkpoint reads and no version/key/recovery initialization. The recent inventory returns at most 30 entries from 100 selected records. Normal runtime initialization adds a `(source, created DESC)` index; there is no new table or persisted comparison record. Existing 27-table state inventory and SDK profiles are unchanged. Private APIs require highest-admin authentication and no-store responses; public routes remain absent.

The native dialog preserves the builder and survives workflow refresh. It renders provider text through text nodes; source URLs are not returned or fetched. Changing a selection, closing, refreshing or expiring authentication invalidates old responses; private state is cleared and no comparison is persisted in browser storage. New tests demonstrate XSS refusal, stale-response/session isolation, historical expiry versus current eligibility, news-period matching, missing/unknown evidence, read-only behavior and proof tamper refusal.

The implementation contract and next work are in [WORKFLOW_COMPARISON.md](../../docs/WORKFLOW_COMPARISON.md). Full R-07 typed dataflow/larger graphs, active paired execution, expert/holdout datasets and broader approved-provider evaluation remain next. SDK/automation consent, product/cascade contracts and full PostgreSQL/application/operations adaptation remain later steps.

## Verification evidence

**1,324 broad cases passed** and **108 final affected cases passed**, including **36 new comparison cases**. The ordered JUnit classname/name reconciliation yields **1,334 unique latest passes, zero failed/error/skipped**. The broad run preceded the last recent-index/refresh case; the final affected run verifies those scoped changes. Counts overlap and are not summed. No final full broad rerun was made.

Final test counts and machine reconciliation are recorded in [verification.json](verification.json) and [test-reconciliation.json](test-reconciliation.json). The initial 35 comparison cases passed; the final affected set includes the added recent-index case and all compiler/runtime/admin SDK paths. Overlapping runs are never added. Source-trial defects found early (missing projection reference and `node_id` checkpoint-field mapping) were corrected before integration acceptance; final evidence uses the corrected implementation.

The current evidence includes:

- [Broad frontend/admin/workflow/security regression JUnit](broad/regression.xml).
- [Final affected comparison/compiler/runtime/SDK set](final-affected.xml).
- [Initial comparison API/Chromium set](comparison.xml).
- [Static findings and per-finding triage](static-triage.json).
- [Protected public frontend/SDK/package hashes](public-package-preservation.json).
- [Final source hashes](final-source-snapshot.json) and [Canvas/plan synchronization](canvas-validation.json).

Dynamic checks run only on isolated catalogs, MCP agents and controlled API/browser/TLS/PostgreSQL fixtures. Existing authority/lease/fencing/SIGKILL/outbox/retention/gateway/SDK paths are included by the regression entry point; the new comparison service itself issues no outgoing network request and no execution/evidence mutation. The signed generated-run PostgreSQL rehearsal remains part of the existing compiler regression. This does not validate a complete PostgreSQL application adapter or expanded load/HA performance.

Bandit covers the three changed Python modules: comparison evaluator, private router and runtime index. **High 0, Medium 14, Low 16**, all retained warnings individually reviewed, no new comparison-module findings or scan errors. Retained fixed SQL/legacy admin exception-handling warnings were not all removed. Scope differs from earlier scans and is not a whole-platform vulnerability-free certification. Public content checks and protected implementation hashes establish the unchanged public surface within the tested scope.

## Operational limits

No user server stop/restart/replacement, competing project server, direct live DB write, actual production agent/model call, publication, notification, policy activation or retention apply occurred. New Python comparison routes/index require a user-managed frontend/admin restart; current admin HTML may already be visible because it is read from disk. No live administrator session was available and authorization was not bypassed.

A historical principal can expire or be withdrawn without erasing the signed past record. Current API access remains highest-admin only. Current readiness can change while the historical comparison reference stays the same. A missing/pruned/corrupt proof is unavailable, not passed. The bounded inventory is not a complete historical search, and the deterministic comparison reference is not a persisted receipt lookup service. Comparison retains no extra copy of prompts or output bodies.

Full R-07/AC-08, authenticated deployment inspection, real-provider/model/semantic evaluation, complete G0/G1, hosted CI, external app rehosting, capacity/retention/HA and full PostgreSQL conversion remain open. No commit or PR was requested or created.
