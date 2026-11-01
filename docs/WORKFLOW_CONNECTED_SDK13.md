# SDK 1.3: separately reviewed connected deployments

2026-10-18 · `connected-informational-deployment-v1` · manual public news-to-documentation applications.

This profile lets a highest administrator export a web application for an already
reviewed and published canonical public news-to-documentation connection. The
application can be hosted on the exact HTTP(S) origins approved for that deployment.
All execution remains at `https://agentconcierge.biz`; the package does not expose
a provider endpoint, private definition, credential or administrator session.

## Separate publication, deployment and run purposes

The canonical test and publication procedure in
[Public connections](WORKFLOW_PUBLIC_CONNECTIONS.md) remains a prerequisite.
Publication itself does not authorize an external deployment. A new independent
deployment proposal reviews that publication, the fixed news inputs, documentation
recipient/settings, future-title rule, exact allowed origins, quotas and expiry.
The highest administrator explicitly issues this separately revocable deployment.
A preparation response is a review proposal, not an issued grant.

Every manual visitor run requires a new server-signed ticket and two initially
unchecked declarations: sharing the checked first news title with the named
documentation recipient, and one live execution. The actual future title is not
known before the news call. Neither an administrator's publication/deployment
approval nor a publish key replaces those per-run declarations.

The fixed news query, language, result limit and absolute UTC news window remain
visible in each run review. The documentation query is derived only from this
run's certain, signed news checkpoint. It is never accepted from the browser or
silently replaced with the original news query. Invalid, sensitive, address-bearing,
empty or overlong titles stop downstream dispatch rather than being coerced.
These checks do not universally classify every possible personal datum or verify
the factual truth of external content.

## Deployment and capability boundary

The independent deployment identity and grant are stored outside legacy registered
apps. A public publish key is retained only as a hash on the server; it is embedded
in the downloaded public application as a deployment control. A key and Origin
allowlist are not proof of a person's identity. Anyone able to run authorized
client code can observe that public key, so quotas and revocation remain necessary.

The signed grant binds the publication revision, canonical definition and original
reviewed proof, allowed origins, limits, owner and expiry. It cannot outlive its
publication. New invocations recheck the current publication, deployment, owner,
control epoch, pinned connections and evidence. Source-derived arguments and
captured checkpoint provenance are rechecked before documentation dispatch.
The signed checkpoint authenticates the retained source projection and its
provenance; it does not authenticate the provider's raw wire, authorship or truth.
An administrator export proposal is single-use, including after withdrawal or a
failed package build. Its nonce is consumed atomically with the grant. At most
20 grants may be issued per owner in an hour. A failed package build attempts CAS
withdrawal; an interrupted download must be inspected in deployment history
before the administrator prepares and explicitly authorizes another proposal.

A signed run ticket binds its deployment, publication, exact origin, notices,
nonce and expiry. Accepted replay resolves to the same run and scoped capability
while the scope remains authorized. It does not admit another run or consume
another start slot. A different deployment, origin, purpose or legacy route cannot
reuse that ticket or capability. Tickets remain in memory and are submitted in
the signed run JSON body; publish keys and scoped run keys travel in headers.
Neither tickets nor keys belong in URL parameters, persistent storage or telemetry.

The ordinary absolute 25-second deadline, maximum two provider tool dispatches,
lease/fence/checkpoint rules and conservative `unknown` quarantine remain. A
process death after dispatch does not establish that the external request failed
or authorize another provider call. An ambiguous start response locks a new start
in that visit; status resume only inspects the existing scoped run. The client
does not automatically retry Prepare, Execute or Cancel POSTs. Status GET retries
are bounded; monitoring timeout does not assert that the server run was cancelled.

## Withdrawal, history and restore

Deployment withdrawal uses the current CAS revision and retains a tombstone.
Publication withdrawal or expiry also invalidates dependent deployment execution.
Revocation prevents later dispatch and requests cancellation of unfinished work.
An external request already in flight may complete; exactly-once external effects
are not guaranteed.

Accepted status/cancel access is distinct from fresh invocation readiness: a
provider becoming ineligible, invocation controls being paused or retained
publication-test proof being pruned must not by itself hide an accepted failed or
unknown outcome. Current publication/deployment/owner authority, origin, key,
capability expiry and retained signed purpose still constrain that access.

Backup restore deactivates the new grants, increases revisions and retains their
tombstones. Execution controls remain paused. It never automatically republishes,
reenables or reissues a deployment from an old snapshot. The PostgreSQL rehearsal
covers this additional execution-state table; it is not a full Store/catalog,
FTS, authentication, collector or ledger migration and is not production HA.

