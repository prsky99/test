# P2-01 bounded retained evidence rollup

This source slice reads existing evidence and recomputes a bounded administrative
summary. It creates no provider call, evaluator result, public badge, customer
portal, recommendation preference or execution permission. It does not complete
the full P2-01 cohort/evaluator/source-review design.

## Scope and provenance

The private administrative routes are under
`/admin/api/workflow-workspaces/{workspace_id}/evidence`:

- `GET /options`: current scopes and withdrawal permission.
- `GET /rollup?resource_id=...&scope=workspace|catalog`: retained summary.
- `POST /withdrawals`: permanent withdrawal in the exact workspace/scope.

Every read requires a current individual staff session and active membership in
the exact workspace. Catalog metadata additionally requires a current global
superadmin. Customer cookies, machine tokens, global staff status without a
membership and another workspace's run reference are not authority. No public
route is registered.

Workspace observations come from retained signed private run/ticket metadata.
Signatures, scope, snapshot retention/revocation and the current resource pin
(including its generation) are checked without decrypting or returning outputs.
Unsent work is excluded from the observed execution denominator. Ticket
revocation, archived snapshots or changed bindings neutralize the source.

Catalog observations must match the current exact connection version/profile.
Execution/transport evidence requires a retained attributable shared-operation
source. Unattributed legacy records are excluded. Explicit shared contract-test
records require the exact retained approval and observation after that approval.
Legacy catalog records do not authenticate an observation-generation epoch or
prove source fidelity: this summary is retained metadata history, not proof of
current callability. A coherent privileged database rewrite is outside this
unsigned legacy source's authenticity guarantees.

## Aggregation and bounds

The policy is `retained-metadata-v1`: at most 200 retained source records from the
selected bounded scan, a 24-hour window capped by each source's actual expiry,
and a 20-logical-observation metadata threshold. A truncated scan is disclosed.
At most 50 original opaque source references are displayed. Data is grouped
separately by evidence scope, contract, dataset and validator version. No scores
are combined across datasets or domains.

Attempt references resolving to one logical operation count once. Conflicting
outcomes conservatively preserve unknown before failure before success. Private
run IDs and retained shared contract report digests provide bounded deduplication
where applicable; unattributed execution records are not invented as samples.
The record's `cases` count is not multiplied into the logical denominator.
Actual observation time, not arrival order, governs the window. Future-clock
observations remain excluded until their observation time; expired records are
excluded. p50/p95 describe the recorded observation interval, not inferred
provider latency or a qualified operating SLA.

Small samples are `insufficient_evidence`. Meeting the count threshold never
establishes semantic correctness, independent review, source fidelity, holdout
quality or an operating cohort: `quality_status` stays `unassessed`, source
fidelity remains unassessable from metadata and qualified operating evidence
stays false. Missing/deleted originals cannot be replaced by retained hashes.

## Withdrawals, retention and cache behavior

Only a current workspace owner may withdraw a source in this workspace scope;
catalog withdrawal also requires superadmin. The exact source must belong to
the authorized scope/resource. A signed permanent tombstone and audit record
are retained, bounded to 500 per workspace. An exact replay is deduplicated;
conflicting content is rejected. Original evidence and unknown run outcomes are
never rewritten or replayed. This scope-local display withdrawal does not revoke
the global Registry approval or delete source payloads; those have independent
authority and retention mechanisms. Restore must preserve withdrawal tombstones.

Rollups are computed on every request, including conditional requests. There is
no positive summary cache. An opaque ETag binds the exact current workspace,
session/member authority, version/generation, source set, controls, withdrawals
and expiry classification. A matching strong validator yields 304 only after
those checks. Weak/wildcard validators do not preserve an old body. Responses
and failures are `no-store`; stale-while-revalidate/stale-if-error are absent.
An expired, deleted, withdrawn, changed-version or unauthorized source cannot
keep a former positive representation alive through 304.

The desktop dialog uses local Lucide SVG paths, text nodes, a centered native
dialog, explicit unchecked withdrawal confirmation and session/workspace/request
epochs. No raw inputs, outputs, upstream URLs, session references, signatures,
credentials or visitor profiles are returned. Ambiguous mutations require a
fresh current read; there is no automatic retry or provider request.

## Remaining operating gates

This slice is isolated source/API/desktop verification. Real cohort qualification,
reviewer independence, consented operating evaluation, full source fidelity,
provider acceptance, public trust pages and public activation remain separate.
Public Workspace access remains closed.
