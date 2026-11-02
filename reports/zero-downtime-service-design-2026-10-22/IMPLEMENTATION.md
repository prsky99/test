# Implementation checkpoint — 2026-10-22

User authorized implementation of stages 1–8, including the verified initial production cutover. No subagents. Existing unrelated working-tree changes preserved. Production is now managed; do not launch the legacy gateway alongside these services.

## Completed stages
1. Baseline and rollback: consistent private PostgreSQL backup, source snapshot and private recovery settings; SHA256 verified. Full restore into disposable PostgreSQL 18 passed, including preservation of the copied writer quarantine. Production DB was not restored or replaced.
2. Durable ownership: explicit additive `service_runtime` schema; signed commands, pending-kind uniqueness, transactional SKIP LOCKED claims, singleton DB ownership plus host locks, owner-conditional completion. Uncertain external effects are not replayed.
3. Background separation: jobs owns collection/health/maintenance; execution owns admitted user executions. Web processes do not launch these workers. Admin actions use durable commands.
4. Web separation: frontend and admin run independently, each with A/B slots, private readiness and warmup. Public ingress blocks admin/internal routes.
5. Execution/shared state: typed/private work admitted durably for the execution process, with existing integrity checks. Shared PostgreSQL/Redis/key-backed state retained. Synthetic session continuity and security regressions passed.
6. Native deployment: Caddy 2.11.7, immutable source/venv releases, serialized switches, retained rollback slots, uncertain-switch reconciliation, launchd and persistent active LaunchAgents. Existing public 8400/admin 8200 addresses retained; no remote Cloudflare setting changed.
7. Verification: legacy affected regressions 136 passed (one sandbox-blocked native fixture passed separately); security/browser/API suite 183 passed; final affected suite 82 passed; final candidate-smoke unit checks 5 passed. These suites overlap and must not be added as unique tests. Content policy: 245 files, zero violations. Real isolated Caddy: 80 requests/zero failures, slow request completed. Full isolated PG18 split-process rehearsal: 20 requests/zero failures, staff session survived admin replacement.
8. Production: cutover completed, then frontend and admin independently deployed r2. Frontend rollback to r1 and return to r2 completed. 195 requests across public URL/local frontend/local admin: zero non-200 responses. Other web and jobs/execution PIDs remained unchanged during each web operation. Workers healthy; all eight reported collector threads alive.

## Current operational state
- State: gateway-data/services/state.json, managed true, phase retained.
- Frontend B / admin B: services-20261022-r2. Previous A slots: r1 retained.
- Jobs/execution: services-20261022-r1 (same runtime code as r2; r2 includes corrected deployment smoke request headers).
- Caddy listens 127.0.0.1:8400 and :8200. Web slots 8401/8402 and 8201/8202.
- Initial legacy port handoff had a measured 47.562-second public-origin connection gap. It was not zero downtime. Initial aggressive monitoring also received 108 rate-limit responses before handoff; recorded separately. Later actual A/B and rollback requests had zero failures.
- Final data: resources 136799, reports 928, workflow_runs 78, typed runs 38. Backup counts: 136682, 928, 78, 38. No report deletion performed.
- Sampled service RSS including two retained slots and Caddy: 933.3 MiB; PG connections 18, active 4, lock-waiting 0. This is an operational sample, not a peak load capacity result.

## Handoff
- Runbook: deploy/NATIVE_SERVICES.ko.md.
- Korean result: reports/zero-downtime-service-design-2026-10-22/RESULT.ko.md.
- Evidence: restore-rehearsal.json, process-rehearsal.json, live-deployment-verification.json, initial-transition-summary.json, final-http-checks.json, live-resources.json.
- Initial backup: gateway-data/runtime-backups/pre-split-20261022-verified (private, ignored); contains DB dump 1.37 GB, source archive 462 MB, original settings/key/DSN and hashes.
- Runtime edits after final r2 package: none. Root agentcon help and optional observation-script sampling/documentation were clarified after live verification; no server restart required.

## Limits retained explicitly
- One Mac is not host/database/power/sleep/logout high availability. LaunchAgents operate at user login.
- Existing global application writer integrity lock remains. Dedicated commands use narrow native transactions; this is not a complete DB concurrency redesign.
- Jobs remains one background service grouping its existing job types; execution is a separate background service. Individual health/crawl jobs are not separate OS daemons.
- Keep N/N-1 API/static asset/job/schema compatibility. Content-hashed asset generation and automatic expand/contract migration orchestration were not added.
- External OAuth provider login, new paid external execution and production crash injection were not performed this turn. Session/execution/security fault checks used isolated synthetic data; actual production verification used read-only requests and deployments.
- Current tests do not establish peak-load throughput or indefinite SSE/WebSocket preservation.
- No broad dependency or source cleanup; no commit/reset of the pre-existing dirty tree.

## Follow-up: repeated admin deployment, 2026-10-22
- User successfully deployed admin A (web-20261022-153406-a66a), then reported `service_slot_in_use` when reusing B.
- Cause: `launchctl bootout` acknowledgment was treated as synchronous exit. The old label/PID can still be unloading when the next start runs.
- Fixed manager stop to wait for both launchd label removal and observed PID exit. A loaded label with no PID is also awaited. Inspection errors fail closed; timeout never force-kills or starts a competing slot. Start also uses this completion barrier for stale loaded jobs.
- 11 deployment tests passed, including three real isolated launchd reuse cycles with delayed shutdown, unrelated service preservation, timeout/inspection failure and isolated Caddy security boundaries.
- Production was not restarted for this fix. Current public frontend, active admin A, workers and proxy PIDs unchanged. Root deployment CLI reads the corrected script immediately on the next invocation.
- Evidence: slot-reuse-fix-verification.json. Earlier r1/r2 active-state notes describe initial handoff, not the user's subsequent deployment.
