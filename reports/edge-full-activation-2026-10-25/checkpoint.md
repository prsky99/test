# Frontend / Admin Edge-first activation

Objective: Edge serves all eligible remote Agent results first; Origin recovery only before dispatch or for the same saved result. Never repeat uncertain Provider IO.

Implemented: private Admin Edge prepare/finish, direct browser delivery with origin-bound tickets, shared ManagedGateway Edge-first IO, x402 probe, native replay fence, signed synthetic Worker health probes. Pending prior direct-result transport and seven public route expansions are included.

Validation: Worker 70 passed, isolated Chromium 22 passed; API final run in progress. Broad Admin/security 183 passed plus unrelated stale copy assertion in test_binary_clock_loader_in_front_app.

Deployment: NOT activated. Cloudflare authoritative account 224f671b6c06e49b2aac6a235410c88d / Zone 68daf89d5a65cb0a2f6e039985094d29 serves a37f7077-aeaa-4f19-bcdc-6a90c5c41200. Wrangler deployment listing points to another historical account even with account env; use verified direct REST only. Preserve existing encrypted secrets. No new secrets or DB migration.

Remaining: stage minimal overlays against latest four active releases; test real candidates; REST version upload/deploy and route additions; signed live synthetic probes; activate all four roles + owner profile direct_result_delivery=true; verify public metadata/private boundaries/runtime health. Existing campaign/soak files untouched.

## Activation milestone
- Worker f0775054-132c-4a11-97ab-6b6d9c86d342 deployed 100%; 12 fail-open routes live. Signed health + 2-byte/40KB synthetic probes passed without Provider calls.
- Frontend/Admin/Jobs/Execution edge-full-*-20261025-141509 activated; direct_result_delivery and native_node_delivery true. Observer reports preferred_backend=worker, free_available, 625 account requests, no runtime block.
- Latest Frontend workflow-library-r2 assets preserved. Initial CLI response/report shape mismatch corrected by authoritative REST readback.
- Renewal Admin direct-output follow-up: same local session/reason audit retained through two scoped aliases; module and CSP permit explicit public Edge. Chromium 7 passed; candidate API validation in progress. Will A/B deploy Admin only after it passes.
- Source/content check: 267 files, zero violations. Existing stale public-copy assertion remains unrelated. Broad specialist-panel test on historical Admin package needs baseline comparison; browser-dependent test omitted from final affected suite.

## Complete
Final Admin edge-renewal-admin-20261025-142200 A/B activated. Final candidate 24 API checks passed, actual UI module 7 Chromium checks passed. Live checks 12/12 passed; configured direct/native flags true and preferred Worker confirmed. Runtime usage633, no runtime block. Core Worker70/API106 plus scoped follow-up checks pass. No live Provider business calls. Final details and known unrelated baseline failures: README.md and validation-summary.json. No required activation work remains.
