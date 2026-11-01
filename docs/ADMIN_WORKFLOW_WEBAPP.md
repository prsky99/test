# Admin workflow app exports

The admin Workflow export dialog produces a registered ZIP package or equivalent
single HTML file using SDK 1.1.0. Public frontend downloads continue to use the
existing SDK 1.0.0, package builder, assets and public workflow API.

## Administrator workflow

1. Save and publish a safe, active template. Export uses its saved definition;
   unsaved canvas edits are not executable definitions.
2. Open the web app export dialog. Select the primitive input arguments visitors
   may change. Empty fields in the generated app retain server-side defaults.
3. Optionally restrict exact HTTP(S) origins, including scheme and port. Configure
   application start limits: 1–30 per minute and 1–5000 per UTC day. A separate
   per-IP limit allows at most five starts per minute, or the lower app limit.
4. Download and deploy the ZIP on an HTTP(S) static host, including a subdirectory.
   The single HTML option embeds the same SDK and runtime under a nonce-based CSP.
   Local file previews depend on browser behavior and require an unrestricted origin
   policy. HTTPS is recommended for production.
5. Reopen the dialog to inspect issued deployments or revoke one. Each download
   issues a separate deployment. Revoke superseded versions explicitly.

## Gateway boundaries

The admin export endpoints require the existing authenticated admin transport.
`GET /admin/api/workflows/{id}/export-app/options` lists input choices and deployments.
`POST .../export-app/package` and `POST .../export-app/html` generate the artifacts.
`DELETE /admin/api/workflows/{id}/apps/{app_id}` revokes a deployment and requests
cooperative cancellation of its pending jobs.

Generated apps call only `https://agentconcierge.biz/api/workflow-apps/{app_id}/runs`
and its status/cancel subroutes. Publish keys are public deployment identifiers;
they are **not user authentication, a payment gate or a secret**. The server stores
only their hashes. Origin allowlists constrain browsers; non-browser clients can
forge Origin. Existing public template endpoints remain independently accessible.

Bindings are generated server-side from allowed primitive input arguments, exposed
as virtual field IDs, and validated again on execution. Submitted graphs, tool names,
unknown fields, credential bindings, reference expressions and invalid scalar types
are rejected. URL-like input receives lexical public-address checks; underlying
network transport guards remain necessary for DNS and connection-time validation.
Changing the published graph invalidates the deployment until a fresh export.

Every run has a separate, hashed, one-hour capability bound to its deployment.
It cannot be read through the legacy public run API. Run capabilities stay in SDK
memory and headers, never in URLs or localStorage. Private workflow definitions,
provider endpoints and credentials are not included in the package. Inputs and
outcomes remain subject to normal server-side execution history retention.

## Runtime behavior

Only transient status GET failures are retried: network failures, timeouts, 429 and
502/503/504. Retries are bounded to three consecutive failures, use exponential
delay with jitter and honor bounded Retry-After. Successful polling gradually slows.
Run and Cancel POSTs are never automatically retried. An uncertain start response
may still represent an accepted server job; review admin history before retrying.

Stop locks immediately, aborts polling and sends one cancellation request. It does
not claim cancellation completed. Run stays disabled until the user checks and
observes a terminal server state. Resume status reconnects the existing run after
monitoring errors. Closing a tab does not cancel execution. Existing server execution
deadlines still apply independently of client monitoring deadlines.

Results reuse node DOM elements, preserve unchanged text selection/scroll, format
objects as JSON, and use textContent. Fallback badges and the SDK onFallback hook
require explicit gateway flags; nested agent output cannot activate them. The current
runner does not implement automatic agent switching, paid fallback or a commercial
availability guarantee. No automatic feedback, telemetry or marketing is added.

## Deployment and verification

Restart the user-managed server normally to load the new routes and assets. Startup
creates additive SQLite tables for deployments, per-run capabilities and counters;
no production server or database was changed during development verification.

Targeted tests are `test_admin_webapp_deployments.py`,
`test_admin_webapp_upgrade_browser.py`, and the existing workflow/package/security
regressions. Reports and the before/after public frontend/package hashes are stored
in `reports/admin-webapp-upgrade-2026-10-17/`.


## Optional SDK 1.2 reviewed deployment profile

SDK 1.1 remains the default export. A separate SDK 1.2 review action is available
only when the current highest-administrator session and backend support it.
This profile accepts an already published, currently approved literal news/docs
compiler definition with its retained certain successful test. The administrator
reviews exact fixed inputs and recipients, at least one exact origin, limits and
expiry, then grants independently revocable deployment authority. Dynamic input
fields, private connected flows and controlled pairs are outside this profile.

The downloaded app prepares a fresh exact preview and requires separate,
initially unchecked sharing and single-run declarations. The new routes use
`/api/workflow-apps-v12/{app_id}`. Existing public SDK 1.0 and admin SDK 1.1
package assets remain unchanged. Run capabilities and tickets stay in memory;
uncertain POSTs are not automatically repeated. This grant does not authorize
publication, automation, result delivery or marketing.

See [SDK 1.2 contract, APIs and limits](WORKFLOW_SDK12_AUTHORITY.md) and
[isolated verification and remaining operating acceptance](../reports/advancement-sdk12-consent-2026-10-18/README.md).
New Python requires the user's terminal restart and authenticated administrator
acceptance. An unavailable approved catalog is a valid blocked state; agents are
not automatically approved to enable the review action.

## Separately reviewed connected SDK 1.3

An already published canonical public news-to-documentation release can now be
exported through its separate **Review SDK 1.3 deployment** action. The highest
administrator reviews the exact origins, limits, expiry, fixed news inputs,
documentation recipient/settings and future-title sharing rule before granting
this independent deployment and downloading its ZIP or single HTML.

Every visitor run still needs fresh, separate sharing and live-run declarations.
Publication, literal SDK 1.2 and private test permissions do not supply them.
Deployment history supports read-only refresh and revision-based withdrawal;
ambiguous exports are inspected before another explicitly reviewed grant.
Existing SDK 1.0, 1.1 and literal 1.2 package assets are unchanged.

See [connected SDK 1.3 contract and limits](WORKFLOW_CONNECTED_SDK13.md) and
[verification scope](../reports/advancement-connected-sdk-2026-10-18/README.md).
Scheduling, events, result delivery and private-pair publication remain separate
unsupported purposes. New Python requires the user's terminal restart and
authenticated operating acceptance with appropriately approved data.
