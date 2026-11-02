# Adoption v1.1 completion checkpoint

Objective: AE-01..AE-08 implementation and isolated acceptance. Complete for source scope.

Canonical record: README.md in this folder; machine summary acceptance.json. The old design-only and early development logs are historical, not the current status.

Completed: stable five-tool MCP /mcp/compact; separate five-route OpenAPI; bounded discovery and immutable schema single-flight; current batch evidence; exact encrypted preparations and signed customer-session/CSRF grants; durable single dispatch/idempotency/unknown; serialized publication sequence and signed cursors/feed; retained execution and health failure/recovery; verified purpose-scoped dependency delivery with version/contract/event selection; Python client; two actual HTTP client checks; Registry schema-validated draft; English SSR/sitemap/metadata; security and owned-schema PostgreSQL validation.

Validation: integration 593 pass / 1 private-cluster test deselected and replaced by shared PG18 owned schemas. Final adoption/API/client/browser 43 pass (39 overlap). Existing browser 27 pass. PG adoption+B2A 12 checks and full application 95 checks pass. Public content 288/0. Bandit 1.8.6: 974 LOC, 0 findings/parse errors. SQL catalog 3802 statements / 232 required tables, current. Temporary schemas removed. No actual accounts/providers or marketing messages.

Fixed boundaries: no candidate cache, new model, new operating SQLite DB, per-user listener, second SDK/stdio bridge or automatic provider replay. Tokens stay in transport/body; no secret query parameters. Payload 8KiB envelope budget, detail 32KiB, stored raw output 64KiB. Prepared ciphertext and terminal output incrementally cleared after 24h; unknown/idempotency metadata preserved. Standard host certification/Registry publication and production performance/HA/DR are not claimed.

Prepared and hash-verified release agent-adoption-20261025-r1 (1257 files). No operating DB migration, deployment, restart or public Workspace opening performed. User owns services. README.md contains migration-first four-service rollout commands. Only operational rollout/read-only smoke remains; do not restart implementation or reopen completed scope. External publication/commercial host reviews require separate operational work.

Final implementation hashes: source-sha256.json. Preserve other repository changes; no reset/commit was performed.

## Operator rollout verified

User ran migration and four-service deployment. Live readonly verification: 37 pass / 0 fail, recorded in live-smoke.json. All four services use agent-adoption-20261025-r1, web readiness and worker heartbeats current; migration marker/six tables installed; local and public compact/schema/feed plus 304/401/404 boundaries passed. No provider calls, customer sessions, alerts, server changes or database writes during verification. Operational rollout/read-only smoke no longer remains. Source scope and this deployment verification are complete. External publication/commercial host review and actual workload/HA/DR remain outside the claimed acceptance.
