# Public frontend security assessment

Date: 2026-10-16 (Asia/Seoul). Assessment of the local working tree, including pre-existing uncommitted work. Changes were applied locally. No production deployment, production attack scan, real payment, email delivery or production data migration was performed.

This file preserves the initial assessment snapshot. See [the follow-up report](followup/README.md) for the subsequent CSP, egress, deployment and stored-token work, including the explicit local token scrub and 282-test verification.

## Outcome and evidence

- **254 related tests passed**, including 75 new adversarial API/transport tests and 10 new Chromium tests. See `tests.xml` for the exact test cases and duration.
- All seven public menus were exercised with the application's actual CSP and response security headers: Overview, Learn, Explore, Test, Workflows, Register and Chat.
- The original HTML snapshot executed a workflow coordinate attribute-injection payload in Chromium. The repaired source blocks that payload. See `original-dom-reproduction.json` and `test_workflow_coordinate_attribute_xss_is_blocked`.
- **53 installed packages audited**. Before remediation: 20 raw advisory records across pip and setuptools, representing 10 unique advisory IDs. After upgrading local pip 24.0 to 26.2.1 and setuptools 65.5.0 to 84.0.0: **0 known vulnerability records**. This result applies to this local environment, not an uninspected deployment image. See `dependencies-before.json` and `dependencies-after.json`.
- Bandit 1.9.4: **0 high, 12 medium and 15 low scanner alerts**. These are scanner alerts, not a count of confirmed vulnerabilities. See `bandit.json` and the triage below.
- Python syntax, English-only frontend source checks and Git whitespace checks passed.
- One non-security framework warning remains: the combined GET/HEAD overview route produces a duplicate OpenAPI operation ID.

## Scope and method

Reviewed the served public HTML/CSS/JavaScript embedded in `agent_market/concierge/front.py` (8,899 extracted HTML lines and 80 innerHTML assignment sites at review time), its route handlers, visitor/session boundary, security manager, outbound testbench, MCP proxy and REST adapter, contact notification helpers and public metadata paths. Reviewed relevant reverse-proxy configuration and query construction in supporting code. Inspected the SVG asset and browser request behavior.

Static review traced untrusted data into HTML attributes, inline event handlers, Markdown rendering, links, JSON script elements, downloaded apps, SQL queries, network destinations and credit accounts. Dynamic probes executed the real ASGI application in isolated TestClient instances and actual Chromium pages using intercepted responses that preserve security headers. Remote attack targets and DNS rebinding were controlled mocks; no hostile traffic was sent to third-party services or production.

The admin dashboard is a separate application and was outside this public-frontend assessment. Legacy extracted HTML copies and one-off patch scripts are not the served runtime and were not rewritten; regenerating the frontend through those scripts requires re-running these checks. This assessment does not certify the operating system, container image, CDN/WAF configuration, real certificates, deployed service, or absence of all vulnerabilities.

## Confirmed findings and applied changes

Severity is a qualitative prioritization based on impact and exploitation prerequisites, not a formal CVSS score.

1. **F01 — Critical: unrestricted public credit minting.** MCP `credit` with `action=deposit` previously increased virtual credit balances without settlement evidence. Public deposits now return a protocol error. Trusted internal settlement code remains available; a verified public funding flow was not implemented.

2. **F02 — High: credit account authorization failure.** MCP balance and call paths accepted caller-supplied account IDs. Balance access now requires a valid visitor token; spending uses the token owner's account. Attempts to select another account fail before proxy dispatch. A fingerprint match is not accepted as payment authorization. Existing integration tests were changed to enforce this security requirement.

3. **F03 — High: A2A testbench SSRF and connection-time DNS risk.** The registry URL was checked while an A2A card could supply a different unchecked JSON-RPC URL. The actual final URL is now checked. The new asynchronous transport resolves and validates addresses at connection time, connects only to public literal IPs, disables environment proxies and redirects, and fails closed if address pinning is unavailable. TLS retains the original host context.

4. **F04 — High: TLS certificate verification disabled.** Testbench requests used `verify=False`, permitting interception by an attacker on the network path. Certificate verification is now enabled.

5. **F05 — Medium: workflow DOM attribute injection.** Node position values were interpolated into CSS and SVG without a numeric type constraint. A malicious stored/imported graph could introduce an event attribute. Chromium reproduced script execution against the original snapshot. Coordinates are now required to be finite numbers and clamped; malformed values use numeric defaults. Other dynamic IDs and displayed counters were escaped. Exploitation requires influence over the saved/imported graph; writing localStorage alone is not a separate remote exploitation path.

6. **F06 — Medium: forwarded-address spoofing and proxy context confusion.** Routes directly trusted the first X-Forwarded-For value. An untrusted peer could bypass its ban; proxy vendor headers could also override the correct identity. All relevant routes now use the security manager's proxy-aware resolver. It ignores forwarded headers from untrusted peers, ignores unverified vendor headers, and walks the X-Forwarded-For chain from the trusted side. Visitor fingerprints and A2A context bindings use the same resolved address, preserving separation between different callers behind the trusted proxy.

