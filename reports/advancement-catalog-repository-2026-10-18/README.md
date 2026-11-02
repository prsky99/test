# Bounded private catalog repository pilot

2026-10-18 · v1.25 · read-only selected profile, not operating PostgreSQL migration.

The planned coherent unit is complete: explicit private28-column lookup/key/batch/filter/count, native repeatable snapshots, SQLite/PostgreSQL synthetic schema/parity, public projection compatibility, security/API/browser regression and a separate atomic write migration design. This catalog batch edits no existing application sources. Adapter/frontend/SDK/dependencies stay byte-identical; concurrent Store/survey edits are recorded separately and verified from a new freeze. **This catalog pilot itself needs no restart.** Operating reflection of the separate server-loaded changes was not verified.

## Final evidence

**814 passed /100 new / failure,error,skip0** in one frozen affected selection of24 modules/76.69s. New cases are only the three added catalog modules(65+19+16); preexisting tests newly selected are not called new. Historical369(v1.24),845(v1.23),full2,878(v1.22), focused and initial runs are not added. This includes real isolated API/authority/projection, Chromium, TLS, current version evidence and existing workflow runtime compatibility. [JUnit](affected/regression.xml) · [log](affected/regression.log) · [case reconciliation](test-reconciliation.json).

All394 final source/test/supporting hashes stayed frozen in the final accepted run; prior386 are byte-identical, two concurrent Store/survey changes are recorded separately, and six Python files are new. Public content66 source/maintenance files(not pages)/violations0, HTML synchronized, SDK/package11 and public/main4 unchanged. No server import/route/operating table/backend switch was added by this catalog batch. [Hashes](final-source-snapshot.json) · [checks](source-checks.json).

Actual final PostgreSQL14.22(version140022)/psycopg3.3.6 passed17 strict boolean contract checks in1436.385ms, stderr empty and private Unix-only cluster stopped/removed. SQLite and PostgreSQL match the six synthetic records and selected read contract; no production capacity measurement is implied. CAS/repeated stale update/rollback use trusted fixture write statements, not a catalog writer API. [Actual final result](postgres-catalog-final.json).

## Concurrent source changes

The first selection passed764 cases, but source-freeze verification detected two concurrent edits outside this batch: gateway/store.py(full-schema normalization error handling) and collector/capabilities.py(usage-record failure handling). Its result is preserved in [initial-drift](initial-drift/regression.xml) and is not accepted or added to final totals. Those edits were not overwritten or claimed as catalog work. The current394 sources were refrozen; usage/evaluation modules were added and the final24-module selection ran against that stable state. [Change hashes](concurrent-source-change.json). No operator server action or live reflection check was performed for those separate changes; the catalog pilot itself adds no server-loaded import.

## Security and concrete findings

Bandit raw scope: three new catalog/fixture/CLI modules **High0/Medium5/Low1**, errors0. Five B608 warnings concern trusted source column/WHERE/fixed-placeholder construction, with all request values bound and no request-selected identifiers/SQL fragments. One B106 is the synthetic unused password for the disposable local-trust cluster, not an operating credential. Independent review records the input-to-SQL boundary. No scanner suppression, relabeling as raw0, or whole-platform absence-of-vulnerability claim. [Raw scan](static-final.json) · [independent triage](static-review.json).

A conservative isolation test first failed because SQLite read_uncommitted=ON was admitted. The guard now refuses it without mutating the setting. A concrete follow-up reproduced main/TEMP tables named pragma_read_uncommitted returning a false0; the explicit function-form probe now fails closed rather than trusting a shadow table. InitialRED1/RED2 and final cases remain in [verification](verification.json) and [independent review](independent-review.json). Three initial selected-row comparison failures were a test fixture missing sqlite3.Row, not a product bug; the original failures remain. No successful counts were invented or added twice.

Native SQLite WAL and PostgreSQL repeatable-read tests verify old-inside/new-outside reads after another connection commits. PostgreSQL default READ COMMITTED is refused, rather than mislabeled a repeatable snapshot. Closed/thread-bound views, cancellation cleanup, bounded/exact identities, oversized/malformed rows, null/empty/malformed raw JSON, injection-like bound keys/filters, stale registry hash and existing public-agent canonical URLs/redaction/schema/citation behavior are tested. Snapshot semantics depend on trusted connections; this is not an arbitrary SQL sandbox, a public DTO or an authorization bypass.

## Delivered boundaries and limits

The [read contract](../../docs/CATALOG_REPOSITORY_CONTRACT.md) explicitly selects28 fields. It preserves private original bindings, JSON TEXT/nulls and inactive/down/quarantined facts without creating Registry/version/callability/evidence rows. Record repr hides values; a fresh as_private_dict remains private and must not be published. Existing public projection is tested using an explicit selected public value and store=None, avoiding Registry enrichment writes.

Batch and page bounds are50, input duplicates collapse by first occurrence, list order is idASC keyset and count ignores the page cursor. These are not Chat relevance/newest ranking, FTS/BM25/vector ordering or unrestricted Store.resource parity. Row/payload checks reject rather than truncate. Adapter total result bounds apply after driver decoding; count/query CPU and operating latency remain unmeasured. Hash preconditions are observed registry content only, not execution versions/permissions or protection against later updates.

The current bounded static inventory completes119 Python files/2647333bytes/4792 syntactic findings, including122 unresolved SQL-call markers. Source hashes match; no code import/DB/config/network or raw source/SQL/value output. Runtime receivers/aliases/nested ownership, complete migration and an atomic repository capture are not inferred. [Inventory](storage-boundary-inventory.json).

The [write migration contract](../../docs/CATALOG_WRITE_MIGRATION_CONTRACT.md) records exact key/ID/hash/reset/null/FTS/vector/evidence and nested transaction behavior, separating observed legacy quirks from proposed future guarantees. It is design only. No catalog upsert, revision table, index job or collector wiring was implemented. Full Store/search/credential/admin/visitor/workflow/ledger migration, operating DSN/cutover/rollback, representative load/DR/HA/RPO/RTO, actual human/provider quality and R-07/AC-08/G0/G1 remain open.

No new operating UI/API acceptance was attempted; the prior authenticated v1.22 inspector observation remains historical. Operator server actions/direct live DB writes/provider/model tasks/approvals/grants/notifications/marketing0. PostgreSQL fixtures reuse the previously verified clean-environment/private-socket cluster lifecycle; their CLI accepts --run only, never an operating connection/path, and retains a possibly live private fixture if shutdown cannot be confirmed.

Next: [atomic catalog writer·revision-bound index work](../../docs/POSTGRES_CATALOG_WRITER_PLAN.md). [Platform design](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md) · [remaining order](../../docs/REMAINING_WORK_BATCHES.md).
