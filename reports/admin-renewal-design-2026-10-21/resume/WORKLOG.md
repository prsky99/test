# Renewal resume checkpoint

Scope: continue the existing parallel /admin/next renewal, preserve legacy APIs/data, finish reliable seven-area read/navigation behavior and validate safe mutations already implemented. Destructive retention/partition cutover, legacy deletion, global role migration and two-person command rollout retain the design's explicit migration/approval gates.

Baseline: 17 existing API/Chromium tests passed. Existing P1/P2 backend + customers/security unreported code preserved.

Implemented in this resume: public-service sanitized aggregate endpoint/module; cache allowlist excludes private/financial/legacy reads; pending response tag/session fences; immediate logout concealment, expired-session handling and UI cleanup; server bounded single-flight refresh/invalidation; audit version zero/gap handling; truthful credit reconciliation states; organization metadata drilldown; security incident visibility without superadmin audit access.

Validation complete: 136 deduplicated passing cases; renewal 27 cases; native PostgreSQL 10 authenticated GETs + authority/conditional/mutation checks. JS 11 modules pass; F/E9 clean; two S608 fixed-source identifier constructions manually reviewed. Public inventory 238 files clean.

The final source fingerprint is source-hashes.json. Integration.xml is superseded per case by final-feature.xml, search-final.xml and public-final.xml. Earlier baseline/core/feature runs are historical, not unresolved failures.

Operating restart acceptance: user restarted; 2026-10-21 17:03 KST read-only checks 8/8 passed. New route now returns expected unauthenticated/machine 401, shell/assets 200 and source matched, legacy authenticated overview 200. CSP/no-store/nosniff present. All 20 source fingerprints unchanged. Evidence: operating-after-restart.json. Individual staff authenticated operating data/UI interaction remains unverified; isolated authenticated PostgreSQL/browser evidence remains valid. No operating mutations. Existing /admin/ui, actual customer/credit state and retention unchanged.

Future design work (not claimed implemented): viewer/default-password/legacy-machine-auth migration; common two-person risk commands; durable summary tables/worker and partition cutover; full specialist/mutation migration; evidence-gated legacy cleanup. See design 13.3. No competing server was launched.

Follow-on P1 authentication work completed in source: see ../auth/WORKLOG.md and design 13.4. The old 20-file fingerprint remains historical; current scope is ../auth/source-hashes.json. The previous restart smoke predates the authentication changes; a fresh user restart is pending.

2026-10-21 evening (Claude review of Codex P1): restored legacy test regressions across ~20 files by moving tests to individual staff sessions (policy unchanged); removed machine-token helper from report_pipeline_common; regenerated SQL catalog. Implemented design 13.3 item 2 first slice: admin_risk.py (15-minute review window, different approver, sole-superadmin fresh-login exception) wired into WAC commands and the renewed console commands tab. Generic command queue for non-WAC risky actions remains next. Server restart required for the new registered query.

2026-10-21 evening (cont.): generic reviewed command queue (workspace_admin_reviewed.py, table in WAC SCHEMA) with execution kill-switch release as first applier; v2 review API + gateway UI. Fixed catalog builder so explicitly migrated WAC tables are excluded from startup validation (regenerated catalog had added them; read-only prod comparison showed a startup mismatch risk; now identical validation scope, 0 column mismatches). Operator steps: restart, then WAC migrate CLI to add admin_reviewed_commands.
