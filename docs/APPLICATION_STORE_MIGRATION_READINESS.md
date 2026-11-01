# Application Store migration readiness

`application-store-migration-readiness-v1` records current source-bound gaps
without opening a database, executing source/schema initializers or connecting
to PostgreSQL. It reuses `storage_inventory.scan()` rather than replacing the
completed bounded AST storage-boundary scanner.

Run the source-only command explicitly:

```sh
.venv/bin/python scripts/audit_store_migration_readiness.py --scan
```

No database, DSN, root directory, environment config or output path is accepted.
The report goes to stdout. Paths are fixed repository-relative Python source
locations. Source hashes bind the exact read bytes; a changed file between the
scanner and declaration pass produces incomplete evidence. Reading many files
does not create an atomic filesystem snapshot.

## What the source manifest establishes

The report includes bounded statically recognized table names, source declaration
locations, subsystem ownership labels, original scanner SQLite feature counts and
unresolved SQL counts. It emits no raw SQL, source excerpts, string literal values,
connection URLs or credentials. Source symlinks/nonregular files, parse failures,
work limits and unresolved/partial declarations are not rewritten into a zero
result or a complete-schema claim.

Named owners cover catalog/observation/search/vector, capability/evidence,
staff authentication/security, visitor privacy/consent/delivery, operational
metadata, workflows/authority/outbox, customer identities, private workspaces,
provider proofs and accounting. Unrecognized names remain explicitly
`unclassified_owner_required`. A declared owner is a migration work assignment,
not verification that an implementation exists.

The table list can include private adapter profiles and fixture schemas. Dynamic
DDL, engine-generated FTS/vector tables and migrations may add runtime objects
that syntax alone cannot resolve. `schema_coverage_complete` and
`operating_ready` therefore remain false. Successful CLI exit means only that
the bounded declaration pass completed; it never enables the PostgreSQL Store.

## Optional caller-owned fixture schema

`capture_schema(SQLiteAdapter(...))` is an internal test/rehearsal API. The caller
must already own the explicit connection; the helper never accepts a path or
creates one. An actual native read-only transaction and non-relaxed SQLite
isolation are checked. Any temporary tables/views, unsupported identifiers,
adapter errors or exceeded limits return incomplete with no partial table list.

Only table/view names and bounded column names/types/required/PK/hidden metadata
are read. Defaults, row values, DDL and keys are omitted. The schema hash captures
that declared shape, not indexes/triggers/constraints, authorization semantics,
row parity or migration completeness. Maximums are 512 objects, 128 columns per
object, 4,096 columns total and 2MiB metadata. No source/target cross-database
atomicity or transaction-throughput claim is made.

## Missing implementation versus operating decisions

The existing low-level adapter, private catalog repositories/writer, observation
ownership, fenced index artifacts, bounded source capture/owned-copy rehearsal
and selected execution/private-table PostgreSQL rehearsals are completed units
to reuse. Their isolated correctness is not an application backend switch.

The **remaining application development** is explicit:

- Replace or adapt actual legacy Store/direct SQLite call sites through reviewed
  domain repositories, including stable IDs/keys, row/NULL/time mapping,
  transaction ownership and commit-uncertainty behavior.
- Preserve full catalog mutation effects, FTS tokenization/ranking and vector
  generation/provenance semantics. The private lexical profile is not silently
  interchangeable with current search behavior.
- Implement staff/customer session and object authorization, privacy/consent,
  credential sealing, evidence/eligibility, notification destinations and restore
  revocation on the new backend, rather than only copying their table rows.
- Preserve workflow/private-run admission, fence/deadline/unknown behavior,
  replay tombstones, result delivery, deployment/automation grants and accounting
  transaction invariants through actual application repositories.
- Verify both-backend API/browser behavior, concurrent writers, rollback,
  fail-closed restore, source/target reconciliation and complete native schema
  ownership. Unsupported domains must block activation.

The **separate operating decisions** are the concrete source/target, credentials,
writer exclusion/journal boundary, maintenance window, rollback/cutover approvals,
representative workload and measured RPO/RTO/HA targets. Those decisions cannot
substitute for missing repository code. Conversely, implementation can progress
on disposable fixtures while the operating target is undecided.

The explicit caller-owned PostgreSQL application profile is now implemented for
reviewed paths; see [APPLICATION_POSTGRES_STORE.md](APPLICATION_POSTGRES_STORE.md).
It includes actual native application/API/search/vector contracts and retains
explicit source gaps. The source-only audit reports that checked-in profile
separately; it never treats its table catalog as native execution evidence or
full application readiness. The operating backend remains unchanged. No public
API switch, migration write, dual writer, server restart, actual provider call
or production readiness claim is introduced.
