# Explicit storage adapter foundation

2026-10-18 · v1.24 · private development contract `explicit-storage-adapter-v1`.

This foundation introduces a separate low-level SQL boundary and a source
inventory. It does not replace the application Store, migrate its schema or
enable an operating PostgreSQL backend. The server still constructs the existing
SQLite Store directly. Public frontend, APIs and SDK packages are unchanged.

## Application compatibility and explicit selection

`open_store(backend='sqlite', sqlite_path=':memory:')` is an optional programmatic
factory. Its SQLite branch returns the original Store and preserves its raw
connection/cursor/row and transaction behavior. Unknown backends, including
`postgresql`, fail with `unsupported_backend` before inspecting a path, importing
the application Store or an optional PostgreSQL driver, or doing file/database
I/O. URI/scheme-style DSN strings are refused. Other strings are interpreted only
as explicit SQLite filenames; no PostgreSQL conninfo parser is invoked. There is
no backend environment switch or automatic fallback.

Existing Store nesting uses the same connection context, not savepoints: a
successful inner context can commit earlier outer writes, a failed inner context
can roll back earlier outer writes, and mutation through `query()` can leave a
transaction open. Compatibility tests pin these behaviors. They were not silently
changed as part of this foundation. Direct `_db/_lock`, `sqlite3.Row`, cursor
`lastrowid`, schema scripts, FTS, JSON and independent reader/heartbeat connections
still require deliberate subsystem migration.

## New low-level interface

- `SQLiteAdapter(connection)` and `PostgresAdapter(connection)` accept explicit
  caller-owned connections. Connection use is exclusive while attached; callers
  retain responsibility for closing it. PostgreSQL requires an idle psycopg3
  connection with autocommit enabled. The module does not import a PostgreSQL
  driver, accept a DSN or open connections at import/construction.
