# Explicit application PostgreSQL Store profile

Current service selection, full application source capability, driver packaging,
durable writer activation and current-state rollback are documented in
[Explicit service backend](APPLICATION_RUNTIME.md). The scoped limitations and
verification counts below describe earlier source slices and remain historical.
The service, collector and worker now support the explicit native runtime;
operating HA/load/DR acceptance is separate. `full_application_source_supported`
and `service_runtime_supported` describe that source support; the legacy
`full_application_ready` field remains false because this source artifact alone
does not establish an approved operating deployment.

`application-postgres-store-v1` is a caller-owned native PostgreSQL binding for
reviewed current application paths. Selection never migrates or approves a
database automatically.

The internal factory is `open_store('postgresql', connection=owned_connection,
initialize=True, workflow_key=synthetic_or_operator_managed_32_bytes)`. The
caller supplies an idle autocommit connection and retains its ownership. The
factory never accepts a DSN, reads connection environment settings, connects,
cuts over, dual-writes or restarts a server. Initialization requires an empty
database; attachment validates the profile. The workflow key is explicit and
exactly 32 bytes; no ephemeral signing key or misleading SQLite path is created.

## Implemented source and boundaries

- Current catalog identity, scalar/NULL/JSON/time mapping, catalog mutations,
  reports/reviews, workflow definitions, footer inquiry/privacy repositories,
  staff authentication/session revocation, and metadata use native PostgreSQL.
- Existing customer identity, organization/invitation, staff/customer signed
  draft/snapshot repositories run through registered SQL. Native contracts also
  execute the current two-step typed MCP graph, consent/replay fences, conserved
  simulated metering, provider proof and 7:3 simulated settlement/refund paths.
  Identity/provider HTTP responses are controlled fixtures, not live providers.
- Public workflow template listing and ZIP download are exercised through the
  actual FastAPI frontend. Public content and HTML remain unchanged; the native
  Insights data seam is described below.
- The current compatibility batch implements the collector's due/host filters,
  scheduling, retired-resource backoff, static evaluation, priority union,
  deactivation and statistics. Collector reads and postpone batches are capped
  at 5,000 rows; malformed batches are rejected before any write. Current
  observation bundles are tested against rebinding and concurrent reservations.
- Native credentials use the caller's explicit workflow key with an independent
  encryption purpose. Missing/wrong keys, swapped names, altered ciphertext and
  blind overwrite/delete attempts fail closed. Legacy credit/clearing methods
  preserve virtual-ledger behavior, serial ownership and account conservation;
  they do not submit provider payments, withdrawals or payouts. A deposit or
  reserve has no caller event key and is not safe to retry after an unknown
  commit acknowledgement.
- Actual private customer execution, opaque customer principals, staff/customer
  ticket separation, SDK2/BFF code exchange, consent, replay, retained status and
  deployment withdrawal are exercised natively. Public Workspace access remains
  closed by default; these contracts do not enable customer login or deployment.
- Current observation guard context managers retain native generation/sequence
  ownership. Observability and workflow heartbeat use the Store transaction
  seam; they do not open an inferred SQLite file.
- `application_store_sql.json` contains explicit reviewed SQLite/PostgreSQL
  statement pairs, trusted schema scripts and source hashes. Arbitrary runtime
  SQL, unknown schema scripts and unknown PRAGMAs are refused. Placeholder
  projection happens when building this checked-in artifact, never at runtime.
  Fixed dynamic query families have bounded placeholder/identifier allowlists.

Writer transactions serialize on a native advisory lock, matching existing
`BEGIN IMMEDIATE` ownership. Reads use a native read-only repeatable snapshot.
Caught SQL/admission errors poison the enclosing transaction. Commit or rollback
acknowledgement uncertainty permanently poisons that Store handle; no automatic
replay occurs. Results, parameters, FTS projections and dense scans have explicit
row/byte limits. Native transaction-local statement/lock deadlines are 5s/1s.
Failed batch iteration, caught unknown `Store.query` calls and combined native
execute/cursor-cleanup failures also poison the enclosing transaction/handle.

