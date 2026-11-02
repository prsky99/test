# Workspace Template Hub and Gemma 4 E4B

Implemented and verified on 2026-10-24. Frontend source is ready; the running
frontend has not been restarted or replaced by this work.

## Delivered behavior

- Workflows now has a Template Hub shortcut and a hub below the AI editor. The
  initial AI controls retain their existing first-screen placement. All new copy
  and source comments are English; the design uses Pearl surfaces and local
  Lucide-style SVGs, keyboard labels and the existing loading/CSP/theme system.
- The hub lists currently published, proof-valid protected products, including the
  existing research products when eligible. Select one, personalize declared
  public search inputs, review the exact settings/credit quote, and save a private
  version. Another customer/workspace cannot read or operate that saved record.
- Protected copies keep the reviewed product graph and original fallback runtime.
  Each run needs fresh explicit sharing consent. Eligible failures can use one
  verified alternative; uncertain requests are not automatically repeated.
  Availability/hash/proof is checked again before save, run and download.
- A successful test of the current saved revision is required to download the app.
  The ZIP contains the user's saved defaults and uses the fixed public routing
  gateway; it contains no run capability, provider secret or upstream credentials.
  It follows the existing public product execution limits and per-run consent.
- Saving a new template workflow costs one credit. Saving edits before its first
  download costs zero; saving edits after download costs one credit. Downloading
  the same tested revision again costs zero. Existing plan enrollment and role
  requirements remain in force.
- Editable contract starters open in the existing step editor. Their input fields
  and graph can be changed and reviewed through the existing workflow lifecycle.
  Unavailable connections disable the starter action. A changed/custom graph does
  **not** inherit a product's fallback proof. Agent connection hints distinguish
  "fallback available in Template Hub" from fallback enabled on a custom graph.
  Protected product customization currently edits declared inputs; arbitrary
  product-graph editing is deliberately not labeled as verified fallback.

## Model settings and measured results

The configured model is the local OpenAI-compatible Gemma 4 E4B service, rather
than the former Gemma 3 1B/Ollama path. No inference server was restarted or
reconfigured. The application continues to use the configured fixed endpoint.

