# B2A discovery, resumption and recovery

This document replaces unconditional verification, token-saving and automatic
recovery claims with explicit contracts. Discovery suggestions never authorize
an execution, workflow run, payment, notification or marketing delivery.

## Evidence and contracts

`concierge/discovery_state.py` reads the latest execution evidence for the exact
current connection version. Verification requires a successful, unexpired
execution within 24 hours, an available supported profile, current admission,
and a supported informational MCP tool where applicable. Review, quarantine,
inactive bindings and the invocation kill switch withdraw verification. A
health response, caller feedback or old-version report cannot create proof.

Agent cards expose `capability_contract` with protocol, required input names,
connection version, verification state/times and an opaque fingerprint. Domain
contract approvals and their test results remain separate in
`capability_contracts`. General execution proof does not prove semantic
interchangeability or input/output compatibility.

The SVG badge states recorded evidence, not continuous availability. Its
`data-checked-at`, `data-expires-at` and scope describe its evidence. The handler
never proposes a cache age longer than the earlier of five minutes and evidence
expiry; stricter site-wide cache controls may apply.

## Session resumption

`GET /api/agent/v1/resume` requires `X-Visitor-Token` or the existing authorization
transport. URL query tokens are not accepted. Authentication occurs before
conditional request processing; a matching validator is not an authority token.

The response retains task/protocol scope and failed IDs and returns up to three
current agent or workflow choices. It compares all displayed choices, including
connection/schema/evidence changes, semantic approval/readiness changes, and
workflow definition/availability changes. It does not overwrite the previous
baseline simply because a preflight GET was made.

Conditional GET uses HTTP weak comparison for strong and weak ETags, validator
lists and `*`. Malformed/oversized validator fields do not produce a 304. An
unchanged response has an empty body. Current selection is re-evaluated on every
request; there is no request-time LLM, but neither backend work nor external
model-token use is guaranteed to be zero. Clients should revalidate before use
and no later than the earlier of the suggested interval and `expires_at`.

## Optional next-tool suggestions

The first selected agent may have at most two `next_steps`. Candidates must pass
the requested protocol scope, failed-ID exclusion, current execution evidence,
public admission and bounded informational-tool schema checks. Automatic/Any
scope uses A2A first and MCP second; x402 requires an explicit request. The same
scope is retained for follow-ups. Suggestions expose managed gateway addresses.

Historical transition frequency only orders possible suggestions. Cold-start
siblings require an affinity with the selected tool and have no fabricated
probability. No provider is contacted to obtain a suggestion. Invalid metadata
or an optional storage failure drops the suggestion, logs only its error class,
and preserves the primary recommendation/result. A hint is neither approval to
run nor proof that one tool's output fits another's input.

## Outcome reports and recovery

`POST /api/agent/v1/report` requires an existing visitor session and JSON.
MCP `tools/call` with `name=report` retains the existing visitor transport and
legacy first-contact behavior. Both use `concierge/recovery.py`.

Required fields are positive integer `resource_id` and boolean `ok`. Optional
fields are bounded `task`, `error`, structured `error_type`, and an explicit
`protocol`. Error types are `timeout`, `http_5xx`, `auth_error`,
`schema_mismatch`, and `rate_limit`. Structured types take precedence over the
conservative text classifier. Unknown fields/types are rejected. Provider error
text is not echoed or used as instructions.

Caller feedback updates session outcomes and existing feedback storage, not
Registry evidence. Failed reports return `alternatives` (at most three), legacy
`alternative` (the first or null), eligible published `workflows`, and an
explicit `suggestions_only`/`execution_authorized=false` boundary. No candidate
is guaranteed. Prior selected protocol scope is retained unless explicitly
changed. Candidate enumeration and failure-history inspection are bounded.

Recovery excludes failed IDs, normalized same endpoints/hosts, and known or
declared shared failure dependencies, including shared publisher metadata.
Different hosts alone do not establish full independence. Missing or invalid
dependency information can refuse a candidate, never grant independence.
Published workflows must have available, currently verified agent bindings and
must not include failed/aliased dependencies. Authoring, input sharing, run
authorization and delivery grants remain with the existing workflow runtime.

The direct MCP call path uses the same recovery selector only after a definite
failure. Unconfirmed dispatched calls remain paused; they do not trigger an
automatic retry or alternative execution.

## Validation and rollout

The initial audit cases are maintained in `tests/test_b2a_retention.py`, with
additional adversarial HTTP, evidence, metadata and failure-domain cases. The
historical audit command imports those regressions without duplicating product
logic. Positive verified cases carry current version-bound execution evidence;
negative cases keep their rejection assertions.

Affected API/Gateway/notification regressions and browser CSP/XSS/privacy checks
are required. SQL remains parameterized and the explicit PostgreSQL catalog must
be rebuilt/checked. `python -m scripts.rehearse_b2a_retention_postgres --run`
uses a disposable Unix-only database, accepts no operating DSN, and prefers an
installed PostgreSQL 18 on macOS. Platform resource failures must be reported
separately from application failures.

When another postmaster cannot start because of OS shared-memory limits, use
`python -m scripts.rehearse_b2a_retention_postgres --run --schema --full`.
This explicitly reads the existing private local Unix-socket profile from
`gateway-data/agentcon.env`. It requires PostgreSQL 18 and database CREATE
permission. It creates randomly named owner-only schemas, initializes the
checked-in application schema with synthetic data, compares SQLite/PG discovery
contracts, then runs the full application contract fixture. It rejects enabled
event triggers, foreign schema references and changed schema ownership. Its
search path and writer advisory lock are separate from production, and cleanup
refuses foreign dependents before dropping only its own schema identity.

The normal Store factory still selects the reviewed public runtime schema. The
rehearsal class is selected only by this explicit CLI. No operating application
data is copied or written, no role/server configuration is changed, and no
service is restarted. Database catalog DDL and synthetic fixture writes do occur.
Shared-cluster concurrency is limited to two writers; it is not a capacity test.
Production lexical/pgvector ANN projections are not attached: fixtures exercise
the existing bounded FTS projection and exact vector/provenance path. Native
index, crash recovery, restore/HA and load acceptance require separate fixtures.

Package and runtime verification are separate from source verification. A user
deploys the frozen release after shared-source changes are finished. An HTTP 200
on a new route alone is not acceptance of its trust or recovery behavior.
