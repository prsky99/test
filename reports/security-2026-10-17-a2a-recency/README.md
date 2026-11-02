# A2A defaults and recent verified recommendations

2026-10-17. Working-tree implementation for the user's `stock news` and
`mcp stock news` scenarios. The user-operated server was not stopped or restarted.
Tests use isolated apps/databases, synthetic listings, intercepted browser traffic
and existing controlled transports. This report does not establish deployed parity.

## Behavior

- New requests with no named protocol default to **A2A**, including the Chat Auto
  option, REST/A2A discovery, MCP discovery tools and the admin simulator.
- A specific selector overrides question text. Otherwise an explicit A2A/MCP/x402
  mention filters the question. **Any protocol** deliberately searches all three.
  Protocol preference is independent of the transport used to call the concierge.
- `stock news` selects one eligible A2A match. `mcp stock news` selects one eligible
  MCP match. A subsequent `details 1`, alternative or outcome preserves the prior
  protocol; a new protocol-unspecified discovery question defaults to A2A again.
- No eligible A2A match returns `no_match`; it does not silently substitute x402.
- Relevant, safe candidates with successful test/execution evidence rank first,
  ordered by that successful verification's timestamp, then recent successful
  activity, quality grade, quality score/reliability and remaining stable ties.
  Older high-grade evidence cannot displace a more recently verified eligible
  lower-grade candidate solely because of grade. When no relevant successfully
  tested candidate is available, recent health evidence remains the fallback.
- Existing active/public-endpoint, failure, quarantine, grade-F and 24-hour
  availability gates remain. Timestamps are never rewritten to manufacture recency.
- Chat prepends new replies and scrolls to the newest reply. Home, Chat, page/social
  metadata, agent card, `llms.txt`, tool descriptions, admin simulator and persistent
  project guidance reflect the new defaults/order. Public copy/comments remain English.

## Verification

Final counts are recorded in `verification.json` and the adjacent JUnit files.
Full-suite runs include existing transport, notification, admin, frontend and
security regressions. Focused tests additionally exercise the exact two questions,
newer B vs older A evidence, explicit Any/x402 choices, no A2A fallback, structured
requests, unchanged follow-up scope, bad/ambiguous protocols and unsafe new candidates.

Real Chromium/CSP tests cover 390px/1280px views, newest-first DOM order, one result
per answer, explicit/default protocol selection, metadata, accessibility, reduced
motion, light/dark themes, escaping, private/commercial-content hiding, notification
controls and admin regression paths. Synthetic screenshots are included.

Public content checking, embedded/extracted HTML equality, JavaScript parsing and
Python compilation are checked. The installed-dependency audit is stored in
`dependency-audit.json`; static findings remain in `bandit.json`, including reviewed
SQL-construction heuristics rather than an assertion of zero scanner warnings.

Legacy tests that intend to exercise MCP/x402 now specify that preference instead
of relying on the previous unfiltered default. Ranking fixtures identify their
intended primary candidate with a real recent synthetic success record, matching
the new product policy. Dedicated default tests exercise unmodified Auto/no-filter
requests rather than masking the A2A behavior in a shared fixture.

## Limits and operation

“Recent” describes recorded successful verification/activity. It does **not** prove
that news articles returned by an external provider were published recently. This
service recommends a connection and does not fetch or rewrite stock-news articles
in its recommendation request. No new network or model call was added to that path.

Existing task-watch permissions are not migrated or widened: an explicitly chosen
Any/MCP/x402 watch keeps its scope. Historical Chat snapshots remain historical;
new replies appear before them. No production catalog, message or verification date
was edited for this change.

Restart the user-operated server normally to load the source changes. Live deployment
configuration and external provider output/deliverability were not tested. The
security checks establish their stated local scope, not a vulnerability-free or
production penetration-test certification.
## Recorded results

- Full regression: **892 passed**, zero failures/errors/skips (`regression.xml`).
- Focused API/security: **151 passed**; compatibility checks: **60 passed**.
- Final real Chromium regressions: **19 passed**, including both stock-news views
  and the normal cookie-selection confirmation flow (`browser-regression.xml`).
  These subsets overlap the full suite and must not be added to its count.
- Public frontend: **45 files, zero policy violations**; embedded/extracted HTML
  match, scripts parse and changed Python modules compile.
- Installed dependencies: **53 packages, zero known vulnerabilities returned** by
  the queried advisory service. This does not predict undisclosed vulnerabilities.
- Bandit: **0 high, 56 medium, 47 low warnings**. Medium findings include 54 SQL
  construction heuristics and two serving/public-bind warnings. The selection
  query uses a fixed report-time expression with parameterized values; protocol
  and fast-chat modules have no findings. Existing desk/store/query heuristics
  use fixed fragments/identifiers and bound values. Low warnings include existing
  exception handling, protocol labels and non-security jitter. Findings remain
  in `bandit.json`; they are not described as zero scanner warnings.
