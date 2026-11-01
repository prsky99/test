# Private typed news-to-documentation connection

2026-10-18 · v1.13 connection profile, documentation updated for v1.14 retained-input inspection; source verification remains separate from deployed acceptance.

This release adds one reviewed data connection to the [bounded composer](WORKFLOW_COMPOSER.md). A private administrator can send the first validated news result title as the next documentation search query. It does not add arbitrary expressions, general field mappings, a public workflow profile or automatic paired testing. The existing independent-search profile remains the default.

## Selection, review and authority

The private workflow composer offers **Independent searches** and **News title to documentation search**. Generation accepts `flow=independent` or `flow=news-title-to-docs-v1`; an IntentSpec can also carry the same flow value. Conflicting or unsupported values are rejected. A connected request must explicitly request both `news.search.v1` and `docs.search.v1` through its prompt or IntentSpec. The server orders these as news first, documentation second, regardless of planner step order.

The connected graph is exactly the composer's manual trigger followed by `search-1` (news) and `search-2` (documentation). Its signed mapping is fixed:

- Source contract: `news.search.v1`, source node `search-1`.
- Source path after output normalization: `items[0].title`.
- Target contract: `docs.search.v1`, target node `search-2`, target field `query`.
- The documentation `language=en` and result `limit` remain the reviewed literal values. No other source field is forwarded.

The signed target binding uses audience `workflow-composer-connected-node-v1`. It binds the original literal input, source and target identities/contracts, full source pin and source binding hash (including the exact reviewed news input), the fixed path and target field, sharing authorization and notice. Admission rejects a different source binding even when it carries another valid compiler signature for the same provider pin. Generation signs `sharing_authorized=false`; a preview copied through a legacy workflow-save path therefore cannot execute as an authorized connection. The draft's displayed documentation input is the original reviewed objective, with a clear disclosure that only its query will be replaced at runtime.

Saving requires both existing private-save authorization (`authority=true`, `notice=workflow-composer-save-v1`) and separate title-sharing authorization (`flow_authority=true`, `flow_notice=workflow-composer-flow-v1`). Only this explicit save produces a target binding signed with `sharing_authorized=true`. These actions save a private draft and do not call an agent. Model-planner permission remains a distinct per-draft choice and does not authorize either sharing or execution.

The native centered review dialog has a separate, initially unchecked title-sharing checkbox. Candidate replacement preserves the reviewed objective and fixed period but resets sharing, save review and test state. Close, logout and session expiry clear private preview/consent state; consent is not stored in browser storage. The live-test checkbox separately authorizes the objective going to the news agent and the checked first title going to the selected documentation agent. The test uses the saved workflow and the existing idempotency key/polling behavior.

Execution accepts only a private `admin` source with a valid current highest-administrator principal. The runtime checks authority at admission and again at execution/dispatch, including existing role revocation, expiry and kill-switch boundaries. Possession of a saved sharing proof is not current execution authority. The source and target must still match their current approved, safe stateless MCP contract/schema/connection pins and required evidence. The target cannot introduce credentials or additional node-data fields through this profile.

## Same-run output proof and transformation

The documentation query is reconstructed from a retained, successful source checkpoint in the exact running workflow. An in-memory previous-output value or an arbitrary caller-supplied query cannot substitute for this proof.

Before forwarding, the resolver checks:

1. The current workflow snapshot hashes to the run's definition digest, the run source/principal has the required scope, and the signed target binding and sharing notice are intact.
2. Exactly one matching source node exists, its news contract/input/pin is valid, and the signed connection equals the server's fixed source-to-target mapping. The expected direct graph edge must be present without additional routing fields.
3. Exactly one bounded source checkpoint is present. Its HMAC, audience `workflow-checkpoint-v1`, run ID, workflow digest and source node ID must match this execution.
4. Its record is successful, identifies the expected source resource/node, preserves the reviewed source input, and has `record.data` equal to the retained full `flow_output`. The profile does not accept a projected or substituted subset as the source proof.
5. Recorded start/elapsed values have strict numeric, finite and range checks. Booleans, nonfinite values, negative latency, latency above 60,000 ms, a source start before run creation or an observation more than five seconds in the future fail closed. The existing news contract is revalidated at the signed observation time, including its requested period, freshness, source URLs, partial-date behavior and newest-first ordering.

An MCP result can wrap the validated object in `structuredContent`; otherwise the object itself is used. Normalization selects this one documented envelope and does not parse provider text or coerce another representation into JSON. The complete normalized news output must pass `news.search.v1` before selecting its first title. An empty result set cannot create a default documentation query.

