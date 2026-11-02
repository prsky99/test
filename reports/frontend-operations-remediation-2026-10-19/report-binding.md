# Report subject and execution-evidence remediation

Implemented in source on 2026-10-19. No live database, provider, seed script or project server was opened for writes or restarted. Verification used disposable in-memory/temporary databases and controlled HTTP fixtures. Existing dirty source changes were preserved.

## Behavior

- Report identity requires the same resource ID and protocol, a matching supplied subject name, and the complete canonical endpoint. A managed gateway URL also requires a matching current immutable connection version; a database-local numeric ID and common display name alone are insufficient.
- Recommendation ranking no longer falls back from execution time to report publication time. A report can affect verification rank only when actual start/finish timestamps, execution scope, current version, subject, outcome and the latest unexpired registry execution evidence agree. Forged timestamps, static imported success flags, other protocols and versionless/unrelated reports cannot supply this priority.
- Saving an execution or contract report requires matching recorded scope evidence. Metadata is inserted atomically with the report; the subject/evidence is rechecked after acquiring the writer lock. Historical documents remain stored, and exact-endpoint historical reports can remain publicly visible with `published_at`, `executed_at`, `execution_finished_at`, `evidence_scope`, `execution_measured`, `execution_verified` and an explicit historical/current state. Original success/latency fields remain reported facts; publication is not relabeled as execution.
- Existing unrelated or unbound managed-gateway reports remain administrative history and are omitted from public attribution. This intentionally removes badges for the old versionless managed reports; it does not delete their stored bodies or rewrite their claimed original results.
- SQLite Store initialization installs INSERT and identity/version UPDATE guards. They also reject direct-SQL seed/import attempts with a mismatched local kind/name/endpoint or a managed endpoint without a locally bound version. Existing rows are not rewritten. These guards take effect when the user next starts the updated Store; this task did not install them in the running live database. The raw-SQL guard is SQLite-specific. Native PostgreSQL continues to use validated Store writes and fail-closed public evidence checks; no untested native trigger/migration was introduced.
- Seven maintained hardcoded `seed_*reports.py` entrypoints now refuse execution before opening a Store. Historical generated batch scripts were preserved; they must not be run against a live database. Their direct writes are guarded after the updated SQLite Store initializes.
- `scripts/import_test_reports.py` requires explicit `--db` and `--reports` paths, defaults to read-only preflight, resolves `subject_key` independently within the selected destination, validates name/protocol/endpoint, and imports historical documents only with an explicit `--apply`. It does not copy another database's numeric identity or claim provider execution. It was not run against production.

## Public cards, filters and cache

Public report counts and has-report queries use a conservative subject predicate and then revalidate complete current identity. Report grades/scores on cards come only from matching recorded evidence; historical report publication cannot override the current grade. Both fresh and cached cards are rechecked, including Learn/Insights cards. The report drawer receives the full evidence metadata and Store context for current-vs-historical labeling.

Drawer subject filtering happens before its five-report limit, so five newer bad imports cannot hide a legitimate older report. The final focused report-binding suite has **21 passing tests**, including this case.

Explore's execution filter and Insights execution lanes require unexpired succeeded eligibility, a schema-complete local connection version, matching execution proof, and no newer failure. Per-card registry projection supplies the final current authorization/schema/version check. Healthy status and untimed legacy `trial_ok` flags no longer qualify by themselves. Legacy machine fields remain available; Insights adds the separately defined `execution_verified` count.

Evidence-filtered Explore requests bypass both local and Redis result caches so their counts/query predicates refresh. Cached bootstrap DTOs and Insights lanes remove invalid current execution claims after revalidation. Normal card caches retain the performance benefit while refreshing report identity/grade/count and execution readiness.

## Files

- `agent_market/concierge/report_evidence.py`: canonical identity, deterministic current version, persisted evidence matching, SQLite raw-import guards.
- `agent_market/concierge/selection.py`: measured execution ranking without publication-time fallback.
- `agent_market/concierge/report_projection.py`: bound public history, separate publication/execution metadata and truthful verification flags.
- `agent_market/gateway/store.py`: validated report creation, atomic evidence metadata and SQLite guard installation.
- `agent_market/concierge/front.py`: only card/filter/cache/report evidence portions were changed by this subtask; root owns Home HTML and drawer presentation.
- `scripts/import_test_reports.py` and seven retired report seed entrypoints.
- `tests/report_fixtures.py`, focused report-binding regressions, and existing recommendation/projection/bootstrap/menu fixtures updated to record actual isolated evidence where verified status is intended.
- The independent reviewer owns the bounded PostgreSQL SQL-catalog extractor/registration repair, including fixed report/card/summary queries. No arbitrary runtime SQL fallback was added.

## Validation

Latest core run after strict execution filters and truthful schema/evidence fixtures: **145 passed**:

```text
.venv/bin/python -m pytest tests/test_report_evidence_binding.py tests/test_fast_single_recommendation.py tests/test_capability_registry.py tests/test_gateway_report_projection.py tests/test_front_bootstrap_lock.py -q --tb=short
```

Coverage includes numeric-ID drift and protocol/name/endpoint mismatch; raw SQLite INSERT/UPDATE guards; retention but public rejection of bad legacy history; forged execution timestamps; measured publication-vs-execution time; current connection changes; canonical per-database identity resolution; retired seeds refusing before database access; managed URLs requiring a real version; warmed caches losing unrelated report counts/grades; and execution filters rejecting healthy-only/expired evidence.

The final related run passed **77 tests** covering the report-binding regressions, both updated menu cases, task-update security and operational observability. A final separate contract-scope regression also passed: authentic contract reports remain stored but cannot become execution verification. Earlier overlapping runs passed 128, 122 and 68 tests; these are not added to a unique total. Root consolidates the final browser/API/security runs.

The first direct browser launch was blocked by the macOS sandbox MachPort permission. Root separately ran the authorized isolated browser suite. The native PostgreSQL rehearsal could not run in this interpreter because the required driver was unavailable; the reviewer regenerated the explicit catalog and confirmed `--check` reports no difference. This is source/fixture compatibility evidence, not a live PostgreSQL cutover test.

## Remaining operating action

The updated source needs the user's normal server restart/deployment to become active. Do not rerun old seed batches as a remediation step. Review existing bad reports administratively before any separately authorized repair; none were deleted or migrated here. Verify current deployed API/card/filter behavior and SQLite guard presence after the authorized restart.
