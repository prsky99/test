# Reviewed public news-to-documentation connections

2026-10-18 · `public-news-title-to-docs-v1` · source verification and operating acceptance are separate.

The public connection is a separate canonical release. It does not publish an
existing private connected draft or controlled pair, and does not extend the
literal SDK 1.2 deployment grant. Existing public SDK 1.0, administrator SDK 1.1
and literal SDK 1.2 packages retain their own routes and scope.

## Definition and explicit test

The highest administrator selects one currently approved stateless MCP news
source and one documentation recipient. The candidate fixes an English news query, absolute
UTC start time, language and result limit, plus the documentation language/limit.
The complete graph is exactly `start → news → documentation`. The only derived
field is the first news result's title becoming the documentation query.

Preparation performs no provider/model call and does not reserve a run.
Eligibility is rechecked against current registry metadata. The signed candidate
lasts 15 minutes. Sharing and one actual test run require separate unchecked
declarations. Test admission reserves a new canonical definition with its own
audiences, owner, nonce and signed bindings. It must execute that definition;
an earlier private test of another audience or digest cannot establish its proof.

The test and public run keep the standard absolute 25-second budget and at most
two tool dispatches. There is no planner, credential binding, fallback, extended
budget, schedule, event, result delivery or automatic external retry in this
profile. Completed checkpoints can be reused after recovery; dispatched requests
whose outcomes are uncertain remain unknown and are not automatically replayed.

## Publication authority

A successful test alone does not publish anything. Publication preparation
verifies the original signed principal and admission/call-start validity,
canonical definition, complete checkpoint set, certain successful attempts,
input hashes, source/target output contracts, causal order and derived-input
provenance. It reads retained evidence from one consistent snapshot. Contract
success does not certify factual accuracy, expert quality or an unseen holdout.

The administrator reviews a separate publication proposal and explicitly grants
public display and manual execution under this narrowly defined rule. The
independent publication grant binds the canonical definition, reviewed inputs,
source and target pins, rule, original test proof, owner, control epoch and expiry.
Its requested duration is 300–86400 seconds, bounded by the original test's
remaining 24-hour validity. Current owner role, definition, approvals and evidence
are checked again for new runs. Changing execution controls invalidates old
reviews; a pause/resume cycle does not revive a stale review.

Publication grants have CAS revisions and retained revocation tombstones. A
withdrawal requests cancellation and prevents later dispatch even if a separate
cancellation signal is lost. An external request already in flight may complete;
there is no exactly-once external-effect guarantee. Restore deactivates grants,
increments revisions and pauses execution controls. It does not republish them.
Each canonical tested definition receives at most one publication record. A new
release after expiry or withdrawal requires a fresh candidate and canonical test;
the old tombstone and URL are not recycled.

## Public review and execution

Only actively authorized, currently eligible releases appear in the optional
Workflows listing. Their separate page is `/connections/{release_id}`. An empty
registry adds no empty placeholder to the existing template menu. Existing three
templates and their downloads remain independent.

The visitor requests a fresh run review. It shows the exact fixed news inputs,
recipient aliases, fixed documentation settings, expiry and the first-title
sharing rule. **The future news title is not known yet.** The page does not claim
that the visitor reviewed the actual future title. The visitor separately permits
sharing the checked first title with the named documentation recipient and one
live execution. Publication permission is not reused as either declaration.

The signed public ticket lasts at most five minutes and cannot outlive its grant.
It binds the release revision, canonical definition and rule hashes, notices,
review time and nonce. Actual title and resolved arguments are obtained only from
this run's signed successful news checkpoint and certain attempt. Empty,
address-bearing, known secret/private-path, overlong or otherwise invalid titles
stop the downstream request. Values are refused rather than truncated or rewritten
to manufacture a usable query. These checks are not universal personal-data or
factual-accuracy detection.
The run principal cannot outlive the ticket. A late submission or earlier grant
expiry can therefore end authorization before the full 25-second budget elapses.

