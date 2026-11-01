# Private review preparation worksheets

2026-10-18 · v1.15 · bounded R-07 review preparation; source verification remains separate from deployed and expert acceptance.

The private [connected-test inspector](WORKFLOW_RESOLVED_EVIDENCE.md) adds preparation of one **identity-minimized single-run review worksheet**. It provides reviewed task context, the verified actual documentation query when retained, bounded result-title/date/partial metadata and six blank human-review dimensions. Administrators preview the worksheet, then separately acknowledge review before downloading a local JSON file. Preparation neither sends the file to a reviewer nor authorizes external sharing.

This is preparation for an actual human process. It establishes no expert judgment, grade, provider-quality certification, winner, holdout cohort or controlled comparison pair. The [literal-input comparator](WORKFLOW_COMPARISON.md) continues to exclude connected graphs. Connected publication, deployment/public sharing and schedule/event execution remain gated as before.

## Read-only API and review flow

`POST /admin/api/workflow-composer/review-packet` requires current highest-administrator authorization and accepts exactly `{run_id}` with a retained `wr_` reference. Callers cannot supply a reviewer, rubric, source URL, title, excerpt option, score or execution choice. Successful responses and endpoint validation errors use `Cache-Control: no-store`; the common administrator request guard handles malformed bodies and authentication before the endpoint.

`ReviewPackets.prepare()` returns an envelope containing `ok`, the complete `packet`, a controlled `download_filename` and `download_media_type=application/json`. Only the `packet` object belongs in the downloaded worksheet. The download filename contains its opaque case reference; it contains no run, workflow, resource, provider or reviewer identity. No server file, export record or identity mapping is persisted.

The administrator first opens a completed connected test, explicitly prepares its worksheet and reviews its metadata-only preview. A separate unchecked acknowledgement enables local JSON download. Changing the selection, refreshing/preparing again, closing/Escape, logging out or expiring authentication invalidates the worksheet and acknowledgement. Stale/session-mismatched responses cannot repopulate the preview. The existing builder state and workflow-list refresh remain independent. Neither preview nor download submits a workflow run or provider/model request.

## Retained-proof boundary

Preparation reuses the inspector's complete signed-definition, historical-authority, source-output, actual-input and source-checkpoint-provenance checks. The inspector's internal `inspect_store()` accepts an existing read snapshot; its normal `inspect()` wrapper retains the original validation and read-only behavior. Packet preparation obtains both the verified public projection and original signed news-query context inside one consistent SQLite read transaction. It never joins a verified projection from one snapshot with a subsequently changed source binding.

The retained workflow must match the private manual three-node `news-title-to-docs-v1` profile. Both signed source/target bindings, the separate sharing authorization, stored run authority and nested highest-admin principal scope remain required. The principal's numeric finite nonboolean expiry must follow historical admission and each successfully assessed node's recorded start. Later present-day expiry or approval drift does not erase valid history; the runtime separately enforces actual execution/dispatch authorization. This worksheet does not extend authority or require a response to complete before expiry.

A successful complete source checkpoint must match its exact reviewed input/resource/run/node and full `flow_output`. Its news contract is revalidated at the signed observation time. The first title is reconstructed with the existing safe-title validator; the target's actual arguments and `typed_input` hash must match that same source proof. Successful target output is likewise validated at its signed observation time. Preparing the worksheet does not fetch or repeat an external request.

The original news query is checked again against the bounded public-title/objective export policy. Both that objective and any verified actual query must remain exactly unchanged under the metadata privacy-minimization policy; otherwise the export is refused. This purpose-specific check does not depend on a historical producer having already masked known secret patterns, and it never substitutes masked text while claiming to show exact input. The packet distinguishes `reviewed_objective` from `actual_documentation_query`; they must not be silently substituted for one another. An actual query is included only when both input proofs are retained and verified. Failed/unknown target calls can have a proved actual input without a successful result; workflow/external/provenance states remain separate.

Missing/pruned source or target evidence produces an unavailable actual query or unscored result, never a guessed value. Unknown, unsuccessful and absent-certainty results remain explicit. A valid source node in an otherwise unsuccessful run can retain its own metadata while downstream metrics stay unavailable. Available but invalid signatures/scopes, source-output substitutions, mismatched actual arguments, source hashes, dependency times or historical authority cause a bounded refusal. No output value or hash alone replaces missing proof.

## Fixed packet profile

The initial version is `workflow-review-preparation-v1`, schema version 1. Its packet contains:

- `review`: `status=unreviewed`, unset reviewer, no recorded judgments, `human_expert_reviewed=false`, `provider_quality_certified=false`, `holdout_status=not_established`, and factual accuracy/source fidelity marked `not_assessable_from_metadata`.
- `context`: the checked original objective, requested news-window start, language/result limit, verified actual documentation query or `null`, and explicit actual-query availability.
- `execution`: workflow status, external outcome or `not_recorded`, and input-provenance status. These are recorded execution facts, not quality scores.
- `results`: fixed `Source`/`Target` labels, contract assessment/reason, partial/result-count availability and items named `Source result 1` or `Target result 1`. Items contain only minimized title text, a truncation flag, publication time when present and retrieval time. Display titles are capped at 240 characters; truncation is explicit.
- `rubric`: the fixed version/hash and six dimensions with `judgment=null`, empty notes and unset reviewer. Source fidelity explicitly requires separately reviewed source material; other dimensions remain metadata/context-only prompts.
- `limitations` and zero-side-effect facts: no provider/model calls, new runs, evidence writes or publication.

