# Application PostgreSQL source profile verification

The explicit caller-owned application Store now implements native catalog,
search/vector, current authentication/private repository and public workflow
paths. The operating application continues to use its existing SQLite backend.
No server was restarted; no operating DB, DSN, provider or key was used.

- `native-contracts.json`: 30 actual native application contracts passed on a
  disposable PostgreSQL cluster, TCP disabled. Includes public template listing
  and real ZIP download HTTP routes, staff/customer authority revocation,
  organization/invitation/signed snapshots, two-step typed MCP execution/replay,
  conserved simulated meter and provider-agreement settlement/refund,
  Unicode/BM25 SQLite parity, fenced vectors/RRF, malformed-vector lexical
  fallback and four-connection catalog identity concurrency.
- `pytest.xml`, `pytest.log`: 248 focused security, native integration, SQLite
  search/vector and readiness regressions. The required native pytest case
  deliberately poisons the parent libpq/key configuration; the fixed child
  environment and pre-initialization Unix transport checks isolate it.
- `source-hashes.json`: exact 11 implementation/test/document source hashes.
  `application_store_sql.json` is deterministic (`--check` unchanged), with 158
  tables and 1,531 declared SQL pairs (1,503 normalized runtime statements).
- `bandit.json`, `security-review.json`: automated static scan found 25 medium
  B608 and six low fixture/subprocess findings, zero high. Each finding was
  reviewed: fixed source identifiers/query fragments and bound values; fixed
  isolated worker argv; synthetic fixture tokens. No actionable issue remains
  within this source review. The raw findings are retained.

Independent native evidence is retained alongside the main finalization report:
`../advancement-finalization-2026-10-18/pg-independent-resolved.json` verifies ten
trigger/session/timeout/rollback cases, and `pg-independent-wrapper-resolved.json`
verifies the 30-contract wrapper with a polluted parent environment. Both were
rerun on the final frozen application source, with source/catalog hashes checked
before and after. Cursor-cleanup uncertainty also has a dedicated unit regression.

The exact current call-site map is
`../advancement-finalization-2026-10-18/pg-coverage-review.json`: 78 called Store
methods, 50 concrete, 28 unsupported; public frontend direct Store method calls
have zero missing implementations. This is a method/source map, not proof of all
dynamic `_db` branches. The 28 remaining methods concern collector scheduling,
credential sealing and legacy credit/clearing operations. Complete durable
worker recovery/delivery, native backup/restore quarantine, migration
reconciliation and operating qualification require further work.

`full_application_ready=false` remains explicit. Missing source is not renamed
as an external operating gate. See `../../docs/APPLICATION_POSTGRES_STORE.md`
for the precise implemented scope, resource caps, remaining methods and source
versus operating decisions. This report makes no production cutover, HA,
RPO/RTO, workload capacity, ANN or latency claim.

CI provisioning follow-up: the workflow pins `psycopg[binary]==3.3.6`, installs
PostgreSQL 16 tools, checks their fixed Ubuntu package paths and allows a bounded
40-minute expanded regression job. The helper searches that fixed directory
without inheriting `PATH`. `ci-provisioning.json` and its pytest XML/log record
45 focused checks passing, including both real native profiles. These overlap
the preceding suite and are not added as unique tests. The hosted GitHub job and
Ubuntu package installation have not been executed locally; no local service was
installed or started.
