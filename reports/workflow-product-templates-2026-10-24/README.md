# Verified workflow product development and qualification

Status: **operating v2 acceptance complete. Fallback is enabled; templates
41/42/43 are published and publicly verified.** Same IDs were requalified after
repair; no duplicate products were created. See [the final operating acceptance](OPERATING_V2.md)
for actual HTTPS browser, changed-input API, controlled-outage and exported-app
results, plus the signed expiration/capacity limits. Historical failure/withdrawal
sections below are preserved as history and are superseded by that acceptance.

## Delivered products

- **Research Search API** — public English keywords/result limits to normalized
  research records, source links, retrieval times and partial-result status.
- **Research Comparison Board** — two independently declared topics, two source
  panels, reciprocal Crossref/arXiv fallback and deterministic local response join.
- **Source Bibliography API** — real titles, links, retrieval times and source
  reference dates; no invented authors, scientific findings or citation content.

Sources are the first-party local Research Papers handler backed by real Crossref
queries, and Paper Finder's arXiv-only native tool. The generic Paper Finder search
also uses Crossref and was explicitly excluded as a supposedly independent source.
Different native input/output schemas use reviewed signed generic mappings. They
preserve original URLs/times and reject unsupported non-English prose. Search
coverage differs between bibliographic articles and preprints; the UI discloses
this instead of claiming identical records. Other service domains were not padded
with fixed-data or unverified templates.

## Implementation

- Signed product draft/acceptance/publication records bind workflow graph, public
  descriptions, tool/schema approvals, mapping profiles, semantic policy and
  implementation files. Normal success alone cannot qualify a product.
- Each distinct primary needs a successful signed private controlled-outage run,
  an actual completed alternative business dispatch, preserved authority and
  successful checkpoint signatures. Request bodies cannot supply success proof,
  provider identifiers, arbitrary graphs or a fault-injection switch.
- Active product routing uses 100% of explicitly opted-in eligible requests,
  at most one alternative for the entire run, at most 1,000 admissions, and a
  23-hour operator window bounded by proof/profile expiry. Existing canary limits
  remain unchanged. Missing consent, exhausted capacity, changed/revoked proof,
  disabled routing or expired policy blocks protected execution; it cannot silently
  downgrade to an unprotected baseline.
- Runtime inputs are signed into each run snapshot rather than mutating the saved
  graph. Input changes therefore do not invalidate its routing fingerprint.
- Public hub input controls are generated in both the source shell and the actual
  Pearl publication. The separate generated publication was rebuilt; editing only
  `front.py` would not have updated the displayed UI.
- Product ZIPs provide English static web apps, bounded input forms, fresh consent,
  CSP, loading/status feedback, safe text/source-link rendering, a manifest and
  deployment instructions. Calls go through agentconcierge.biz, capabilities stay
  in memory/headers, and POST requests are never automatically repeated.
- Authenticated administrator product downloads use the same public product format
  without issuing SDK deployment grants. Ordinary SDK/export formats are preserved.
- The local-owner operator checks immutable source equality and readiness across
  frontend/admin/jobs/execution **before mutations**. It rejects conflicting
  current tool approvals, preserves existing templates/history, reuses current
  qualified products on repeat runs, and audits the distinct local-owner identity.
- Additive schema migration and fail-closed restore revocation are included.

## Failure found and corrected

Repeated live tests exposed Crossref **HTTP 429** on the second consecutive list
query (`quantum error correction`); a direct identical transport check returned
200 then 429. This was a real upstream quota issue, not a successful empty result.
Earlier failed attempts remain in `qualified-live-final.txt` and
`qualified-live-source-diagnostic.txt`; they were not counted as passes.

Crossref documents separate list-request and concurrency limits. The adapter now
serializes list calls within each process, spaces responses conservatively by at
least 1.1 seconds, respects stricter bounded rate headers and 429 cooldowns, and
fails before a new source request if its existing deadline cannot accommodate
waiting. There is no hidden network retry or fabricated replacement result.
The final paced run passed all three products and repeated-registration checks.