Only the accepted title replaces the documentation `query`; the complete resulting argument object must pass `docs.search.v1`. Dispatch-time validation reconstructs and compares this input again inside the scoped run context, then rechecks the current target pin. This preserves the existing durable prepare/dispatch, fencing, authority and output-validation boundaries.

The documentation checkpoint records `typed_input` with the profile, source node ID and SHA-256 digest of the full signed source-checkpoint payload. This provenance reference is covered by the documentation checkpoint's HMAC. It connects the recorded downstream query to the retained source proof; it does not certify the source's factual claims. If required proof is absent, pruned or invalid, the runtime cannot infer a successful connection from a hash alone.

## Untrusted title and timing limits

A title must be a nonempty string of at most 500 characters, already free of surrounding whitespace. The validator rejects Unicode control/format characters, the redaction marker, address/contact/secret/private-path patterns and template/markup patterns through the existing public-objective safeguards. A title is never trimmed, truncated, stringified, serialized, translated or interpreted as an expression. There is no array fan-out, result concatenation, URL fetching, fallback query, second source selection or extra external attempt.

These are bounded safeguards, not complete privacy or prompt-injection detection. A schema-valid title can still be irrelevant, misleading or unsuitable as a documentation query. Public input review and the separate human-evaluation work remain necessary. The `language=en` request field does not prove that every provider title is English or accurate.

The connection adds no time or retry allowance. The composer's explicit test uses the standard signed run budget: 25 seconds total, with node work also bounded by the remaining deadline and existing outbound-operation limits. The preexisting separately authorized private extended profile remains 60 seconds total/15 seconds per node; this release does not select it automatically. Recovery retains the original run deadline. Source proof checks do not authorize repeating a dispatched or uncertain call, and a failed/blocked source cannot dispatch documentation.

## Unsupported combinations remain gated

Compiled drafts, including connected drafts, remain excluded from automatic fallback configuration. Selecting another candidate creates an explicitly reviewed and tested replacement draft; it does not authorize an extra provider attempt within the current run.

The existing [recorded comparison](WORKFLOW_COMPARISON.md) requires identical literal inputs and deliberately rejects any graph containing a connected node, including its news source. Connected documentation inputs depend on the proved source output, so treating the placeholder objective as the compared query would produce a misleading pair. The v1.14 [single-run retained-input inspector](WORKFLOW_RESOLVED_EVIDENCE.md) verifies actual input and source provenance without changing that exclusion. A future paired profile must additionally establish identical complete resolved inputs and compatible source context before admitting connected records.

## Retained-input inspection

In the private workflow menu, **Inspect connected test** reads one completed administrator run through the highest-admin-only `GET /admin/api/workflow-composer/resolved-input/runs` inventory and `POST /admin/api/workflow-composer/resolved-input` with exactly `{run_id}`. It checks the signed definition, sharing binding, stored authority, full successful news checkpoint, reconstructed title query, target actual input and exact `typed_input` source-checkpoint hash. A valid target must follow the signed source observation. Contracts are revalidated at recorded observation time; current eligibility is shown separately.

The inspector verifies a finite nonboolean principal expiry strictly after historical admission and after each successfully assessed node's start. This complements the runtime's execution/dispatch expiry guard without claiming an exact retained network-dispatch timestamp. It does not compare historical expiry with today's time or require the response to finish before expiry. Failed/blocked/cancelled nodes may legitimately begin after expiry and remain unscored; invalid successful proof is rejected. Missing/pruned source proof cannot be replaced with its hash, and unknown outcomes never become successful whole-run assessments.

The response shows the verified actual documentation query only when both input proofs are retained, safe source metadata and explicit per-node metrics/unavailability. It omits raw proofs, full URLs, excerpts, endpoints and credentials. The centered native dialog uses text nodes, memory-only state and stale-response/session guards. Inspection makes no provider/model calls, new run, quality evidence, grade, comparison pair or publication. No execution, delivery or marketing authority is inferred.

The first connected release supports private administrator tests only:

- Composer publication is rejected by the backend, and publication controls remain disabled even after a successful test. The UI describes the tested draft as private.
- Public template projection excludes connected definitions, including definitions manually marked as templates.
- Automatic schedule/event configuration is refused before creating schedule data. Public, scheduled, event, deployed-webapp and verification execution sources are also rejected at runtime admission. A saved sharing choice cannot become authorization for these other purposes.
- No connected public download, deployed execution or SDK input-sharing profile is enabled. Existing public SDK 1.0 and admin SDK 1.1 implementation sources remain unchanged; SDK 1.2 needs its own versioned authority, disclosure, expiry and revocation design.

