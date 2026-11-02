# Workspace template hub and Gemma 4 E4B

Objective: Workspace template selection/use/editing, truthful fallback labels,
model-specific empirical generation tuning. No unrelated admin changes; no
service restarts/deployments and no real customer account/credit mutations.

Implemented: `workspace_template_hub.py` signs private saved configurations and
immutable versions; uses existing credit rules, current membership/CSRF, CAS,
review signatures, current published product hashes and proof checks. Execution
uses existing protected product runtime (one explicitly consented alternative);
sealed run capabilities remain server-side. Download requires current successful
saved-version test. `customer_template_hub_view.py` injects English Pearl/Lucide
cards/editor/library; editable contract starters use existing typed review path,
without inheriting product fallback. Existing AI first-screen layout preserved.
Routes/core/view wired. `workflow_model_proposer.py` uses temperature 0 and 128
query-only output tokens for recognized Gemma 4 E4B aliases; other paths unchanged.

Validation: 187 unique non-browser affected tests pass (64 focused +123 integration,
disjoint suites). One unrelated full private-cluster PostgreSQL test cannot start
because macOS System V shared-memory IDs are exhausted; no system/HBA/process
changes attempted. PostgreSQL 18 fixed-SQL checks 9/9 pass in a removed private
schema of metadata DB; app DB never used for those synthetic rows. Reviewed empty
workspace_template_records table/index installed in app DB; fresh native whole
schema attach succeeds. 52 model/API cases pass (31 actual generations, 21 local
clarifications/denials), plus 8 real-model native browser generation/save/run cases.
Sampling comparison 3 profiles x31 =93/93 passed; selected constrained-128 profile
p95 .4861s vs prior .5276s in this bounded run; median essentially unchanged.
29 browser regressions passed before final starter addition. Final hub browser
suite has 3 scenarios (mobile/desktop save-run-download, editable starter), pending
last selector fix rerun. Focused lint/syntax pass, 255 public files/0 violations.

Completed: final hub browser 3/3, schema guards 4/4, schema/catalog checks passed;
README and validation-summary.json written. 191 API/unit/schema guards and 30
distinct browser regressions passed. User must `agentcon restart frontend` to
load source/UI. No remaining source task in this scoped request.
Admin/jobs/execution sources affecting product proof/runtime were not changed.
Preserve dirty baseline/other work. No subagents, no production model/account tests.

Post-restart: user deployed frontend web-20261024-232757-c0d8, active B ready.
All seven feature files match. Public catalog has protected products41/42/43
fallback true. Home/catalog200; unauth workspace303 and customer APIs401.
Computer-use timed out twice, so authenticated operating UI not rechecked.
No new source changes/restarts/account writes. Evidence post-restart-*.json.
