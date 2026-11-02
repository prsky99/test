# Catalog and recommendation operations — 2026-10-19

Window: 00:00–11:40 KST (2026-10-18 15:00–2026-10-19 02:40 UTC). Read-only SQLite connections used `mode=ro` and `query_only`; no server, scheduled job, database, or network execution was started or modified. Aggregate evidence is in `catalog-metrics.json`. Resource state was observed around 11:42 KST and is a snapshot, not reconstructed historical state; event queries use the declared window. Independent short queries can differ slightly while collection continues.

## Actual activity and available supply

- 2,481 resources were first recorded today: A2A 1,890, MCP 187, x402 404. Of these, 1,860 A2A resources came from ERC-8004, so most new supply reflects registry ingestion rather than proven task completion.
- The catalog snapshot held 118,016 resources: A2A 32,629, MCP 33,922, x402 51,465. Active resources totaled 113,751; 92,951 were active and `healthy`/`reachable`.
- 433,555 health-check records fall in today's window; 66,598 were `fail`. The observed healthy/reachable share is 84.64% overall: A2A 57.76%, MCP 90.05%, x402 91.76%. These are endpoint-check outcomes, not user-task success rates. The same endpoint can be checked repeatedly and healthy/reachable do not imply execution success.
- Of 36,049 active healthy/reachable x402 resources, 7,856 (21.8%) had no `last_ok_at` within the previous 24 hours. Health labels alone overstate fresh supply.
- A conservative reproduction of non-task selection gates leaves an **upper bound** of 77,147 resources before task relevance, current connection version/schema, and the final registry failure check: A2A 25,548, MCP 25,910, x402 25,689. This is not a count of recommendable or callable agents. Only 697 have a selected successful-verification timestamp within 24 hours: A2A 62, MCP 608, x402 27. Some of those timestamps come from legacy reports whose integrity is discussed below.
- The A2A upper-bound supply is highly concentrated: 21,875/25,548 (85.6%) are `docs_knowledge`; web search has 209 and travel/maps/weather 87. A2A-default chat can therefore have plenty of listings but little task-specific fresh execution evidence.
- Actual capability evidence recorded today: MCP execution 173 successes and 67 failures (72.08% of 240 evidence records succeeded), covering 166 success resources and 63 failure resources with overlap possible. x402 has 17 transport records (2 successes, 15 failures), not execution records. No A2A execution records appear in this capability-evidence table for the window. Absence here does not prove no external/manual execution occurred.
- Current unexpired capability eligibility exists only for MCP: 267 succeeded and 105 failed. Among upper-bound supply, 263 retain unexpired succeeded execution eligibility. No contract-scope capability evidence was found.
- No `feedback` or `agent_outcomes` records were created in today's window. All-history feedback is one failed rating; all-history outcomes are three failures. There is no meaningful customer task-success denominator here.

## P1 — report evidence is disconnected from live catalog identity

Today's 126 newly created test reports are exactly 42 per protocol. All 1,172 historical reports are marked successful, and none have `executed_at` or `evidence_scope`. Today's report methods include discovery, initialize, tools-list and HTTP 402 challenge checks, which must not be presented as successful user-task execution.

The report data has a confirmed identity-binding defect:

- 84/126 today's reports have a protocol different from the linked collector resource: 21 A2A reports point at MCP resources, 21 A2A reports point at x402 resources, and all 42 x402 reports point at MCP resources.
- All 126 resource IDs exist in the active collector database. None of the 126 report agent names exactly matches the linked collector resource name; exact name inequality alone is not decisive, but concrete examples prove unrelated identities. Report #1172 describes **Autoblogging.ai**, while its `resource_id=45308` is **WHOIS** in the collector database.
- In the stale `gateway.sqlite3` catalog, all 126 kinds match and 88 report names match exactly. This strongly supports cross-database numeric ID drift as the cause; it does not establish which process originally chose those IDs.
- Managed gateway URLs are intentional: all reports store `/api/gateway/{kind}/{id}`. Their inequality to upstream catalog URLs is expected and is **not** used as evidence of incorrect binding.

A read-only reproduction using the current source confirmed that the candidate SQL for the task `whois` attaches the successful Autoblogging.ai report #1172 to WHOIS #45308, and `public_report()` accepts this pair. The report's `connection_version_id` is null, so the optional version mismatch guard does not reject it. This demonstrates incorrect candidate attribution and public projection; it does **not** establish that a real chat returned this resource, because later relevance/current-evidence gates still apply.

Source evidence:

