# R-05/R-06 operational hardening — v1.10

2026-10-18 · source implementation and isolated acceptance complete; user restart and authenticated deployment smoke pending.

## Analysis and implementation order

The supplied review correctly identified primary-evidence lockout, a single-row editor, invisible delivery-grant revocation, fixed run-budget pressure, missing operational retention/reconciliation tools and incomplete routing migration rehearsal. Historical line numbers, PID 83439 and source test counts were not treated as current deployment proof. R-01–R-06 bounded source acceptance does not close full G0/G1. External effects are not globally at-most-once: an operator-approved new delivery may duplicate an externally accepted message whose acknowledgement was lost.

Implemented in this order:

1. **Repeated-primary failures:** configure/shadow still require current successful evidence from both agents. An approved signed canary checks primary active/safe binding, exact schema and unchanged approval without requiring its latest successful outcome; the alternative always needs fresh successful execution/contract evidence. Consecutive primary error/invalid/preflight failures no longer lock out later explicitly opted-in requests. Admission caps, one alternative per run and post-dispatch unknown refusal remain.
2. **Private multi-node editor and grants:** up to six explicit node/contract/alternative rows, full loaded-pair preservation, duplicate/unsafe backend rejection, exact revoked-grant counts and reapproval shortcut. A separate schedule target protects unrelated unsaved builder state. No delivery consent is preselected or inferred.
3. **Budgets and heartbeat:** public/apps/automation/default-admin total remains 25 seconds. Only an explicit current highest-admin manual request can admit a signed 60-second total/15-second baseline-node profile. Canary keeps nested 12/8-second limits. Original deadline and idempotent profile binding remain. Heartbeat reuses a thread-scoped short-timeout connection, closes it and tolerates bounded busy/locked pulses; durability is not lowered.
4. **Reconciliation and explicit delivery:** append signed CAS review statements with opaque references; never rewrite the original unknown. A retained successful result and original unknown delivery may receive one separately signed new event after latest not-received review, current verified inbox, specific permission and duplicate-risk acknowledgement. Current role, expiry, result/destination hashes, review and kill switch are rechecked. No provider rerun, old event reuse, automatic uncertain resend or unlimited resend chain. Unknown manual events can be reviewed.
5. **Retention and recovery inventory:** default preview, explicit maximum-20 batch, known terminal bodies after 14 days and selected metadata after 90 days. Apply takes the writer lock and refuses queued/running work or claimed/dispatched deliveries. Snapshot/checkpoint/archive integrity failures are held. Active/unknown evidence and replay/idempotency/consent/budget/delivery tombstones stay. A cooperative half-second check between runs is not a hard transaction-latency SLA. Restore writes a private capped `0600` inventory of IDs/states/counts and fresh-approval instructions; no URL/key/input export or automatic reactivation.
6. **PostgreSQL and security acceptance:** trusted source DDL, 27 state tables, full row/signature/quote/backslash round-trip, owner CAS, bounded canary admission and manual source-event uniqueness. Temporary Unix socket only; cluster cleaned up. Full application PostgreSQL adaptation/cutover remains separate.
7. **Remaining deployment gate:** user-controlled frontend/admin restart, authenticated highest-admin controls/policy/budget/recovery/reconciliation/retention-preview checks, then approved real-provider shadow/canary acceptance and R-07 work. This run did not activate production fallback or send live notifications.

Detailed contracts: [operations design](../../docs/WORKFLOW_OPERATIONS_HARDENING.md), [main design v1.10](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md), [structured plan](../../docs/platform-advancement-plan.json).

## Verification results and counting

