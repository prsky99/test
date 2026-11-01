# Operational observations (R-02)

Internal implementation contract · 2026-10-18 · source implemented; deployment verification requires the user's next terminal restart.

`agent_market/observability.py` adds a bounded, best-effort metadata journal to the existing catalog Store. Frontend and admin processes using the same database can inspect the same records. This journal is an observation layer; it does not schedule, resume, bill, or authorize work.

## Counting and timing

Independent published-connection automation uses the fixed `workflow_automation`
operation source. Provider attempts keep their existing workflow source labels;
the label itself never grants execution or future-input-sharing permission.
See [automation](WORKFLOW_CONNECTION_AUTOMATION.md) and the separate
[read-only storage observation](WORKFLOW_STORAGE_OBSERVATION.md). New backend
source still requires the user's normal restart and operating acceptance.

- **Recommendation:** one task search performed by fast Chat. `matched` and `no_match` are separate; greetings and details are excluded. Selected resource metadata records server selection. It does not record a human click or connect a visitor's searches into a conversion funnel.
- **Execution:** one registered-agent execution through Testbench, the managed gateway, or the legacy proxy. Admission denials are operations with no dispatched attempt. Format demos and protocol discovery/handshakes are excluded.
- **Workflow:** one accepted saved run. Provider steps are attempts within that run. Idempotent replay and status polling do not add operations. Public, admin, schedule, and event sources are separate metadata labels; they confer no permission.
- **Delivery:** one internal event/destination send. Retries add attempts to the same operation. `accepted` means transport acceptance, not recipient receipt, native browser confirmation, or advertising permission. Workflow delivery has a separate operation linked to its parent run. Existing destination verification, consent, binding, and retry policies remain authoritative.
- **Attempt:** one prepared provider step or send. `dispatched` means the adapter entered its tool/message/probe/send boundary. DNS, TLS, policy validation within a courier, or network failure can still prevent bytes from reaching the recipient. It is not proof of provider receipt. Individual handshake/poll HTTP exchanges are not additional business attempts.
- **Timing:** `elapsed_ms` is observed wall time for an operation/attempt. `dispatch_to_result_ms` covers the observed adapter round trip when a result is captured. Neither measures provider CPU time or a pure provider-only duration. A timeout without a confirmed result leaves round-trip timing unmeasured.

The admin response separates counts by kind/status and exposes prepared, dispatched, and uncertain attempts. Retries are not added to successful logical-operation counts. A recovered delivery may have one accepted operation plus an earlier unknown attempt. Do not combine recommendation, execution, workflow, and delivery into one success-rate denominator.

## Uncertain outcomes and idempotency

Operations and attempts have independently generated opaque references. Saved runs and delivery events derive stable references only from internal identities. HTTP trace headers cannot select them. The public support reference is a locator, not authentication or an authorization capability.

Final operation states use a compare-and-set update. Duplicate callbacks do not add final events; a late different attempt result does not rewrite the earlier result. A dispatched timeout/network failure is unknown rather than a confirmed failure. Managed workers still running after the request deadline retain their existing execution slot; their trace objects are detached when the request ends, preventing late metadata writes or retroactive success.

Admin queries project overdue unfinished observations as unknown: recommendation 30 seconds, execution 120 seconds, workflow 300 seconds, delivery 48 hours. This is explicitly marked `observation_stale`; stored state is preserved. The projection does not recover a worker or reconcile an external side effect. Durable execution, shutdown/recovery guarantees, fencing, checkpoints, and outbox remain R-05 work.

## Data and access boundaries

Three additive tables contain only bounded metadata:

- `platform_operations`: opaque identity, fixed kind/source/protocol/status/error, public numeric resource/workflow IDs, optional parent operation, and timestamps/duration.
- `platform_attempts`: opaque identity, operation, atomic ordinal, fixed protocol/status/error, resource ID, timestamps/duration, and optional transport/protocol booleans.
- `platform_observation_events`: unique event key, operation/attempt references, fixed event/status/error, and timestamp.

No prompt, output, wire body, provider/destination URL, tool name, visitor/session/profile, IP address, consent record, token, credential, run key, or personal contact is copied into these tables. Historical operations are not backfilled.

