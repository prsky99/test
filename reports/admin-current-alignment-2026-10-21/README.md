# Administrator alignment with the current frontend and PostgreSQL

Date: 2026-10-21 (Asia/Seoul)

## Result and operating state

Source fixes and isolated verification are complete. The user restarted the operating server on 2026-10-21 at 10:50:33 KST. Subsequent GET-only operating checks confirm that the revised administrator overview, current recipe cards and PostgreSQL statistics are loaded. The agent did not stop, restart or replace the server, change customer records, or issue execution permissions. Individual staff browser acceptance remains separate from these API checks.

### Operating restart verification

See `operating-smoke.json`. Overview returned HTTP 200 in 3.692 seconds on the first measured request and 0.012 seconds on the immediately repeated cached request. The correct administrator page (`/admin/ui`) returned 200 with the live recipe renderer and CSP. The preliminary `/admin` probe returned 404 because it is not the configured UI route. An unauthenticated overview request returned 403 as expected.

All 14 authenticated/public data reads in the initial sweep returned 200. The four available registered recipe bindings and three template IDs agree between the public frontend and administrator APIs. Closely timed catalog snapshots also agree: 124,748 cataloged, 96,260 reachable, and 124,498 with a status check. These counts continue changing with collection. Index diagnostics identify PostgreSQL; all eleven recorded source fingerprints still match the verified sources.

No overview HTTP 500 was found in the reviewed post-restart log interval. Repeated collector capability-bundle `invalid_parameters` warnings and an operational metadata recording warning remain visible; this administrator verification does not certify those separate ingestion/observability issues resolved.

## Findings and fixes

1. **Overview HTTP 500:** operating logs identify `overview_data -> vec_stats` and a PostgreSQL statement timeout. The publication query underestimated correlated generation/owner predicates and selected extensive nested-loop lookups. A materialized metadata projection retains every generation, current owner, job status, resource admission, model descriptor and vector-byte hash condition while avoiding that plan. A bounded operating read-only comparison timed out at four seconds with the old query; the revised query completed in 3.264 seconds. This is one diagnostic sample, not a latency SLA or a comparison of immutable catalog counts.
2. **Optional diagnostics blocked the whole dashboard:** vector statistics now have an independent read transaction and a bounded 60-second cache with explicit capture time/staleness. Failure is represented as unavailable, without a fabricated zero or 100% completion. Other overview data remains available. A primary overview storage failure returns a bounded 503 response. Independent menu navigation no longer depends on first loading overview diagnostics.
3. **Frontend/admin counts differed:** the overview now reuses the current Pearl public catalog and execution-summary projection. Catalog totals, protocol charts, reachability observations, status-check coverage and the 24-hour execution totals share those definitions. Legacy trial flags no longer stand in for current successful executions. Operational retired-excluding category/maintenance information remains separate and labelled. Customer-request totals include interests, inquiries, cancellations and privacy requests.
4. **Stale operating descriptions:** PostgreSQL statistics no longer describe the engine as SQLite/Apple Silicon. Fixed throughput and unconditional lane-running claims were replaced with measured recent check throughput and actual collector state. Unavailable statistics retain an explicit missing-data display.
5. **Administrator Testbench lagged the frontend:** removed the four invented negative-ID presets and fixed successful response generators. Guided cards now load the same current recipe bindings as the public Testbench. Missing or unavailable bindings are disabled. An old negative simulation ID returns not-found instead of a fabricated successful execution.
6. **Owned agents incorrectly used their public HTTP URL:** owned Testbench calls now use the existing managed proxy/local dispatcher. Stored schema checks, input validation, invocation control and execution evidence remain enforced. Refreshing an owned tool specification uses its registered local schema. Provider failures no longer advertise guaranteed-success examples. The existing three active owned workflow templates are shared by the frontend and administrator APIs.

## Verification

- **217 unique tests passed**, with zero unresolved failures in the effective result set. See `verification-summary.json` for case-level evidence and deduplication.
- **102 native PostgreSQL GET paths** exercised using a disposable Unix-socket cluster, a synthetic staff identity and a synthetic workspace: 97 returned 200; five correctly rejected missing input/context with 400/422. No 5xx responses. Parameterized execution/release/delivery paths are not all exercised by this menu-read sweep.
- **27 native PostgreSQL test cases** passed, including current owned recipe bindings, native query parity, read-only boundaries, session revocation and vector-byte tamper exclusion.
- Real Chromium checks cover administrator menus, CSP, hostile markup, private-session changes, cache isolation, polling/backoff, optional-diagnostic failure and navigation without overview. A click journey selects a current owned recipe, changes its input and runs the local agent successfully.
- All four owned Testbench recipes execute the real adapter implementation against controlled source responses; disabling invocation prevents source dispatch. Current frontend and administrator template IDs agree for all three active templates.
- **237 public frontend files:** zero content-policy violations. Public frontend source/rendering was not modified by this change.
- Python parsing, JavaScript `node --check`, and Ruff F/E9 checks passed with existing unused-import/local-variable checks excluded. No dependency installation was required.

The initial combined run retained one obsolete negative-ID expectation and two Chromium sandbox launch errors. The expectation was updated to a real registered fixture; only the affected tests were rerun with the required browser execution permission, and all three passed. Initial XML/logs are retained; `affected-recheck.xml` supersedes those results. Subsequent overview-only rendering changes passed the two affected browser cases in `overview-browser-final.xml`.

## Secure coding and dynamic security scope

Reviewed bound SQL values/fixed identifier allowlists, authentication before caches, no-store responses, unavailable-data handling, output escaping, removed fabricated results, and local dispatch admission/kill-switch enforcement. Dynamic API/browser cases exercise unauthenticated/cross-origin denial, individual-session isolation/revocation, hostile inputs, CSP and XSS rendering. Operating credentials were neither exposed nor replaced.

Ruff's security scan remains in `security-static.json`: 23 S608 findings on source-owned SQL construction and 13 broad-exception/continue findings (S110/S112). The SQL sites use fixed fields/orders/predicates or generated placeholder counts with bound caller values; the scan cannot infer those boundaries. Broad exception warnings remain visible for existing fallback, logging and request-parser code. These scanner warnings are not a claim that every possible vulnerability has been excluded; a separate Bandit installation/full penetration test was not performed.

## Remaining acceptance and limits

- User-controlled restart and operating overview/Testbench/workflow/customer-request read checks are complete. No additional restart or database migration command is required for these changes.
- Individual staff browser interactions, workspace management and subscription/credit actions were not exercised against operating customer data in this restart check. Their isolated regression evidence remains recorded above; configured machine access was not used to bypass individual-session requirements.
- Native menu tests use synthetic data; Chromium uses isolated application databases and controlled source responses. They do not certify every historical operating record, every parameterized detail/action, external source uptime, financial transactions or large-scale concurrent load.
- No live external agent/data-provider request was made for acceptance, and no real customer data was changed. Operating frontend/public caches can have different capture times; compare equal definitions and displayed timestamps rather than expecting independent requests to be an atomic snapshot.

Evidence: `native-menu-reads.json`, `native-postgres.xml`, `backend-regression.xml`, `affected-recheck.xml`, `overview-browser-final.xml`, `browser-regression.log`, `live-recipe-browser.log`, `source-hashes.json`, and the browser screenshots in this directory.
