# Current application/collector PostgreSQL compatibility

The current source binds the previous 28 missing Store methods through explicit
native collector and credential/virtual-ledger mixins. The historical called
method inventory now maps 78/78 to concrete implementations. This does not prove
all dynamic SQL branches or make the entire application PostgreSQL ready.

`application-compatibility-verification.json` and `application-source-hashes.json`
bind the implementation, schema registry, source-derived public query families,
customer fixture and tests. The exact registry is deterministic (`--check`
unchanged): 158 declared tables, 1,626 explicit SQL pairs, 1,598 normalized runtime
pairs. No additional application table was introduced by this compatibility batch.

- `application-native.json`: 36 native contracts, including actual Home HTML and
  bootstrap, workflow listing/ZIP download, default-closed Workspace access,
  current customer execution, staff/customer ticket separation, SDK2/BFF code
  exchange, consent/replay/status/revocation, typed execution, signed snapshots,
  vector publication/RRF and current authority. Controlled HTTP transports only.
- `collector-native.json`: 22 native contracts, including scheduling/host filters,
  retired backoff/tombstones, statistics and static x402 evaluation against
  SQLite; current HealthChecker single/batch HTTP; concurrent observation owner
  reservations and stale binding refusal; active-need/pending-offer priorities;
  public weighted FTS with hostile query text and live visibility gates.
- The collector contracts also reproduce the exact same-epoch rollback ABA in
  exception, caught-poison and direct-rollback paths and verify that uncommitted
  text is never reused. Committed read projections keep their cache behavior.
- The real Insights consumer handles 2,007 eligible prices using native upper
  medians: MCP even-size 2,002 rows gives 1,002; A2A odd-size gives 5; x402 even-size
  gives 8. Inactive/retired rows are excluded. Results match the original SQLite
  consumer without globally increasing the 2,000-row query cap.
- `application-native-regressions.xml`: 47 focused tests pass, including the
  above actual native suites and fail-closed execute/cursor-cleanup, statement
  admission and batch-iterator failure cases. `collector-regressions.xml` records
  a separate earlier 234-case native/SQLite collector/evaluation/guard regression
  layer. These layers overlap; their counts are not a unique-test total.
- `application-collector-static.json` retains raw automated findings;
  `application-collector-security-review.json` explains the fixed-identifier,
  bound-value and synthetic subprocess/token findings. No high or actionable
  finding remains in that scoped review. Finance and worker/archive evidence
  have their own files in this directory.

All native fixtures use owned disposable PostgreSQL Unix clusters with TCP
disabled, a clean client environment and pre-initialization transport checks.
Unexpected Python IPv4/IPv6 socket creation is blocked and counted; Redis is an
explicit offline fixture. Native clusters are stopped and removed. This is a
scoped Python/native fixture boundary, not a blanket raw-process/browser claim.

The operating application, server and database were not changed. Virtual legacy
ledger operations do not submit provider payments or payouts. The separate
private worker/archive kernel is not general online operating backup or a
cutover mechanism. Missing broader SQL/route, migration/reconciliation and
operating recovery integration remains distinct from external approvals,
provider/IdP credentials and workload/HA/RPO/RTO acceptance.