`GET /admin/api/observations` requires authenticated superadmin access through the existing session/system-admin credential boundary. A local dashboard header alone does not grant access. The response is `Cache-Control: no-store`. Filters accept 1–168 hours, 1–50 operations, and a strict `ex_` plus 24 hexadecimal-character reference. The admin reader uses a read-only connection and a consistent read transaction. References/values are escaped in the UI.

The Errors menu contains **공통 실행 추적**. Detail/history opens a centered native dialog with keyboard dismissal. Automatic list refresh does not replace or close the open detail. Detail is a snapshot; close/reopen to refresh it. Logout clears the dialog and invalidates pending UI responses.

## Storage, retention, and failure behavior

Startup creates tables/indexes idempotently without changing business columns. File-backed observation writes use short-lived independent SQLite connections with a 50 ms busy timeout, avoiding contention on the catalog Store reader lock. The in-memory test path uses the existing Store lock, skips an active caller transaction rather than committing it, bounds lock acquisition to 20 ms and SQLite busy wait to 50 ms, and restores the business connection timeout afterward. This is not a hard total request latency guarantee.

Retention targets seven days, with incremental deletion of at most 200 expired operations on each new operation. At the 20,000-operation cap, up to 200 oldest finished observations are removed; active records are not evicted for capacity. Each operation admits at most 100 attempts. Related attempt/event metadata is deleted in the same transaction; catalog/business records are untouched. An idle database can retain expired metadata until new work triggers pruning. This is not a guaranteed seven-day deletion deadline.

Missing records from contention, storage failure, limits, or pruning cannot be reconstructed or included in a complete denominator. Writes are best effort and do not block valid business execution on recording failure. A fixed warning and process-local failure count expose recording failure without logging exception details. The admin response always states `coverage_complete: false`; aggregate health/complete telemetry coverage is not yet implemented. Do not call these observations a billing ledger, complete analytics, or an SLA result.

## Deployment and restoration

The user operates both servers. Do not start or restart a project server automatically. New tables are initialized when updated frontend execution components start; the admin can report unavailable until then. Both processes must use the same catalog DB for shared lookup. No production schema migration was manually run during development.

The isolated regression verifies repeat initialization, a separate read-only connection, reopening, and SQLite online `Connection.backup()` restoration with catalog and observation records preserved and `integrity_check=ok`. It does not copy a live database file or exercise production disaster recovery. Existing backup/key handling policies still apply. Rolling back application code leaves additive tables in place; do not drop business data or restore upstream URL exposure.

Evidence: [R-02 implementation and security regression](../reports/advancement-r02-2026-10-18/README.md), `tests/test_operational_observability.py`, `tests/test_operational_observability_browser.py`. Next: deploy/smoke R-02, then R-03 versioned agent/binding/profile contracts, capability evidence, and readiness. Full G0 remains open.

R-03 follow-up: a live successful R-02 call left a running observation under catalog lock contention. The independent file-backed writer and held-reader regression above address the source path. The subsequent user restart verified a normal real news request with a matched succeeded/finished shared record; authenticated live admin lookup remains pending. R-03 execution evidence is also produced. See [connection evidence contract](CONNECTION_EVIDENCE.md).

R-04 adds persistent admission/dispatch controls and signed workflow authority. An observation storage no-op does not bypass controls; a detached attempt rejects a new dispatch without accessing storage at that boundary. These are execution safety controls, separate from the best-effort journal. See [execution authority](EXECUTION_AUTHORITY.md); next implementation is R-05 durable execution/recovery, with full G0 still open.

R-05 separates authoritative execution state from best-effort observation metadata. `DurableRuns` owns leases/fences, prepared/dispatched attempts, signed checkpoints, completion/outbox transactions and recovery events. Private recovery lookup does not return checkpoint bodies or credentials. A killed worker can leave an observation incomplete even when durable state is reconciled; do not substitute the journal for ownership/replay decisions. See [durable workflow contract](DURABLE_WORKFLOWS.md) and the [R-05 report](../reports/advancement-r05-2026-10-18/README.md).