- Existing initial workflow/fallback/recovery regressions: 87 passed.
- Broad entry point, `scripts/run_frontend_regressions.py`: 1,241 cases, initially 1,240 passed and one TLS test fixture failure. The fixture's single-segment recipient path collided with a generic `/{channel}` test route; changed to `/workflow/manual-results`. Product acceptance was not weakened.
- Corrected final boundary set: **225 passed**, including workflows, durability, fallback, authority, recovery/API, private SDK/browser, HTTP and TLS.
- Final operations set after manual-unknown review and idle/tamper retention guards: **48 passed**. It includes 38 core cases, nine private-browser cases and one actual controlled TLS case.
- Latest result per JUnit `classname`/`name` across the broad, final boundary and final operations runs: **1,255 unique passed, zero unresolved failed/error/skipped**. Overlapping runs are not added. The full broad suite was not repeated after the last scoped integrity changes; affected final operations paths were rerun.
- Public content check: **53 files, zero violations**; embedded HTML and extracted HTML synchronized. Seven public frontend/SDK/package implementation files retain their input hashes.
- Canvas: existing artifact updated, inline plan identical to JSON, TSX transform without warnings, original 14 AC tickets/10 R groups/four gates preserved. No claim of full Canvas host rendering.

Machine evidence: [verification](verification.json), [case reconciliation](test-reconciliation.json), [broad JUnit](final/regression.xml), [boundaries](final-boundaries.xml), [final operations](operations-final.xml), [PG rehearsal](postgres-rehearsal.json), [package preservation](public-package-preservation.json), [Canvas validation](canvas-validation.json).

Dynamic security scenarios use isolated catalogs/credentials, authenticated APIs, Chromium, controlled informational providers and real TLS recipients, independent processes, real SIGKILL, lease/late-owner checks, signature/scope tamper, role withdrawal, destination/result drift, kill switch, revision conflict, deadline, cancellation, unknown and replay boundaries. The TLS recipient intentionally accepts an original message then responds unsuccessfully; the original stays unknown and a separately approved new event can duplicate content. This demonstrates the disclosed risk rather than an exactly-once claim. Private dialog screenshots were visually inspected for centered, bounded layout; live administrator access was not bypassed.

## Secure-coding scope

Bandit scans nine changed Python modules: runtime, persistence, fallback, budgets, operations, maintenance, backup, dashboard and isolated PG rehearsal. **High 0, Medium 36, Low 18**, no scan errors. Every finding has an individual retained-warning rationale in [static triage](static-triage.json). The scan includes fixed internal maintenance/backup SQL construction, legacy private dashboard paths and controlled PG SQL/temp tooling. Request values are bound; caller-provided table/schema SQL is not executed. New budget/operations/runtime/fallback/persistence modules have no reported findings. Raw prompt/result/contact/secrets are absent from new public responses and private operation projections; private endpoints require current highest-admin authorization and no-store responses.

These results do not certify the entire platform or every provider. Lower-severity retained warnings were reviewed, not all removed. This scope differs from earlier reports, so warning counts should not be compared as a trend. Source hashes capture the verified implementation; no claim is made for later unrelated edits.

## Live observations and remaining limits

Normal read-only local frontend/admin UI GET returned HTTP 200 with CSP. The supplied old PID was absent; the observed current process was left untouched. An independent read-only SQLite connection found fallback disabled and zero policies. Evidence: [GET/process observations](live-readonly-verification.json), [control observations](live-control-readonly.json).

Under `AGENTS.md` the user owns terminal server operation. **No stop/restart/replacement, competing project server, direct live DB write/migration, live provider task, production retention apply, live manual send or production canary activation was performed.** New Python routes/schema need the user's frontend/admin restart. Fresh live highest-admin controls/policy/recovery inspection is still pending because no authenticated session was available.

Remaining acceptance: actual approved-provider shadow/canary cohort, full G0/G1, expanded-volume writer contention/retention and disaster-recovery/HA, whole historical public-artifact inventory, externally rehosted packages, hosted CI and full PostgreSQL Store/FTS/auth/collector adaptation. Compaction reuses SQLite pages; it does not automatically shrink the DB/WAL file. Retained unknowns and replay tombstones intentionally continue to consume space. Manual review is an operator statement, not cryptographic evidence of remote nonreceipt. Standard safety/auth/contract gates and unsupported protocol/credential/write/payment exclusions remain.

R-07 AI composition follows the deployment checks. This hardening does not implement or activate the composer, organization v2, commerce or support roadmap work.