Attachment checks actual physical columns and PK/unique/check constraints.
Every transaction also checks the four exact catalog/observation/vector trigger
bindings and function bodies, enabled state and execution characteristics, and
requires `session_replication_role=origin`. Writers hold table locks while
checking and mutating. This prevents missing/disabled trigger or replica-session
drift from reviving old generation-pinned evidence. This is not a claim that all
arbitrary PostgreSQL DDL, index/default/identity changes have been attested.

## Search and vector semantics

PostgreSQL is the persistent source of truth. The lexical projection is an
ephemeral in-memory native SQLite FTS5 index, rebuilt on the persistent catalog
epoch. It preserves the existing tokenizer, Unicode and BM25 behavior, rather
than substituting PostgreSQL text search. Projection limits are 200,000 rows and
128MiB; rebuilding is bounded and does not claim production performance.
Exact source-derived public Explore/Insights query families are registered.
The named Explore adapter binds an FTS5 rank array as JSON and applies current
visibility, quality and trial weighting in a native snapshot. Explicit/hostile
query text, current retirement/quarantine/inactive exclusions and weighted order
are checked against SQLite. Aborted writers invalidate their cached epoch,
including caught poisoned errors and direct rollback, preventing epoch ABA from
reusing uncommitted text while keeping committed read-cache reuse.

Insights uses the explicit `insight_price_medians()` consumer projection on
PostgreSQL, with the original SQLite query as its fallback. Native window
functions return one exact upper median per kind. Even-sized distributions retain
SQLite's `prices[len(prices)//2]` behavior without transferring all prices or
raising the generic query cap; the real Insights function is tested beyond
2,000 priced resources. This is a backend data seam, with no UI/copy/HTML change.

Vector bytes, generations, claims, jobs and provenance persist in PostgreSQL.
The existing fenced publication contract is reused. Search uses exact float32
cosine, current provenance checks and existing 0.4/0.6 reciprocal-rank fusion;
the dense scan is capped at 20,000 rows/80MiB. Over-capacity or malformed vectors
retain lexical results. Native SQL errors abort the snapshot. This implements
bounded exact search, not ANN, pgvector, scale, throughput or latency guarantees.

## Native worker and private archive scope

The explicit caller-owned `PostgresWorkflowWorker` attaches the current durable
runtime without inferring a DSN, client, courier, schedule or control activation.
Actual queued execution, heartbeat/fence/lease/CAS, signed checkpoint reuse,
SIGKILL boundaries, tamper and outbox uncertainty have native contracts. The
worker does not enable scheduled admission or result delivery.

An authenticated, optionally encrypted `pg_dump`/`pg_restore` kernel supports
only an owned private Unix cluster and a new empty unpublished target. Restore
quarantines old authority and ambiguous execution/delivery while preserving
vault ciphertext and held financial rows. It does not settle/refund those rows
or reactivate grants. [NATIVE_WORKFLOW_POSTGRES.md](NATIVE_WORKFLOW_POSTGRES.md)
describes its exact restrictions. `operating_backup_ready` remains false.

## Remaining source and operating work

`coverage()['full_application_ready']` remains false. The current call-site
review identifies 78 called legacy Store methods: all 78 now have concrete
implementations, including the previous 28 gaps. Native collector, credential,
virtual-ledger, customer execution and worker/archive contracts cover the paths
described above. A concrete method and registered schema are not proof of every
parameter branch, raw dynamic SQL route or end-to-end application domain.

The current service still constructs its existing SQLite Store. The accepted
v1.36 baseline left direct consumer families, full-profile transfer and general
archive preparation for the next batch; their new scoped implementations and
native proofs are described below. Unknown SQL remains denied. Complete
both-backend route/parameter execution coverage and the separate path-only
SQLite utilities are not implied by the 78-method map.

Operating acceptance still requires a concrete target and credentials,
maintenance ownership, approval, identity/provider integrations, representative
workload and measured HA/RPO/RTO targets. The new transfer/archive preparation
contracts do not switch the service or establish those operating measurements.

## Reproducible verification

`python -m scripts.build_application_store_postgres_catalog --check` checks the
fixed source/catalog projection. `--write` intentionally updates that source
artifact using an owned in-memory schema parser; no operating database is read.

