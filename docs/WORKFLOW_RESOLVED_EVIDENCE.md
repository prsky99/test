# Retained typed-input evidence inspection

2026-10-18 · v1.14 · bounded R-07 continuation after the public gateway follow-up.

The private workflow menu adds **Inspect connected test** for one completed administrator test of [the `news-title-to-docs-v1` connection](WORKFLOW_TYPED_FLOW.md). It shows the documentation query actually recorded with its source-checkpoint provenance, successful node contract metrics and safe source metadata. The original **Compare completed tests** remains a separate literal-input evaluator and continues to exclude every connected graph, including its upstream news node.

This is an evidence inspection prerequisite for a future controlled comparison profile. It does not establish that two runs are comparable, start either run, call an agent/model, fetch sources, create capability evidence, change ranking, approve a candidate, save a graph or publish a template. Source fidelity, factual accuracy and task relevance still require human review; no expert scores or automatic winner are assigned.

## Private read-only profile

Both APIs require current highest-administrator authorization. Successful responses and endpoint validation errors use `Cache-Control: no-store`; the common administrator request guard separately rejects malformed/oversized bodies and unauthorized requests before the endpoint. No public route exists.

- `GET /admin/api/workflow-composer/resolved-input/runs` considers at most 100 recent terminal `admin` runs through the existing recent-run index and returns at most 30 supported typed definitions with retained verifiable execution authority. Entries contain bounded run/workflow references, status, observation time and fixed opaque labels. This is a recent inventory, not full historical search. Missing or invalid execution authority excludes the entry; a missing checkpoint is reported by inspection rather than implied successful.
- `POST /admin/api/workflow-composer/resolved-input` accepts exactly `{run_id}` with one `wr_` reference. It cannot accept a URL, tool, input replacement, comparison partner, execution flag or new authorization. It uses POST to keep the run identifier out of query-string logs while remaining read-only.

The evaluator version is `resolved-input-evidence-v1`. A deterministic `rse_` inspection reference binds this version, the run reference and available signed source/target checkpoint hashes. `cp_` is an opaque shortened source-evidence reference; raw signatures, snapshots, connection/approval pins and authority envelopes are never returned. Current eligibility is deliberately not part of the historical reference and may change independently.

File-backed inspection uses one consistent SQLite `mode=ro` transaction. In-memory test stores use a savepoint under the existing lock and roll it back/release it without changes. All identifiers are bound SQL values. The reader uses bounded snapshot (180,000 characters), authority (16,384 characters) and checkpoint (262,144 characters) reads with an extra sentinel character to detect oversized records, including trailing whitespace after otherwise valid JSON. There is no new table, worker, schema/key initialization, queue recovery, delivery operation or database write. The state-table rehearsal inventory remains 27 tables.

## Definition and authority proof

The loader verifies the retained snapshot digest and workflow identity against the signed stored run authority. It accepts only the original manual three-node compiler shape: `start` → `search-1` (news) → `search-2` (documentation), with the exact two ordinary edges and no fallback policy. Both search nodes must retain their signed stateless MCP bindings, exact tool, resource and literal input, with no extra node-data fields or output projection.

The news binding must use `workflow-composer-node-v1`; the target must use `workflow-composer-connected-node-v1`. The target must preserve the separately authorized sharing flag and `workflow-composer-flow-v1` notice. Its fixed mapping must equal the compiler's mapping reconstructed from the retained source, including the complete source pin and source binding hash. Replacing the reviewed news input or a path/target with another valid-looking node does not preserve this proof.

The stored run-authority HMAC must bind the exact run, workflow, definition digest and `admin` source. Its nested principal signature must record the `workflow-runtime-v1` audience, matching workflow, administrator kind and highest-administrator role. Principal expiry must be finite numeric data (never a boolean), strictly later than recorded run admission. Each successfully assessed node must have started while that authority was valid. This verifies the historical recorded node-start boundary; the runtime separately enforces current authority again at actual dispatch. The inspector does not claim an exact retained network-dispatch timestamp. Provider responses may complete after expiry; this read-only historical check does not extend execution authority or require expiry to follow the response. Failed, blocked or cancelled nodes may legitimately record a later start after authority has expired and remain unscored. Later present-day principal expiry, role withdrawal, approval changes or evidence age do not erase a valid historical record. Current request authorization is enforced independently by the API guard. Viewing history grants no present execution or sharing authority.

## Source, resolved query and target proof

Each available checkpoint must verify its HMAC, audience, exact run/definition/node scope, resource, MCP/agent identity and known record status. Strict finite numeric start/latency checks reject booleans, negative values, latency over 60,000 ms, a start before run creation and an observation more than five seconds in the future. A successful record must retain its complete `record.data` as `flow_output`; a projected or substituted subset cannot become source proof. Cancelled-after-output records may retain a flow value while the runtime suppresses the record output; they remain unscored and do not need a successful-output equality assertion.