Immediately before documentation dispatch, the runtime rechecks the current
purpose, grant, pins, controls, exact arguments and captured source-checkpoint
provenance. An identically worded title does not authorize replacing its retained
source evidence. The checkpoint hash authenticates the retained privacy projection,
not the provider's original raw wire or the truth of its content.

An accepted nonce returns the same run and release-scoped capability while the
request remains authorized. Legacy public run routes and SDK routes cannot use
that capability to bypass publication withdrawal or expiry. Capabilities stay in
memory and request headers. The client never automatically retries a POST. An
ambiguous start error, including HTTP 400 after submission, locks another start
and asks the visitor to inspect status. Only bounded transient status GET retries
are automatic. Stop requests cancellation without asserting it has completed.

Accepted failed/unknown outcomes remain inspectable through their existing scope
when provider eligibility or retained publication proof becomes unavailable.
Metadata access is separate from fresh invocation readiness. Revocation, grant
expiry, capability expiry and owner authority still constrain access. Public
capabilities last at most one hour from admission and end earlier if their grant
expires or is withdrawn. Public
status returns fixed labels and permitted news/docs item fields; raw provider
wrappers, private pins, graph, proof and internal diagnostic fields stay private.
Known provider connection addresses are not relabelled as source citations.

## Routes and limits

Administrator routes require the current highest-administrator session and
existing dashboard/origin/CSRF guards, bounded exact request objects and no-store
responses. Their base is `/admin/api/workflow-publications`:

- `GET /options`, `POST /prepare`, `POST /test` prepare and explicitly test a new definition.
- `GET /tests`, `POST /inspect-test` inspect retained canonical tests.
- `POST /prepare-publication`, `POST /publish` review and separately authorize publication.
- `GET /releases`, `POST /releases/{release_id}/revoke` inspect and withdraw a release with its current revision.

Public routes use `/api/workflow-connections`:

- `GET /` lists up to 20 eligible releases; `GET /{release_id}` exposes minimal metadata and separate current readiness.
- `POST /{release_id}/prepare` accepts an empty object and invokes no provider.
- `POST /{release_id}/runs` accepts the signed ticket and separate sharing/live declarations, never client graphs or titles.
- `GET /{release_id}/runs/{run_id}` and `POST .../cancel` require its scoped `X-Workflow-Key`.

Start limits are ten per release per minute, five per client IP per minute and
500 per UTC day. Existing hashed-IP quota counters are reused without registering
an SDK app. Preparation has a separate counter; accepted nonce replay does not
consume another start slot. Same-origin guards constrain browser calls and are
not a person's identity or authentication proof. There is no new account,
notification subscription, advertising delivery or implied marketing permission.

## Verification and rollout

Development uses isolated databases, local fixture providers and browsers. It
does not automatically approve production agents, execute production providers,
issue production publication grants or restart the user's server. The new Python
and administrator actions require the user's normal restart and authenticated
operating acceptance. Source markers and fixture runs are not operating acceptance.

See the [verification report](../reports/advancement-public-release-2026-10-18/README.md)
and the [previous 61-file content inventory](../reports/advancement-public-release-2026-10-18/public-content-files.txt).
The inventory counts source and modification scripts, not public pages or agents.
The [current inventory](../reports/advancement-public-release-2026-10-18/public-content-files-current.txt)
also includes this release's public page builder and JavaScript asset. Run
`python scripts/check_front_content.py --list` to inspect the current selection.

The later [connected SDK 1.3](WORKFLOW_CONNECTED_SDK13.md) supports separately
reviewed manual deployments of an already published canonical connection.
Publication permission alone does not authorize that deployment, another
visitor's sharing/run declarations, scheduling or result delivery. The original
same-origin public connection page retains its independent routes and purpose.

Bounded [administrator automation](WORKFLOW_CONNECTION_AUTOMATION.md) is also a
separate reviewed purpose. Its schedule or authenticated event grant never
changes the publication page or a visitor's one-run authorization.
