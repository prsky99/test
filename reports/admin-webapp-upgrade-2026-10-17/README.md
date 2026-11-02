# Admin workflow web app upgrade — 2026-10-17

The admin ZIP and single HTML exports now use an isolated SDK 1.1.0 profile.
The public frontend workflow download remains on the existing SDK 1.0.0 and API.

## Delivered

- Administrator-selected primitive input fields, mapped and validated on the server.
  Blank inputs retain saved defaults. User submissions cannot replace graphs, tools,
  provider connections or credentials. Saved workflow inputs remain unchanged.
- Per-deployment public keys, optional exact-origin restrictions, per-app/IP start
  limits, UTC daily limits, deployment listing and authenticated revocation.
- One-hour run capabilities scoped to a deployment; legacy public status endpoints
  cannot read these runs. Key hashes are stored; runtime capabilities use memory
  and headers, with no cookies, query tokens or localStorage.
- Adaptive status polling, bounded transient GET retries with Retry-After and jitter,
  and no automatic retries of start/cancel POST requests.
- Stable result DOM with formatted JSON, preserved unchanged selection/scroll,
  textContent rendering, and fallback callbacks/badges only for explicit server flags.
- Immediate cancellation lock and polling abort. A confirmed terminal state is
  required before another run; status failures can reconnect to the same run.
- Equivalent ZIP and standalone HTML downloads using the same enhanced runtime.

## Verification

127 targeted regressions passed: 77 API/runtime/transport tests in api.xml and
50 Chromium/package/public security regressions in browser.xml. The browser suite
also contains package/static assertions; it is not 50 independent penetration scans.

Checks covered real controlled MCP execution with submitted inputs; admin export
and revocation; run/key/deployment isolation; expired and incorrect capabilities;
restricted origins; rate limits; malformed, oversized and reference-injection inputs;
private literal URLs; transient GET recovery and retry bounds; single POST behavior;
DOM preservation and XSS rendering; cancellation/reconnection; external HTTP(S)
hosting/subdirectories; single HTML execution; CSP and public frontend regressions.

Public content checker: 48 files, zero policy violations. Python compilation passed
for all changed modules. frontend-preservation.json confirms unchanged public HTML,
shared SDK and every public ZIP member after normalizing its random CSP nonce.
The embedded HTML in front.py remains synchronized with extracted_html.txt.

## Scope and limits

Testing used isolated SQLite databases, controlled provider transports and Chromium.
It did not stop, restart or replace the user's terminal server, modify the production
database, send marketing, incur provider charges or scan production infrastructure.
These results cover the modified paths and selected regressions, not a guarantee
that all source code or a production deployment is free of vulnerabilities.

Publish keys are intentionally public deployment controls, not end-user authentication
or billing authorization. Origin can be forged outside browsers. Public template APIs
remain independently available. The fallback hook is ready to display future explicit
server events; automatic agent switching, paid fallback and SLA guarantees are not
implemented by this change. Existing execution deadlines still apply. Browser file
preview support depends on its file-origin/CSP rules; HTTP(S) hosting is recommended.

The user-managed server must load the updated source through its normal restart or
reload process. Startup creates additive deployment/capability/counter tables.
Existing downloaded packages retain their previous code; download again to obtain
this admin upgrade. Operational details are in docs/ADMIN_WORKFLOW_WEBAPP.md.
