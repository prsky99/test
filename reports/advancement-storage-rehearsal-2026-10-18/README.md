# Storage retention, recovery and load rehearsal

2026-10-18 · v1.23 · standalone synthetic tooling, no operating database or server change.

The next planned coherent unit is complete: safe explicit CLI, current-schema mixed-purpose fixture, actual retention/authority/replay checks, bounded SQL contention, online backup/new-path quarantine, disposable-restored-copy physical compaction, security/API/Chromium regressions and design updates. Existing production tools were reused.

## Current verification

**845 passed / 83 new / failure,error,skip0** in one final frozen affected selection of **36 modules** (386.40s). This includes the new core/CLI/invariant/independent-review tests plus storage, durability/SIGKILL, recovery, authority, SDK/publication/automation, product proof and comparison, API/Chromium/TLS and existing PG state-table rehearsal. It is an affected selection, not a fresh full-platform suite. Historical v1.22 full-suite2,878 and overlapping focused/initial executions are not added. [JUnit](affected/regression.xml) · [log](affected/regression.log) · [case reconciliation](test-reconciliation.json).

Existing372 scoped source/test/supporting files are byte-identical; seven new Python source/test files bring the frozen scope to379. New Python7 compile, public content66 source/maintenance files(not pages)/violations0, embedded/extracted HTML synchronized, SDK/package11 and public/main4 unchanged. No existing server import/route or operating schema is added. **No additional server restart is required.** [Source checks](source-checks.json) · [freeze](final-source-snapshot.json).

Bandit scans the three new runner/fixture/shim modules: **High0 / Medium0 / Low0**, scan errors0. Independent code review found no additional unresolved issue in this bounded scope. Dynamic child audit hooks disallow external socket connect/bind/listen/DNS and subprocesses, operating-path/key access and unexpected writes; anonymous local asyncio wake-up sockets are not external network activity. Tests cover parser bounds, inert import/help, configured-key refusal, bootstrap environment-read traps, exclusive0600/no-symlink output, no diagnostics/private IDs, real copied-only VACUUM, role/CSRF/consent, strict proof completeness, handled failure/timeout cleanup and unchanged process environment/classes. [Scan](static-final.json) · [triage](static-triage.json) · [independent review](independent-review.json). These are not a whole-platform vulnerability-absence certificate.

## Measured disposable scenario

[Actual CLI report](rehearsal-final.json): iterations50/readers4/writers4; initial fixture17 runs,45 checkpoints, one unknown, one pending delivery, current synthetic SDK1.2/1.3/publication/automation grants and four purpose-specific withdrawal sets. In-memory fixture MCP calls36; external providers/models/workers/schedulers0. One durable recovery run and two queued/prepared restore scenarios are added separately. Fixedseed20261018 controls scenario content, not cryptographic IDs, timestamps or timings.

The CLI completed in **1349.691ms**. SQL phase committed200 of200 attempts and200 consistent reader snapshots; natural busy0 and skipped0, plus one independently forced held-writer refusal. Attempt latency p95 write0.177ms/read0.371ms. These small fixture figures measure SQL contention, not workflow throughput or operating capacity.

Seventeen top-level checks require exact strict boolean proof sets: durable5, retention15 and restore18. Active work blocks maintenance. Syntheticclock+91days exercises one explicit body batch(limit20;14 compacted, invalid proof held1) and one metadata batch(limit1;one authority/event set removed). Remaining bounded metadata candidates12 are visible; this is partial cleanup. Attempts, replay/idempotency, actual withdrawals, signed archives, unknown, invalid and pending-delivery holds are checked. Actual publication/SDK/comparison loaders refuse archived details as new proof.

The backup reuses the existing private key/checksum/inventory protocol and restores only to a new path. Unfinished runs/deliveries become unknown, all applicable grants are inactive with revision increments, controls are paused, sessions removed and secrets absent from inventory. Three previously valid status/read capabilities are refused after restoration. Old invocation tickets were already invalid after retention; separate before/after no-replay checks do not misattribute that refusal to DR. Inspection uses mode=ro/query_only and no recovery/launch.

Physical checkpoint/VACUUM ran only on the disposable restored copy with controls paused. DB allocation changed from1589248 to1343488bytes; source load file allocation was unchanged. WAL presence/absence is reported explicitly rather than fabricated as a zero measurement. Integrity and the fixed selected critical-state fingerprint match; this is not universal application equivalence. The private temporary workspace was removed and the new report mode is0600. [Environment/bounds](source-freeze-input.json).

## Findings and retained initial observations

- Intentional synthetic provider timeout emitted execution/resource diagnostics on stderr. Seed unknown through actual DurableRuns prepared/dispatched/expired-lease recovery instead; final stdout is aggregate JSON and stderr empty. No global logging suppression or shared transport patch was added.
- Ordinary fresh Store initialization could read configured administrator bootstrap values. Before Store initialization, the helper now exclusively creates the private DB and a synthetic sadmin, so the initializer skips configuration reads. A trap test and synthetic-password verification reproduce the boundary. `AGENT_UPDATES_KEY` name presence is refused before work without inspecting its value. No operating key or bootstrap value is copied.
- Independent review reproduced that old invocation tickets were already rejected before DR. Preconditions and names now distinguish retained-ticket no-replay from causal revocation of previously valid read keys.
- Initial test assumptions were corrected: closed fixture Store is intentionally setNone(the captured DB handle must reject access); Runtime usesrun_due rather thantick; configured system ADMIN_TOKEN is intentionally a separate highest-admin credential, while an ordinary session follows current user role. No existing authorization behavior was changed or labeled a confirmed escalation.
- Initial static warnings used fixed internal table identifiers and a nonsecurity seeded topic. Fixed SQL maps and a SHA-derived topic remove warnings; no suppression was introduced. Original scans/failures remain as initial observations and do not inflate final passes.

Focused/initial JUnit summaries and exact scope are preserved in [verification](verification.json). Product source stayed frozen during the final affected suite.

## Operating limits and next source work

After the user restart/refresh, the authenticated v1.22 product-v2 inspector opened with empty inputs and schema/options GETs; anonymous protected schema/storage GET403/no-store and public connections GET200/no-store. No sample POST, operating approval/provider execution/grant or delivery. New standalone rehearsal modules add no server import/route, so no further restart is needed. [Read-only restart observation](restart-readonly.json).

Operating server actions/directDB writes/provider/model tasks/approvals/grants/notifications/marketing0. All execution, grant, fault, retention and compaction actions above are synthetic disposable fixtures. No actual operating maintenance, DR, payment, advertising or provider-quality claim is made. SQL busy/load/backup/physical progress budgets are cooperative; there is no global hard deadline, SIGKILL directory-cleanup guarantee, production SLA/HA/RPO/RTO or full PostgreSQL adapter.

Next: [explicit storage adapter boundary/SQL inventory/isolated contracts](../../docs/POSTGRES_STORE_ADAPTER_PLAN.md). Actual reviewed humans/sources/access/pre-run allocation, actual product-provider integration, representative load/DR, full subsystem adapters/cutover/rollback/HA and organization/ledger/support remain separate. Full R-07/AC-08/G0/G1 stay open. [Contract](../../docs/STORAGE_DR_LOAD_REHEARSAL_PLAN.md) · [remaining batches](../../docs/REMAINING_WORK_BATCHES.md) · [platform design](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md).
