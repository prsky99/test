# Explicit application transfer and transition preparation

Current `activate_application` and `rollback_activation` extend this preparation
profile with durable source retirement, restartable native service attachment
and explicitly approved capture of current target changes. See the
[service writer lifecycle](APPLICATION_RUNTIME.md). The no-activation and
no-reverse-copy limitations below describe the earlier preparation-only API.

`application-transfer-preparation-v1` implements a bounded transfer of every
present, known application table from an explicitly supplied SQLite `Store` to
an explicitly supplied, freshly initialized PostgreSQL application Store. It
has no DSN, environment discovery, runtime backend selection, dual write,
operating switch, reverse-copy or automatic retry interface. Accepted v1.36
reports remain historical; current evidence is under
`reports/advancement-batch7-2026-10-19/pg/`.

## Transfer and reconciliation

`copy_application(source, target, operation_id=..., source_workflow_key=...,
source_vault=...)` accepts idle caller-owned Stores. The operation ID has the
fixed `apm_` plus 32 hexadecimal format. Both workflow roots must be explicitly
supplied, exactly 32 bytes and equal. A nonempty credential table additionally
requires the original explicit `CredentialVault`; it decrypts in memory using
name-bound authentication and reseals with PostgreSQL's separate encryption
purpose. No credential key file or secret is inferred or exported.

The source keeps `BEGIN IMMEDIATE` under its Store lock. A separate native
session advisory fence excludes participating PostgreSQL writers, and the copy
transaction takes `ACCESS EXCLUSIVE` locks on every known target table to
exclude direct SQL writers during that transaction. The source is never
mutated. Native statement/lock deadlines remain 5s/1s. Source/table/row/value
shape, counts and both semantic and actual bytes are bounded: 200,000 rows per
table, 1,000,000 source rows and 8 MiB per row/cell. Source actual bytes, native
actual bytes and canonical source bytes each have an independent 512 MiB
ceiling; this is not a summed I/O or process-memory ceiling. A 120-second
post-operation deadline also applies. These are refusal limits, not measured
capacity claims or a hard process-kill deadline.

Unknown source tables, changed affinities, temporary tables, unknown target
relations, nonempty targets and key mismatches refuse the transfer. Missing
optional known source tables represent empty tables and are listed explicitly.
SQLite FTS/vector engine shadow tables are a fixed engine-internal exclusion;
ordinary application rows, IDs, signed payloads, revocations and tombstones are
copied. FTS content and vector bytes/generations/provenance remain intact.
Native internal state is constructed by its explicit profile, not copied from
an unrelated SQLite control record.

Only the four attested native application triggers are temporarily disabled in
the owned copy transaction; they are enabled and attested before commit. The
profile never enables `session_replication_role=replica`. All target rows and
signed operation receipts commit together. Identity high-water marks include
SQLite's consumed AUTOINCREMENT values after row deletion; implicit row order
is preserved in the four native `_ac_rowid` projections. Sequence adjustment
uses transactional `ALTER SEQUENCE RESTART`, rather than nontransactional
`setval`, so a late copy failure does not consume or publish identity state.

Each table receives a keyed, order-independent digest over typed rows. BLOB
values contribute their length/hash to canonical row signatures while their
actual bytes still count toward the transfer quota. Credential comparison
uses a purpose-bound keyed plaintext digest, never plaintext output. Reconcile
also compares future identity counters. A count match alone cannot approve a
copy. Unknown commit/lock acknowledgement poisons the affected Store handle;
there is no retry or assumption that rollback proved a lost commit absent.

## Persistent quarantine and explicit review

The signed receipt lives separately in `agent_migration_control`. Its exact
PostgreSQL system identifier, database OID and name are HMAC anchored. A staged
or prepared target refuses ordinary Store transactions and fresh attachment.
The gate is checked after writer admission or native read-only setup, so a
writer which waited behind a transition cannot bypass it with an earlier
check. An absent gate preserves the existing unclaimed native profile.

`review_application(connection, workflow_key=..., operation_id=...)` provides a
bounded same-connection, thread-owned context under the native session lock.
It permits explicit reconciliation after reconnect or an unknown commit reply;
it does not retry copying. The review Store closes at context exit. Review is
not an HTTP-serving or activation scope and is intentionally unavailable to
other request threads.

`reconcile_application` reacquires source and target fences and compares every
known row/identity counter against the staged baseline. Changed source or
target state remains visible and prevents transition preparation.

## Independent preparation, without service activation

`PreparationAuthority` requires a separate explicit key and an injected current
owner/evidence verifier. Its proof must resolve owner identity, stopped ingress
and workers, external-outcome reconciliation, compatibility evidence and a
rollback point. The receipt exposes only hashes of those references. Approval
is bound to exact target identity, schema, operation, phase, baseline and
revision, with a maximum five-minute lifetime. Preparation reconsults the
verifier using fresh caller-supplied proof and rechecks expiry and a five-second
post-return verifier budget. That budget is not a hard callback kill mechanism.

`prepare_transition(..., phase='cutover'|'rollback', authority=..., approval=...,
proof=...)` creates only a signed preparation event. It refuses outstanding
workflow/attempt/outbox uncertainty, private `prepared/dispatched/unknown`
runs, typed `running/unknown` runs, admitted metering, pending task deliveries
and held virtual credits. Those rows are preserved; no automatic cancellation,
refund, dispatch or reconciliation is manufactured. A rollback preparation
also requires the original baseline to remain equal, so target divergence
cannot silently recreate stale source permissions or discard later commits.

There is no activation operation in this module. `operating_enabled`,
`cutover_authorized` and `full_application_ready` remain false. Database fences
do not stop an external provider request already in flight or prove process
shutdown. Independent evidence and an actual operator-reviewed operating
cutover remain separate work. Equal typed rows do not prove every historical
signature, legacy JSON payload or runtime feature is healthy; current runtime
validators and compatibility fixtures still apply.
