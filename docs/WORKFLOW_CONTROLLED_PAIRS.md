# Private controlled news-to-documentation tests

2026-10-18 · bounded R-07 implementation · not expert or holdout evaluation.

One explicitly authorized private test retrieves news once, validates the first result title, and uses that exact title and identical fixed settings for two distinct documentation agents. Both targets refer to the same signed source checkpoint in the same durable run. The first target runs before the second. This creates a controlled common-input observation; it does not establish factual accuracy, representative quality, a fair randomized experiment, an automatic winner or a protected holdout.

This profile is separate from the existing [literal-input comparison](WORKFLOW_COMPARISON.md), [single connected-test inspector](WORKFLOW_RESOLVED_EVIDENCE.md), metadata review worksheet and [offline governance plan](WORKFLOW_EVALUATION_GOVERNANCE.md). Those contracts retain their original meaning. Real reviewer qualifications, source review, access controls and independently chronological pre-execution allocations remain operating prerequisites for expert benchmark claims.

## Prepare, authorize, execute and inspect

The highest administrator opens **Run controlled pair** in Workflows. Approved candidates come from the current informational catalog. The administrator enters a public English news objective and selects one news source plus two distinct documentation agents. No model is used.

Preparation returns a short-lived, owner-bound signed plan. It freezes the selected current versions, schemas, approvals, exact source query/time window, target input templates, ordered graph, profile and notices. The preview identifies both targets, fixed English settings, result limit, source time window and call/deadline bounds. A proposal is not execution permission, and preparing it does not call an agent, reserve a private workflow or admit a run. Candidate checks use the existing registry and can refresh internal connection-version metadata; this preparation boundary is not a promise of zero catalog writes.

Two initially unchecked authorizations are required: share the checked first news title and fixed settings with both selected targets, and perform one live controlled pair. Changing the objective or any selection invalidates the plan and both authorizations. The backend repeats all checks; a browser checkbox alone cannot authorize a call.

Execution is one atomic-purpose request, not two independent browser Run requests. A single durable run owns the source and both target attempts. The normal current administrator principal gains a pair-purpose field covered by its server signature and bound to the owner and exact shared definition. That purpose is retained in the existing run-authority record and checked during execution and dispatch. Ordinary Run, public, schedule, event, verification and deployment requests do not acquire it.

The signed pair descriptor retains the original plan review time; the purpose binds that descriptor through its pair hash. Admission, dispatch and recovery reject a plan older than the last execution-control change. Pausing and resuming controls, including after restore quarantine, therefore cannot revive a previously reviewed plan. This operational revocation boundary is not an independent timestamp or a holdout-allocation record. Historical inspection evaluates the original admission and call times without invalidating valid old results merely because controls changed later.

The browser clears the plan and authorizations after submitting execution. It inspects status using read requests and never automatically repeats Execute after connection loss. Closing the dialog clears local state; it does not claim that an already accepted server call was cancelled. Recorded tests can be inspected later without creating another run.

## Same source context and bounded calls

The graph contains exactly a manual trigger, a pinned news source and two pinned documentation targets. Its real edges carry source data from news to each target; there is no invented edge claiming that Test A's answer was sent to Test B. Execution order is fixed and disclosed, so observations include order and changing-provider-state effects.

Only the first news result title, if valid, is placed into the documentation `query`; the rest of the complete argument object is identical for both targets. Empty, unsafe, masked, overlong, malformed or unverifiable titles stop downstream calls. There is no truncation, substituted query, URL lookup, expression, fan-out beyond these two reviewed targets, credential binding or model-generated input.

Each successful source checkpoint is authenticated against the run, definition, node, reviewed source input, complete retained output and observation time. This is the stored privacy-projected checkpoint, not a raw transport transcript or a guarantee that every source claim is true. Each target records the exact resolved input and the same source-checkpoint hash, plus its pair purpose and side. Source output is not re-fetched between targets. Per-target calls still recheck current agent bindings, tool/schema approval, eligibility, run authority, cancellation, controls, ownership/fence and remaining budget.

There are at most three tool invocation dispatches: one news call and one call per documentation target. Transport setup and schema checks are not additional task invocations. The existing standard 25-second absolute workflow deadline and per-node limit apply. There is no automatic deadline extension or extended-budget selection for this first profile. Insufficient time remains a failed or unavailable observation rather than an invented successful comparison.

Test B requires Test A's authenticated successful checkpoint and durable successful attempt certainty, checked before B preparation and again before dispatch. A failure, cancellation, unknown outcome, missing proof, changed source context or revoked authority blocks B. The profile has no fallback and does not turn the second target into a retry of an uncertain first request. This conservative boundary means that some tests cannot produce two completed results.

## Durable admission and recovery

The signed plan nonce reserves one private saved definition using a serialized database transaction. Its owner-bound stable idempotency key admits at most one durable run. Repeating the same accepted request while its plan, current authority and eligibility remain valid returns the original run rather than launching a second source or target test; otherwise it is refused without new calls. A crash between reservation and admission reuses the reservation. Unexpected conflicting or modified definitions fail closed. At most 20 new owner-specific reservations per hour are accepted; a refused admission may leave a private reservation for manual inspection.

