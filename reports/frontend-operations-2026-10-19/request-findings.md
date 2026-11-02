# Frontend request and operational log analysis

Window: 2026-10-19 00:00:00 inclusive through 11:40:00 exclusive, Asia/Seoul (UTC+09:00). This corresponds to 2026-10-18 15:00:00 through 2026-10-19 02:40:00 UTC. Read-only analysis; no server, database, or frontend source changes. Later audit probes are excluded.

## Evidence and timing quality

The live process writes console/access records to `logs/agentcon.log`, with source-specific application records in `logs/<source>/2026/10/<source>_2026-10-19.log`. Source and console application timestamps are host-local KST: `agent_market/logger.py` formats local `asctime` and selects the file date with `datetime.fromtimestamp(record.created)`. Source `all` logs duplicate source-specific records and must not be summed with them. `gateway.log` is historical and is not the current live console.

The console snapshot is 6,868,383,258 bytes. Binary seeking to the midnight boundary and streaming the selected slice inspected 2,139,533,188 bytes and 9,308,465 lines. Application records cover 00:00:00–11:39:59. Uvicorn access lines have **no timestamp**; their time is inferred from the preceding dated application line. All 2,645 access records fall between adjacent application timestamps inside the window; no boundary-straddling access record was observed. The maximum adjacent bracket is 23 seconds, and 2,628 of 2,645 brackets (99.4%) are at most 5 seconds. These brackets are neither exact request times nor latency measurements.

## Actual traffic

- 2,645 HTTP access records: 2,335 admin path requests (88.3%) and 310 non-admin requests (11.7%). Route-family classification cannot prove the listener or a unique visitor.
- 2,201 requests (83.2% of all traffic) are local admin dashboard polling: `/admin/api/overview` 1,108 and `/admin/api/timeseries` 1,093.
- 2,363 access peers are loopback, 282 non-loopback. There are 83 distinct non-loopback network peers; this is **not** a user count because proxies, bots, and operators are mixed.
- Status totals: HTTP 200 = 2,498; 400 = 10; 401 = 24; 402 = 13; 403 = 64; 404 = 17; 405 = 17; 415 = 2. No HTTP 5xx or 429 was observed. HTTP success does not establish business completion or uninterrupted uptime.
- Home `GET /` = 69: 54 non-loopback HTTP 200, 1 non-loopback HTTP 403, 14 loopback HTTP 200. These are page requests, not 69 real users.
- Exactly four POST requests: `/` HTTP 415 twice, `/a2a` HTTP 200 once, and local `/admin/api/auth/login` HTTP 200 once. No POST to `/chat`, `/mcp`, `/api/test/execute`, workflow runs, or notification subscriptions was observed. The `/a2a` 200 alone cannot prove a recommendation or execution.
- Known public discovery requests include `robots.txt` 18, `sitemap.xml` 7, and agent-card discovery 7. Generic scanner paths and repeated local fixture routes mean public requests cannot be treated as customer engagement.
- Gateway GET requests: MCP 21 (15 HTTP 405 and 6 HTTP 400), A2A 7 (3 HTTP 200 and 4 HTTP 400), x402 17 (2 HTTP 200, 13 HTTP 402, 1 HTTP 404, 1 HTTP 405). Discovery, method errors, protocol rejection, and actual dispatch must be measured separately. These are machine protocol status facts, not product-interface copy.
- Repeated local requests to all-zero synthetic workspace/inbox references and unauthorized options endpoints indicate development/security checks on the live process. They must be separated from customers in analytics.

Hourly non-admin requests (KST): 00h 40, 01h 49, 02h 32, 03h 13, 04h 7, 05h 18, 06h 7, 07h 7, 08h 26, 09h 30, 10h 29, 11:00–11:40 52. The 11h bucket is partial.

## Security and attribution

`security_events` contains 32 scanner-probe events and 32 corresponding auto-jail events, representing 32 triggering incidents rather than 64 attacks. Probe families are 31 WordPress paths and 1 environment-file path. All 32 generated 900-second auto-jail warnings. No successful exploit is evidenced by these records.

