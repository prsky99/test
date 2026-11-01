# Reviewed capability adapters

The private typed runtime normally requires an exact registered contract schema.
Existing live tools often return valid native data with a different schema. A
reviewed deterministic adapter bridges a narrowly selected native tool while
preserving its actual endpoint, full schemas, annotations and connection version.
It does not invent a provider, rewrite its registration or grant execution access.

The initial `paper-docs-v1` profile supports the existing Paper Finder
`search_papers` tool as `docs.search.v1`. Its exact native input/output schemas and
read-only, non-destructive, idempotent annotations are fixed in
`agent_market/capability_adapter_profiles.json`. The endpoint/tool/contract tuple
is fixed in code; user-supplied endpoints, expressions, mapping rules and arbitrary
transform code are unsupported.

Logical inputs remain `{query,language,limit}`. The provider receives only its
native `{query,limit}`. Query length must satisfy the native 200-character limit;
values are rejected rather than shortened. Whole-graph execution review includes
a notice describing the paper-index source, native restriction and non-endorsement.

Normalized results contain actual paper titles and source URLs. Excerpts identify
these as paper-index records and include only returned title/venue/year/index
metadata. They are not fabricated abstracts or generated summaries. The provider's
own `as_of` time is retained and must agree with `asOf`; missing, stale, future,
inconsistent, unavailable, over-limit or mismatched-query responses are rejected.
Partial-source notes remain partial. No source timestamp is refreshed by the adapter.

An administrator must explicitly approve the current native tool and perform a
real contract test. The test uses the ordinary managed gateway and its current
schema/SSRF/TLS/budget/charge controls. It records normalized contract evidence with
an adapter-specific dataset identifier derived from the frozen native schema and
loaded implementation hash. Old generic evidence is insufficient. A source schema,
annotation, binding or implementation change prevents reuse of that evidence.

Typed workflow versions and one-use tickets pin the adapter descriptor in addition
to their existing current authority, source binding, policy and version pins. Every
literal/projected input is validated before conversion and dispatch. Original
logical input hashes and normalized outputs remain in the existing signed/encrypted
execution lineage. Ordinary native-schema execution and all other contracts retain
their existing path.

A complete but invalid adapter result records a failed step and contract rejection,
stops downstream dispatch and records negative adapter-contract evidence for that
same source version. Native transport success is retained separately. Timeouts,
lost responses and changed authority retain their existing unknown/fail-closed
behavior and are never automatically resubmitted.

Offline tests use isolated synthetic responders. A separate real public probe is
recorded in `reports/workspace-account-samples-2026-10-19/live/`; that probe alone
is not an administrative approval, production contract test, independent factual
quality score or completed customer sample installation.

## First-party Research Papers

`owned-research-docs-v1` also maps the exact registered first-party
`search_research_papers` capability to `docs.search.v1`. The public endpoint
identifies the registration; dispatch executes the local data engine rather than
making an HTTP call back through the service. Only the fixed Crossref public
source is queried. Full identity, schema, annotations and immutable version must
match. Logical English queries are preserved up to 500 characters; native results
are capped at five and a larger logical limit is explicitly marked partial. DOI
records and their original retrieval timestamps are preserved, including cache
age; the adapter does not generate research content or freshen old sources.

Startup upgrades only the exact preceding 160-character first-party schema. It
creates neither contract approval nor success evidence. Use
`scripts/activate_owned_workspace_contract.py --db <active-db>` to inspect the
exact version, then explicitly apply that version with `--apply
--expected-version <cv-reference>`. Confirm the active server's actual DB path;
do not assume a default database. The CLI starts no server and changes no public
navigation. Its real local call must yield verified transport/protocol evidence,
current execution readiness and successful normalized contract evidence. Missing
optional analytics alone cannot produce a success claim. Audit records distinguish
an explicit operator check from a browser administrator action.

The original Paper Finder implementation is retained byte-for-byte in
`paper_capability_adapter.py`, preserving implementation digests in existing
signed workflows. The dispatch facade and first-party adapter have a separate
first-party implementation digest. Existing customer workflows and uncertain
runs are retained; they are not migrated or replayed automatically. See
`reports/workspace-defect-remediation-2026-10-20/README.md` for local-source,
contract, browser and credit acceptance evidence.
