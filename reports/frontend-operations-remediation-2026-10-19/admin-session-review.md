# Administrative refresh security review and fixes

Read-only review covered measured Home aggregation/rendering, logging limits/redaction, the launcher, and administrative refresh/recording UI. Source fixes described below were applied without any live process, configuration, or database change.

## Fixed review findings

1. **Stale authenticated responses crossing a session change.** `api()` now captures token plus an internal session version, and checks them after transport and body parsing, including before handling 401/403. An old unauthorized response cannot clear a newer account's token. An old success cannot return its private body to a new account's renderer. Session changes discard the overview cache and keep the main administrative surface hidden until a successful refresh under the current session.
2. **Queued refresh crossing logout/login.** Queued manual refreshes carry their requesting session. The refresh finalizer discards old requests and old global-banner/success updates; a queued refresh from the current session may proceed after the previous single flight has drained.
3. **Detached child reads bypassing the single-flight/backoff boundary.** Each refresh tracks its current-session GET requests, including reads launched by loaders that handle errors locally. It waits for those requests before releasing the single-flight guard. Failed child requests cause backoff even when a child loader displayed its own error. Static/hidden/unauthenticated surfaces do not arm the refresh timer.
4. The parent task repaired reproduced log redaction holes for unquoted sensitive headers/assignments, byte-tuple header representations, URL userinfo, and raw exception values passed to the administrative log buffer. The original reproduced cases were rechecked successfully. A subsequent root-query-path redaction edge was separately reported to the parent task.
5. The parent task removed the stale Home loop/schedule claim and based historical protocol aggregation on immutable connection-version profiles. The measured Home period, outcome distinction, empty state, chart units and aggregate-only payload were reviewed; no visitor identity, endpoint, private operation reference, or request body is introduced by that summary.

## Validation

The browser regressions use an intercepted in-process administrative test app and synthetic accounts, delayed responses, isolated database data, and no production requests. New cases prove that old success/401/body-parsing results cannot cross sessions, queued old work is discarded, child security reads remain single-flight, and locally caught HTTP 503 causes refresh backoff.

```sh
REDIS_PORT=6399 .venv/bin/python -m pytest -q tests/test_admin_refresh_pacing_browser.py tests/test_operational_observability_browser.py tests/test_home_measured_verification.py
```

Result: **13 passed** in 14.77 seconds, including six refresh/session browser regressions; see `admin-refresh-review.log`. Local browser execution used the permitted isolated test environment. No running project server was launched or replaced.

Focused Bandit results are in `proxy-bandit.json`; no high-severity finding was reported. The remaining medium findings in the inspected security code involve fixed SQL fragments with parameterized values and a string-only test Redis namespace check. The parent task owns the consolidated final scan.

## Operational limits reported to the parent task

- A 20-MB rotating handler with five backups bounds newly written logs in steady state. On first rollout an existing oversized console can be renamed intact into a backup and remain larger until subsequent rotations. Existing evidence must not be described as immediately reduced to the nominal cap.
- The launcher's separate `.startup` stream remains a distinct, unrotated stderr/stdout destination unless the parent task adds a separate bounded path. Queue-overflow diagnostics can also reach it. This is separate from the managed logging queue.
- No source edit changes the already-running service. Application fixes require the operator's normal restart, with post-rollout checks. Private runtime settings and existing rules remain under operator control.
