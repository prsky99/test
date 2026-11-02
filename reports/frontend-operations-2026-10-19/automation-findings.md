# Automated operations: 2026-10-19

Window: **00:00 inclusive to 11:40 exclusive KST**, equivalent to 2026-10-18 15:00 to 2026-10-19 02:40 UTC. This is an eleven-hour-forty-minute window, not a full day. The final read transaction began at 11:44:08 KST; mutable queue/catalog snapshots are explicitly labeled below. SQLite was opened with `mode=ro`, `query_only`, and a read transaction. No service lifecycle action, operational write, or external probe was performed.

## Executed activity

- **433,555 persisted health checks across 95,857 distinct resources**, averaging 10.32 checks per second. These are automatic upstream catalog checks, not frontend page requests or customer task executions.
- By protocol: A2A 80,963 checks (42,435 healthy; 4,327 reachable; 34,201 fail), MCP 195,573 (115,137 healthy; 60,977 reachable; 19,459 fail), x402 157,019 (134,771 healthy; 9,310 reachable; 12,938 fail). `reachable` does not prove usable task execution. In particular, x402 protocol HTTP 402 responses are often recorded as healthy protocol handshakes; these are not frontend payment failures.
- **1,617 completed per-source crawl records: 1,612 successful and 5 failed (99.69% recorded source-pass success)**. Each of the three sources has 539 records; all five failures were MCP registry ReadTimeouts. Collector logs contain 539 pass starts and 538 pass-done messages; per-source database records and whole-pass log messages have different granularity and are not added together.
- Successful crawls recorded 229,107 seen rows, 597 new-resource events, 18,271 changed-resource events, and 882 deactivations. Events are not unique providers. One x402 full crawl completed at 02:17:54 KST: 26,741 seen, 404 new, 5,768 changed, 882 deactivated, 881.6 elapsed seconds. Other recorded successful passes were incremental.
- Crawler warnings show 22 ReadTimeout retry messages and 5 upstream server-error retry messages. Five MCP passes exhausted recovery. The current loop applies a fivefold minimum-gap backoff following any source failure (`collector/agent.py:118-131`); retries use exponential delays (`gateway/crawler.py:241-280`).
- Collector capability/A2A logs report 27,401 checked items (24,637 A2A, 2,764 MCP), 204 `trial_ok` and 149 `trial_failed` outcomes. These are automatic probe/trial outcomes, not customer task execution counts. Authorization discovery checked 77 items. Chain/host discovery logged 12,720 resolution attempts and 8,460 fetch failures; their exact upstream causes require a separate per-source investigation.
- **47 logged customer-request rescans**, with all reported counters (`checked`, `intros`, `offers`, `usage_updates`, `expired`) zero. The scheduler existed, but these rescans did no customer-request work during this window.

## Configured automation versus actual delivery

The current scheduler invokes workflow work every five seconds, and purpose-scoped task-watch work on the main scheduler loop (up to thirty-second sleeps); these intervals are configuration/code, not proof of work execution (`gateway/server.py:69-94`).

- No workflow runs, workflow deliveries, connection-automation admissions, or workflow-maintenance events were created in the fixed window. At inspection, there were no workflow schedule rows, connection-automation grants, reliability evaluation plans, or evaluation jobs.
- Two task-update events were created in the window, both **manual polling / ready**, with zero send attempts. At inspection, active watches comprised two polling destinations and one browser destination, plus one revoked polling watch. The two ready events do not prove native browser notification delivery or user consumption. Task refresh is separate from outbound delivery in `concierge/task_updates.py:534-565`.
- Four public-front initialization markers occurred at 00:21:23, 08:35:56, 09:26:42, and 10:56:43 KST. Matching SSL scheduler initializations were recorded. These markers support process initialization activity; they do not establish four customer-visible outages or the restart actor.
- Five warnings stated operational metadata recording was unavailable (00:07:27, 00:36:07, 09:10:20, 10:20:40, 11:21:47 KST). Operational journal totals should therefore be presented as observed records, not a guaranteed complete census.

## Priority 1: the vector queue can remain idle behind an ineligible head

**Observed data:** 113,915 open vector jobs at the 11:40 cutoff, reconstructed from job lifetime timestamps (`created < cutoff` and `finished IS NULL OR finished >= cutoff`). There were 124,808 jobs created within the fixed window, with zero recorded claim attempts across those rows. At inspection, all retained pending/superseded jobs had zero attempts; current vector provenance contained zero rows while the physical legacy vector table held 78,924 rows. Physical legacy rows must not be presented as current indexed coverage.

