# Managed public agent connections

Implemented 17 October 2026. This contract covers registered-agent connections and
the public Testbench. The existing Concierge `/mcp` and `/a2a` discovery services
remain separate from per-agent execution. Public workflow ZIP/SDK v1.0 and admin
workflow application v1.1 retain their existing deployment contracts.

## Public connection profiles

Each supported connection uses
`https://agentconcierge.biz/api/gateway/{kind}/{resource_id}`. IDs must be positive
registered integers below 2147483648, and the path protocol must match the registry.
No upstream URL, destination override, authorization header or client-selected
session identifier is accepted as a routing instruction.

- **MCP:** stateless JSON-RPC POST; `initialize`, `ping`, `tools/list`, `tools/call`
  and `notifications/initialized`. GET returns 405 with `Allow: POST` and a profile
  description. Streaming, server-side MCP sessions, resource access, sampling and
  cancellation are not advertised. Initialization negotiates the supported
  `2025-06-18` profile. Remote provider discovery/handshakes remain internal.
- **A2A:** GET returns the managed 0.3 Agent Card; POST accepts `message/send` and
  `SendMessage` and returns synchronous text/data messages. Registered JSON-RPC
  guide endpoints and recorded method overrides are honored only on the registered
  public origin. Arbitrary continuations, callback configuration, task polling,
  streaming and task cancellation are not supported. Pending, failed and malformed
  provider results never become completed messages. Upstream task/context handles
  are not exposed. Informational input screening is conservative and is not a
  guarantee about an independent provider's internal behavior.
- **x402:** GET performs one bounded probe. POST accepts only `{"action":"probe"}`.
  A structurally valid v1/v2 challenge is distinct from successful resource access.
  A bare HTTP 402 or an L402 header is insufficient. v2 challenges are also emitted
  in the `PAYMENT-REQUIRED` header. Financial fields required by machine clients are
  preserved; automatic authorization, settlement and paid request replay are not
  implemented by this profile.

## Admission and outbound boundaries

`execution_policy.py` supplies shared active/quarantine/security/endpoint checks and
bounded offline schema validation. The MCP proxy applies registered capability
and safe-tool checks before upstream contact, checks the pinned compact capability
hash after discovery, and validates inputs against the full live schema before
calling the tool. Changed compact capabilities quarantine the resource. A compact
hash is not a complete immutable full-schema version registry; that remains a
separate advancement item.

The additional name-based safety check distinguishes confirmed informational
nouns from action substrings, including `skills`/`kill`, `credit`/`edit`,
`design`/`sign` and `posts`/`post`. Exceptions require an explicit read-only
declaration and a recognized query action. They apply to complete words, including
camelCase names. Ambiguous singular query objects must follow the query without
an intervening action/conjunction. Signing and destructive verbs elsewhere in the
name, credential inputs and unregistered tools remain refused.
The same check drives managed MCP tool listings, Testbench details and execution;
published workflows use it through the shared proxy.

Public managed calls require healthy/reachable resources and reject unapproved
provider authentication or charges. x402 challenges can be inspected without
spending. Natural-language A2A requests are limited to informational requests and
obvious action/PII patterns are refused. Schema references and regex constraints
requiring unsupported validation are rejected rather than fetched or evaluated.
Names inside a schema's `properties`/definition maps are ordinary field names:
an argument named `pattern` or `$ref` is not itself an executable regex or remote
schema reference. Actual schema-level regex/reference constraints remain refused.
Workflow input validation reuses this bounded validator instead of maintaining a
different recursive keyword scan.

Public execution uses TLS verification, public IP validation at connection time,
no environment proxies or redirects, bounded response sizes and a shared absolute
operation deadline. The standard managed MCP/A2A transports force public-only
connections even if the operator enables development private-network access.
Explicitly injected HTTP transports are trusted application dependencies, used by
controlled integration tests; no public request can select one.

Four process-wide execution slots have no waiting queue. A timed-out worker retains
its slot until it finishes. Per-IP probe limits and public request/body limits also
apply. The managed operation limit is eight seconds; Testbench accepts a smaller
limit down to two seconds. A timeout does not prove that an independent provider
stopped processing, and does not trigger automatic retry or fallback.

## Public projection and evidence

`connections.py` projects explicit invocation/discovery bindings to managed URLs.
It preserves independent news, documentation and result links, including documents
on the same provider origin. Nested and double-encoded report JSON is handled.
Agent detail responses use an allowlist instead of dumping registry discovery or
private authentication records. Stored resource URLs and original report evidence
are not rewritten. Recommendations use the same projection across REST Chat, MCP,
A2A and task-update selection. Existing Chat display restrictions remain in effect.

Only valid positive IDs and supported protocols produce managed URLs. Demo IDs or
unbound records produce no fabricated fallback address. Browser origin checks use
a parsed exact HTTPS origin, default port and no userinfo, not a string prefix.
Old discovery caches and pre-upgrade Testbench session history are discarded;
unrelated browser preferences and saved workflow canvases are retained.

`/api/test/execute` displays the actual sanitized client envelope (method, path and
body), with `scope: client-to-gateway` and `sanitized: true`. Credentials and ambient
browser headers are excluded. The response inspector is labeled a gateway result
summary. `latency_scope: gateway-operation` excludes browser network travel and is
not presented as provider-only or end-to-end round-trip time.