Google documents Gemma 4 system turns and an explicit thinking control token;
this bounded query-extraction task keeps thinking off and accepts only strict
JSON. See [Google prompt formatting](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4).
The [official general generation configuration](https://huggingface.co/google/gemma-4-E4B-it/blob/main/generation_config.json)
uses temperature 1, top-p .95 and top-k 64; those general sampling values were
compared with deterministic settings rather than assumed optimal for this task.

The same 31 supported public objectives were tested with three request profiles:

- Prior deterministic setting: 31/31 passed; median .3388s, p95 .5276s.
- Deterministic query-only 128-token setting: 31/31 passed; median .3416s,
  p95 .4861s.
- General Gemma sampling: 31/31 passed; median .3858s, p95 .5974s.

Applied temperature 0, non-thinking strict JSON and a 128-token query-only ceiling
for recognized Gemma 4 E4B aliases. The generic agent-selection path retains its
existing larger bound; other model profiles are unchanged. This is a bounded
single-host measurement, not a universal speed or quality guarantee. Median
latency was effectively unchanged; the smaller limit primarily bounds excess
output. The validated contract compiler continues to select approved resources,
set step counts, validate inputs and connect declared prior outputs.

After tuning, all 52 customer API generation scenarios passed: 31 actual model
calls and 21 local clarification/rejection cases. Actual-model requests had
median .3630s and maximum .5450s in that run. Covered 2/3/5/10 steps, news/document
ordering, independent topics, result limits, date windows, English/Korean input,
C++/.NET/version subjects, negative instructions and unsupported/private requests.
Eight native-browser real-model cases also passed, including generation,
credit-confirmed save and execution against isolated synthetic agent transports.
These tests do not claim real external agents were called in the generation suite.

## Verification and security scope

- 191 distinct affected API/unit/schema-guard tests passed: 64 focused, 123
  disjoint integration cases, and 4 additive-migration guards.
- 30 distinct browser regression cases passed across the existing theme/mobile/
  loading suite and the three template-hub cases. The hub cases cover mobile and
  desktop select/edit/review/credit-save/run/result display/ZIP download, and
  opening/modifying an editable starter. Screenshots are in `browser/`.
- Actual MCP transport under isolated controlled preflight failure reached the
  alternative and succeeded. Signed saved settings remain separate from the
  published graph; no provider call occurs on selection/review/save.
- CSRF, foreign-workspace access, viewer/runner restrictions, forged reviews,
  stale CAS, expired proof/review, unsafe/undeclared inputs, duplicate dispatch,
  uncertain admission, encrypted run-key storage, version-bound downloads and
  credit idempotency/races were checked. No client POST is automatically replayed.
- Nine native PostgreSQL 18 SQL checks passed using a temporary schema in the
  metadata database; the schema was removed. They cover binding, lookup,
  workspace isolation, uniqueness, CAS/stale-CAS, ordering, counts and the index.
- An empty `workspace_template_records` table and its lookup index were added to
  the configured application DB. No existing table, customer row, customer credit,
  fallback policy, product publication, HBA rule or server process was changed.
  Fresh native application-profile attachment and final schema checks passed.
- SQL catalog: 232 tables / 3,723 fixed statements, regeneration check unchanged.
  Focused fatal/undefined-name lint and Python syntax passed. Public-content
  check: 255 files, zero violations. This is affected-feature secure-coding and
  dynamic browser/API regression coverage, not a whole-platform penetration test.

One unrelated existing full fresh-cluster PostgreSQL regression could not start:
macOS System V shared-memory IDs are exhausted (`shmget`, ENOSPC). It is explicitly
excluded from the 191 passing cases. The environment was not modified to bypass
that condition. A new random database was also refused by the existing HBA rule;
that temporary database was removed. Native SQL checks instead used a removed
private schema in the metadata DB, and the real application schema was separately
validated after the additive change. No full fresh-cluster lifecycle pass is
claimed for this run.

## Rollout

Run in the user's terminal:

```sh
agentcon restart frontend
```

Then refresh the customer Workspace → Workflows page. Use **Template Hub** in its
header, or **Create with AI** to return to the natural-language editor. This work
does not activate the public Workspace navigation link or change its publication
setting. Admin/jobs/execution restart is not required for these source changes;
the protected product execution implementation and its signed proofs are unchanged.
After restart, check the currently signed product verification window rather than
assuming expired/withdrawn templates should remain listed.

For another already provisioned PostgreSQL deployment, run the reviewed additive
schema command before loading this frontend version:

```sh
.venv/bin/python -m scripts.migrate_workspace_template_hub --check
.venv/bin/python -m scripts.migrate_workspace_template_hub --apply
```

Only the dedicated table/index are eligible for creation. Existing schema
mismatches are rejected; this tool never automatically alters existing tables.
The local configured DB has already passed this step.

## Evidence

`focused-final.log`, `integration-final.log`, `schema-guards.log`,
`browser-complete.log`, `hub-download-browser.log`, `model-final.log`,
`model-final/summary.json`, `sampling/summary.json`, `native-sql.log`,
`native-attach.json`, `schema-applied.json`, `schema-final.json`,
`catalog-final.log`, `catalog-coverage-final.log`, `lint.log`, `content-check.log`.

Earlier failed development checks are retained to show fixes and environment
limits. The first sampling harness used the wrong state-key assertion; its log
is `sampling-harness-before-fix.log`. The preserved valid model outputs were
reassessed with the corrected assertion; model requests were not repeated for
that harness correction. `sampling/results.json` contains the corrected checks.

## Post-restart operating verification

The user restarted the frontend. Active release `web-20261024-232757-c0d8`
is ready; all seven feature files match the verified source, including the new
UI/core/routes, model proposer and SQL catalog. Home and template catalog return
200. The catalog contains the three protected research products (41, 42, 43), all
with fallback availability. Workspace pages redirect unauthenticated requests to
sign-in, and customer session/template APIs return 401 as expected. No additional
service restart, customer mutation or live workflow execution was performed.

Computer-use connection timed out on both attempts. Therefore authenticated
post-restart interaction is not claimed; the previous isolated browser results
and identical deployed sources are the available UI evidence. Raw bounded
results: `post-restart-source.json` and `post-restart-http.json`.
