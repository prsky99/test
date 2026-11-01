# Bounded informational workflow alternatives

R-06 · 2026-10-18 · source implementation; production activation is disabled by default.

This release adds an explicit routing policy to the durable workflow runtime, including its reviewed PostgreSQL store. It supports approved stateless MCP tools implementing `news.search.v1` or `docs.search.v1`. It does not automatically search the catalog for a substitute. A highest-admin operator selects an explicit compatible primary/alternative pair and reviews the current evidence first.

## Contract and consent boundary

Both connections must have current successful execution and contract evidence, a complete immutable connection version, and explicit `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true` annotations. Native input/output schemas must match the contract exactly, or an explicitly verified signed [generic I/O profile](WORKFLOW_IO_TRANSFORMS.md) must bridge the exact native and canonical schemas. The native schemas are never weakened. The primary node must explicitly name the approved tool. Connection version, tool approval timestamp, graph execution fields (including output-alias node names, transform recipes/profile IDs and trigger type) and policy revision are pinned. Credential-bound definitions, provider authorization, unsafe destinations, inactive/quarantined connections and unsupported schemas cannot gain alternative execution through this policy.

The validators check the defined shape, English request language, public HTTPS source URLs, retrieval recency, limits, duplicates and news period/order. They do **not** independently fact-check sources, certify a provider's implementation as side-effect-free, or supply an expert quality benchmark. Product comparison is excluded until numeric values/units and comparison meaning have a verified normalization contract. A2A tasks/sessions, x402, writes, payments and credential propagation are excluded.

A signed policy is separate from per-run permission. Public and authenticated admin executions may submit the boolean `allow_fallback=true` with `fallback_notice=readonly-fallback-v1`. The unchecked UI states that the same task input may be sent to one other verified agent. Permission is reset for the next run and is not saved to local storage. Anonymous visits, notification/marketing consent, a saved schedule, a downloaded app or a prior run do not authorize this sharing. Schedules/events/verification/deployment sources cannot opt in in this release. Existing public SDK 1.0 and admin SDK 1.1 packages send no new consent and retain baseline behavior.

Sensitive inputs rejected by the existing credential detector are not routed to an alternative. This is a credential guard, not a claim of comprehensive personal-data recognition. A consenting search may contain task information; the disclosure must remain factual.

## Disabled → shadow → bounded canary

The global `workflow_fallback_control` is a persistent revision-CAS switch, initially off. A separate signed per-workflow policy chooses `disabled`, `shadow` or `canary`. The superadmin APIs are:

- `GET/PUT /admin/api/fallback-control`: strict `{enabled, revision}` body.
- `GET/PUT /admin/api/workflows/{workflow_id}/fallback`: strict revision, mode, explicit node/resource/contract pairs, authorization notice, percentage, admission cap and expiry.
- `GET /admin/api/workflows/runs/{run_id}/recovery`: existing private recovery view plus routing attempts/decisions.

Admin **Errors → informational fallback** contains the switch and a multi-row policy editor for up to six explicit node alternatives. Grant revocation returns an exact count and an explicit schedule/inbox reapproval shortcut. The recovery dialog remains centered, escaped and stable across list refresh. Ordinary admin/operator roles cannot edit or inspect these private policies.

Shadow sends only the normal primary request. It checks that response and current candidate evidence; it never calls the candidate, duplicates the task or changes baseline business success due to a failed shadow semantic check. A signed receipt binds graph/pair fingerprint, workflow, run and node. Each configured node needs a valid current receipt from a successful normal workflow within 24 hours before canary may be configured. New bindings, schemas, approvals, input graph or pair selection invalidate readiness. No fixture or client-submitted flag creates provider evidence in production.

Canary has a maximum 10% deterministic keyed sample, 100 selected admissions per policy revision, and 24-hour expiry. The default form proposes 5%, 10 runs and one hour; an operator must apply it. Selection uses a server HMAC of the new run ID, separate from visitor identity. A DB compare-and-update counter bounds independent processes; selected admission is not a claim that an alternative actually ran. There is **one alternative attempt per entire workflow run**, including multiple configured nodes. A control/policy revision change blocks previously admitted alternative attempts, including off→on revival. Disabling does not require healthy providers.

## Failure, time and durable execution

The standard 25-second workflow deadline is retained. Explicit highest-admin runs may use the signed 60-second extended profile described in [operations hardening](WORKFLOW_OPERATIONS_HARDENING.md); public/apps/automation retain the standard budget. Selected primary calls have an inner 12-second budget and alternatives an inner 8-second budget, each nested within the remaining overall budget. Less than three seconds remaining blocks an alternative. The bounded transport clamps I/O and late responses are rejected; synchronous provider code is not forcibly killed. This is not a universal wall-time SLA.

Configuration and shadow require successful current evidence for both connections. Within an already signed canary, the primary keeps binding/schema/approval and active/safe connection checks while only the alternative requires current successful evidence. A primary failure cannot lock out a later explicitly opted-in canary run. Original uncertain dispatched requests are still never automatically repeated.

An alternative is allowed only after a pre-business-dispatch network failure, a verified definitive MCP error response, or a completed response that fails the supported output contract. Contract-invalid output records failed contract evidence. It is not allowed after a post-dispatch timeout/network ambiguity, cancellation, policy/auth/schema refusal, insufficient time, missing/expired evidence or changed binding. Invalid output from the alternative ends the run. No parallel provider probes occur.