The existing queue, lease/fence, per-attempt `prepared`/`dispatched` boundary, signed checkpoints and original deadline remain authoritative. Recovery reuses completed signed checkpoints. Work interrupted before dispatch can resume within the original authority/deadline; a dispatched request whose outcome is unknown is not replayed. A whole-run failure or unknown outcome is never erased merely because one target produced a valid result.

No new state table is introduced. Existing workflow definitions, versions, runs, authority, attempts, checkpoints and events retain the evidence. This does not establish exactly-once effects at an external provider. Failed or interrupted reservations and unknown evidence remain subject to the existing conservative operating/retention procedures.

Live, explicitly authorized provider calls use the existing managed invocation and contract-evidence recording pipeline. Structural contract success can update actual execution eligibility; it is not a new expert grade, factual score, benchmark certification or automatic recommendation winner. Isolated test fixtures create no production evidence.

## Read-only historical inspection

Inspection authenticates the retained four-node definition, pair bindings and owner/purpose authority; each checkpoint and attempt; the source contract and observation; both resolved input objects; and their same-source provenance. Historical authority is checked at admission and successful call starts. Current eligibility/version/approval is a separate observation and cannot silently rewrite valid history.

The inspector uses one consistent read-only snapshot. It does not initialize versions, refresh catalog records, recover queues, invoke agents/models, change evidence, rank a winner or write a score. Pruned, failed, unknown, cancelled and unfinished evidence remains explicit and unscored. Invalid signed scope or inconsistent retained proof is refused rather than displayed as a valid pair.

The interface shows the actual common query only when it can be verified, source partial/publication/retrieval metadata, fixed Test A/Test B roles, recorded outcomes and available contract metrics. Recorded latency includes runtime/gateway work and is not provider CPU time or a quality grade. Provider text is rendered as text, with no raw response, source-URL fetch, clickable untrusted address, signature, secret or private authority envelope.

## Publication is a separate contract

Successful pair execution is private evaluation permission only. It does not publish either target, the graph, a source title, a comparison report or a quality claim. Publication readiness is a read-only view of missing gates; it collects no unused consent and changes no grant or public flag.

Public publication remains blocked by the composer, public projection, public runtime, export/deployment and automatic-execution boundaries. A future publication profile needs independently versioned authority/revocation, exact tested definition and source-sharing scope, safe public projection, explicit public-run input sharing, SDK/deployment/automation purposes and actual required review evidence. An administrator's pair checkbox or an HMAC proposal cannot replace those permissions.

Readiness returns `ready=false` with four fixed missing gates: `PUBLIC_TITLE_SHARING_PROFILE_REQUIRED`, `PUBLIC_PER_RUN_AUTHORIZATION_REQUIRED`, `SDK_DEPLOYMENT_AUTHORITY_PROFILE_REQUIRED` and `SEPARATE_PUBLICATION_CONSENT_REQUIRED`. No unused publication checkbox or consent receipt is collected.

## Private API

All six routes under `/admin/api/workflow-composer/controlled-pair` require the current highest-administrator session and existing dashboard/origin/CSRF protections. Responses use `no-store`; errors do not echo submitted objectives, proofs or private diagnostics.

- `GET /options`: current bounded approved candidates.
- `POST /prepare`: exact objective and source/target selections; signed 15-minute owner-bound plan.
- `POST /execute`: signed plan plus fresh explicit `workflow-controlled-pair-share-v1` and `workflow-controlled-pair-run-v1` authorization notices; accepted runs return 202.
- `GET /runs`: bounded retained controlled-pair inventory.
- `POST /inspect`: one retained run inspected without invocation or evidence writes.
- `POST /publication-readiness`: read-only explanation of the missing public-use permissions.

The four-node profile is `news-title-docs-pair-v1`. It is independent of the original literal comparison and three-node connected-test routes; those routes do not provide a shortcut to its execution purpose.

## Browser and deployment boundaries

The native centered dialog is independent of the unsaved workflow builder and normal page refresh. It keeps plans, selections, authorizations, run references and results in memory only. Session/role changes, close/Escape, changed selections and stale responses cannot restore an old plan. Provider content uses text nodes. New actions require the exact running-backend capability marker; an older server leaves them disabled instead of sending a new execution request to a missing route.

Public frontend copy, metadata, Chat, footer consents and existing SDK/download package sources are unchanged. The user continues to operate the development server. New Python behavior requires the user's restart followed by authenticated acceptance; opening the disk-served administrator HTML alone does not prove the new backend is loaded. Development and security verification use isolated databases, providers, browser routes and temporary ports.

The [v1.17 verification report](../reports/advancement-r07-controlled-pairs-2026-10-18/README.md) records final test reconciliation, the reproduced and corrected control-change race, process-termination recovery boundaries, static scope and remaining operating limits.

The later [single-target public connection](WORKFLOW_PUBLIC_CONNECTIONS.md) is a
separate canonical audience, explicit test and publication/run authority. It does
not publish this four-node private pair or satisfy these pair-specific readiness
gates, and no pair approval is inherited by its public routes.
