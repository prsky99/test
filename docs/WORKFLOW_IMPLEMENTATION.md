# Workflow implementation and operation

The recommended implementation order was:

1. Remove generated success/delivery claims; protect public definitions and preserve saved work.
2. Connect admin, public UI and downloaded apps to one bounded execution engine with recorded runs.
3. Persist schedules, verify event triggers and deliver only to purpose-authorized verified inboxes.
4. Make catalog composition and app export factual; protect platform credentials.
5. Run isolated protocol, API, TLS, browser and security regressions.

All five implementation steps are complete. The user's terminal server was not stopped,
restarted or replaced. Tests used temporary databases, controlled transports and temporary
loopback TLS servers, with no real recipient deliveries.

## Execution and definitions

`agent_market/workflows.py` is the shared server runtime. Run the saved graph from the
admin canvas; the public UI and exported apps run a server-owned published template ID.
Duplicate display names do not select another template. Public requests cannot supply an
arbitrary graph or platform credential binding.

The runtime persists immutable graph/connection/schema snapshots, workflow runs,
node states and delivery acknowledgements. It rejects cycles, duplicate/unknown nodes,
unsupported reference syntax and non-ancestor input references. Exact output references
retain their JSON types. Router conditions are booleans or structured comparisons;
true/false branches are editable in the admin inspector. Disabled nodes are skipped;
failed dependencies block downstream calls. There are no generated sample successes.

Execution uses the protected MCP/REST/x402 proxy and A2A JSON-RPC transport. MCP schemas
remain pinned. Resource endpoint hashes, protocol and schema identity are checked against
the submitted snapshot. Private/credential-bearing endpoints are refused. Provider requests
that require additional payment authorization fail without making an automatic payment.
A2A message replies and completed task artifacts are supported; unfinished remote tasks
are reported without pretending they completed. Streaming and long-running task polling
are outside this bounded runtime.

Runs use a 25-second shared outbound deadline, four local executor threads and a bounded
12-run queue. HTTP redirects, environment proxies, private DNS destinations and oversized
responses remain restricted. Inputs and outputs have size/complexity limits. Input schemas
with regex patterns or references fail closed. Cancellation is cooperative: an in-flight
request can finish before the next step is stopped. Neither automatic action retries nor
uncertain delivery retries occur. An explicit new run is a new execution; admin idempotency
keys prevent re-submitting the same definition as a second execution.

Admin history shows persisted runs and snapshots. Public results require the per-run
capability in `X-Workflow-Key`; it is not displayed or exported. Public responses omit inputs,
private delivery configuration, known secrets, personal email addresses and private paths.
Sensitive output is also removed before passing it to a downstream step.

Builtin seeds have stable registry entries and are insert-only. Editing, renaming, disabling
or restarting does not overwrite them. New demo counters start at zero. Admin cards derive
runs, successful executions, ratings, likes and forks from actual persisted records;
imported run totals remain separately labeled `legacy_runs_count` in the API.

## Scheduling and inboxes

Use the admin schedule dialog to save a mode, preset, IANA time zone, enable flag and optional
verified workflow result inbox. Supported presets are daily 09:00, hourly, Monday 09:00 and
every six hours. This is a preset scheduler, not an arbitrary cron interpreter. The dialog
shows the next run and whether its worker is active. The worker uses the existing gateway
scheduler setting (`SCHEDULER=1`) with a separate five-second tick so catalog scans do not
hold up scheduled workflows. Saving a schedule does not itself establish worker availability.

Webhook/A2A inboxes need an explicit `workflow-results-v1` authorization and a six-digit
verification code delivered to the dedicated HTTPS inbox. The code expires after one hour
and five incorrect attempts close verification. Resolved A2A endpoints must use the verified
host. Only fixed verification content is sent before proof of control. Destinations and
signing secrets are encrypted with a separate purpose-derived key. Revocation removes
stored secrets and prevents further delivery. Existing task-update or marketing permission
never authorizes workflow reports. Public template runs do not deliver to the administrator's
private inbox, even when a schedule has one configured.

Successful authorized runs send signed JSON/A2A payloads with an event ID and artifact
SHA-256. Acknowledged transport is labeled `ACCEPTED`, not proof that a person read it.
Failure is recorded as `FAILED`; interrupted delivery is `uncertain`. Email/Slack delivery
is not implemented and the old simulation controls no longer claim it occurred.

