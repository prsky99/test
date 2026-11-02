# Search, Chat and Workspace quality development

User authorized implementation of the upgrade design while the other active chat implements autonomous-agent adoption v1.1.

Owned scope: concierge/query_intent.py, retrieval_metrics.py, discovery.py, hybrid_explore.py, selection.py, workflow_discovery.py, workflow_goal_evaluation.py, workflow_goal_policy.py, dedicated quality tests/evaluator and this report folder. Before each shared integration edit compare its current source to this scope.

Avoid edits to agent_access/*, capability_registry.py, concierge/front.py/security.py/task_updates.py, gateway/store.py, public_metadata.py, SQL catalog/build/migration scripts, server wiring, generated frontend publication, execution/Edge and credit authority modules. Other chat owns those. No external chat messages or server operations.

Implement: condition-preserving retrieval, explicit negative capability handling, verified exact-name shortcut, common workflow topic/dependency validation, privacy-safe local spans, executable isolated evaluation. Existing query-vector cache/singleflight and typed compiler remain in use. Final API/browser/security regressions use isolated stores only. Proposed model/reranking/SLO targets require subsequent calibrated experiments, not invented results.

Completed: read current adoption checkpoint and modified path inventory; captured pre-edit hashes. Current on-disk AGENTS.md already aligns maximum three/A2A-first/MCP-fill/explicit-x402 policy; preserve it.

Remaining: implementation, affected tests, isolated evaluation, security regression, source conflict check, final report.

## Final implementation milestone

Implemented local intent/exclusion separation, constraint-preserving hybrid retrieval, verified native exact-name embedding shortcut, explicit-name Explore admission, Template exclusion checks, all-named-subject and real title-binding checks, actionable factory needs_details, privacy-safe opt-in stage capture, offline evaluator and dedicated tests. Small factory exception handling edit added after confirming no other-chat ownership overlap.

Validation: final combined API/unit/security/adoption regression 392 passed, including 36 new quality cases and 35 adoption cases collected at that time. Browser 6 passed (4 new cases rechecked after final factory edit), offline meaning/plan 32/32, public content 275/0, Ruff F/E9/S on 4 new modules 0 findings, changed Python compile passed. Production DB/model/provider requests and server/deploy operations: 0.

Other active chat still owns adoption/schema/metadata/server wiring; final path inventory shows no overlap with these quality edits. SHA256 manifest in validation-summary.json. Full design's labeled 300-case operational baseline, conditional neural rerank/model/ANN calibration, complete candidate cache invalidation, node-local automatic repairs/resume, paid subscription entitlements and rollout remain separate next phases; no SLO achievement or whole-plan completion claim.

Final report: README.ko.md. No further repeat testing required unless code changes. Ready to deliver this first milestone.
