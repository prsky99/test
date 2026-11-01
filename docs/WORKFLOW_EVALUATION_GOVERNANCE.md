# Offline evaluation governance plan

2026-10-18 · bounded R-07 planning support · actual human evaluation pending.

This private, offline planning step connects the [candidate manifest](WORKFLOW_HOLDOUT_REVIEW.md) to a proposed independent review process. It validates the consistency of an authored plan. It does not appoint people, verify qualifications, collect source material, enforce access controls, reserve tasks, run an evaluation or establish an unseen holdout.

The existing [review worksheet](WORKFLOW_REVIEW_PACKETS.md) remains a metadata-only, unscored view of one retained private test. It cannot replace a separately reviewed source bundle or prove factual accuracy. The 30 public machine fixtures remain development material.

## Explicit command and authored format

Run from the repository root, using existing physical paths:

```sh
.venv/bin/python -B -m scripts.validate_workflow_evaluation_plan --manifest /physical/path/manifest.json --plan /physical/path/plan.json
```

The public, deliberately synthetic example is:

```sh
.venv/bin/python -B -m scripts.validate_workflow_evaluation_plan --manifest tests/fixtures/workflow_holdout_manifest.json --plan tests/fixtures/workflow_evaluation_plan.json
```

That example demonstrates four cases/families, seven unfilled role slots, six pending procedures and missing source bundles. It does not name or appoint actual people. One `--manifest` and one `--plan` are required; repeats, abbreviations, output/repair/execution flags and unexpected arguments are refused. The direct script entry point also works outside the repository working directory. There is no implicit input discovery.

The plan accepts exactly `schema_version`, `profile`, `plan_id`, `version`, `stage`, `manifest_binding`, `rubric_binding`, `slots`, `procedures`, `allocations` and `plan_fingerprint`. Schema is integer `1`; profile is `offline-evaluation-governance-v1`; stage is `pre_execution`. Plan versions are integers from 1 through 1,000,000. The manifest binding must match the separately validated dataset identity, version and fingerprint exactly. The rubric binding must match `workflow-review-rubric-v1` and its pinned SHA-256; the fixed bundled rubric is also checked for drift.

The canonical plan fingerprint binds every declared field except itself, using finite, sorted-key, compact ASCII JSON. The validator checks the supplied fingerprint and never rewrites either input. A changed version, assignment, record, source declaration or access list requires a new deliberate freeze.

There are 7–32 role slots. Each slot has an opaque `slot_id`, a role, and separate identity/qualification/conflict states and records. Pending identity has a null commitment; `self_declared_unverified` identity requires a unique SHA-256 commitment. Qualifications and conflict records are either pending/null or self-declared unverified opaque `{ref, sha256}` records. IDs and record references are bounded lowercase ASCII identifiers with digits, dots, underscores and hyphens; they are not URLs, paths or contact addresses. All slots must be used by an allocation.

The exact six procedure keys are `identity_and_qualification`, `conflict_and_independence`, `source_material_review`, `candidate_access_control`, `pre_execution_reservation` and `disagreement_adjudication`. Each is pending/null or `declared_unverified` with an opaque record/hash. A declared procedure is not a completed or enforced procedure.

Each family allocation contains its original `family_id`, `split`, complete unique `case_ids`, `roles`, `access` and per-case `source_materials`. The singular `roles.reviewer` key holds 2–4 distinct outcome-review slots. Other roles contain one slot each. Source availability is `pending`, `metadata_only` or `separate_source_bundle`; only a separate bundle can carry a `declared_reviewed_unverified` review reference. No accepted state says verified, approved or completed.

Successful validation exits zero with `status=needs_human_actions`, aggregate pending/declaration counts, content fingerprints and fixed unestablished evidence gates. Zero means the declaration is structurally consistent, not approved for execution. Invalid input exits nonzero with a fixed reason code. Individual task/family/case/slot IDs and private record references are omitted from success output.

## Operating sequence

1. Freeze a candidate manifest with honest task-family groups and complete literal inputs. Validate it using the existing offline manifest validator. Do not relabel published fixtures or reuse their queries as held-out cases.
2. Author an evaluation plan against that exact dataset version, manifest fingerprint and pinned six-dimension rubric. Describe proposed role slots, per-family assignments, source-material handling and the required private procedures. Pending records are honest missing work, not approval.
3. Validate the plan locally. Inspect aggregate pending counts and address its structural errors. A successful result still requires real human actions; it grants no execution or sharing authority.
4. Separately identify actual people, privately verify their relevant qualifications and conflicts, obtain their participation and confirm their independence. Map opaque slot references to those records under restricted access. A distinct string or self-declared identity commitment cannot prove that two people are independent.
5. Before any measured run or disclosure to an executor, an independent custodian must reserve the exact manifest/plan/rubric versions in an access-controlled ledger with independently verifiable chronology. Record who could access candidate tasks and when. The current CLI neither creates that ledger nor accepts historical run results as proof of reservation.
6. Collect source/task evidence through a separately authorized process. Review its relevance, completeness, freshness, lawful use and privacy before assessment. Keep unavailable source fidelity unassessed. A source-bundle reference or its hash is a declaration until the underlying material and review are actually verified.
7. Design and authorize controlled execution separately, including actual input/source context, provider/model sharing, bounded call budgets, provenance, cancellation and unknown-outcome handling. Obtain two independent judgments and adjudicate disagreements before drawing quality conclusions or seeking publication consent.