- `agent_market/concierge/selection.py:79` joins by numeric `resource_id` plus kind without checking the subject binding. `:125–151` converts report success and creation time into verification priority; `:171` checks connection version only when supplied.
- `agent_market/concierge/report_projection.py:79–87` checks ID and kind, then accepts the historical URL as another replaceable binding. It does not validate the report subject against the current connection version.
- The actual report IDs created today, 1047–1172, match static records in `scripts/insert_batch351.py` through `scripts/insert_batch392.py`. `insert_batch392.py:15,19–36` sets current creation time and hardcodes subject, success, status, latency and wire data. `:380–409` writes identical numeric IDs into both databases without resolving a per-database subject binding. These insertion scripts perform no network probe themselves. Separate prior probes cannot be inferred from their success labels.
- `scripts/seed_scheduled_reports.py` similarly defines static records and writes them, but it is not the source of today's 126 IDs. Do not attribute today's insertion schedule to that script without independent scheduler/log evidence.

Recommended correction: resolve the exact live resource by canonical subject/binding and immutable connection version before report insertion. Require measured execution start/finish, scope, operation reference and artifact digest for executable verification claims. Quarantine the 84 protocol-mismatched reports and review all 126 current-day reports; retain editorial/imported reports with explicit provenance outside the successful execution denominator. Rebuild public report projection and ranking metadata from validated bindings. Never copy database-local numeric IDs between catalogs.

## P2 — catalog size and verification freshness need different metrics

`selection.py:150` ranks successful verification first, then timestamp, recent activity, grade, score and reliability; protocol is a candidate filter. Safety, health freshness, latest failure, endpoint and relevance gates exist. This is a stronger basis than the legacy weighted ranking module and should remain the documented public behavior.

However, an endpoint with recent health but no successful execution can still enter the fallback supply. A2A has very little current execution evidence despite being the default protocol. Report timestamps also fall back to report publication time. Prioritize A2A task execution checks, common user task coverage, and failed/unverified MCP retries before adding more near-duplicate registry listings. Report separate counts for discovered, fresh reachable, schema complete, execution verified, and contract verified.

Legacy `trial_ok` cannot be treated as proof by itself: 9,789 active A2A, 4,581 active MCP and 37,679 active x402 resources have `trial_ok=1` with no trial timestamp. `gateway/store.py` contains a historical healthy-to-trial-ok backfill. Current selection mostly avoids assigning a success timestamp from untimed legacy flags, but dashboards and metadata must do the same.

## P2 — Home counts are a New York snapshot

`concierge/front.py:150–186` caches counts by **America/New_York midnight**, not KST and not a live count. The latest stored snapshot is 2026-10-18 04:00 UTC (Oct 18 13:00 KST): A2A 23,284, MCP 30,021, x402 42,903, total 96,208. Its construction filters `first_seen <= midnight` but uses health state at first computation, so it is not an exact reconstruction of historical midnight health. Label the timezone and snapshot time; expose fresh reachable/verified counts separately. Root analysis also identified fixed Home success/chart values; those must not be interpreted as measured operational success.

## P2 — storage load is material, with no integrity failure established here

At first observation, `collector.sqlite3` was 3,350,704,128 bytes plus 781,625,832 bytes of WAL. Later read-only page statistics attribute about 1.32 GB to resources, 0.917 GB to vector data, 0.299 GB to health records and 0.095 GB to FTS data, excluding indexes and other tables. There are about 7.19 million health records; oldest and newest span roughly six days. The collector source retains seven days and prunes daily (`collector/agent.py:29,263–266`). These figures indicate sustained write/storage load, not corruption.

The stale `gateway.sqlite3` has 64,213 resources and its latest observations are from Oct 17. It should not serve as the identity source for reports inserted into the current collector catalog. Consolidate operational ownership of one authoritative catalog and use immutable binding references across systems. Add disk/WAL size and checkpoint-age monitoring, bounded diagnostic reads and retention metrics. No live checkpoint, vacuum, integrity scan, backup or repair was attempted; no claim of database integrity is made from file existence or page counts.

## Practical priority order

1. Fix report subject/version binding and remove unmeasured reports from success/verification claims.
2. Replace fixed/public reliability counters with timestamped, scope-specific measured metrics and denominators.
3. Improve A2A execution coverage and relevant task coverage, then close stale x402 health gaps.
4. Track recommendation-to-detail-to-test-to-confirmed-outcome conversion using aggregate events; today's outcome tables provide no customer-success evidence.
5. Consolidate catalog identity and monitor database/WAL growth and collector retention without interrupting the user's server.
