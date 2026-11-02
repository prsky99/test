# Explore report history and count reconciliation

The administrator's 1,172 is a report-row count. It covers 1,113 distinct catalog resource IDs. It is not the number of currently discoverable agents.

A read-only snapshot on October 19 found 423 report rows bound to 422 distinct resources by the existing canonical subject check. Of these resources, 415 were active and healthy/reachable and seven were down. One extra trusted report row is a second report for the same resource. No trusted resources were quarantined. The public API separately returned 419 matching agents, 45 items, and `total_is_estimate=false` in 2.649 seconds. That live response and the database snapshot were taken at different times; their four-resource difference is not explained by this audit. A subsequent bounded protocol-specific request timed out after 15 seconds; no further public probes were made.

The remaining 749 report rows do not establish the current resource's identity:

- 472 use a numeric gateway path without a matching current connection version.
- 244 have the same protocol but a different name. All 244 also lack a matching full provider endpoint; none are a direct-endpoint, name-only rename.
- 33 have a different protocol.

Comparison with the original report database did not establish a safe bulk recovery. For 745 of the 749 rows, the original resource is missing (147), has the same protocol but another name (494), or has both another protocol and another name (104). The other four have a credible original subject: two no longer have a unique matching catalog key, and two have a unique matching key, protocol, and complete endpoint but a renamed target. The latter two could be reviewed for a separately audited historical rebind. No report or resource was changed in this investigation. A numeric gateway path alone cannot prove a provider endpoint or an actual execution.

The backend now treats `has_report=true` as a historical search over nonquarantined subjects. Both `eval_security='quarantine'` and `health_status='quarantined'` are excluded in SQL and rechecked against the current resource before counts and projection. Inactive, down, failing, unknown, and retired resources may appear only when a report passes the existing subject check. Ordinary Explore stays within the live catalog. Combining `has_report=true` with `verified=true` retains both the live boundary and current execution evidence requirements. Publication history never creates measured execution evidence or a report grade.

The response distinguishes the units:

- `total` and `total_unit='agents'` count distinct matching resources.
- `matched_report_count` counts trusted report rows for exactly the same search and filters.
- `historical_agent_count` counts matching agents outside the live catalog.
- `report_scope` is `history`, or `live` when current execution is requested.
- If the bounded candidate window is exceeded, the two additional counts are `null`; the existing upper-bound and window-limit flags remain explicit.

Historical cards include `active`, current `health_status`, and `catalog_status`. Identity checks, quarantine exclusion, protocol checks, current execution gates, and the finite native SQL boundary remain enforced.

The historical candidate query retains the report-ID semijoin and protocol subject predicate. On a read-only production snapshot it counted 1,080 coarse candidates in 0.0052 seconds and read its first 1,000 candidates in 0.0093 seconds. These are SQLite query timings, not end-to-end HTTP timings.

Validation: 83 focused identity/history/index/native-registration tests passed after the health-quarantine correction. The earlier broader run passed 107 application-store/native-boundary/inventory tests; two tests requiring an actual PostgreSQL driver/server were deselected. The finite catalog has 3,239 statements and 205 tables, including the current fixed schema-failure query. A subsequent embedded HTML/source change requires regenerating its source hash.

Supporting artifacts: `explore-report-counts.json`, `explore-report-name-drift.json`, `explore-report-provenance.json`, `explore-report-original-subjects.json`, and `explore-history-query-plans.json`. These contain aggregates and fixed SQL plans, without report bodies, visitor data, private bindings, or credentials.
