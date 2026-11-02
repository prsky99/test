# Current application PostgreSQL source batch

This batch preserves the accepted v1.36 history. It adds the full known-profile
SQLite-to-PostgreSQL transfer, exact reconciliation, exclusive ownership fences
and independently authorized cutover/rollback **preparation**. A copied target
remains quarantined. There is no service switch, reverse copy, automatic replay,
operator credential discovery or operating database access.

The source catalog contains 2,922 declared statement pairs and 164 tables.
The current desktop administrator, collector listing, Visiting Agents,
Notification Preferences, Chat recommendation and URL duplicate paths have
explicit native projections or finite source-owned query families. SNS rejects
malformed historical timestamp types consistently in both backends. The actual
Chat path exposed and fixed an interest upsert that needed PostgreSQL
`GREATEST` and qualified conflict columns. Its metadata projection explicitly
sets and verifies SQLite TEMP storage in memory.

## Verification

- `final-contracts.xml`: **55 pytest cases passed**, including the native
  transfer/quarantine and desktop admin/collector proofs, failure injection,
  strict consumer validation and the previously sandbox-blocked old PostgreSQL
  workflow round-trip.
- `application-native.json`: **42 controlled native checks passed**, including
  six typed SDK2 ZIP/BFF/consent/two-node/replay/revocation checks.
- `admin-native.json`: **21 native checks passed**, including actual authenticated
  desktop routes, current role withdrawal, hostile bound inputs, Visiting Agents,
  collector filters, retention, comparison reads and controlled RAG publication.
- `migration-native.json`: **32 native checks passed**, including typed full-table
  copy, credential resealing, vector provenance, deleted-ID high-water,
  rollback-safe sequences, writer exclusion, quarantine and independent proof.
- `selection-native.json`: **62 checks passed**, including actual A2A/MCP Chat,
  current execution eligibility, a matching candidate beyond 2,000 rows, exact
  URL priority, Unicode/quote inputs and in-memory TEMP cleanup.
- `sns-native.json`: **182 checks passed**, including the repaired historical
  JSON timestamp boundary. Its pytest wrapper and sibling SQLite cases are
  recorded separately in `sns-regression.xml`.

Native subchecks are not added to pytest totals. Every native fixture owns a
disposable PostgreSQL Unix socket with TCP disabled, drops inherited connection
and secret configuration, verifies transport before writes and removes its
cluster. Provider HTTP is controlled in-process; unexpected Python TCP creation
is blocked. These guards do not claim whole-browser or arbitrary native-process
network coverage.

The earlier `regression-initial.xml` retains one stale registry-count assertion;
its corrected public16/admin8 split passes in the final layer.
`sqlite-compatibility.xml` retains 126 passes and one sandbox-blocked old native
fixture; that exact fixture passes in `final-contracts.xml`. These files remain
visible rather than being relabeled as all-pass results. The parent immutable
integration layer is a separate acceptance artifact:777inputs/97modules/1,604unique
pytest cases, failures/errors/skips0. Its [final native index](../final-native/index.json)
contains regenerated admin21, migration32, selection62 and SNS182 artifacts from
the exact final catalog. Earlier component native JSON files remain component
layer evidence; their distinct catalog hashes are not relabeled as one run.

## Secure-coding review and scope

The bounded whole-tree inventory covers 185 source files and 1,652 sinks.
`consumer-review.json` explicitly disposes of 12 residual raw expressions as
native-replaced SQLite branches, an already-open native reader or guarded
legacy schema migration. It also records separate SQLite stores and utilities;
a syntactic sink or 78/78 method map does not establish every parameter branch.

The six-file Bandit scan reports **zero high findings and 50 medium B608
findings**. Their exact report and reviewed fixed-source/parameter boundaries
are retained in `static-bandit.json` and `static-review.json`. This is not a
zero-finding scanner claim. Independent migration and consumer review is kept
alongside the native evidence.

`verification.json` binds the final source and artifact hashes. The profile keeps
`full_application_ready=false`. Public Workspace access is held; real commerce,
advertising delivery, operating migration and service activation remain disabled.
Concrete target ownership, provider/identity settings, representative workload
and operating recovery measurements are not supplied by these synthetic proofs.
