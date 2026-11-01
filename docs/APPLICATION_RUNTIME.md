# Explicit service backend and writer lifecycle

The gateway, its collector and scheduler, the standalone collector, the durable
worker and owner maintenance share the selected persistent Store. SQLite remains
the default. The container includes the PostgreSQL driver; native installations
install `requirements-storage-postgres.txt` before selecting PostgreSQL.

`APPLICATION_STORE_BACKEND=postgresql` requires
`APPLICATION_POSTGRES_DSN_FILE` and `APPLICATION_WORKFLOW_KEY_FILE`. Both must
name regular files owned by the runtime UID, with mode `0400` or `0600`; symlinks
are refused. The first contains a libpq connection string with explicit host,
database and user. Network connections require certificate and hostname
verification. Inherited libpq service/connection overrides are refused. Unix
sockets support owner-controlled local deployments and disposable tests.

The second contains **exactly 32 raw bytes of the existing task-update root key**
(the original `.updates-key` custody). It is not the derived
`WorkflowRuntime.key`. Retain the original credential vault key separately for
authenticated credential transfer and rollback. Do not generate replacement
keys to make an existing database attach successfully.

The normal `agentcon` literal private-settings parser accepts the three setting
names. `agentcon check` validates the selected backend rather than opening the
SQLite path when PostgreSQL is selected. A missing driver, invalid private file,
unexpected schema or unapproved migration/restore gate fails closed; no SQLite
fallback or schema initialization occurs. Public Workspace access remains an
independent, closed host gate. Administrator authentication is unchanged.

## Independently approved transition contract

`application_store_migration` operates on caller-owned, idle Stores and requires
`PreparationAuthority` with a separate authority key and a current independent
proof verifier. The verifier binds the exact operation, revision, phase,
database anchor and reconciliation baseline to owner, ingress drain, worker
drain, external-outcome reconciliation, compatibility and rollback evidence.
The application does not substitute a Boolean assertion for these records.

1. Stop new ingress admission and drain the existing collector, scheduler,
   workflow, notification and customer workers. Resolve unknown external effects
   independently. Retain the source and original key custody.
2. `copy_application` transfers the finite reviewed schema, credentials by
   authenticated decrypt/reseal, identity high water marks and replay records to
   a new native target. The target remains quarantined.
3. `preparation_challenge(..., phase='cutover')` and `prepare_transition` require
   fresh current owner proof and equality to the transferred baseline.
4. A distinct `activation` challenge and `activate_application` durably fence
   every old SQLite table writer before committing the native `service_active`
   gate. Missing optional tables in the finite reviewed schema are materialized
   and fenced in the same retirement commit, including paths used by stale raw
   schema constructors. A new native process can then attach. This does not
   change DNS, ingress, public features or process settings automatically.
5. Configure the same selected backend for the service and any independently
   managed collector/worker, then start them only under the approved operation.
   The native transaction, queue CAS, lease and dispatch fences remain enforced.

If target activation fails after source retirement, both remain stopped. A
fresh independently approved activation can verify the same retirement and
complete it. Lost commit replies are reviewed; no external operation is retried.
Preparation, activation and rollback also verify the signed payload and SQL
locators of remote A2A tasks, evaluation jobs, machine notices and Stripe sandbox
commands. Active or uncertain effects, invalid evidence and inspection limits
block handoff; a terminal-looking unsigned locator cannot conceal an effect.

## Rollback and change capture

After stopping ingress and draining target workers, issue a new
`rollback_activation` challenge. `rollback_activation` refuses target divergence
by default. Explicit `capture_changes=True` copies current target data back
under both writer reservations, including current revocations, sessions,
idempotency and financial tombstones; credentials are resealed with the original
source vault. It verifies equality, identity high water marks and foreign keys.

The target stop receipt must commit before the reconciled source is released.
A lost target commit leaves the source retired. Fresh independent proof can
finish an interrupted rollback while that retirement still exists. No workflow,
payment, refund, notification or unknown effect is replayed by data capture.

The process owner closes its connection only after scheduler, collector and
workflow drains succeed. A timeout leaves storage attached for the outstanding
worker; it cannot silently detach underneath a running provider call.

## Retention and restoration

Existing workflow body/event maintenance and private output retention remain in
place. Owner workspace maintenance additionally compacts expired research bodies,
known terminal circuit claims and expired admissions which never acquired a
draft, snapshot or ticket after 90 days. It keeps signed hash receipts and
permanent replay tombstones. Unknown effects, protected admission pins, financial
records, key/disclosure withdrawal and restore blocks are retained.

Both SQLite and native PostgreSQL restore paths block old sole-owner recovery
policies/requests and Stripe sandbox orders. The private restore inventory
contains bounded identifiers and review instructions, without credentials,
inputs, proof bodies or personal profiles.

`scripts/rehearse_application_runtime_postgres.py` uses a disposable, Unix-only
cluster to exercise the actual service, public bootstrap, collector, Ledger,
worker, private-file connection factory, retirement, restart, interruption and
current-state rollback. Its default uses the checked-in catalog. The explicit
`--provisional-catalog` development option rebuilds source metadata only in its
child process and is not final release evidence.

Actual HA topology, representative load/lock contention, operating RPO/RTO,
ingress cutover and independent operational ownership remain environment
acceptance. A local synthetic cluster does not establish those results.