For event mode, save an enabled configuration and securely retain the event key shown once
in the dialog. The endpoint is `POST /api/workflows/events/{workflow_id}` with:

- `X-Workflow-Timestamp`: current Unix seconds, accepted within five minutes.
- `X-Workflow-Event-ID`: unique ASCII letters/digits/underscore/hyphen, at most 100 characters.
- `X-Workflow-Signature`: `sha256=` followed by hex HMAC-SHA256 of
  `timestamp + "." + event_id + "." + exact_request_body`, using the event key.

Signatures, timestamps and duplicate event IDs are checked before execution. The authenticated
body cannot replace the saved graph or its tool inputs. Event keys can be rotated. Automatic
runs cannot use platform credential references. Interrupted runs fail visibly after their
lease expires; uncertain provider actions are not silently repeated.

## Composer, export and credentials

The composer is explicitly catalog matching (`generation_method=catalog_match`, `llm_used=false`).
It creates a draft from registered resources and requires input/tool review; empty catalogs
return a validation error. Agent replacement also uses registered eligible resources and
does not offer synthetic preset IDs. The configured LLM is not falsely claimed to have run.

Export requires an active safe public template. Both export builders use the shared English
runtime in `agent_market/concierge/workflow_app.js`. The connected app requires internet
access and uses the current published definition. It includes no platform key, simulated
output, random proof, client-only login or payment gate. Its CSP uses nonces and one HTTPS
service origin. CORS applies only to public workflow run/status/cancel endpoints and uses
no cookies or admin session credentials. Private workflows cannot be exported as executable
public apps without publishing a safe definition.

Platform credentials use authenticated AES-GCM storage bound to each credential name.
Existing plaintext fields migrate transactionally on Store initialization; current API
masking and internal credential references continue to work. A sibling `.credentials-key`
file is created atomically with owner-only permissions. Keep this original key with protected
backups; loss or tampering fails closed. Workflow inbox encryption continues to use the
separately purpose-derived `.updates-key`. Encryption does not erase plaintext from historical
DB snapshots, old WAL copies or existing backups; those require a separate retention/cleanup
operation. No online vacuum, live DB recovery or credential rotation was performed here.

## Applying the source changes

Install the updated requirements (adds `jsonschema`) in the normal runtime environment and
restart the server in the user's terminal when ready. No scheduler or real inbox was enabled
in the running service by this work. On startup, schema/seed registry/credential migrations
run without overwriting saved workflow definitions. Existing stale agent IDs or tool names
must be reviewed and rebound to a registered agent; an unbound default is now a visible
failure rather than a generated successful report.

Validation results are recorded in `reports/workflow-implementation-2026-10-17/`.

## Published template hub (2026-10-17)

The built-in catalogue now contains exactly three manual, read-only recipes:

- **Daily Tech News & AI Research Digest**: Agent Pulse `get_latest_signals`
  retrieves three technology news items and three research items, including source
  links and publication dates.
- **Capacitor Camera Integration Brief**: Capawesome `search_docs` finds camera
  permission documentation; `list_plugins` returns matching camera plugins.
- **Padel Racket Discovery & Comparison**: PadelTrue `search_rackets` finds two
  Nox AT10 models; `compare_rackets` receives their actual returned slugs. Provider
  ratings are calculated estimates, not independent play-test measurements.

Definitions live in `agent_market/workflow_templates.py`. Endpoint references bind
only to registered catalogue resources with matching kind and URL. Empty catalogues
keep the definitions unbound and fail visibly rather than inventing resource IDs.
The old synthetic template seeders are retired. Restart seeding uses stable registry
keys and preserves deliberate edits, renames and disabled states.

The explicit replacement command is `scripts/replace_workflow_templates.py` with
`--db`, `--verification-db` and `--apply`. Without `--apply`, it only validates recent
execution proof. It requires matching graph inputs, actual successful node attempts,
read-only tools and current schema hashes. It stores an owner-only JSON backup under
`security-backups` before deleting hub definitions in one transaction. Historical
runs/versions and ordinary workflows remain. Schedules and destination secrets for
removed templates are revoked. Only the selected registered resources receive the
reviewed schema pin update; the runtime continues to reject later schema drift.