Five security network peers appear; one accounts for 28 of the 32 jails. That peer belongs to an edge-proxy address family listed in [Cloudflare's official IPv6 list](https://www.cloudflare.com/ips-v6/). The provider's [official IPv4 list](https://www.cloudflare.com/ips-v4/) was also checked. The four remaining peers account for one jail each. Triggering user-agent families are 28 non-browser automation strings and 4 browser-like strings; browser-like strings do not prove a human.

This creates a material **attribution and collateral-blocking question**, not proof of a bypass. `SecurityManager.resolve_ip` relies on a configured trusted hop chain (`agent_market/concierge/security.py:264`), while `guarded_request` blocks the resolved address before checking routes (`agent_market/concierge/front.py:2063`). Verify the ingress trust chain and whether independent clients are sharing the banned peer. Do not blindly trust arbitrary forwarded headers or exempt every public proxy range.

A second observability gap is confirmed in source: the blocked-address 403 branch returns without calling `record_blocked`. Thus 64 HTTP 403 access records coexist with only 32 probe and 32 jail event records, and a blocked home request cannot be attributed from the security journal alone. Reporting a zero `blocked_ip_403` journal count as zero blocked requests would be wrong.

## Runtime and operational health

Four server-start markers recur at 00:21:23, 08:35:56, 09:26:42, and 10:56:43 KST. They evidence repeated process starts, with the runtime already active at midnight. Exact downtime, restart reasons, and availability percentages cannot be calculated from startup markers.

Five warnings state that operational metadata recording is unavailable and metrics may be incomplete: 00:07:27, 00:36:07, 09:10:20, 10:20:40, 11:21:47. These warn only once per journal instance (`agent_market/observability.py:82`), so five warnings do **not** mean only five dropped observations. Execution warnings show 15 x402 failures (13 `AUTH_REQUIRED`, 2 `UPSTREAM_PROTOCOL`). Reconcile these with `platform_operations`/attempt/event coverage; do not calculate an end-to-end success rate from the partial journal.

The console contains 9,280,092 DEBUG records, 25,603 INFO records, and 84 WARNING records. DEBUG constitutes approximately 99.7% of dated console records, mainly `httpcore.connection` and `httpcore.http11`. Current-day logging alone produces 2.14 GB by 11:40, while useful routed application logs are much smaller. The source's INFO/default logger controls do not sufficiently constrain the console handlers in the observed runtime.

## Prioritized improvements

1. **Restore trustworthy operational completion records.** Investigate short-timeout independent observation writes and writer contention; make dropped writes a durable alert/counter; reliably reconcile stale `running` operations after restarts. Validate request→dispatch→completion linkage using isolated data. Avoid using partial counts as service success KPIs.
2. **Validate the proxy/client attribution chain and collateral bans.** Confirm each trusted ingress hop, propagate only authenticated/controlled origin information, and ensure one proxy peer's scanner cannot deny unrelated legitimate clients. Add isolated integration tests for trusted/untrusted forwarded chains and shared-peer traffic.
3. **Reduce and bound console logging.** Raise `httpcore` verbosity to warning/info for normal operation, rotate/compress the live console with retention and disk alerts, and verify header/query/token redaction. Preserve structured application failure records and bounded temporary diagnostic logging.
4. **Separate customer, machine, admin, bot, and synthetic traffic.** Label requests at ingress or in structured internal telemetry, keep tests off the live process, and display customer funnel metrics independently of the 2,201 dashboard polls. Do not expose client identities in the product or report.
5. **Add complete HTTP observability and stable deployment evidence.** Include UTC timestamp, route template, listener/surface, status, latency, request correlation, and release identifier; exclude query values, visitor tokens, and raw payloads. Record all blocked requests with bounded aggregation and keep 403/401/405 distinct from 5xx. Log graceful stop/start reasons and use an external uptime probe for availability.
6. **Improve machine discovery and method diagnostics.** Investigate why MCP gateway requests are all rejected by method/protocol checks, and why customer-auth/public connection paths requested by checks are unavailable. Publish correct method/link guidance and test it against the deployed release before assuming a broken business flow.

## Limits

Access logs lack native request timestamps, latency, user-agent, referrer, release identifier, and browser experience. They do not prove real-user counts, conversion, LCP/INP/CLS, TLS edge availability, or provider protocol success. A reverse-proxy network peer is not an end-user identity. Absence of observed 5xx is not a complete availability guarantee. This analysis inspected logs, security aggregates, and related source; it did not inject attacks, run security regressions against production, change settings, or restart the service.