7. **F07 — Medium: incomplete resource budgets.** Several POST handlers bypassed the 64 KiB body reader. Declared and chunked requests now share a global 64 KiB limit and 10-second body deadline; encoded request bodies are rejected. Global request concurrency is enforced; workflow runs have a rate limit, a 100-node cap and a 500-edge cap. Live testbench responses have a 1 MiB decoded-content limit and a 25-second total deadline. These response limits do not extend to every legacy synchronous outbound path; see remaining risks.

8. **F08 — Medium: malformed input produces server errors.** JSON primitives, non-object nodes, malformed MCP initialization data and non-finite timeouts could cause 500 responses. Object readers, graph/type limits, RPC parameter checks and finite timeout validation now return controlled client/protocol errors. Type checks no longer rely on Python assertions.

9. **F09 — Medium: unnecessary credential persistence/exposure.** Contact inquiry records received the raw visitor bearer token; they now store its SHA-256 hash. Public agent detail responses could expose credential fields in structured metadata. Recursive redaction now masks recognized credential keys, including structured JSON wire reports. Synthetic marker tests confirm redaction. Historical records were not migrated, and arbitrary prose containing secrets is not guaranteed to be recognized by structured-field redaction.

10. **F10 — Low: inconsistent error-response hardening.** Early ban/scanner responses bypassed security headers, and some failures returned exception text. Headers now apply to handled error responses; generic public failure messages replace internal exceptions. Server-side diagnostics remain available. The unsubscribe path's missing hashlib import was also repaired.

11. **F11 — Medium: Host header poisoning.** Without an explicit configured public URL, links and machine-call instructions used the incoming Host header. The fallback origin is now the canonical public domain; trusted configuration can still override it.

12. **F12 — Low: unbounded search cache growth.** Arbitrary query keys accumulated indefinitely. Search-cache insertion now enforces a 256-entry cap under a lock.

## Static scanner triage

The 12 B608 SQL-construction alerts were manually traced in public discovery/search, visitor retention/interest queries and security management queries. User values use bound parameters; interpolated fragments consist of code-defined predicates, constant table names or generated placeholder lists. The reviewed alerts were not confirmed as exploitable SQL injection. No suppression annotations were added.

The 15 low alerts include defensive fallback handlers and detector matches for documentation/sample challenge strings. They remain visible in the scanner artifact. Bandit scans Python and does not validate the embedded JavaScript; the manual sink review and Chromium attack probes cover that additional boundary. A clean or low-severity scanner result is not a security guarantee.

## Remaining risks and deployment follow-up

- **CSP / browser credentials:** The page still permits inline scripts and event handlers. A nonce/hash-based script policy needs an event-handler refactor. Visitor tokens remain accessible to application JavaScript for continuity; any future same-origin XSS can access them. No claim of a strict CSP or complete XSS immunity is made.
- **Other outbound paths:** Registration inspection, legacy MCP proxy and REST-adapter requests still use their existing synchronous code. They do not uniformly share the new testbench streaming response and total-duration limits. Existing public-address checks were reviewed; whole-system egress and response-budget hardening remains follow-up work.
- **Historical credentials:** Only new inquiry writes are hashed. Review/expire any historical raw tokens, and inspect prose wire logs for credentials before publishing them. No production data was read or modified for migration.
- **Deployment:** Rebuild/redeploy the changed source and verify the actual certificate chain, the `FORWARDED_ALLOW_IPS` deployment setting, Caddy's handling of incoming proxy headers, and the installed package inventory. Do not use a wildcard trust policy for directly reachable application ports. Local build-tool updates do not update existing containers automatically.
- **Distributed abuse controls:** Concurrency and rate-limit state are per process. A multi-worker or multi-host deployment needs compatible edge/shared controls. This assessment did not run a load or denial-of-service test against production.
- **Funding behavior:** Public MCP deposit calls intentionally fail until backed by a verified settlement implementation. Clients depending on the previous unauthenticated virtual-deposit behavior must be updated.
- **Legacy frontend regeneration:** Re-applying older one-off patch scripts can restore unsafe code. Treat the runtime source and regression tests as the reviewed implementation.

## Reproduce

From the repository root:

```sh
.venv/bin/pytest -q tests/test_front*.py tests/test_concierge*.py tests/test_mcp_proxy.py tests/test_rest_adapter.py tests/test_customer_requests_hub.py tests/test_p4_clearinghouse_and_universal_gateway.py tests/test_clearinghouse.py --junitxml=reports/security-2026-10-16/tests.xml
```

The security audit cases do not require production services. Chromium and the Python Playwright package must be available for browser tests. The original-snapshot reproduction used an ephemeral pre-change snapshot; the permanent regression test verifies the fixed source.

The standalone Canvas view is `frontend-security-audit.canvas.tsx`. Machine-readable evidence is stored alongside this report. The scanner environment was temporary and separate from the project runtime.

## Reference criteria

- [OWASP DOM-based XSS prevention](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html): use context-appropriate output methods and encoding.
- [OWASP REST security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html): validate input types and reject oversized request bodies.
- [OWASP CSP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html): CSP is defense in depth and does not replace secure rendering.
