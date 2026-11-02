# Restart closeout execution — 2026-10-19

The user restarted the project server and requested continued work. The assistant
has not started, stopped or replaced it. Existing nine-step/42-requirement scope
and pending real-target acceptance conditions are retained.

## Completed in this continuation

- All three browser modules containing the previous12 diagnostic failures pass
  on the latest source:60 cases,0 failures/errors/skips (`affected.xml`). The
  earlier launch-denied sandbox record is retained separately and does not count
  as a product failure.
- Fixed a real verification gap: the content checker omitted the built default
  publication, its templates, generation helpers and source assets. It now scans
  217 files with0 policy violations. Its26-case runner/inventory module passes,
  including two new guards proving inclusion and rejection of non-English
  published content (`checker-final.xml`). Intermediate fixture failure is
  retained in `checker.xml` and superseded by the actual corrected result.
- Read-only smoke on the restarted server passed: supervisor RUNNING; root,
  presets, workflow templates, auth options and sign-in GET requests returned200;
  unauthenticated session returned401. All successful reads had CSP/no-store.
  Root without a browser Accept header is the existing machine welcome response;
  actual HTML navigation was checked separately. Individual GET times are not
  performance acceptance; the run overlaps isolated regression load.
- Actual browser GET-only navigation reached Test, Workflows, Chat, List Your
  Agent and About without page errors. Workspace public navigation stayed hidden.
  No provider execution, form submission, login or customer data mutation occurred.
- Critical Ruff had0 findings. Bandit on `agent_market` had High0/Medium169/Low80,
  scan errors0. All contexts already existed in the earlier repository scan;
  automated warning counts are not a vulnerability certificate. See
  `security-summary.json` and the linked earlier warning review.

## Whole regression and source provenance

The316 selected modules run in four nonoverlapping isolated shards. Counts and
final state will be linked in `verification.json`. Do not add focused reruns or
old baseline counts to unique whole passes.

During execution this task changed only the content checker and its26-case
module. These are pinned in `late-tooling-source.json`; the affected module and
content check are rerun separately. An external change to `new/build_en.py`
was also detected. The original snapshot, additional generator inventory,
final hash differences and actual coverage are kept separately. Current evidence
must not be described as a completely frozen single-source run if differences
remain. No unverified build is generated over the other task's publication.

## Original external acceptance conditions

Customer HTTPS/SDK deployment, real Push test click, independent recovery keys;
approved real long-task A2A and independent evaluator/corpus/trust custody;
designated PostgreSQL HA/load/RPO/RTO; eligible payment TEST account; hosted CI
and peer signoff remain required where the existing plan requires them. Isolated
fixtures do not satisfy these conditions. No new feature IDs were added.

Ollama's existing actual generation remains complete. Claude's earlier personal
CLI compact-plan test passed but is not a hosted customer integration. Gemini's
UNSUPPORTED_CLIENT is not confirmed quota exhaustion. ChatGPT actual inference
remains on the user's hold; no new model inference or payment ran in this
continuation. Hosted customer provider integration remains subject to its
existing approval, isolation, withdrawal and actual acceptance conditions.

## Staged publication correction

A real build race was reproduced: the previous builder copied design-preview
HTML directly into the served tree before composing the operating pages. A
request during that interval could receive a preview as the default page.

`new/publication.py` now renders in a temporary tree under a serialized publisher
lock. Render failure or an incomplete operating entry leaves served files
untouched. Completed assets are replaced first, completed HTML next, index last,
then the manifest. Replacement is atomic per file, not a whole-bundle transaction;
readers can briefly mix completed asset generations. No live publication was
rebuilt by this task. The wrapper is used by subsequent builder invocations.
Temporary trees/lock files are excluded from Git; the lock cannot follow symlinks.

Thirty builder/selection tests passed, including render failure, incomplete
entry rejection, completed publication and actual builder staging cleanup.
A complete disposable rehearsal produced43 HTML documents and passed syntax
checks for operating.js/pearl-ui.js. New publication/checker Bandit had0 findings.

Two further existing publication modules were missing from the selection. The
runner now selects test_pearl_* and explicitly requires the menu, UX and staged
publication modules. The started broad316-module cohort is retained as-is; its
new selection is319 modules and supplemental coverage is recorded separately.

Current workflow UI stores results inline and exposes the old detail dialog on
explicit request. Older assertions were updated to open that control, while
keeping outcome, consent, input-retention and connected-download assertions.
The20-case bounded hydration module and4-case workflow views module passed.

Separate frontend regeneration and test changes continued during execution.
The final-source confirmation question remains pending; no repeated fresh whole
run is started over that moving tree. Actual failures and later focused passes
are recorded individually; this is not a frozen319-module whole certification.

## Recorded final status of this continuation

The started316-module whole diagnostic finished:5761 passed,5 failed,0 errors,
0 skips (5766 cases). All five failures were stale UI assumptions in four workflow
browser modules. Each complete affected module passed after using the current
collapsed editor, recorded-report wording and explicit output-details control:
20 bounded bootstrap cases,4 fallback/template-view cases and4 runtime cases.
These overlap the whole run and are never added to its pass count.

The104-case intermediate publication cohort recorded4 failures after additional
external UI changes. The latest28-case menu/refresh/UX/cached-navigation rerun
passed and covers all four failed cases. Test source changes are preserved in
the source manifests rather than presented as a single frozen full run.

Current selection is319 modules (three additional publication modules). No new
whole run is launched while other frontend changes continue. The pending source
confirmation, original real-target conditions and peer acceptance remain.
See `verification.json` for exact cohorts, failures, replacements and source drift.

This continuation modified verification tooling, tests and the offline builder;
it did not modify the operating Python server. These changes do not require
another project-server restart. The staged publisher takes effect on subsequent
builder invocations. No live publication was regenerated by this task.

Review package: [peer handoff](peer-handoff.md), [verification](verification.json), [remaining order](../../docs/DEVELOPMENT_REMAINING_AFTER_RESTART.md).