The packet omits run/workflow/resource IDs, registered agent names/references, source hosts, full URLs, summaries/excerpts, document versions, raw response/proof bodies, authority, pins, checkpoint hashes, current eligibility, latency and existing quality grades. The fixed rubric dimension IDs and opaque case reference are worksheet identifiers, not provider identities.

Known credential patterns, inline URL/contact text and detected private paths are minimized using the existing inspector text policy. This is not a complete personal-data detector. Task and result titles may identify a topic or origin even after internal identities are removed. The worksheet therefore claims **identity minimization**, not guaranteed anonymity, double blinding or a statistically controlled blind benchmark. Administrative preview is still required before local download, and external distribution remains a separate decision.

## Rubric and case-reference integrity

The six questions come from the fixed rubric rows in [the existing evaluation artifact](workflow-evaluation-cases.json): task relevance, source fidelity, temporal fit, missing-data honesty, typed-query usefulness and data-sharing safety. The 30 machine-validation examples are not exported or reclassified as human-reviewed/holdout cases.

The rubric version is `workflow-review-rubric-v1`; its SHA-256 is `8feda26ea73dce348bd3b101cb6147e0e59e62f4a68907fc4cac6d0364c8b8dd`. Preparation reads at most 65,536 bytes from the fixed local artifact, validates its unreviewed status, exact six-row order and field shape, bounded strings and this hash. Missing, malformed, oversized or silently modified rubric data fails closed. Rubric changes require an explicit version/hash update; no caller-selected file or question set is accepted.

The opaque `rwp_` case reference uses a dedicated server-keyed HMAC domain binding the packet profile, retained inspection reference, rubric hash and identity-minimized packet content. The raw retained reference and HMAC proof are not exported. Re-preparing unchanged evidence produces the same case within this profile; changed retained content or a different signing key produces another case. Profile/domain separation avoids exposing a reusable raw run/checkpoint identifier across other surfaces. This case reference is not an offline-verifiable signature or an imported judgment, and no reverse mapping is stored.

## Why excerpts and factual scores are absent

`news.search.v1` and `docs.search.v1` permit arbitrary provider summary/excerpt strings up to 2,000 characters. Valid structure, a public-source URL and known-pattern masking do not establish that all text is appropriate for further sharing. Redaction can also alter the claims that a reviewer would otherwise assess. This initial worksheet therefore omits those fields instead of presenting a sanitized fragment as original evidence.

Factual accuracy and source fidelity cannot be assessed from the supplied metadata. Qualified independent reviewers need separately reviewed source material, their actual judgments, disagreement records and adjudication before any benchmark conclusion. This version accepts no completed-review import, writes no scores and updates neither recommendation ranking nor capability evidence. A later excerpt/source-sharing profile requires an explicit purpose, bounded reviewed fields, provenance/redaction disclosures and separate release approval.

Holdout status is also not established by downloading a worksheet after execution. A real protected test split requires an independently governed pre-run reservation/versioning and leakage policy. The separate offline manifest work can validate candidate overlap/format, but it does not retroactively turn these cases into a held-out cohort or expert evaluation. The [offline evaluation governance plan](WORKFLOW_EVALUATION_GOVERNANCE.md) adds structural checks for proposed roles, source-handling and per-family allocations; it still verifies no real person, source review, access enforcement or chronological reservation.

## Verification and remaining acceptance

Isolated tests exercise exact packet shape, original-versus-resolved context, unset judgments and unavailable factual/source assessments, identity/grade/URL/host/excerpt omission, title minimization/truncation, current-readiness independence, failed/unknown/missing honesty, proof/expiry tamper, version-pinned rubric failures and memory-store no-write/no-transaction behavior. A concurrent isolated SQLite writer changes a run between proof reads to verify that preparation retains one consistent read snapshot. API/Chromium tests separately cover role guards, text rendering, preview/download acknowledgement, exact downloaded JSON and stale/session state. See [the v1.15 verification directory](../reports/advancement-r07-review-preparation-2026-10-18/) for completed results and actual scope.

There is no new database table, production provider/model call, publication, delivery, maintenance activation or direct live database write. Public frontend and SDK implementations remain unchanged by this private unit. The user manages the server; new Python behavior needs their restart. Basic HTTP/CSP/anonymous refusal observations do not establish authenticated private acceptance. Full R-07/AC-08, G0/G1, actual expert reviews, protected holdout sampling, approved real-provider cohorts and controlled typed-pair orchestration remain open.

After the user's next restart and administrator refresh, the latest authenticated central inspector and worksheet controls were observed with the correct empty-list state. There were no retained connected tests for live preparation/download, so those end-to-end live actions remain unverified. See [v1.16 observations](../reports/advancement-r07-evaluation-governance-2026-10-18/restart-readonly.json). The separate offline governance tool changes no server module and requires no additional server restart.