`python -m scripts.rehearse_application_store_postgres --run` starts only an owned
disposable PostgreSQL cluster with TCP disabled and a private Unix socket. Its
client runs in a clean child environment, dropping inherited libpq, OAuth,
bootstrap and artifact-key settings. Transport is asserted before schema writes.
No DSN, database path, server or output path is accepted by that command.
Unexpected Python IPv4/IPv6 socket creation is blocked and counted even if a
fallback catches the error. Redis is an explicit offline fixture; HTTP is an
in-process controlled transport. This is a scoped Python/native fixture guard,
not a statement about every possible raw process/browser transport.

Security unit tests are in `tests/test_application_store_postgres.py`. Native
and SQLite regression evidence is in `reports/application-store-postgres-2026-10-18/`;
independent trigger/session/transaction review evidence is in
`reports/advancement-finalization-2026-10-18/pg-independent-resolved.json`.
Those reports are the immutable historical v1.35 baseline. Current collector,
finance, public query, customer and native worker/archive results are in
`reports/advancement-pg-compatibility-2026-10-19/` with source hashes and the
78/78 method map. The main, collector, finance and worker native contracts use
separate disposable clusters; their checks are not a unique regression-test sum.

## Current batch: full transfer and additional consumer families

The batch after accepted v1.36 adds the explicitly quarantined full known-table
transfer/reconciliation and independent transition-preparation contract in
[APPLICATION_STORE_MIGRATION.md](APPLICATION_STORE_MIGRATION.md). It does not
replace the earlier subset `CatalogCopy` or claim operating backend readiness.
Both migration and general restore deployment gates are checked at native
transaction admission; pending targets cannot be served by a normal Store.

Desktop administrator query families now cover fixed agents/needs/audit
filters, user changes, overview/errors, three time buckets, Notification
Preferences, Insights and Explore, including the existing FTS5 ranking. Native
ASCII folding, literal backslashes, NULL ordering and truncating time buckets
preserve the corresponding SQLite contracts. Median prices use the bounded
native upper-median projection instead of transferring an unbounded price list.
The collector listing uses a named native fixed-predicate/FTS projection rather
than enumerating every possible filter permutation. ERC-8004 constant-host
maintenance, visitor interest/prune, task-update due selection, security
filters and SNS fixed query families also have explicit bindings. Separate
native contracts exercise actual administrator and collector FastAPI routes,
current sessions, role withdrawal, hostile bound values and origin controls.

The whole-tree metadata-only consumer inventory is
`python -m agent_market.application_store_coverage --audit`. It separates exact
pairs, named families, native overrides, SQLite-only utilities, isolated
profiles and unresolved expressions. A syntactic match is source coverage,
not proof that every runtime branch executed. The current batch also closes
URL-deduplication and recommendation candidate projections, Visiting Agents
filters, administrator test-agent/alternative lookup, signed retention and
native comparison readers. Legacy separate broker/payment stores and the
path-only SQLite template-replacement/backup utilities are explicitly outside
this application binding. They open their own SQLite connections rather than
accepting the application Store; the new PostgreSQL transfer/archive APIs are
separate explicit contracts. Native initialization/heartbeat/FTS-vector SQLite
fallback branches remain visible in the scan without being presented as
missing native implementations. The profile continues
to advertise `full_application_ready=false`; method-name coverage alone does
not establish complete source compatibility or authorize deployment.

Current native application proof additionally exercises the typed SDK2
package/BFF, exact whole-graph consent, two-node execution, replay, customer
attribution, retained history and deployment revocation. Public Workspace
access remains held and real payment/provider capabilities remain disabled.

Current Chat recommendation projection retains the existing exact SQLite FTS,
legacy numeric/Julian timestamp, JSON and ranking semantics through a fresh,
bounded ephemeral metadata projection inside one native PostgreSQL snapshot.
It does not cache a positive recommendation or bypass current verification.
Source report timestamps retain their declared REAL affinity; arbitrary ISO
text injected into a REAL column is refused by the native write/transfer
contract, rather than silently expanding the schema. Historical SNS trial
JSON timestamps must be numeric; string/boolean/object/null timestamps are
excluded in both backends, and the native JSON projection guards every cast.
