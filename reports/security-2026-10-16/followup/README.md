# Security hardening follow-up

Date: 2026-10-16 (Asia/Seoul). This follows the initial public-frontend assessment. Local source changes and the explicit local visitor-token scrub were completed. Production was inspected read-only, not redeployed.

## Verified outcome

- **282 tests passed** across the public frontend, actual Chromium pages, MCP proxy, REST adapter, visitor memory, credit boundary and administrator authentication. The suite includes an actual loopback slow-drip HTTP server demonstrating that repeated small reads cannot extend the operation deadline. See `tests.xml`.
- Browser attack tests demonstrate that scripts without an approved nonce and HTML event attributes are blocked by the response CSP. Workflow execution/download, legal controls and the dynamically rendered inspector still work.
- Compose configuration validation and Caddy 2.11.7 configuration validation passed. Docker Engine was unavailable, including outside the sandbox, so the image was not built and no container was restarted.
- Bandit: **0 high, 17 medium, 15 low alerts** in the expanded Python scope. The 17 medium alerts are query-construction detectors: the prior parameterized queries, three additional administrator queries using constant fragments and bound values, and two scrubber queries whose table/column names come from the fixed allowlist. They were manually reviewed; no suppressions were added. JavaScript was additionally reviewed and tested in Chromium.
- Syntax, touched-file whitespace, shell syntax and English-only frontend checks passed. The pre-existing combined GET/HEAD OpenAPI operation-ID warning remains; it is unrelated to security behavior.

## CSP changes

The served page uses a fresh cryptographically random nonce for its two executable script blocks on every HTML response. `script-src` no longer permits `unsafe-inline` or `unsafe-eval`; `script-src-attr 'none'` blocks executable HTML attributes. Default API/error responses allow no scripts. The middleware preserves the HTML response's nonce policy while still setting other security headers.

All 116 inline event attributes were converted to inert data attributes selecting 93 fixed JavaScript callbacks registered through event listeners. The dispatch mechanism performs no eval or source compilation, works with dynamically inserted controls, and preserves event propagation/default handling. The extracted HTML mirror was synchronized to the served source.

Downloaded standalone apps now contain an independent nonce-based CSP meta policy. They prohibit network calls and executable event attributes. Inline CSS remains permitted for the existing design, so this change is specifically script hardening rather than removal of every inline style. Browser visitor tokens remain JavaScript-accessible for the existing continuity feature; future same-origin script compromise would still be significant.

## External calls

The legacy synchronous paths now share bounded clients: registration inspection and health probing, MCP discovery/execution, REST specification fetching/calls and notification delivery. Controls include:

- Absolute 25-second operation budget shared across requests, with every socket read/write/connect/TLS operation clamped to the remaining time.
- At most 16 requests per operation and 1 MiB per response. Notifications retain their lower 256 KiB card / 64 KiB reply limits.
- Five-second preflight DNS checks, a four-worker resolver with bounded admission, public-IP validation/pinning at connection time, verified TLS, no environment proxies and no redirects.
- Identity encoding requested; compressed upstream responses are rejected to prevent decompression bombs. Servers that insist on compression need explicit adaptation.
- Stream closure and owned-client cleanup on normal/error paths. The asynchronous testbench retains its 25-second total deadline and 1 MiB limit.

DNS work that has already entered the operating-system resolver cannot be force-cancelled; timed-out work retains its admission slot until completion. This bounds concurrent resolver work and prevents queue growth while the caller returns on its deadline. Preflight DNS has a separate five-second allowance; the 25-second network budget should not be described as including every application/database/preflight step.

## Existing token verification and remediation

Four local databases were inspected without printing token values: `gateway-data/gateway.sqlite3`, `gateway-data/collector.sqlite3`, `agent_market.db`, and `data`.

The collector database contained **14 message text fields with a raw visitor token**. The first token-issuance reply had been persisted in the conversation log, even though the visitor table itself stored a hash. New writes and history reads now redact token strings. Inquiry writes enforce hashing at the Store boundary, and public metadata/prose rendering redacts recognized visitor-token strings.

The 14 legacy fields were masked after creating an owner-only rollback backup inside the ignored `gateway-data/security-backups` directory. Backup directory permissions are `700`, file permissions are `600`. The shareable report contains only counts, not backup content or credential values. The rollback backup contains original credentials and must remain private.

After the scrub, the selected fields contained **0 raw visitor-token fields**. Visitor IDs and token hashes were checked unchanged; identities, balances and ownership were not reset. This is a logical record scrub, not forensic deletion of historical WAL frames, filesystem snapshots or backups. See `token-inventory.json`.

The inventory also found **4 active legacy administrator sessions** in raw storage at the deployment-check snapshot. New administrator sessions are now hashed with a prefix; stored hashes cannot be replayed as bearer tokens. Existing sessions are upgraded when their owners authenticate through the new code, preserving their bearer token. They were not bulk-modified while old runtime workers may still use raw keys. Counts can change as the old runtime continues to operate.

## Operational settings and live verification

The checked-in Compose profile now trusts only Caddy's fixed address on a dedicated network, replacing `FORWARDED_ALLOW_IPS=*`. Application ports remain private except for the loopback administrative port. Caddy overwrites forwarded IP/protocol headers, removes unverified vendor headers and blocks both `/admin` and `/admin/*`. The gateway drops capabilities and prohibits privilege escalation.

Production startup rejects wildcard/trust-all proxy networks, non-HTTPS public origins, short administrative API secrets, private agent destinations and active default administrator credentials. A fresh production database requires a separate bootstrap password of at least 16 characters. Existing administrator passwords are not silently overwritten. Development self-signed certificate scheduling/generation is disabled in production; direct TLS requires provisioned certificate/key files. The Compose profile uses Caddy-managed public TLS.

The Docker build now upgrades pip/setuptools to the security floors before installing requirements. A future image still requires an actual build and package audit; the local audit does not update old containers.

One read-only HTTPS GET to the production domain verified:

- Certificate chain/hostname verification succeeded using the client's normal trust store.
- TLS 1.3; certificate expiry **2027-01-13 11:43:29 UTC** (20:43:29 Asia/Seoul).
- HTTP 200; HSTS, nosniff and frame protection present.
- **The live page still allows inline scripts, has no script nonce, and does not yet block HTML event attributes.** This confirms that the local CSP changes have not reached that runtime.

See `live-https.json` and `deployment-checks.json` for sanitized machine-readable results. No attack inputs, credentials, payment operations or deployment mutations were sent to production.

## Required operational follow-through

1. Change default administrator credentials in the actual deployment database through its authenticated private administration interface. Three inspected local databases still had an active default account; their credentials were not silently changed or printed.
2. Start the deployment's Docker Engine or provide the actual deployment execution environment, then rebuild/redeploy consistently across workers. Docker Engine was not running in this workspace; a remote host/path was not available.
3. Re-run the read-only HTTPS and stored-token tools after rollout. Expect nonce-only scripts, blocked event attributes and no new raw visitor-token logs. Legacy administrator session rows will migrate on authentication through the updated version.

Deployment instructions and exact safe commands are in `deploy/SECURITY.md`. Private rollback material must not be attached to a report or committed. Existing browser token persistence and inline CSS are explicit architectural exceptions, not silently declared resolved.

## References

- [MDN CSP implementation guidance](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/CSP): nonce script authorization and replacing inline handlers with event listeners.
- [Caddy reverse-proxy documentation](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy): forwarded-header handling and explicit proxy trust.
- [HTTPX timeout documentation](https://www.python-httpx.org/advanced/timeouts/): phase-specific timeout behavior, supplemented here by an absolute operation deadline.