- A frozen `Statement(name, sqlite, postgres, readonly=False)` contains separate
  trusted source SQL variants. SQL is not request input and is never rewritten by
  replacing question marks or interpolating values. Leading comments, transaction
  commands, PRAGMA/ATTACH, scripts and unsupported command channels are refused.
  Each driver executes a single statement; PostgreSQL uses server-side binding
  and explicit preparation. See the official [prepared statement contract](https://www.psycopg.org/psycopg3/docs/advanced/prepare.html)
  and [multiple-statement limits](https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html#multiple-statements-in-the-same-query).
- `with adapter.transaction(readonly=False) as session:` owns one transaction.
  `session.execute(statement, params=())` returns immutable result snapshots.
  There is no raw script or implicit execution outside an active session.
  Nested new-interface transactions are refused. A session is thread-bound;
  concurrent use of one adapter is refused, while sequential thread transfer
  depends on the supplied driver's own rules.
- `Result.rows` contains rows supporting integer/name/slice/keys/dict access.
  Duplicate column names are refused. Generated IDs use explicit `RETURNING`;
  a fake PostgreSQL `lastrowid` is not supplied. `rowcount` remains driver-native,
  including SQLite SELECT's -1, rather than claiming identical cursor behavior.
- Parameters must be an exact tuple, at most64 values/64KiB: null, signed64bit
  integers without bool, finite float, UTF-8 text without NUL/unpaired surrogates,
  and bytes. Text/bytes are at most16KiB each. Exact decimal amounts and UTC text
  can be preserved as declared text; native NUMERIC/Decimal, timezone conversion
  and accounting precision policies are not silently synthesized.
- Results are checked at1000 rows/1MiB decoded scalar values. These are returned
  data checks after driver decoding, not a universal server query-time or memory
  sandbox. Query, lock and cancellation budgets belong to the explicit connection
  policy; the isolated PostgreSQL harness sets its own bounded timeouts.

## Transaction certainty and security

An execution error poisons the transaction. Catching that error inside the block
still rolls back the whole block and reports `transaction_failed`; SQLite and
PostgreSQL cannot silently disagree by committing earlier statements. Ordinary
caller exceptions roll back and propagate. Active-session cancellation also
poisons the transaction, including when a later cursor-close operation fails.

A failed commit acknowledgement reports `commit_unknown`, even when a subsequent
rollback fails. No automatic retry/reconnect occurs, and the adapter becomes
unusable. The caller must reconcile independently; an exception does not prove a
commit was rejected. Commit interruption also disables reuse. BEGIN is marked as
requiring cleanup before awaiting its control cursor, so acknowledgement failure
cannot strand a writer lock. Cursor/config cleanup failures preserve the primary
uncertainty or cancellation and disable reuse.

Read-only sessions use SQLite `query_only` or PostgreSQL native transaction
read-only controls, in addition to the declared statement hint. SQLite's prior
setting is restored, per-cursor row factories avoid changing the connection's
factory, and existing authorizers/progress handlers are not replaced. Native
PostgreSQL read-only restricts persistent writes; temporary objects, trusted
functions and driver/session configuration are not an arbitrary-SQL sandbox.
Connections and statements must remain trusted application inputs. Explicit
autocommit/transaction ownership follows the official [transaction guidance](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

Driver text, SQL, parameters and connection addresses do not appear in fixed
`StorageError.code` messages. This is a low-level private interface, not a public
DTO or an authorization boundary for untrusted Python objects.

## Static dependency inventory

`python -B scripts/audit_storage_boundary.py --scan` reads only the fixed
`agent_market` Python source tree. It imports no source and opens no database,
configuration, environment credentials or network connection. Output contains
source-relative file/line/column/category, hashes, aggregate counts, unresolved
SQL and explicit coverage limits; it excludes raw SQL, source excerpts and string
values. The CLI accepts no database, root, source, DSN or output path.

The bounded AST scan identifies Store definitions, name-shaped tx/query calls,
private attributes, SQLite connections/cursors, lexical nested contexts and
SQLite-specific SQL indicators. Receiver types, aliases, branch/interprocedural
flow, generated/template SQL and actual nested ownership remain unresolved unless
separately reviewed. `complete` means the bounded syntactic scan completed, not
PostgreSQL compatibility or migration completeness. File hashes identify read
bytes without pretending to capture the repository atomically. Exhausted byte,
node, resolution or string-work limits produce explicit incomplete results.

## Optional actual PostgreSQL verification

The operating requirements remain unchanged. Install
`requirements-storage-postgres.txt` only in a separate verification environment;
it supplies the optional psycopg3 binary driver. The official
[installation guide](https://www.psycopg.org/psycopg3/docs/basic/install.html) describes
the driver variants. No package is installed by the application or rehearsal CLI.

`python -B scripts/rehearse_storage_adapter_postgres.py --run` accepts no DSN,
database, source, input or output path. It creates a private temporary local
cluster with fixed synthetic schemas and a Unix socket only. A fixed-code child
receives a clean environment so inherited PG credentials/services/home settings
cannot select an operating connection. Checks cover explicit ID/scalar binding,
rollback/poisoned transactions, native read-only, session/thread limits, output
bounds, concurrent single-owner CAS and stale fencing. Reports contain aggregate
checks/versions only. Missing tools/driver or incomplete checks fail explicitly.

The cluster is stopped before removal. If both shutdown attempts fail and its
private pid file remains, the mode0700 fixture is preserved and the CLI returns a
fixed error rather than deleting potentially live database files. Handled success
and failure paths are tested; abrupt process termination and OS stalls are not
automatic-cleanup or global deadline guarantees. No user project server or
operating database is started, stopped or modified.

The [verification report](../reports/advancement-storage-adapter-2026-10-18/README.md)
records final source hashes, current tests, static triage and initial findings.
This is not a full Store/FTS/auth/collector/ledger adapter, migration/cutover,
production capacity, HA/SLA or a provider-quality certification. The next unit is
the [catalog repository pilot](POSTGRES_CATALOG_REPOSITORY_PLAN.md).
