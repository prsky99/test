# R-07 private typed output connection — v1.13

2026-10-18 · Source implementation and isolated verification; authenticated deployment acceptance pending.

## Delivered

The private workflow composer can connect `news.search.v1.items[0].title` to `docs.search.v1.query`. The default independent searches remain unchanged. The server owns the mapping, graph and inputs; no planner expression, arbitrary path/URL, coercion, truncation, fan-out, default query or extra retry is introduced.

Generation saves or executes nothing. Its connected-node preview has `sharing_authorized=false`; only an owner-bound proposal saved with separate explicit title-sharing permission produces an executable signed binding. An explicit live test remains a separate choice. Replacement/close/logout/expiry clear UI consent. The native centered dialog renders untrusted values through text nodes and accurately labels successful connected tests as private.

The signed connection binds exact source/target IDs, contracts, current pins, path/field, reviewed literal settings, source binding hash (including the original news input), sharing decision and notice. Admission rejects a different valid same-pin source objective before queueing. At runtime and dispatch, same-run source checkpoint HMAC/audience/run/digest/node, successful status, source input, complete output equality, strict observation timing and the news output contract are verified. Only a safe 1–500-character title becomes the documentation query. Empty/oversized/control/address/secret/template/markup inputs fail closed. The downstream checkpoint signs the source proof hash.

Current highest-admin manual authority is required. Public projection/publication, scheduled/event configuration and execution, deployment/verification principals, automatic fallback and the existing literal-input comparison profile remain unavailable for this connected profile. These scopes require separate contracts. Existing independent comparison/publication and public frontend/SDK downloads are preserved. No table is added; the 27-table PostgreSQL state rehearsal includes a connected snapshot, three checkpoints, actual resolved arguments and provenance.

The evaluation artifact has 30 machine cases and six unscored human-review dimensions. It is **pending human review**, not expert-certified provider quality or a benchmark winner. Schema/fixture validity does not prove relevance, factual accuracy, privacy or English-language provider behavior.

## Verification

- Broad isolated regression: **1,414 passed**, 0 failed/skipped (`broad/regression.xml`, 553.34 s).
- Final affected paths: **212 passed**, 0 failed/skipped (`final-affected.xml`, 77.29 s), including 104 new typed-flow/evaluation cases, existing composer/model-TLS, comparison, runtime and admin SDK browser cases.
- Reconciled latest outcome by `(classname, name)`: **1,438 unique passed**, 0 unresolved failures/skips. Counts overlap and are not summed. Broad started before final timing, automatic-configuration, bounded-read, source-binding and copy hardening; final affected tests cover those changes. The full broad suite was not repeated after them.
- New tests: 26 connection/runtime/storage cases, four Chromium cases, 11 independent role/evidence/unknown review cases and 63 curated-artifact/input checks.
- Five relevant Python modules scanned: Bandit High 0 / Medium 14 / Low 16. All warnings match previously reviewed unchanged private-admin paths; typed-flow/composer/runtime/comparison modules have zero scanner findings. `static-triage.json` retains per-finding rationale.
- Manual review found negative/boolean elapsed-time and future-observation acceptance in otherwise signed source records; strict numeric/time checks now reject them. A second review found that a same-pin source from another signed objective could reuse a sharing binding; the source binding hash and prequeue check now prevent it. These are signed-evidence integrity fixes; no lower-role HMAC bypass is claimed.
- Dynamic API/browser checks cover separate share/save/test authority, copied unauthorized previews, current role downgrade/account deactivation, wrong source scope/input/output, checkpoint tamper, unsafe/empty titles, publication/comparison exclusion, automatic-configuration refusal, source uncertainty/idempotency and checkpoint continuation without another source call.
- Typed continuation simulates abrupt process exit before target preparation. Existing R-05 real SIGKILL/fence/outbox tests remain in broad scope; the new simulation is not described as an additional SIGKILL test.
- New dynamic provider requests execute the registered MCP code path against isolated `MockTransport` fixtures. Existing TLS/model/browser and PostgreSQL tests use local fixtures. No production provider/model cohort or semantic/expert quality evaluation is claimed.
- Public content check: 53 files, 0 violations. Seven public frontend/ZIP/SDK implementation hashes remain unchanged; embedded HTML and `extracted_html.txt` are synchronized. Public Home/meta copy requires no new claim for this private-only feature.
- Inline admin JavaScript syntax and changed Python compilation pass. `connected-private-draft.png` was visually inspected: centered native scrollable dialog, explicit title-sharing disclosure and private status.

Initial development trials (`typed-first` and `review-initial`) retain the discovered test-harness mistakes and three timing-validation failures. The resumed-step harness was corrected to model abrupt process exit instead of an ordinary caught exception; nonexistent helper calls and missing deployment-fixture assumptions were removed. Final JUnit results supersede those attempts. No failed test is omitted from the final reconciliation by summing only successful executions.

## Restart and operational boundary

`restart-readonly.json` observes listener PID72182, Home/admin HTTP200+CSP, existing comparison/composer markers and anonymous generation/publication/control/maintenance403 after the user restart. Independent mode=ro inspection found fallback off and zero policies. These prove basic observations and anonymous refusal only. The user-owned server was not stopped, restarted, replaced or supplemented with a competing project server.

New Python behavior requires another user-managed restart. Authenticated highest-admin live composer/typed-control/recovery/retention acceptance is still pending. Development performed zero server operations, direct live DB writes, production provider/model tasks, production publication/delivery, canary activation or automatic maintenance. Full R-07/AC-08 and G0/G1 remain open.

## Continuation

1. User restart and authenticated private acceptance of this profile.
2. Independent expert review/adjudication, held-out tasks and measured approved-provider evidence.
3. Resolved-input/provenance-aware comparison and publication design, then additional narrow mappings.
4. Explicit paired-run orchestration with separate per-call consent, budget and unknown handling.
5. Opt-in SDK1.2/deployment and schedule/event sharing contracts; keep SDK1.0/1.1 unchanged.
6. Reviewed product/cascade contracts and measured storage/operations acceptance.

See [typed connection](../../docs/WORKFLOW_TYPED_FLOW.md), [composer](../../docs/WORKFLOW_COMPOSER.md), [recorded comparison](../../docs/WORKFLOW_COMPARISON.md), [main design](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md), [verification JSON](verification.json) and [latest test reconciliation](test-reconciliation.json).