The current run authority, global invocation/workflow controls, owner/fence/deadline/cancellation, policy/control revision, graph, connection, approval and candidate evidence are checked at the actual tool-dispatch boundary. An off switch prevents later business dispatch; it cannot undo a request already accepted by a provider.

Signed run admission is committed with the run and R-04 execution authority. `workflow_routing_attempts` records ordinal one/two, agent ID, fence, prepared/dispatched/final status and fixed reason. It records no raw input/output, endpoint or token. It complements the R-05 logical node attempt rather than replacing it. Before reserving an alternative a conservative recovery barrier is written. A hard crash at that boundary or after external acceptance requires review and cannot replay either primary or alternative. This may stop a safe-but-unconfirmed attempt; availability is subordinate to avoiding uncertain repeats. A committed signed node checkpoint can be resumed without invoking either provider again.

Only a completed, contract-valid alternative incorporated into the successful signed checkpoint adds `fallback_used=true`, chosen resource/agent ref, original requested resource and attempt count to the result. Candidate preparation or a nested provider field is not a server-confirmed fallback. Failed/cancelled nodes do not report successful fallback. The unchanged SDK hook reads the server summary. Final workflow result/count/outbox still commit atomically. No result delivery authority is inferred from opting in.

A policy change changes the workflow runtime digest and revokes old delivery grants, so an earlier single-provider delivery grant cannot silently authorize a changed sharing definition. Reauthorize result delivery separately if needed. Restore turns the fallback switch off, removes policies/shadow receipts and requires a fresh review; old pending executions and deliveries remain quarantined by R-05.

## Observability and acceptance limits

Private inspection exposes fixed decisions/reasons, distinct routing attempts and 24-hour grouped outcome counts with mean/max total routing elapsed milliseconds. The elapsed value includes provider wait; it is not provider CPU time or pure selection overhead. The selected-admission cap and actual attempts are different denominators. Best-effort common observations remain distinct from the durable routing tables. No visitor-level marketing funnel is introduced.

See [R-06 verification](../reports/advancement-r06-2026-10-18/README.md). Tests use isolated MCP transports, SQLite databases, real Chromium/API requests, controlled HTTP/TLS regressions, independent runtimes and real SIGKILL worker boundaries. This release has no production shadow/canary cohort, provider-wide semantic certification, authenticated live admin acceptance, high-availability/load certification or full PostgreSQL adapter. The latest isolated PostgreSQL rehearsal covers 27 execution/routing/operations tables, including these seven routing tables; full application adaptation is still absent. Full G0/G1 acceptance remains open. Public SDK/downloaded apps stay on their existing execution contract.

## Equivalence-group exclusion (2026-10-24; source hardening, no operating activation)

Future group-based alternatives must collapse registrations sharing the same
normalized endpoint, regardless of their names or resource IDs. For the first
pilot, different paths, queries, ports or schemes on the same hostname must also
be excluded as mutual alternatives. Different hosts remain unverified until
backend, provider/upstream, credential/quota and correlated failure dependencies
are reviewed. Shared CDN IPs alone do not establish a shared origin.

A known failed endpoint or failure domain must exclude its aliases across groups.
Availability, pinned address/version, contracts, authorization and circuit state
must be rechecked immediately before dispatch. With no qualified independent
alternative, stop rather than cycling through aliases. Independent providers
can still fail simultaneously; this policy does not guarantee availability.

The R-06 source now calls fallback_independence.require_distinct during policy
configuration and current-pair/dispatch rechecks. It rejects normalized endpoint
aliases, a shared hostname, declared shared publisher/remote/site evidence and
the reviewed shared Crossref dependency. Passing these negative checks is not
proof of an independent origin or a routing grant. Runtime transactions do not
perform DNS/CNAME discovery and never trust the offline audit as authority.

All 526 candidate groups were reviewed: 381 had no qualified pair and 145 still
had unverified origin/upstream independence. No operating fallback was enabled.
The real-TCP failover regression passes, but its two local test servers are not
public-provider independence evidence. Full findings and source-rollout limits:
reports/agent-fallback-validation-2026-10-24/README.md.
See `reports/agent-equivalence-review-2026-10-24/README.md` and its read-only
inventory and synthetic identity checks for the current scope and evidence.

## Generic transformations and activation readiness (2026-10-24)

Private administrator workflows accept local `input_transform` and `output_transform`
nodes. Registered tools with differing supported native schemas can use signed,
real-call-tested `io_profile` mappings; policy alternatives accept
`alternate_io_profile`. Profiles expire after 24 hours and bind the connection,
tool approval, mapping rules and implementation digest. Profile changes/revocation
are rechecked before business dispatch; restore revokes profiles. These mappings
do not expand R-06 to A2A, x402, writes, arbitrary code or unknown shared origins.

The private control GET APIs now include bounded activation readiness. Enabling
requires at least one current canary with successful bound shadow evidence and
current eligible pairs, with invocation/workflow controls enabled. Turning off
continues to work without healthy providers. No policy is automatically created
or enabled by a schema preview/profile test. The renewed console exposes this
under Service Settings (`T05`), including the generic I/O review dialog.

The operating empty profile table was added and the actual PostgreSQL 18 Store
schema attachment verified. Runtime source deployment and an independent real
provider pair remain separate requirements; no operating fallback was enabled.
