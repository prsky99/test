# Restart acceptance and workflow heartbeat contention correction

2026-10-20 KST. The existing user-started server is listening locally on its
admin/frontend ports. No project server was started, stopped or restarted by
this task. The agentcon PID-file status alone was not used as server truth.

## Operating verification

Actual public-origin evidence is retained under
`../owned-agents-publication-2026-10-20/deployed-restart/`:

- Four owned Testbench examples are registered, available and completed through
  actual browser Run Now controls with HTTP 200 and execution_succeeded=true.
- Two additional owned MCP handlers returned real source-backed structured
  output. All six agent outputs checked here contained no literal Hangul.
- Three workflow ZIPs downloaded successfully. Each manifest uses the published
  workflow execution mode and https://agentconcierge.biz gateway. Package source
  includes the managed workflow run call.
- All nine public pages passed initial HTML title, description, canonical and
  JSON-LD checks. Root inspection explicitly requested text/html; the root's
  default JSON content negotiation was preserved.
- Sitemap, robots, llms guides, agent card, MCP manifest and social preview
  returned HTTP 200. Browser JavaScript errors: zero. Workspace link remains
  unavailable as previously requested. No search-indexing outcome is claimed.

Workflow completion was additionally checked using each fresh submission's
run_id and its in-memory capability. Those capabilities were never recorded.
The new runs exposed intermittent lease loss: a pre-dispatch run resumed and
then hit its original deadline; dispatched runs were correctly quarantined as
unknown, rather than replayed. These failures remain in the operating history.
`verification-confirmed.json` deliberately records completed=false. The earlier
browser report is retained separately and must not substitute for fresh-run
completion proof. No failed or unknown record was marked successful.

## Correction

- A busy heartbeat previously waited the regular two-second interval before
  each retry. Three consecutive busy samples can consume the eight-second
  lease even when the worker and external data sources are still running.
  Busy failures now retry after 200 ms, returning to the ordinary two-second
  cadence after success. Transient contention emits one bounded admin warning;
  other heartbeat database errors expose only their error type/name.
- Initial claim timestamps are captured after the database writer reservation,
  so time spent waiting for that reservation does not shorten a fresh lease.
  COALESCE still preserves the original deadline on resumed runs.
- Ownership validation captures current time after obtaining the writer
  reservation. A worker that expired while waiting cannot dispatch using a
  stale timestamp. Expired/replaced ownership and the original deadline remain
  authoritative. No lease length, total execution budget, fallback permission,
  security switch or uncertain-outcome retry policy was widened.

## Verification and rollout boundary

- 116 selected regressions passed, zero failures/errors/skips in 64.58 seconds:
  new consecutive-busy and writer-wait expiry cases, durable checkpoint/recovery,
  process-kill boundaries, operational controls, authority, runtime and the
  activated owned frontend browser/package journey.
- New tests pass Ruff; changed runtime/persistence modules pass Bandit with zero
  findings. The frontend policy checker remains clean. These are scoped checks.
- PostgreSQL statement metadata was regenerated; its consistency check is clean.
  Native PostgreSQL/DR acceptance was not repeated in this SQLite correction.
- `source.json` records the unchanged implementation/test hashes during the
  regression run. Previous 315-case publication acceptance precedes this fix.

The operating server still runs the pre-correction modules. The user must
restart the existing server from their terminal to load this correction; no
post-fix operating success is claimed before that restart. The isolated checks
prove the corrected busy-retry and expiry behavior, while a fresh operating run
is required to confirm the deployment under its current writer load.
