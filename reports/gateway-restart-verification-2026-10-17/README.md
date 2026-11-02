# Server restart verification and design v1.2

2026-10-17 · Internal verification record. The user restarted the server in their terminal. This task did not stop, restart, replace, or launch a competing project server.

## Verification scope

- Post-expiry normal local/public checks: **38 passed**; both homepages returned 200 and both sampled MCP lists contained a registered tool. The test-generated blocks expired naturally.
- Initial local HTTP and public HTTPS checks: **42 passed** across both origins. Latest frontend markers, fresh CSP nonces, content/security headers, demo metadata, catalog/detail projections, MCP metadata, A2A card and unsupported x402 action rejection were verified. Public TLS certificate validation was enabled.
- Isolated managed gateway/security/TLS regressions: **113 passed**, no failures or errors. These use disposable data and synthetic providers rather than invoking production agent tasks.
- Public frontend content check: **51 files, 0 violations**. Product source hashes match the earlier verified implementation snapshot; this revision changes documentation and the existing design Canvas.
- Earlier implementation evidence remains separate: **494 unique tests / 500 executions** in `../managed-gateway-hardening-2026-10-17/`. Those historical totals are not additional tests run by this restart check. Existing static scan findings remain documented there.

Operating third-party task completion, payment, marketing delivery, long-running tasks, production load and long-term availability are outside this live check. The first sampled MCP item returned a valid empty registered-tool list; an existing route is not proof that every catalog item has usable safe tools. Follow-up metadata checks are recorded separately.

## Temporary security block during verification

The initial blocked-path check requested `/.env`, which correctly returned 403 and triggered the configured 900-second scanner auto-jail for the two verification connections. Subsequent normal requests from those connections were consequently blocked. This was a test-induced security response, not evidence of a server crash.

No whitelist, security-policy relaxation, direct database alteration, or manual rule deletion was used. The follow-up script excludes scanner paths and verifies normal access after natural expiry. Other security rules are not attributed to this test or modified. Raw IP addresses and credentials are omitted from this report.

## Design revision

- `../../docs/PLATFORM_ADVANCEMENT_DESIGN.md`: v1.2 incorporates the implemented managed gateway baseline, supported protocol boundaries, truthful Testbench output and verification evidence.
- `../../docs/platform-advancement-plan.json`: 7 modules, 14 backlog items and 4 release gates. AC-00 / AC-13 distinguish completed baseline work from remaining contracts and operations work.
- Existing `platform-advancement-design.canvas.tsx`: same inline plan, updated status and roadmap; TSX syntax validated with esbuild. No new visual browser rendering assertion is made in this resumed check.
- Full G0 remains open: versioned readiness/binding/profile registry, caller/actor and operation trace convergence, a real runtime invocation switch, canary/rollback and capacity/recovery checks remain. Durable execution, automatic fallback, AI composition, organizational authentication and settlement remain proposed development.
- Public SDK 1.0 and admin SDK 1.1 compatibility requirements remain unchanged. This documentation update does not require another server restart.

## Evidence

- `live-smoke.json`: initial 42-check live snapshot.
- `live-safe-followup.json`: normal metadata checks after block expiry, without scanner paths.
- `live-tool-metadata.json`: bounded registered-tool metadata check; never tools/call.
- `isolated-security.xml`: 113 isolated regression results.
- `document-checks.json`: document/JSON/Canvas consistency, dependency graph and source hashes.
- `verification.json`: final combined status and actual verification scope.

The `design-v11.md`, `plan-v11.json` and `canvas-v11.tsx` files preserve the previous document state for review; they are historical artifacts.
