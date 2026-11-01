# Typed product evidence contract

2026-10-18 · `products.compare.v2` · private inspection profile `product-semantics-v2`.

This release adds a versioned product evidence schema and an offline inspection
tool. It preserves `products.compare.v1` and the existing news/documentation
compiler, publication, SDK and one-alternative-per-run boundaries. It does not
enable product composition, product fallback or public product comparison.

## Meaning and limits

Each requested criterion has a distinct ASCII `criterion_id` and an explicit dimension.
Each result declares its product brand, model, variant, identifier scheme/value,
source URL and retrieval time. Every requested measurement appears exactly once,
as either reported evidence or an explicit missing value. The identifier field
`criterion_id` avoids the credential-sensitive generic field name `key`. Reported measurements
retain the original decimal quantity, unit, source and observation time.

The bounded unit registry supports mass (`kg`, `g`, `mg`), length (`m`, `cm`,
`mm`, `in`, `ft`), duration (`s`, `min`, `h`), storage (`byte`, decimal
`KB`/`MB`/`GB` and binary `KiB`/`MiB`/`GiB`), power (`W`, `kW`), energy
(`Wh`, `kWh`) and volume (`L`, `mL`). This is a project allowlist, not a complete
unit ontology or UCUM implementation. Cross-dimension units and unknown aliases
are rejected. Multiplication uses fixed exact decimal factors and an explicit
local arithmetic context; original evidence is retained. Decimal and binary
storage units are distinct.

Quantities and amounts are nonnegative plain decimal strings with at most twelve
integer digits and six fractional digits. Signed numbers, exponent notation,
leading-zero aliases, JSON numbers, booleans and non-finite values are refused.
Price-basis quantity must be positive. No automatic rounding, missing-to-zero
conversion, price division or currency exchange is performed.

A reported price requires amount, currency, basis quantity/unit, source and
observation time. A pack basis additionally requires its item count; other bases
must have a null pack count. Currency support is explicitly limited to USD, EUR,
GBP, CAD, AUD, JPY, KRW, CHF, SGD and NZD. These are project-supported codes, not
complete ISO 4217 coverage or validation of payment minor-unit precision.
The contract does not establish taxes, delivery charges, commercial availability
or equivalence of differing offers.

Retrieval must be within the preceding 24 hours, with at most five seconds of
future clock tolerance. Each reported observation is UTC, no later than its
retrieval and no more than 24 hours before retrieval. V2 accepts the bounded UTC
form `YYYY-MM-DDTHH:MM:SS[.1–6 fractional digits]Z` or the equivalent `+00:00`
offset. Finer precision is rejected instead of being silently truncated. This admits observations
up to 48 hours before inspection; it does not promise every observation was
made within the last 24 hours. Pair inspection preserves both observation and
retrieval times. Different observation instants prevent direct comparison even
when dimensions, currency and basis otherwise match; equivalent UTC spellings
are compared as instants.

Missing measurements or prices require null evidence fields and `partial: true`.
Reported-but-incomplete or contradictory evidence is rejected. Explicit partial
results remain partial and are never silently completed from another product.
Duplicate criterion keys, repeated measurement keys and duplicate declared
brand/identifier tuples are refused. Identity is a provider declaration, not a
verified manufacturer identity or product equivalence certificate.

## Private inspector

The current highest administrator can open **Inspect product semantics v2** from
Workflows. Its centered native dialog accepts exact JSON input and output
objects. **Validate offline sample** validates only the supplied sample and shows
original/normalized quantities, prices, times, source strings and pair mismatch
reasons. Text is escaped; source strings are not fetched or made executable.
The schema and bounded options are available for inspection.

The private routes are:

- `GET /admin/api/workflow-product-semantics/schema`
- `GET /admin/api/workflow-product-semantics/options`
- `POST /admin/api/workflow-product-semantics/validate`

POST accepts exactly `{input, output}`. Requests are limited to 128 KiB, depth
12 and 3,000 JSON value nodes, with duplicate keys, non-finite values and unknown
fields rejected. The shared contract validator additionally limits each input
or output object to 32,000 serialized characters. At most ten products and ten
criteria are accepted. Same-origin/CSRF protections, current active highest-admin
role checks and `no-store` responses apply, including refusal paths. Validation
does not save the sample. Edits, dialog closure, role/session changes and logout
invalidate pending client results; samples are not stored in browser storage.

Options report stored v1/v2 approval row counts separately from readiness. Those
counts can include historical versions and are not fresh eligible-provider
counts. Provider readiness is explicitly not evaluated by this offline tool.
It never calls a registry method that creates versions as a side effect of
inspection.

## Evidence and execution boundary

Offline success means only structural/semantic consistency with this bounded
contract. Every result explicitly denies source verification, factual accuracy,
expert review, ranking, live execution and currency exchange. Syntactic source
checks require public HTTPS addresses without credentials, private literal
addresses, secret query fields or known platform invocation gateway URLs. They do not perform DNS, fetch a source, pin
an IP address, establish source ownership or prove the declaration is true.

The registry recognizes v2 separately. An existing explicit private contract
approval requires an informational MCP tool with the exact complete v2 input
and output schemas and explicit read-only, nondestructive, idempotent hints.
A separate real execution check must be current before the explicit live v2
contract test. That test validates output and rechecks current connection version
and unchanged approval after the response. Offline inspection cannot create
callable/contract evidence, approve a tool, execute a provider, choose a winner,
publish a result or grant fallback authority.

Actual current provider schemas, successful real evidence, explicit approval,
reviewed price/product semantics and separately designed execution consent are
still prerequisites for compiler/routing integration. No existing news/docs
checkpoint or arbitrary pasted sample is presented as a retained product run.
No product fallback or cascade is introduced by this release.

## References and verification

Fixed inch/foot conversion factors were checked against the official
[NIST conversion table](https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b8).
Currency-code scope is deliberately narrower than the maintained
[SIX ISO 4217 lists](https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html).
Neither reference is fetched at runtime.

Current tests, static review, dynamic API/browser checks, immutable-source checks
and remaining operating limits are recorded in the
[release verification report](../reports/advancement-product-semantics-2026-10-18/README.md).
The user operates the development server. New Python requires one batch-end
user restart and administrator refresh; development uses isolated test data.