These are operational prerequisites. They are not actions performed by validating JSON, and this repository contains no real reviewer roster, expert credential, private source bundle or hidden evaluation result for this step.

## Independent roles and evidence boundaries

The plan separates curator, custodian, executor, source reviewer, two outcome reviewers and adjudicator. Their references must resolve to the correct structural roles, and the same slot cannot fill conflicting positions. Nonempty self-declared identity commitments cannot be reused to disguise multiple roles. Nevertheless, changed hashes or references can conceal the same person; verifying real identity and independence remains a private human responsibility.

Qualification, conflict, source-review and procedure records use opaque references and claimed SHA-256 commitments only. Do not embed names, email addresses, credentials, local paths, source URLs, source excerpts or result bodies in these references. Identifier syntax is not a complete de-identification detector. The tool does not follow these references or open caller-referenced material. It separately reads the fixed bundled public fixture/rubric inventory for drift checks. It never computes or verifies the content hashes of private records. A claimed hash proves neither authorship nor the truth of a declaration.

Every manifest family and every case must be covered exactly once, with the original split preserved. Candidate task access before execution is limited in the declared plan to the curator and custodian. During-review access must include the assigned source reviewer, outcome reviewers and adjudicator; it may also include other roles assigned to that family. This validates an intended access list; it does not install permissions, guarantee blinding or prove that no developer, model or other person has seen a task.

The six rubric dimensions remain task relevance, source fidelity, temporal fit, missing-data honesty, typed-query usefulness and data-sharing safety. Rubric identity is versioned independently of a plan or dataset. Changing a plan, manifest or rubric requires deliberate version/fingerprint review, not automatic repair.

## Source handling

Pending material and metadata-only worksheets cannot be promoted into factual or source-fidelity evidence. A declared separate source bundle requires a bounded opaque content reference/hash and a structurally separate source-review role in its family allocation. A pending review has a null review record; only `declared_reviewed_unverified` requires a review reference/hash. Those declarations do not prove that the source exists, is accurate, was reviewed or was collected before an outcome was seen.

No source URL is fetched, source file opened, external upload performed, worksheet modified or score recorded by this tool. Source absence remains explicit. A successful structural check must never be described publicly as an expert quality certificate or held-out provider benchmark.

## Real reservation remains a separate implementation

The authored plan intentionally has no completion timestamp, provider run reference, score or historical worksheet identifier. Adding a local timestamp, recomputing a SHA-256 or signing a document with an application key after seeing an outcome cannot establish pre-execution chronology.

A future reservation service must verify actual authorized identities and roles; enforce access and disclosure logs; bind exact plan/manifest/rubric hashes before execution; preserve independent chronology and immutable revisions; tie measured runs to that reservation and approved input-sharing authority; and protect withdrawal, retention and unknown-outcome boundaries. It needs a separately reviewed threat model, operating authority and isolated acceptance tests before activation.

The plan validator is deliberately usable before that service exists. Its output keeps real reviewer assignment, identity/qualification verification, actual source review, enforced access, chronological reservation, unseen status and human judgments unestablished. No candidate eligibility, quality grade, recommendation rank, publication state or execution permission changes.

## Compatibility and security scope

The tool is an explicit offline command, with no server route or administrator screen. Existing public frontend, gateway, SDK/web-app downloads, workflow runtime, authority, unknown barriers and metadata worksheet APIs remain unchanged. No schema initialization, database/key-store access, polling, server restart, provider/model call, delivery, publication, fallback activation or automatic maintenance is performed.

Use physical file paths and `python -B` to avoid interpreter bytecode-cache writes. Both inputs use bounded regular-file reads with no-follow semantics. Malformed structures, duplicate JSON keys, nonfinite values, symlinks/pipes, unsupported fields, mismatched fingerprints and incomplete/cross-role allocation are refused. CLI errors are fixed codes and do not echo input paths, tasks, identities, record references or tracebacks. Successful output is aggregate-only and still reports missing human evidence.

The synthetic fixtures in `tests/fixtures/` demonstrate validator behavior only. They are public test data, not an operational plan, appointment, source review or reserved evaluation cohort. Existing task guards reject known private/secret patterns and unsupported executable content; they are not complete sensitive-text or prompt-injection detectors. Regression checks verify local validation and isolation; they do not establish real expert agreement, representativeness, factual provider quality, secrecy or production-scale performance.