Results separately report `simulated`, `transport_ok`, `protocol_valid`,
`task_status` and `execution_succeeded`. The four demo presets have no live URL,
quality grade, fabricated provider timing, real financial claims or successful
execution assertion. They never contact a provider. Their measured time is labeled
local demonstration processing.

The four main Testbench cards are now reviewed **live MCP examples**: technology
news, camera documentation, racket research and famous train routes. Their
`Run Now` actions resolve positive registered resource IDs and use the normal
managed execution API. `testbench_examples.py` resolves only the reviewed canonical
bindings, then checks resource admission, schema pin availability, tool safety
and arguments. Missing/ineligible examples are disabled; they never silently
fall back to a demo. Existing negative-ID format demos remain separate in the
selector and retain their truthful non-executing API semantics. A2A and x402
registered tests remain available through the selector.

`GET /api/test/presets` keeps the legacy `presets` array and adds `live_examples`.
The Home bootstrap includes the same examples and scopes its cache to the backing
store so one app/store cannot advertise another store's resource IDs. Home/Test
copy and metadata distinguish live examples from format demonstrations.

Testbench shortcuts are generated from the selected agent's allowed registered
tools. Generic sample inputs are generated only from public schemas and validated
before publication; stored provider defaults, examples and private trial arguments
are not reused. Unresolved identifiers still require user input. Selection requests
are versioned so a late response cannot overwrite a newer selected agent, and
execution waits for the connection to load. These controls do not replace server
admission or full live-schema validation.

## Validation and deployment

### Stabilization update, 18 October 2026

Initial Testbench catalog refreshes update options without restarting the same
explicit selection or replacing edited inputs. Outdated catalog loads are ignored;
an in-flight execution prevents another recipe from dispatching. Execution history
and inspection use the endpoint captured for that run.

Managed execution failures include an allowlisted `error_code` and an opaque
`correlation_id` (`ex_` plus 24 hexadecimal characters). MCP/A2A execution errors
carry these fields in JSON-RPC `error.data`; Testbench preserves HTTP refusal/busy
statuses and shows a support reference. Proxy and workflow failure categories use
the same vocabulary. Existing result/state/protocol fields retain their meaning.
These references grant no access and are unrelated to visitor/authentication tokens.
Admission messages and raw provider errors are not used as a public diagnostic dump.

The `agent_market.execution` logger records only the reference, public resource ID,
protocol, fixed category/stage and exception class. It records no arguments,
messages, URLs, headers, tokens or visitor identities. This is a diagnostic logging
foundation, not the persistent cross-process operation/attempt registry or complete
recommendation/execution/delivery metrics proposed in R-02. Existing log retention
and administrator access controls apply.

Task-update approval and queued delivery also bind to an internal HMAC of the
registered provider connection, protocol/authentication state and capability hash.
A stable public gateway URL cannot conceal a changed private binding from these
checks. Irrelevant fetched timestamps/descriptions do not invalidate approval.
Legacy pending events without this binding evidence are canceled rather than
sent without a fresh check. No new destination or advertising permission is inferred.

Use `python scripts/run_frontend_regressions.py --output reports/frontend-regressions`
for the isolated public feature/security gate and catalog-name corpus. An explicitly
provided `--catalog-db PATH` enables the read-only whole-catalog metadata audit;
it does not contact providers. The GitHub workflow uses read-only permissions,
commit-pinned official actions and no deployment credentials. Its hosted run must
still be confirmed after the change is committed/pushed. Product source changes
require the user's server restart; this workflow never operates that server.

See `reports/managed-gateway-hardening-2026-10-17/README.md` for final results,
source snapshots, static scanner triage, real TLS integration, browser regressions
and compatibility verification. Tests use disposable databases, controlled
providers and temporary loopback listeners; they do not scan the live service.

The user starts the project server in their terminal. No operational server,
database, secret or deployment configuration was changed by this implementation.
Reload/restart that server to activate these source changes. Production reverse
proxy reachability and real third-party availability require a separate deployed
smoke check after that restart; local tests do not establish their state.

The execution compatibility follow-up is recorded in
`reports/gateway-execution-fix-2026-10-17/README.md`. It includes a reproduction of
the `signals`/`sign` false positive, isolated browser execution through a downloaded
ZIP, and separate real read-only provider tests for all three published recipes.
The public SDK and ZIP builder remain unchanged; their server-side execution uses
the corrected shared proxy after the user restarts the server.

The broader compatibility review and live-example correction are recorded in
`reports/catalog-gateway-policy-audit-2026-10-17/README.md`. The reusable read-only
audit is `python -m scripts.audit_gateway_catalog DATABASE OUTPUT`. It examines
every catalog record and stored MCP tool definition without invoking providers;
separate evidence identifies which real providers were actually called.

References for challenge validation:
[x402 v1](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v1.md),
[x402 v2](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md).


## v1.14 public projection follow-up

Known execution path families, final REST/A2A/MCP reply projection and historical report identity/privacy are hardened without rewriting canonical upstream records. Independent citations remain sources, historical wire records are explicitly sanitized, and old public projection caches are invalidated. See [review and ordered changes](GATEWAY_PROJECTION_FOLLOWUP.md) for the bounded policy, regression evidence and remaining deployment acceptance.