On the active catalogue, the replacement removed 26 hub definitions and installed
IDs 34, 35 and 36. Each was then executed through the existing public server API;
all three succeeded and their runs are visible in admin history. Recorded times
were 2.76 seconds (digest), 3.22 seconds (camera) and 3.63 seconds (rackets). These
are observations from this verification, not availability or latency guarantees.
Evidence is in `reports/three-workflow-templates-2026-10-17/`.

The new `output_select` option stores/displays selected response fields with explicit
bounds. Sanitized raw provider shapes remain available for downstream references;
required field changes fail the step instead of silently displaying an empty result.
Public cache keys and a retired-default migration prevent the old built-in graph
from remaining selected after the hub replacement. Custom saved canvases remain.

The operator's terminal server was kept running. The three database definitions and
successful run histories are already applied; restart that server manually to load
new output selection, updated copy/cache migration, and the new startup seed code.
External provider availability and schema changes can still cause visible failures.

## Self-hosted web app packages and gateway SDK (2026-10-17)

The primary admin export is now a static ZIP. It contains `index.html`, local
JavaScript SDK/app assets, CSS, an app manifest and English deployment instructions.
Upload the extracted files to any HTTP(S) static host, including a subdirectory;
no build tool, application server or local API proxy is required. The secondary
single-HTML download remains available and uses the same SDK execution path.

`POST /admin/api/workflows/{id}/export-app/package` requires the existing admin
session and `X-Dashboard` guard. It only exports active safe published workflows.
The package contains the public workflow ID and display copy, with no copied graph,
provider endpoints, administrator session, platform credentials or run capability.
The ZIP response disables caching, uses a safe attachment filename and includes only
fixed relative file names with regular-file permissions.

`agent_market/workflow_webapp.py` builds packages from the SDK and app runtime
sections in `agent_market/concierge/workflow_app.js`. Those same sources are embedded
in admin and frontend HTML. The wrapper exposes `run`, `status`, `wait` and `cancel`.
Its origin is fixed to `https://agentconcierge.biz`; callers cannot select a provider
or arbitrary endpoint. The gateway validates the published workflow and routes agent
calls using the existing bounded execution engine.

The SDK uses CORS with `credentials: omit`, no referrer, no redirects, bounded
requests/polling and no automatic POST retries. Per-run capabilities remain in a
private WeakMap and travel only in `X-Workflow-Key`. Returned handles, DOM state,
URLs and local storage do not contain them. Remote content is rendered as text;
static metadata is escaped and generated apps retain a restrictive CSP.

Browser tests download the actual admin ZIP and serve it from distinct HTTP and
HTTPS origins under `/apps/weather/`. They exercise real controlled MCP executions,
status/cancel capabilities, private-cookie exclusion, malicious metadata, injected
origins, malformed responses and absence of automatic retries. A separately generated
package was also served from a simulated customer origin and successfully executed
through the actual public `agentconcierge.biz` gateway. Evidence and deployable copies
of the three current templates are in `reports/workflow-sdk-package-2026-10-17/`.

The operator server remains running. Restart it manually to register the new ZIP
export API. Generated packages already target the existing public workflow API.

## Public frontend ZIP download (2026-10-17)

Both the public canvas Download Web App button and template-hub download buttons
now request `GET /api/workflows/{template_id}/webapp`. This public, rate-limited
route re-reads the saved workflow and uses the same safe package builder as admin.
Only active safe published templates are exportable. Missing, private, inactive or
credential-bearing definitions return a generic not-found response. Request query
parameters and client-side graph/display edits cannot change the generated package.
Downloading does not start a workflow run.

The browser downloads a ZIP attachment with the SDK, app, CSS and deployment guide.
It masks errors, restores buttons after failure, uses no cookies for the download,
and does not render server diagnostics. The generated app's gateway remains fixed
to `https://agentconcierge.biz`. Home menu metadata, workflow metadata, visible
instructions and the deployment FAQ describe ZIP deployment and required internet
connectivity. Embedded public HTML and its extracted copy remain synchronized.

Tests cover both frontend entry points, successful execution on another host under
a subdirectory, private/unsafe template denial, tampered browser metadata, hostile
published copy and provider output, download rate limits and UI error recovery.
Evidence is in `reports/frontend-workflow-package-2026-10-17/`. The operator manages
server restarts; a running process must reload source to register the new public
ZIP route.
