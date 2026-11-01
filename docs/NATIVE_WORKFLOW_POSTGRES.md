# Native workflow recovery and private archive kernel

The PostgreSQL application Store can now be attached to the durable workflow
runtime through an explicitly supplied native connection and stable 32-byte
workflow key. This is a bounded source implementation and isolated contract
profile. It is not an operating database migration, daemon, backup scheduler,
credential provider, RPO/RTO guarantee, or HA acceptance.

## Worker attachment

`agent_market.workflow_postgres.PostgresWorkflowWorker(connection,
workflow_key=key, proxy=None)` validates the exact key before inspecting the
connection. The caller retains connection ownership. No DSN, environment
connection, configuration file, HTTP client, provider, courier, schedule or
control activation is inferred.

Construction and `tick()` perform storage-only recovery. Calling
`tick(execute=True)` also wakes at most twelve previously queued runs and
requires a caller-supplied execution proxy. The normal runtime still enforces
current execution authority, connection pins, execution controls, global active
capacity, leases, fences, deadlines, signed checkpoints and per-dispatch guards.
Only the caller's proxy may execute business calls. This worker intentionally
does not call `run_due()`: scheduled admission, automation and result delivery
are separate purposes and are not enabled by this attachment.

Recovery distinguishes an interruption before dispatch from an unknown external
outcome. A prepared attempt with a current original deadline may resume. A
completed, authenticated checkpoint is reused. A dispatched attempt interrupted
before a durable outcome becomes unknown and is never retried automatically.
The outbox similarly requeues an expired claim before dispatch, while a
dispatched event becomes unknown and is not sent again. A worker without a
courier never drains delivery, including when execution succeeds.

`wait()` is bounded and does not cancel a blocked provider thread or free its
slot prematurely. `close()` refuses live futures, detaches the Store only after
completion, and leaves the caller's native connection open. The runtime's
module-level bounded executor is shared; individual attachments must not shut
it down. The native heartbeat uses the current Store transaction rather than
opening a SQLite filename, renews the lease without extending the original
deadline, and ends when execution finishes.

## Explicit private archive

`agent_market.workflow_postgres_archive.backup` and `restore` accept an explicit
connection, workflow key, private cluster descriptor and trusted `pg_dump` /
`pg_restore` executable paths. They accept only the owned disposable cluster
shape used by the native fixture: an owner-only directory under `/private/tmp`,
owner-only Unix socket, no TCP listener, and an attested private data directory.
An operating connection is refused. This restriction is intentional while a
separate operating credential and backup policy remain unconfigured.

The archive contains only the current public application schema, with exact
known table names and four attested invariant functions. Unrelated tables,
views or functions refuse export. Fixed tool argv uses no shell and a small
clean environment; inherited passwords, libpq services, artifact keys and
application credentials are not forwarded. The archive is created in a new
owner-only directory with owner-only files and a bounded artifact size.

Every manifest is authenticated. Without an optional artifact keyring it uses
a purpose-derived HMAC from the explicit workflow key; HMAC provides
authentication, not encryption. With an explicitly configured artifact keyring,
the versioned signer supports current and previous keys under their verification
expiry and revocation policy. An independent workflow-key custody commitment
also refuses the wrong workflow key when an artifact signing key remains valid.

`encrypt=True` requires the existing explicit private artifact encryption key
configuration and applies AES-256-GCM with a fresh nonce and manifest context.
It fails closed when encryption is unavailable. The plaintext dump is removed
after sealing; neither workflow-key material nor the artifact keyring is placed
in the archive. The retention date is advisory and does not authorize deletion.
The operator must retain valid decryption/signing key versions outside backups.

Restoration verifies manifest, schema fingerprint, key custody, artifact size,
checksum and authenticated encryption before invoking `pg_restore`. It restores
the bytes already authenticated into a private temporary file, avoiding a path
replacement between verification and tool use. The target must contain no public
relations or functions, including sequences, views, materialized views and
foreign tables. Only its verified empty default public schema is dropped,
without `CASCADE` or `--clean`; a concurrent unexpected object aborts restoration.
No existing application target is overwritten, and no implicit schema migration
is attempted when the source fingerprint differs.

The restored private target remains unpublished. Before successful return, one
writer transaction quarantines unfinished execution/delivery, increments fences,
pauses execution controls and schedules, revokes sessions/memberships/tickets,
clears disposable SDK capabilities and signed meter/fallback policies, and
permanently blocks old private releases, typed flows, agreements and provider
transfer offers. Existing vault ciphertext, signed receipts and financial held
ledger rows are preserved unchanged; restoration does not decrypt, settle,
refund, redeem or sweep them. A count-only review inventory and current-owner
reapproval guidance are returned without exporting principals, endpoints or
inputs.

The tool's restore transaction and application quarantine transaction are
separate. This is safe only within the explicitly owned, private, unpublished
fixture boundary. On any failure the target must remain unavailable and be
discarded through a separately authorized action; no partial target is returned
as ready, no automatic cleanup/drop occurs, and no grants are reactivated. A
general online operating restore would additionally need exclusive restore
ownership, a credential provider, deployment gates and measured recovery drills.
`operating_backup_ready` therefore remains false.

## Isolated verification

`python -m scripts.rehearse_workflow_native_postgres --run` creates its own
Unix-only PostgreSQL cluster and accepts no operating path, DSN or credential
argument. Native subprocesses use a clean environment and Python socket/name
resolution guards. MCP execution uses an in-memory synthetic transport; Redis,
model services, external providers and result delivery are not contacted.

The fixture exercises actual queued execution; `SIGKILL` at prepared, checkpoint
and dispatched boundaries; checkpoint tamper; cross-connection CAS and capacity;
stale-owner dispatch denial; heartbeat and connection/thread lifecycle; outbox
uncertainty; encrypted archive rotation, revocation, tamper and wrong-key denial;
empty-target guards; restored unknown-state isolation; vault/held-ledger
preservation; and unrelated-source-object refusal. Cluster shutdown is confirmed
before removal. These contracts demonstrate the bounded source behavior, not
production load, delivery acceptance, finance activation, operating backup,
disaster recovery time or whole-application PostgreSQL readiness.