References: [Crossref request limits](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/),
[Crossref list-request announcement](https://www.crossref.org/blog/announcing-changes-to-rest-api-rate-limits/),
[OpenKrill provider support](https://tools.openkrill.app/support),
[JSON Schema regex profile](https://json-schema.org/understanding-json-schema/reference/regular_expressions),
[OWASP ReDoS guidance](https://community.owasp.org/attacks/Regular_expression_Denial_of_Service_-_ReDoS).

## Validation evidence

- `final-regressions.txt`: **302 passed**, exit 0, one consolidated selection of
  engine, transforms, approvals, fallback, API, Chromium, standalone ZIP, isolated
  TCP interruption, first-party adapters and source quota controls. No skip/failure.
- `operator-cli-tests.txt` and `final-product-tests.txt`: four additional immutable
  deployment-state tests and one authenticated admin download test passed. Including
  overlap only once gives **307 unique pytest cases**. The latest product/CLI
  selection contains 23 cases and does not add another 23 to that total.
- `qualified-live-products.json` and `qualified-live-paced.txt`: three products
  accepted/published **in a disposable catalog**, four controlled single-primary
  outage runs, normal shadow runs, changed public inputs, protected admission,
  structured real data, ZIP generation, and idempotent repeat qualification.
  `isolated=true`, `operating_mutations=0`; IDs 4/5/6 are disposable IDs.
- `live-product-tests.json`: earlier real-data fault scenarios additionally cover
  both sources unavailable and safe failure, including the comparison reverse
  switch. These older trials are supplementary, not current operating approvals.
- `postgres18-products.json`: **8 native PostgreSQL 18.6 checks** for fixed SQL
  upsert, signature/quoted payload roundtrip, lookup, additive/idempotent schema,
  empty operating table and application-store attachment. Session-private TEMP
  rows were used. The only application schema mutation was one empty table.
- `static-check.txt`: focused Ruff F/E9 review passed; Python/JavaScript syntax
  checks passed. `content-check.txt`: **252 public files, 0 content violations**.
- `catalog-check.txt`: checked-in PostgreSQL catalog current, 231 tables and 3,711
  fixed statements. `operating-rollout-gate.json`: stale deployment rejected
  before mutation; operating fallback still 0/revision 0, products still 0.

Secure-coding review covered input whitelists/bounds, output escaping, HTTPS links,
CSP, secret/visitor-token non-disclosure, signature/authority integrity, stale
proof withdrawal, private fault scope, restore isolation, absence of automatic
POST retries, and authenticated download behavior. These are affected-path checks,
not a certification of every platform route or dependency.

## Initial operating rollout — completed; use the repair batch below now

The empty schema is ready. Per `AGENTS.md`, the user runs services directly; the
agent has not deployed or restarted them. Run in the project terminal:

```sh
agentcon package workflow-products-20261024-v1
agentcon deploy frontend workflow-products-20261024-v1
agentcon deploy admin workflow-products-20261024-v1
agentcon worker-deploy jobs workflow-products-20261024-v1
agentcon worker-deploy execution workflow-products-20261024-v1
```

After deployment confirmation, continue the already-authorized operation:

```sh
.venv/bin/python -m scripts.qualify_workflow_products
.venv/bin/python -m scripts.qualify_workflow_products --apply --authorize-public-provider-tests --publish-passed
```

The agent will inspect operating proof, hub projection, real execution and download
responses. Only passing products are registered. If current providers cannot pass,
they remain private; the implementation does not label the isolated result as
operating success.

## Practical limits

Independent endpoints/operators and provenance checks cannot prove complete
physical network/CDN independence. Controlled preflight outages do not shut down
external providers; general regressions separately stop isolated TCP providers.
Original-source caches may return previously retrieved real records, whose original
times are preserved. Cross-process quotas and upstream outages remain possible.
No zero-failure SLA is claimed. Approval is deliberately time/capacity bounded;
renewal needs fresh qualification. Test ZIPs in this report use disposable IDs and
must not be deployed as operating products.

## Operating follow-up: delivery repair history (resolved by v2 acceptance)

The user deployed v1 to all roles. Common files matched (21 per role), public
pages/assets returned 200, but the 24-connection PostgreSQL cluster had all 21
ordinary slots occupied. With explicit user approval, only the drained, inactive
frontend/admin A processes were stopped. Active B processes, the database and old
release files were preserved. Ordinary connectivity recovered.

The CLI was corrected to verify worker release identity from the actual running
command and immutable manifest, because worker heartbeat payloads do not carry a
release field. Native local-owner contract approval now performs its authority
check and audit within the PostgreSQL writer transaction rather than requesting
SQLite's nested BEGIN guard. These are operator-tool changes, requiring no server
reload. Nine CLI cases initially passed, and same-ID requalification is now tested.

Operating native qualification initially passed and registered IDs **41, 42, 43**.
However, the actual public worker path then failed with `UPSTREAM_PROTOCOL` and
`unknown/uncertain` attempts for the owned research agent. The successful laboratory
and initial owner CLI used native delivery; the running worker also loaded Edge
configuration. First-party MCP was being sent through public Edge HTTP instead of
its validated local handler. Unknown dispatched requests were correctly not
repeated, so there was no silent duplicate native call.

**The three products were withdrawn (`is_template=0`) and fallback paused. They
are not currently offered as operating products.** The earlier successful native
qualification alone must not be presented as successful public service validation.
The initial browser assertions verified loading/consent controls but did not check
the terminal outcome; the saved screenshot shows the failure. Its JSON is marked
loading-only/failed and the browser script now explicitly requires terminal success.

The prepared correction in `edge_gateway/native.py` returns to the normal local
binding path before any Edge ticket or packet for first-party identities. External
providers retain their original Edge path; uncertain requests still never request
native replay. The owner qualification tool now loads the same optional Edge
settings as the service and can requalify the same withdrawn IDs without creating
replacement products. Proofs are regenerated after shadow/controlled-outage runs.

`edge-local-security-regressions.txt`: **96 affected cases passed**, exit 0.
`edge-local-static.txt`: focused source/fixture lint passed (standard imported
pytest-fixture naming exemptions only). PostgreSQL catalog remains current; no
schema or public rendering change is required by this repair.

Only the execution worker needs the new native delivery code. The other roles
have matching common product code and remain active. Run this user-owned batch:

```sh
agentcon package workflow-products-20261024-v2
agentcon worker-deploy execution workflow-products-20261024-v2
```

After confirmation, run the guarded operator again, then require successful real
public changed-input runs, browser terminal success and current ZIP downloads
before treating registration as complete. No replay of the old unknown runs is
planned. No additional service or database restart is requested.
