# Explicit owned-copy catalog migration rehearsal

2026-10-18 · v1.29 · bounded prospective subset; no operating import/backend switch.

`catalog_copy.py` imports a named owned-copy subset into a new empty explicit
private target, reusing the registry normalization, observation clock validators,
fenced index outbox and actual lexical artifacts. There is no Store initializer,
DB path, DSN, driver connection, automatic schema creation or server route in the
core API. The CLI accepts only `--run` and owns disposable fixed source/target
fixtures. It cannot select an operating database.

## Supported source and explicit exclusions

The source profile `owned-legacy-subset-v1` has exactly four base tables with exact
column names/order:44 selected resource fields, one source control/epoch row,
owner clock metadata and an exclusion manifest. Extra tables, views, TEMP shadows,
extra/missing columns, duplicate declarations and additional control rows are
refused. Target tables/column lists are also explicitly checked. PostgreSQL
resolved search path must be pg_catalog/public for the reused trusted statements.
This checks the declared structure and actual inserted-value round trips, not all
possible database constraints, triggers, extensions or arbitrary function safety.
Connections and their owners remain trusted.

The fixture uses sparse stable IDs7/41. It retains ID/key, first-seen timestamp
zero, last registry sighting, inactive state and NULL/unknown distinctions. Registry
normalization is the explicit strict prospective profile: canonical JSON, network
ordering, derived host and supported casing/time representation may differ from
stored legacy bytes. Refused or truncated source values are not silently repaired.
Original stored content_hash (including NULL) is preserved separately in
`catalog_copy_mappings`; the prospective canonical registry hash and raw source-row
digest are separate fields. No legacy hash is recomputed as its original evidence.

The seven fixed exclusions are auth, trial, history, authority, fts_vector,
unselected_fields and uncoordinated_writers. Each must declare zero; nonzero or
unknown counts block import and return a fixed aggregate rejection manifest.
Source auth fields must be NULL. Known credential patterns in every selected text
field, including decoded HTML/percent metadata, are refused. This is deliberately
conservative and is not a universal detector for unlabeled secrets, personal data,
arbitrary encodings or schema semantics. Raw source/target data remains private.

These are four synthetic tables, not the complete operating Store: the current
Store has67 known resource fields; the selected44 omit23 fields including auth
methods, capability summaries, trial/usage history, probe/error fields and extended
evaluation metadata. Source-domain zeros mean excluded data is absent from this
owned fixture, not that all operating subsystems were inventoried or migrated.

## Source fence and lifecycle

`source_snapshot(source_adapter)` holds a source transaction for the full target
import. It performs SELECT/locking only; source rows are not changed. SQLite uses
the adapter's BEGIN IMMEDIATE reservation and blocks other ordinary writers,
including in WAL mode. PostgreSQL locks the source control row; participating
copy writers must acquire that row before updating data and incrementing the epoch.
This is cooperative exclusion, not exclusion of arbitrary SQL, privileged sessions
or unknown operating writers. The manifest is a declaration, not proof that such
writers do not exist. Source capture is not a native read-only transaction.

The resulting CopySource is private, active only within the context and on its
owning thread. The importer reloads/validates the held source before writing and
before committing its receipt. Caller-accessible cached maps are never the data
authority. Changes against the declared fence/digest are refused; summary counts
also use freshly validated values. A closed or cross-thread object is refused.
Two databases are not one atomic transaction, and a nonparticipating PostgreSQL
writer can evade the cooperative protocol; this profile cannot authorize cutover.

## Target transaction, baseline clocks and recovery

`CatalogCopy(target_adapter).apply(source, operation_id='cp_'+32 lowerhex,
model_hash=MODEL_HASH)` requires explicit initialized private schemas, one disabled
write-control row and otherwise empty target tables. It never overwrites a populated
target. The receipt fingerprint binds profile, held source digest/epoch and lexical
model identity. Exact replay returns the original committed receipt without
restoring copied rows after later target changes; changed input reuse is refused.
`reconcile(operation_id)` is a bounded read-only inspection on a fresh connection.

The initial resource/index revision is source_epoch+1, above the declared source
generation bound. The fixture epoch is5 and new revision6; this is an explicit
prospective mapping, not discovery of an operating legacy worker generation.
Source jobs, claim tokens, leases, grants or sessions are not copied. Synthetic
old revision checks and invalid-token/current-claim tests preserve the existing
fence boundaries; they do not certify that real operating workers were drained.

Owner high-water marks preserve both retained source clock metadata and owned
resource timestamps, including tombstoned cap/evaluation freshness. Baseline heads
refer by cp_ operation ID to the immutable copy receipt and per-resource mapping.
They do not refer to invented ob_ observation receipts: no live observation journal,
execution/quality evidence, version/approval history, eligibility, delivery grants
or customer authority is synthesized or restored. Current raw NULL/tombstone state
stays unchanged. New observations still enforce revision and clock dependencies.

One target transaction owns resource rows, prospective revisions, new index work,
legacy-hash mappings, baseline heads and import receipt. INSERT RETURNING values
must match the bound canonical values, so native type affinity cannot silently
change an ID or original hash. Any intermediate error rolls back logical rows.
PostgreSQL setval advances the identity sequence with a bound maximum imported ID,
so subsequent typed writer IDs exceed imported IDs. Sequence state is explicitly
nontransactional: allocation/gaps are not rolled back or promised gap-free.

A real commit followed by a lost acknowledgement remains commit_unknown and
poisons the adapter. A fresh target connection reconciles the receipt; exact replay
adds no duplicate rows. No automatic retry/reconnect or writer enablement occurs.
The target stays disabled until a caller explicitly enables its private fixture
control. Actual artifact build/publish is separate fenced work after import and
checks current safety/activation without recertifying provider callability.

## Verification and next integration unit

[Accepted evidence](../reports/advancement-catalog-copy-2026-10-18/README.md) includes
native SQLite/PostgreSQL import, source write exclusion within the stated protocol,
sparse-ID continuation, NULL/hash/clock reconciliation, unsupported manifests,
logical rollback, commit uncertainty, reopen, actual artifacts and existing scoped
security/API/Chromium/TLS regressions. Genuine failures for hidden metadata,
known credentials, mutable caches, manifest/control cardinality and target type
coercion are retained alongside corrected results.

Full Store/auth/trial/privacy/workflow/ledger/FTS/vector migration, concrete source/
target writer inventory, human authority, operator cutover/rollback, representative
load/DR/HA and G0/G1 remain open. The next coherent source unit applies reviewed
[observation generation guards to the current collectors](LEGACY_OBSERVATION_GUARDS_PLAN.md),
without activating this copy importer on the operating database.