A successful news checkpoint must preserve its exact reviewed news input. The full normalized news result must satisfy `news.search.v1` at its signed start-plus-latency observation time, including freshness, requested period, source URL safety, partial-date behavior and ordering. Present wall-clock age does not invalidate a formerly valid recorded result.

The inspector reconstructs only `items[0].title` through the same no-coercion/no-truncation title validator used at execution. The target's reviewed language and limit are preserved and the resulting complete argument object must satisfy `docs.search.v1`. Empty, unsafe or over-limit titles legitimately prevent a downstream call; inspection invents neither a replacement title nor a default query.

When the target records an input/provenance or success, its `typed_input` must exactly match the profile, source node and SHA-256 hash of this retained source checkpoint. Its recorded input must exactly equal the reconstructed complete argument object. Its start must follow the signed source observation. A successful target's complete output is then checked with `docs.search.v1` at its own recorded observation time. The returned query is therefore the verified recorded target input, not its original placeholder objective or an in-memory earlier value.

The response separates workflow status/external certainty, node assessments, provenance status and current connection eligibility. Current definition/approval matching and current readiness are read from the same database snapshot; their failure does not rewrite valid historical metrics. A source can have valid recorded contract metrics while its downstream attempt failed or has an unknown external outcome. The top-level assessment and target metrics remain explicit so this cannot be mistaken for a successful whole run.

Missing/pruned source proof leaves the target unscored even if a target checkpoint and source hash remain. Missing target proof, failed/blocked/cancelled nodes, absent outcome certainty and `unknown` do not receive successful target metrics or a fabricated query. A valid news result with an unusable title can retain news contract metrics while showing an unavailable connection. Mismatched signatures, actual inputs, connection scopes or available source-hash provenance are rejected with a bounded error rather than silently scored. The inspection never retries an uncertain execution.

## Returned data and UI

The private response contains fixed agent labels; the verified title query/language/limit when both source and target input proof are retained; contract assessments; node latency, result count, distinct-source count, partial status and date metrics; source titles/hosts/timestamps/document versions; and opaque proof references. It omits full source URLs, summaries/excerpts, raw response bodies, endpoints, credentials, private pins and proofs. Provider metadata text additionally masks known token/credential patterns, inline URL/contact strings and detected private runtime paths. This bounded minimization is not a universal personal-data detector.

The centered native dialog renders every provider value through text nodes. It has no untrusted links, images, HTML insertion or remote resource fetching. Its state is memory-only. Selection changes, refresh, close/Escape, logout and authentication expiry clear or invalidate the result; epoch and session guards suppress late responses. The existing ten-second workflow-list refresh preserves an open inspection and the unsaved builder graph. Viewing an inspection cannot authorize testing, comparison pairing, publication, notification delivery or marketing.

Public Chat, footer/metadata, testbench, independent workflows, downloads and SDK 1.0/1.1 implementations are unchanged by this inspector. Connected publication, public/deployment execution and schedule/event execution remain gated as before.

## Verification and continuation

Isolated unit/API/Chromium tests cover proof signatures and scopes, actual-input/provenance mismatch, full-output preservation, dependency time ordering, payload read limits, historical admission/node-start expiry, current-versus-historical readiness, role guards, failed/unknown/cancelled/retained-missing outcomes, metadata minimization, text-only rendering, refresh/stale response/session behavior and zero execution/evidence writes. See [the verification report](../reports/advancement-r07-resolved-evidence-2026-10-18/README.md) for the final scoped 65-test result, five independent expiry review cases and the earlier 115-test affected regression, without summing overlapping runs. Test fixtures and source-schema checks are not real-provider quality observations or expert certification.

New Python API behavior requires the user's server restart. Read-only HTTP/CSP/anonymous refusal observations cannot replace authenticated live acceptance. The development work does not operate the user's server or use live administrator credentials, provider/model cohorts, production policies, publication or notification delivery.

Next, obtain independent expert judgments and held-out task evidence; specify a strict paired profile using identical complete resolved inputs and matching source input/pin/output context before admitting connected pairs. A separate active paired-run design must explicitly bind each provider call, budget, idempotency and unknown-outcome handling. SDK 1.2, deployment/public sharing and schedule/event purposes require separate versioned authorization designs; this inspection does not enable them.


## v1.15 worksheet preparation

The internal `inspect_store` method allows the new [review worksheet](WORKFLOW_REVIEW_PACKETS.md) to obtain verified proof and original reviewed context in the same read transaction. The existing inspector response and expiry/provenance rules remain intact. Worksheet download excludes internal identities, current grades/readiness/latency and full source content; its six human criteria remain blank. It neither forms a pair nor establishes expert or holdout results.

## Separate controlled-pair inspection

The [private controlled-pair profile](WORKFLOW_CONTROLLED_PAIRS.md) has its own four-node definition, explicit execution purpose and read-only historical inspector. It checks two distinct documentation targets against one retained signed news source and identical complete resolved inputs, including attempt certainty and target order. This single-run inspector continues to accept its original three-node connected profile only; its API does not create a pair or authorize additional calls. Neither inspector fabricates scores from missing or uncertain evidence, and publication remains blocked.
