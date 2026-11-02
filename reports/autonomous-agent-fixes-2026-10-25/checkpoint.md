# Autonomous Agent fixes — completed 2026-10-25

Objective: resolve the quoted Agent compatibility failures and MCP Edge gap, with paper/SNS research. Complete.

Implemented: shared 11-tool MCP contract; legacy query/protocol aliases; task/kind/Any validation; Streamable HTTP manifest; call isError on failure; uncertain-outcome pause without false feedback; public Legacy SSRF policy; Gateway-only prefetch metadata; Ticketed MCP adapter with per-Visitor idempotency, durable ownership and same-Ticket quota Origin fallback. No legacy retry after accepted Ticket, including rollout disabled. Fixed old alternative-candidate fixture with a second relevant provider, preserved relevance gates.

Product files: agent_market/concierge/front.py, agent_market/concierge/mcp_contract.py, agent_market/edge_gateway/machine.py. Only these three applied atop each active web package, preserving unrelated/Admin renewal files and embedded HTML. Tests added/updated in test_mcp_contract, test_edge_gateway_machine, test_autonomous_agent_journey, test_concierge, test_mcp_proxy.

Validation: affected API202 pass; Machine/REST/Gateway155 pass; Frontsecurity22 pass; isolated Chromium11 pass (390 across four groups). Agent12/12 included. Final strengthened path47 pass; staged Frontend47 and Admin47 pass (repeat subsets, not summed). Content263 files/0 violations; compileall and Canvas esbuild pass. Existing OpenAPI duplicateOperationID warning remains; Bandit unavailable and not claimed run.

Activated with existing explicit Frontend/Admin A/B approval: agent-mcp-fixes-frontend-20261025-073530 and agent-mcp-fixes-admin-20261025-073530. Previous slots retained. live-verification.json: both readiness/integrity/pages/assets/auth checks pass; active local + public domain manifest/tools-list11 exact parity, Any/idempotency/transport pass. Jobs/Execution PID+release unchanged. No Worker upload, Secrets, DDL. Edge flags read-only true native/ready, no canary.

Report: README.md includes primary papers/official MCP sources and SNS anecdote caveats. Historical review now points to fix report. Existing Canvas updated to resolved/deployed state. No real Provider/payment calls: deterministic isolated HTTP fixtures and public metadata only. Permission-bound Workspace/disabled Machine workers intentionally retained; optional MCP Workflow authoring/delegation remains future scope. Existing campaign/soak failures and read-only heartbeat monitoring untouched; no 24h or all-provider-success claim.

Remaining: none for scoped compatibility fix and approved web activation. Final user response pending. Do not repeat 390 checks or redeploy absent new changes.
