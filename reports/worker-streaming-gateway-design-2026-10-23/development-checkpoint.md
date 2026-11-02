# Worker Gateway development checkpoint

Objective: implement opt-in Workers Free streaming with authenticated Origin fallback, preserving the administrator renewal and the running development server.

Decisions:
- Add a separate `agent_market/edge_gateway` package, versioned public SDK and standalone Worker. Keep administrator UI/layout files untouched; provide independent aggregate administration APIs.
- Share durable execution claims across Worker and Origin. Use explicit additive migration and fixed SQL for SQLite/PostgreSQL. Do not migrate the user's running database automatically.
- Initial profile: explicitly approved A2A 0.3 informational providers with streaming and the existing synchronous Origin fallback. Preserve current policy, public binding projection and limits. Other protocols/files require independently validated adapters and stay disabled.
- No production deploy, account changes, server restart, external Provider execution or automatic paid upgrade during local implementation.

Completed: implemented separate configuration/auth/state/service/public router, opt-in SDK, streaming Worker, read-only administrator API, account observer, explicit host migration/controls and operations README. PostgreSQL locks serialize cross-connection admission, quota reservations and dispatch capacity. SQLite operator tools never initialize unrelated application tables. No administrator renewal layout files or existing SDKs were overwritten.

Validation: final backend suite 77 passed; real Chromium 11 passed; workerd 8 passed. Native temporary PostgreSQL: additive migration, independent connection claim race, idempotent preparation/receipts, concurrent quota/capacity limits passed. Bandit production-package scan: 0 findings. Public content checker: 248 files, 0 violations. Python compile and Node syntax checks passed. Three selected administrator renewal files retain the pre-development SHA-256 values. See development-validation.json and implementation-status.md.

Deployment remaining: operator chooses the reviewed Provider/version, validates actual Cloudflare Free CPU and Route fail-open in staging, migrates the selected operating DB, installs private settings/secrets/Analytics Read token and activates the Worker Route. These are documented prerequisites, not completed production changes. The user restarts their own server through the normal deployment procedure. Large files, resumable events/cancellation, MCP/x402 and downloaded cross-origin apps remain future separately validated profiles.

Historical architecture.md, contracts.json and validation.json remain design artifacts; they must not be read as evidence that all proposed adapters or a production deployment exist.

Current deployment update: infrastructure is now deployed, with approved additive PostgreSQL migration, encrypted Worker secrets, Analytics Read token, active fail-open Route and Frontend/Admin A/B release. See deployment-summary.md. Provider activation remains gated (providers empty, worker_ready false) after the two approved real probes failed the SSE contract. Earlier not-deployed statements above describe the initial implementation milestone.
