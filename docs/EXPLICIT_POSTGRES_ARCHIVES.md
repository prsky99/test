# Explicit PostgreSQL archive and deployment recovery

The general source API is `agent_market.postgres_operational_archive`. It uses
explicit caller-owned connections, identities and credential providers, rather
than the disposable-directory restriction of the earlier private archive helper.
No command discovers a DSN, password, current server, deployment configuration or
signing/encryption key. No operating connection is selected or changed by tests.
Operating acceptance remains false until the operator supplies and verifies the
missing environment, custody, ownership, deployment and recovery requirements.

## Caller boundaries

`DatabaseIdentity` pins the host/socket, port, database, database role, PostgreSQL
system identifier and database OID. TCP additionally requires an explicit IP
address and trusted root certificate, a currently authenticated `verify-full`
TLS connection, and the matching server address. Tools receive that pinned IP
and certificate policy. Unix sockets remain available for explicitly supplied
connections. The API checks actual server identity before requesting a lease;
it never opens a caller-selected address itself.

`ExplicitArchiveCredentialProvider` is an explicit server-side factory returning
an `ArchiveCredential` lease for exactly `backup`, `restore` or `approve`.
Leases expire within fifteen minutes, are consumed once, and permit one tool
dispatch. Credential passwords never appear in error messages or object repr. Identity, purpose and expiry metadata remain visible to the explicit caller.
Wrong identities, wrong purposes, expiry and replay fail closed. Underlying
database password issuance, expiration and revocation remain the provider's
responsibility; a local lease timestamp does not rotate a database password.

Tool execution uses fixed argument arrays without a shell. A temporary
owner-only passfile supplies the purpose-bound password; inherited password,
service, home and application-key configuration is excluded. Passfiles are
removed and in-memory lease references cleared after ordinary completion or
handled failure. Whole-process `SIGKILL` cannot run Python cleanup; private
temporary-file cleanup and provider-side credential revocation still need an
operating procedure. Tool output is discarded rather than collecting private
driver diagnostics or unbounded stderr in memory.

The caller must explicitly provide trusted `pg_dump` and `pg_restore` paths and
a stable 32-byte workflow key. The source profile still accepts only the current
known public application schema and bounded artifacts up to 128 MiB; it does not
silently migrate an unknown schema or claim unlimited operating data capacity.
The PostgreSQL identity checks require access to `pg_control_system()` and the
database catalog. A deployment role without that explicitly configured access
fails closed rather than skipping identity checks.

## Backup

`backup(connection, directory, identity=..., credentials=..., workflow_key=...,
tools=...)` acquires the current application writer's session advisory lock.
An active competing writer is refused; the source API never changes execution
controls or schedules. The lock excludes new application writers while schema
attestation and the consistent native dump run. The operator must schedule and
measure this writer pause before using it on an operating deployment.

The final archive is mandatory AES-256-GCM under the explicitly configured
versioned private artifact keyring. Missing encryption configuration refuses
the operation. A signed manifest binds the ciphertext digest, schema fingerprint,
source identity digest, workflow-key custody commitment and advisory retention
date. HMAC/signatures provide authentication; AES-GCM provides encryption.
Neither workflow keys, artifact key material nor credentials are exported.
The temporary plaintext dump is owner-only and removed after successful sealing;
retention metadata never authorizes automatic deletion.

## Exclusive restore and deployment gate

`restore(...)` authenticates and decrypts the archive before claiming its target.
The source and target identities must differ. The target must have no public
tables, sequences, views, materialized views or functions. No application target
is overwritten and no automatic discard or retry occurs.

Restoration takes the application writer's exclusive session lock and commits a
fresh signed gate in `agent_restore_control.gate` before tool dispatch. That
control schema is deliberately outside the archived public schema. The normal
native Store checks this gate in both ordinary and direct transaction admission;
pending, failed, quarantined, altered, incorrectly keyed or incorrectly anchored
states deny access. `initialize=True` does not bypass the gate. A temporary
internal scope is bound to the same connection, secret owner token, generation,
deadline and live session lock; it cannot authorize another connection.

After the tool restores its single transaction, the source validates the
application profile and quarantines it in a separate application transaction.
Unfinished execution/delivery becomes unknown with fences advanced; execution
controls/schedules are paused; old sessions, memberships, tickets, destinations,
grants and disposable SDK tokens are revoked; old private releases, typed flows,
provider transfer offers, agreements and sandbox payment intents are permanently
blocked. Retained ciphertext, evidence withdrawal tombstones and financial
history remain unchanged. Restore never sends, executes, settles, refunds or
sweeps anything.

A successful quarantine leaves the durable gate `quarantined`, so the deployment
still cannot be attached. A quarantine or credential failure leaves it `failed`
or `restoring`; even if the native tool already committed its application dump,
the deployment stays unavailable. The tool and quarantine transactions are
separate, and the independent durable gate closes that interval. There is no
automatic unquarantine or reuse of a failed target.

## Independent reapproval

`review(...)` returns a fresh generation/revision/challenge bound to the actual
target and authenticated archive. `RestoreOwnerAuthority` requires an explicitly
configured external current-owner verifier and a separate server-held signing
key. It never derives ownership from restored accounts, sessions, memberships or
historical operator rows. A receipt expires after five minutes and is bound to
that exact challenge; approval rechecks the live external proof. A withdrawn,
expired, substituted, tampered or replayed proof cannot approve deployment.

`approve_deployment(..., authority=..., receipt=..., proof=...)` takes exclusive
ownership again, verifies the current target/owner, requires execution controls
to remain paused, and commits a signed CAS transition plus audit event. This
permits inspection through the Store. It does not enable execution, recreate
old grants, restore prior organization ownership, publish customer Workspace,
activate delivery/payment, or set `operating_backup_ready` true. Current owners
must independently establish new memberships, grants, proofs and per-run consent.

## Verification and remaining acceptance

The CLI `python -m scripts.rehearse_postgres_operational_archive --run` accepts no
operating connection or key argument. It exercises this same general API on a
new Unix-only PostgreSQL cluster with synthetic SCRAM credentials and a private
synthetic artifact keyring. External sockets/name resolution, Redis, model and
provider access are blocked. Actual tool authentication, expired/wrong/replayed
leases, identity/ownership conflicts, corrupt archives, no-overwrite, closed
pending/failed gates, quarantine rollback, unknown execution, signed audit and
fresh live owner approval are tested. TCP/TLS checks have source/unit coverage;
no external TLS or operating provider environment was supplied or accepted.

The operator still needs credential lifecycle, key custody/rotation, role and
certificate configuration, independent ownership recovery, representative data
capacity, restore publication controls and measured recovery drills. The tests
are source/synthetic contracts, not HA, whole-application migration acceptance,
operating RPO/RTO, a legal ownership determination or permission to restart or
change the current server.