The original v1.13 typed connection left the seven protected public frontend/ZIP/SDK implementation sources unchanged; the separate v1.14 inspector also changes none of those implementation sources. Public Chat, metadata, footer, browsing, independent templates and existing download behavior are outside these private profiles. No new database table is introduced; the execution/storage rehearsal inventory remains 27 tables. The existing PostgreSQL rehearsal remains a bounded state-table exercise, not a production Store/FTS/auth/collector dialect adapter.

## Evaluation cases and verification boundary

[The versioned evaluation artifact](workflow-evaluation-cases.json) contains 30 curated machine cases: public technical concepts, exact one-/500-/501-character boundaries, empty/control/address/secret/template/markup inputs and JSON type mismatches. Ten titles are accepted and twenty rejected by the recorded expectations. These deterministic cases make no external requests and never create live capability evidence.

The artifact also defines six unscored human-review rubrics: task relevance, source fidelity, temporal fit, missing-data honesty, typed-query usefulness and data-sharing safety. Every human assessment is unset, `human_expert_reviewed=false`, `provider_quality_certified=false`, and review status is `pending-human-review`. Independent qualified reviewers, retained task/source evidence, disagreement records and adjudication are still required. This corpus supplies neither expert quality certification nor provider ranking, factual-accuracy scores or a winning agent.

Composer fixture checks validate synthetic contract envelopes with zero provider calls and `live_verified=false`. They do not execute this connection or prove a live provider works. Separate runtime/API/Chromium tests exercise actual code paths through isolated MCP transports and test databases, including signed source proof, forwarding, malformed output, tamper, consent, role/scope, recovery and UI publication refusal. Transport requests in those tests are real calls to isolated fixtures, not production-provider observations. See [the v1.13 verification report](../reports/advancement-r07-typed-flow-2026-10-18/README.md) and [v1.14 inspector report](../reports/advancement-r07-resolved-evidence-2026-10-18/README.md) for completed results and precise security-check scopes.

New Python behavior requires the user's server restart. Read-only local HTTP/CSP and anonymous refusal checks can confirm basic deployment observations; they cannot establish authenticated privileged functionality. Authenticated live acceptance, approved real-provider/model cohorts, full R-07/AC-08, G0/G1, hosted CI and capacity/availability acceptance remain open. Development verification does not operate the user's server, activate production policies, publish templates, send notifications or write directly to the live database.

## Recommended continuation

1. Complete user-managed restart and authenticated private acceptance of the new connection; keep live-provider/model evaluation separate from anonymous HTTP/CSP checks.
2. Obtain independent expert reviews, source evidence and adjudication for the six rubric dimensions, then build representative held-out tasks and measured approved-provider cohorts. Machine fixtures alone cannot establish quality.
3. Use the implemented single-run retained-input inspector as evidence preparation, then design a strict resolved-input/source-context paired comparison and separate publication profile before admitting connected pairs or public input-sharing. Define any additional narrow mappings against reviewed source/target meaning and immutable proof boundaries.
4. Design explicit paired-run orchestration with per-call authorization, budgets, idempotency and unknown-outcome handling; comparison itself remains read-only.
5. Specify opt-in SDK 1.2/deployment sharing authority and separate schedule/event purposes before enabling connected public or automatic execution.
6. Continue reviewed product/cascade contracts and measured storage/operations acceptance without expanding existing execution or payment authority implicitly.


## v1.15 review preparation

The connected profile can now supply an [identity-minimized, metadata-only human review worksheet](WORKFLOW_REVIEW_PACKETS.md) after retained proof verification. This does not authorize another call, publication, a comparison pair or expert quality claims. [Offline candidate-manifest validation](WORKFLOW_HOLDOUT_REVIEW.md) checks structural task separation independently; historical runs are not retroactively held-out outcomes.

## Separate controlled-pair profile

The [private controlled-pair profile](WORKFLOW_CONTROLLED_PAIRS.md) adds a separate four-node purpose: one news source followed by two distinct documentation targets using the same signed source checkpoint and exact resolved arguments. It requires its own reviewed plan and separate sharing and live-run authorizations. This does not change the original three-node connection, admit connected runs to the literal comparator or authorize another call through the read-only inspector. Missing or uncertain evidence remains unscored, and publication remains blocked.
