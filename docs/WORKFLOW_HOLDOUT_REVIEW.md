# Offline candidate holdout manifest review

2026-10-18 · bounded R-07 review preparation · pending human review.

The explicit CLI `scripts/validate_workflow_holdout.py` checks a frozen candidate task inventory before a separately authorized evaluation is designed. It does not execute a workflow, read a workflow database, open a key store, call an agent/model, retrieve a source, collect a human judgment or assign a score. A structurally valid file is **not evidence of a hidden, unseen, representative or expert-reviewed holdout**.

The existing [30 published machine fixtures](workflow-evaluation-cases.json) test bounded input safety. They remain development material. Relabelling one as an authored candidate, changing its case name, or placing its accepted title into a different task's query cannot make it held-out evidence.

## Explicit invocation and output

From the repository root:

```sh
.venv/bin/python -B -m scripts.validate_workflow_holdout --manifest /absolute/physical/path/manifest.json
```

For the deliberately synthetic validator example:

```sh
.venv/bin/python -B -m scripts.validate_workflow_holdout --manifest tests/fixtures/workflow_holdout_manifest.json
```

That example is a test fixture, not a real evaluation dataset or an allocation of unseen tasks. Its candidate labels demonstrate the validator's structure only. Its dates and tasks are not provider observations.

Use `python -B` as shown, or set `PYTHONDONTWRITEBYTECODE=1`, to suppress interpreter import-cache writes. The reported `artifact_writes=0` means this tool creates or modifies no manifest, report or evaluation artifact; ordinary Python invocation may otherwise create `.pyc` import caches. The module does not change process-global bytecode settings.

One explicit `--manifest` is required. There are no execution, mutation, automatic repair or output-file flags. Repeated manifest arguments are rejected. Imports and no-argument invocation do not open the application, database or input inventory. Successful validation emits only fixed status fields, aggregate counts and the manifest fingerprint. Failures emit a fixed reason code and return a nonzero exit status without printing the supplied file path, task, input or exception traceback.

The reader accepts one existing regular UTF-8 JSON file of at most 512 KiB, with at most 200 cases. It opens every path component with no-follow semantics and rejects file or parent-directory symlinks, directories, pipes, missing files and files that change during the bounded read. On systems where the safe open primitives are unavailable, it fails closed. Use a physical path; for example, a system alias such as `/tmp` may itself be a symlink. No missing file or directory is created. Duplicate JSON keys, nonfinite numbers and invalid JSON are refused.

## Manifest and freeze contract

The top-level object accepts exactly:

- `schema_version`: integer `1`, never a boolean.
- `dataset_id`: a bounded lowercase opaque identifier.
- `version`: an integer from 1 through 1,000,000.
- `review_state`: exactly `pending_human_review`.
- `cases`: 1–200 case objects.
- `manifest_fingerprint`: the required lowercase SHA-256 canonical fingerprint.

Each case accepts exactly `case_id`, `family_id`, `split`, `origin`, `review_state`, `task`, `contracts`, `inputs`, `task_fingerprint` and `input_fingerprint`. IDs use a bounded lowercase identifier syntax. `split` is `development` or `candidate_holdout`; `origin` is `authored_candidate` or `published_machine_fixture`; the case review state must also be `pending_human_review`. Unknown fields, assessor claims, invented expert identities, scores and review-complete flags are rejected.

`contracts` contains one or both of `news.search.v1` and `docs.search.v1`, without duplicates. `inputs` maps exactly those contracts to their complete literal argument objects. It is not a template or a runtime connection declaration. The existing public IntentSpec/title safeguards validate every task and query. The existing contract validator checks required fields, English request language, bounded result limits and a valid UTC news period. The compiler's result limit remains at most five. URLs/contact/known secret/private-path patterns, markup, expressions, controls, wrong JSON types and overlong public task/query values are refused rather than repaired or truncated. These safeguards are not a complete privacy or prompt-injection detector.

The freeze uses three different references:

