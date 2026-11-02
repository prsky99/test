# Edge output monitoring
User requirement: Every Agent OUTPUT uses Edge first; Origin only after Edge delivery failure. Execution placement is separate from delivery.
Scope: private renewal Admin menu/dashboard, signed output telemetry, source path audit, close uncovered output paths without forwarding private Admin credentials. Preserve execution authority/no-duplicate IO, existing free-limit protection.
Baseline active: edge-full-frontend/jobs/execution-20261025-141509, edge-renewal-admin-20261025-142200.
No new schema/secrets; use existing Edge events/checkpoints. New snapshots captured.

Implemented: read-only Edge/Origin dashboard/menu; output observations in existing Edge events; private output middleware (including API compatibility clients), encrypted Edge output relay with session-bound Origin recovery, public root/Chat/A2A route expansion prepared; updated specialist/staff custom transports. Edge delivery is separate from Origin computation and Origin relay bytes.
Initial validation: API regression48 passed; Worker71 passed; Chromium11 passed. Final combined regression and source coverage review in progress. New dashboard screenshot QA verified desktop; mobile no overflow. No deployment yet for this task.

## Complete
Frontend/Admin edge-output-*-20261025-153117 activated via A/B, Worker edf9cefa-7e8e-4358-8cdf-3238c547bd04 deployed100%, routes16. Actual package checks68 each, Worker73, Chromium17, live15 passed. Read-only PostgreSQL query confirmed real observed MCP response entered the dashboard (Edge1/Origin0, Origin relay1; metadata test, not Provider volume). Signed health/cache3 + output publish2 synthetic probes passed. No live Provider calls, new secrets, migrations or queue-role restarts. Scope and source-path findings: README.md, source-path-audit.json.