## Scope and future automation

The separate [administrator automation](WORKFLOW_CONNECTION_AUTOMATION.md)
contract now supports bounded schedules and authenticated administrator events.
That independently reviewed grant is outside this manual SDK. The SDK does not
collect unattended sharing permission or acquire authority from such a grant.

This release supports only the separate canonical public news-to-documentation
profile. Existing public SDK 1.0, administrator SDK 1.1 and literal SDK 1.2 package
sources and routes retain their own limits. Private drafts, private controlled
pairs, arbitrary graphs, dynamic browser inputs, credentials, fallback, extended
budgets, schedules, events and result delivery remain outside this deployment.

An unattended schedule/event must have a separate future purpose. Its review must
bind the trigger, time/window policy, recipients, fixed and future derived inputs,
frequency, expiry, execution budget, quotas, independent revocation and dispatch/
recovery checks. A visitor's one-run permission cannot authorize future automated
sharing, and publication/deployment permission cannot imply it. No automation
consent is collected while that executor is unavailable. Marketing and task
notification permissions remain independent as well.

Successful contract execution is ordinary invocation evidence, not an expert grade,
quality winner, factual/source certificate or protected holdout result. Independent
reviewers, reviewed source materials, enforced access and chronological pre-run
evaluation allocation remain separate operating requirements.

## Versioned transport and hosting

SDK metadata is `1.3.0`. The separate notices are
`workflow-connection-app-v13-grant-v1`,
`workflow-connection-app-v13-share-v1` and
`workflow-connection-app-v13-run-v1`. They are not interchangeable with the
publication page, literal SDK, private test, delivery or automation purposes.

Highest-administrator routes use the existing authenticated dashboard,
same-origin/CSRF protections, strict bounded JSON objects and no-store responses.
Their base is
`/admin/api/workflow-publications/releases/{release_id}/export-app-v13`:

- `GET /options` and `GET /deployments` inspect readiness and non-secret grant records.
- `POST /prepare` reviews exactly `allowed_origins`, `minute_limit`, `day_limit` and `ttl_seconds`.
- `POST /package` or `POST /html` consumes that signed proposal with explicit `deployment_authority` and `deployment_notice`.
- `POST /deployments/{app_id}/revoke` takes the current integer `revision`.

At least one exact HTTP(S) origin is required. Wildcards, null/file origins,
credentials, paths, queries and fragments are refused. Starts are bounded to
1–30 per minute and 1–5000 per UTC day, with the existing per-IP limit. Requested
grant duration is 300–86400 seconds, clipped to the publication and original
test validity. A review lasting less than five minutes cannot issue a deployment.
Administrator proposals last at most 15 minutes; run tickets last at most five
minutes. A late run submission can end authorization before the full run budget.

Public requests use `X-Publish-Key` at
`/api/workflow-connection-apps-v13/{app_id}`:

- `POST /prepare` accepts only an empty object; it has a separate prepare quota.
- `POST /runs` requires the exact signed proposal and separate `sharing_authority`/`sharing_notice` and `run_authority`/`run_notice` declarations.
- `GET /runs/{run_id}` and `POST /runs/{run_id}/cancel` additionally require the scoped `X-Workflow-Key`; cancellation accepts only an empty object.

The actual registered Origin is required, including on preflight. Cookies and
browser credentials are omitted. Read responses and errors are no-store and do
not echo request keys, private proof, original provider URLs, known private
filesystem paths or traces. Legitimate public source citations can retain paths.
Capabilities last at most one hour from admission and end earlier when either
grant expires or is withdrawn. Current provider readiness is separate from the
accepted history scope described above.

The ZIP contains local HTML/CSS/JavaScript, minimal public deployment configuration
and an English README. A single HTML variant embeds the same assets with nonces.
Subdirectory hosting is supported. The package's restrictive meta CSP permits
connections only to the fixed gateway. The supplied client refuses preparation
and starts inside a frame. The host should additionally send an HTTP CSP with
`frame-ancestors 'none'` and `X-Frame-Options: DENY`; a meta CSP cannot enforce
`frame-ancestors`. Browser/client guards do not replace server authorization or
the host's response headers.

## Verification and operation

Development uses isolated databases, local fixture providers, temporary ports and
browser tests. It does not create production approvals/publications/deployment
grants, execute production providers, deliver notifications or operate the user's
terminal server merely to populate an interface. New Python behavior requires the
user's normal restart and authenticated operating acceptance. The earlier v1.19
read-only dialog/empty-catalog observation is not an SDK 1.3 deployment acceptance.