- `task_fingerprint` binds the task after Unicode NFKC normalization, case folding and whitespace collapse.
- `input_fingerprint` binds the complete contract/input mapping. Requested contract order is normalized; query values, period, language and limits remain exact. A changed query or limit requires a new fingerprint.
- `manifest_fingerprint` binds the complete manifest except its own fingerprint field, including every case, original task, ID, family, split, origin and review state. Canonical JSON uses sorted keys, compact separators, ASCII escaping and finite JSON values. Formatting the JSON differently does not change its semantic freeze.

The exported pure helper functions `task_fingerprint`, `input_fingerprint` and `manifest_fingerprint` support deliberate authoring and tests. The CLI verifies required fingerprints; it never silently generates or updates them. SHA-256 is a content freeze, not proof of authorship, secrecy, chronological reservation or human approval. A file author can recompute a fingerprint, so an independent allocation record remains necessary.

## Development/holdout separation checks

Case IDs must be unique. A family must stay within one split. A normalized task, exact complete input fingerprint or normalized query text cannot cross splits. Query overlap is checked separately, so changing the task label, result limit or contract set cannot disguise reuse of the same search content. Repeated cases within one split are not evidence of sample independence.

The validator additionally reads the fixed bundled public machine-fixture inventory. It requires its known dataset/schema version, 30-case count, pending review state and pinned canonical case digest. Missing, malformed, empty or changed inventory produces `published_fixture_inventory_unavailable`; it cannot silently disable the protection. Supporting a revised public fixture version requires a deliberate version/digest review. Any candidate holdout case declared as a published fixture, or matching an accepted published title through its task or any query, is refused regardless of its claimed origin.

These checks catch exact normalized reuse, not paraphrases, topic leakage, external training exposure, semantic equivalence or intentional false family labels. They cannot establish that a model or developer has never seen a task. Independent authorship, topic grouping, access control, representative sampling and human review remain necessary.

## Review preparation and remaining human work

Validation always reports `review_state=pending_human_review`, `pre_run_allocation=not_established`, `unseen_holdout_status=not_established`, `representativeness=not_assessed`, `human_expert_reviewed=false` and `provider_quality_certified=false`. It creates no capability evidence, recommendation priority, benchmark result, provider score, customer claim, publication permission or execution authorization. There is no new table, schema initialization, queue polling, server operation or storage migration.

The separate private typed-run review worksheet prepares minimized metadata from retained signed evidence. It does not supply source excerpts or full citation URLs and is not a blinded review packet. Source fidelity and factual correctness cannot be certified from that worksheet alone. Missing material requires a separate controlled human evidence process; it must not be filled with fabricated judgments.

Recommended continuation:

1. Author candidate public tasks, complete literal inputs and honest family groups; keep known development fixtures in the development split.
2. Independently inspect the task inventory and its freeze. Use the separate [offline evaluation governance plan validator](WORKFLOW_EVALUATION_GOVERNANCE.md) to check the authored role slots, family/case coverage, source-handling declarations and procedures against this exact manifest/rubric. Record actual reviewer qualifications and access/allocation procedures privately, rather than adding invented reviewer claims to this file. A structurally valid plan still needs real people and independently verified evidence.
3. Reserve a versioned allocation before any measured provider/model run. Associating a historical result after viewing it does not establish an unseen holdout outcome. The current CLI records no such reservation.
4. Collect required source/task evidence through a separately authorized process and obtain independent judgments on the six existing rubric dimensions. Missing source evidence remains unassessed. Record disagreements and adjudication before drawing benchmark conclusions.
5. Design any measured cohort or paired execution with explicit call authority, consent, input/source context, budgets, idempotency, retention and unknown-outcome handling. A valid manifest does not authorize those actions.

The CLI's local schema/safety fixtures and read-only behavior can be regression tested. Actual semantic quality, independent expert agreement, representative held-out sampling and approved-provider performance remain unverified until those real procedures occur.
