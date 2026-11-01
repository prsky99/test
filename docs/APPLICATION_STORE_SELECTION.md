# Native Store selection and duplicate projection

`PostgresSelectionMixin` provides two named, bounded methods used by the existing
public Python handlers: `selection_candidates(match,kind,cutoff)` and
`find_existing_candidates(urls,keys,raw,trimmed)`. The embedded public HTML and
its extracted mirror do not change. Protocol defaults, relevance thresholds,
security/health gates, successful-verification recency ranking, tool selection,
public projection and Chat presentation remain the existing source behavior.

## Exact current selection semantics

One current native read transaction retrieves the existing exact FTS5 matches,
visible resource metadata, relevant resource-ID/URL-linked test reports and
execution eligibility. No candidate LIMIT precedes the Python quality ranking.
The capacity is 200,000 matches/sources and 128 MiB of metadata payload; exceeding
a bound fails closed rather than returning a truncated winner.

The native database remains the sole persistent business Store. A per-request
savepoint on the existing private in-memory FTS5 connection holds temporary
metadata tables and the exact source selection SQL. This preserves SQLite
`strftime`, REAL affinity, `json_valid`, `json_extract`, UNION and latest-report
ordering without approximating them in another dialect. Separate temporary
report indexes preserve the resource-ID and URL lookup paths. The tables are
removed when the savepoint rolls back, including error paths. The adapter sets
and verifies `PRAGMA temp_store=MEMORY` before any temporary metadata, since an
in-memory main database alone does not guarantee memory-only TEMP storage. There is no
business SQLite file or persistent fallback database.

Only the public text FTS corpus uses its existing catalog epoch cache. Health,
reports and eligibility are reread on every selection in the current native
snapshot, so an unchanged FTS epoch cannot retain an old recommendation. The
subsequent Python relevance/current-version/safety gates still execute normally.
Metadata payload capacity is an input/result bound, not a process memory or
response-time SLA. A disposable 2,005-candidate timing observation is recorded
with the native fixture; it is not a service performance promise.

URL duplicate detection uses fixed native SQL with bound, deduplicated JSON
arrays. It preserves active-first, exact-URL-before-variant and ID ordering, plus
the handler's existing slash/A2A well-known/card URL and protocol checks. It does
not introduce an upstream request.

## Compatibility domain and verification

The native physical report `created_at` field remains REAL/DOUBLE PRECISION.
Numeric epoch values, numeric-text coercion and numeric Julian-date behavior are
covered. Arbitrary historical ISO text stored in a SQLite REAL-affinity column
is outside this native schema/import domain and is rejected rather than silently
inventing a normalized observation time. Opaque independent `agent_ref` values
are excluded from cross-store equality comparisons; selected resources, quality,
protocol, metadata and behavior are compared.

The isolated native/SQLite fixture covers literal quotes, Unicode catalog text,
URL variants, authentication facts without tier preference, quarantine/review,
failed evidence, default A2A and explicit MCP via the actual Chat API, fresh
URL-linked reports, latest failures without FTS text changes and a winner after
the generic 2,000-row bound. All provider/model/TCP calls are blocked. Public
Workspace access, operating database cutover and any new commercial behavior
remain disabled.
