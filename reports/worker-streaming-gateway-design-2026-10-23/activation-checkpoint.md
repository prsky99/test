# Current Gateway checkpoint

User requested actual Provider activation. Completed for one verified Provider; never describe all Providers as switched.

Current: CHS Backflow 145303 active, request_mode=json, pinned capability version. owner-only gateway-data/edge-gateway.json worker_ready=true, all required reviews true after actual tests, canary_principal removed. Previous zero-provider config backed up owner-only gateway-data/edge-gateway.pre-activation.json. No secrets in reports.

Final Worker version 669a4e2c-3d07-4887-a615-afcadbc7a91d at 100%. Routes: agentconcierge.biz/api/edge-gateway/v1/*; agentconcierge.biz/api/gateway/a2a/*; agentconcierge.biz/api/test/execute. All request_limit_fail_open=true. Free retained, no paid resource, SHARED_SECRET and CONTROL_ORIGIN names verified preserved. workers.dev/preview remain disabled.

Final host: edge-cpu-20261023-175748, Frontend b/Admin a, readiness verified. Latest release cloned previous active immutable release, only relevant Edge files overlaid and all other manifest files preserved. Jobs health6h-20261023-v1 and Execution services-20261022-r1 unchanged against pre-activation state. No schema migration.

Policy auto, preferred_backend worker, healthy signed Worker/account observer verified; normal monitor threads started. Runtime block false. Actual public Gateway and Testbench calls both backend worker/succeeded with output_bytes matching actual response bodies, no Provider hostname in output. New SDK direct canary also succeeded. Source of truth activation-validation.json.

CPU: initial legacy calls 26.3/12.2ms triggered temporary host origin mode. Optimized approval+claim into one signed callback and shared validation/direct JSON delivery (no intermediate SSE); minified bundle. New public observation window max cpuTimeP99=8630 microseconds (8.6ms), runtime errors0. Cloudflare API schema explicitly confirmed CPU microsecond units. Policy restored auto. Do not claim worst-case CPU/load guarantee; only these sample results tested. No deliberate Free quota exhaustion.

Scope: new Edge SDK, existing same-origin public A2A Gateway and Testbench. All other Provider calls, MCP/x402, external Origin apps and different Workspace/Workflow APIs retain existing paths. Legacy machine JSON-RPC and Testbench output contracts preserved. Same Gateway address benefits compatible same-origin downloaded apps. Rosentic returns -32601; Antigravity endpoint404; Weather Task/history output incompatible with current Origin profile. These were not approved.

Code changed: edge_gateway config.py,service.py,router.py,README.md; Cloudflare worker.mjs/test; tests/test_edge_gateway.py. Canary gate permits unverified CPU only under private exact operator principal. Public-prepare is HMAC+nonce authenticated, rate gated and revalidates existing admission; approved initial public POST carries existing execution authority. Durable shared claim prevents auto replay. Pending/different-input/method/capability changes remain rejected. Provider root-origin URL projection hides known Provider URLs; independent citations preserved. No automatic retry after claimed/unknown execution.

Validation: Python/config/deploy92 passed; Chromium6 passed; Worker22 passed; optimized affected Python36 rerun passed; final Bandit0; public content248/0. No pending permission or restart. Deployment authorization and actual activation were explicit. No payment, reservations, personal data or messages to Provider owners were sent; bounded introduction calls only.

Final user answer should state actual activated count (1), concrete paths, successful actual output and measured8.6ms/0runtime errors, other Providers remain Origin, link deployment-summary.md if helpful. No claim of all-Provider or all-app conversion.