The oldest current pending job inspected at 11:42:45 KST pointed to an inactive resource. Current source selects the oldest job before checking resource eligibility (`legacy_vector_index.py:528-536`). `_resource` rejects inactive, retired, or quarantined resources (`legacy_vector_index.py:438-444`); rejection leaves the job unchanged. `RagPipeline.step` requests one job and breaks immediately when that claim returns empty (`gateway/rag.py:522-532`). Consequently, the same ineligible head can produce repeated `idle` results despite eligible pending work.

**Offline proof:** `PYTHONPATH=. .venv/bin/python reports/frontend-operations-2026-10-19/reproduce-vector-head-blockage.py` completed successfully against an in-memory synthetic database with no provider calls. Three successive pipeline ticks returned `idle,count=0`; all job attempt counters remained zero. Explicitly excluding the inactive head allowed the eligible job to be claimed. Results are saved in `vector-head-blockage-result.json`.

This proves the source mechanism and closely matches observed data. A live-process trace is still required to prove it is the sole runtime cause; installed dependencies or on-disk source alone do not prove which code a running process loaded.

Recommended change: claim eligible current jobs before applying the bounded limit, and safely terminalize or bypass obsolete/ineligible heads while preserving generation, provenance, authorization, and fence checks. Add regression cases covering inactive, retired, quarantined, deleted, and stale-generation heads before eligible work. Monitor successful claims/indexed rows per minute, oldest eligible pending age, current provenance coverage, and an explicit blocked/disabled state instead of treating all empty claims as idle. Validate this on isolated data before any authorized production rollout.

## Priority 2: health-check staleness is concentrated on large hosts

The final 11:44:08 inspection snapshot, evaluated against the fixed 11:40 threshold, showed 4,282 A2A and 18,002 x402 active resources more than one hour past `next_check_at`; MCP had zero. More than two hours overdue: A2A 3,018 and x402 17,882. These are after-cutoff state snapshots, not reconstructed historical queue totals.

An earlier 11:42:29 snapshot showed all 4,317 A2A items more than one hour overdue concentrated on one host; 17,910 of 18,032 x402 items were on one host. The oldest x402 due timestamp in that snapshot was 2026-10-17 20:39:58 KST, illustrating substantial stale coverage despite high overall probe throughput. Hostnames and resource identities are intentionally omitted.

Current code reserves hosts, caps per-host batch admission, and spaces work (`collector/health.py:315-334`); normal intervals also scale with host size, while early failures use the short retry interval (`collector/health.py:275-285`). Those protections reduce upstream pressure, but high-cardinality hosts can remain stale for much longer than smaller hosts.

Recommended change: measure age and coverage by protocol and host, allocate host-aware budgets, coalesce probes only where endpoints share equivalent evidence, and adapt retries/circuit breakers to host failures. Preserve upstream rate limits rather than blindly increasing concurrency. User-facing verification freshness should use factual timestamps; HTTP reachability alone must not imply task success.

## Priority 3: improve operation observability and source isolation

- Repair or explain the operational metadata unavailable warnings; expose completeness flags and a dropped-record count so conversion/execution dashboards do not silently undercount.
- Persist a bounded worker heartbeat with last tick, last claim, queue depth, oldest eligible age, and terminal result. Current successful scheduler invocation without customer work or current vector publication is insufficient evidence of useful automation.
- Isolate registry failure backoff by source so five MCP failures do not unnecessarily slow independent sources. Add bounded jitter and clear timeout/retry metrics.
- Reduce repeated unsuccessful discovery work with host-level failure caching/backoff, preserving planned rechecks for recovery. The resolution log's 8,460 fetch failures warrant target-level classification before changing intervals.
- Record reasoned startup/deployment events and a non-sensitive build identifier to distinguish intentional restarts from crashes and to connect observed behavior to loaded code.

## Scope limits

Mutable catalog state was read after the fixed cutoff and may have improved or changed while analysis ran. Protocol-kind joins use the current resource kind. Existing physical vectors do not prove current provenance or the actual ranking used in a served response. No new availability, security, or browser regressions were executed because this task is read-only operational analysis and makes no frontend/source change. Category logs are analyzed once; `all` and console duplicates are not added to their counts. Detailed sanitized metrics are in `automation-metrics.json`.
