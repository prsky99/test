# Owned data agents — public activation prepared

2026-10-20 KST. The initial development-only package is now explicitly enabled
by the operating frontend composition following user authorization. A user-run
server restart loads the routes and performs the idempotent catalog/template
installation. No project server was restarted by the coding agent.

The four Testbench examples and three connected templates use all six tools.
Existing builtin workflows are retired in place, with full definitions and run
history retained; custom workflows and templates are preserved. Imported package
factories remain disabled by default. The managed execution gateway uses exact
first-party bindings with pinned schemas and the existing authority, control,
fence and cancellation checks, avoiding a self-HTTP call through the edge.

English prose is translated by a separately bounded configured local translator
when available. Unsupported source records are omitted and marked partial;
optional untranslated prose receives an English unavailability notice. Links and
identifiers retain their facts. Translation is not an authority to invent data.
The local translation endpoint was unavailable during this publication check;
translation and failure behavior are covered by isolated tests. Latin-script
language detection is heuristic, not a guarantee of semantic English for every
third-party proper name or title.

Public HTML receives page-specific canonical URLs, English metadata, Open Graph,
Twitter preview and factual JSON-LD. Public discovery uses real page URLs in the
sitemap and llms guides; private account and execution paths stay excluded.
See `reports/owned-agents-publication-2026-10-20/README.md` for actual validation scope.

## Local execution and timeout corrections (2026-10-20)

Owned agent logic executes in the current server or worker process. Public
endpoint URLs are discovery/connection addresses, never a requirement to call
our own public domain from the execution gateway. Fresh proxies and standalone
workers resolve the already approved profile and share a Store-local engine.
Missing or changed first-party identities fail closed instead of falling back
to remote MCP. Exact first-party resource keys also prevent a newer duplicate
URL listing from replacing the owned Testbench or template binding.

Agent work has a six-second budget including same-input coalescing. Source
fetches have a five-second absolute sub-budget and four-second socket timeout.
Optional translation is limited to one short local-loopback call; external
model endpoints are refused. The gateway's eight-second test execution budget
and the standard workflow's 25-second hard deadline remain unchanged.
File SQLite uses a 20-second ownership lease to tolerate its normal ten-second
writer wait. Heartbeats retry briefly under contention without reviving expired
owners, replacing fences or extending original run deadlines.

Completed owned reads do not wait behind catalog writers for optional call
counters or quality-evidence updates. These writes use a short lock/busy budget;
contention is counted and logged, and the write may be skipped. This never
fabricates fresh verification evidence. Dispatch authorization, checkpoints,
run completion and result delivery retain their mandatory durable transactions.

Live-source acceptance forbids proxy HTTP self-calls while executing all six
agents, four Testbench examples and three connected workflows. Separate worker,
duplicate binding, cancellation, schema, checkpoint and actual nine-second
SQLite writer-lock regressions cover the local execution boundary.

## Six independently registered capabilities

The implementation lives in `agent_market/owned_data_agents/`. Each agent has
one stateless MCP endpoint and one read-only tool with bounded input/output
schemas. The endpoint factory is disabled by default. Importing the package
neither fetches data nor creates routes or catalog entries.

- Technology News — Hacker News Search by Algolia; keyword-dependent recent
  stories ordered by publication time with source links. Selected for Testbench.
- Research Papers — Crossref bibliographic search; titles, DOI links, publisher
  and the publication date precision provided by the source. Selected for Testbench.
- Country Profile — World Bank country metadata: country, capital, region and
  income classification. Selected for Testbench.
- Package Metadata — npm public registry: the current version, description,
  license label and package URL. Author identities, emails, scripts and
  installation instructions are excluded. Selected for Testbench.
- Economic Indicators — World Bank annual population, GDP or life expectancy
  observations, with the actual observation year and unit. The default workflow
  selects population. Latest available does not mean current-year measurement.
- Package Security Advisories — OSV lookup for the exact npm package/version.
  A response with no matches is not a claim that the package is secure.

The agents implement data retrieval; they do not require model inference,
subscription login, a third-party agent service, a wallet or credentials.
They still depend on public data source availability and usage policies.

## Three prepared workflows

1. Technology News & Research Brief: news query → the recorded upstream query
   becomes the research agent input. Both stages return source-backed results.
2. Country & Economic Indicator Brief: country profile → its resolved country
   code becomes the population indicator input.
3. Package Metadata & Advisory Review: current npm package metadata → the exact
   returned package name/version becomes the OSV query. A moving `latest` alias
   is never sent in place of that resolved version.

Each graph contains a manual trigger and two agent nodes. All six agents are
used across the three graphs. The existing workflow runtime retains structured
outputs for data transfer and uses bounded readable text for display. No workflow
graph semantics and frontend export SDK remain unchanged. The timeout corrections
above also apply to runtime ownership and local gateway dispatch.

`staging.bundle()` returns six endpoint/tool definitions, four Testbench recipes
and three graphs. It is declarative only and always reports `applied: false`.
The operating frontend composition uses its explicit, idempotent activation
profile; the staging bundle itself performs no installation.

## Reliability and security

- Real source JSON is normalized; there is no hard-coded record fallback and no
  generated substitute result. Empty source results remain empty.
- A bounded in-memory cache reduces repeated calls. Retrieval time stays fixed
  when a cached record is returned. `live`, `fresh_cache` and `stale_cache`
  explicitly distinguish the result origin/freshness. A source failure can use
  only a previously validated real response within its finite stale limit.
  Otherwise the tool returns a safe `isError` response, not success.
- Identical concurrent requests share source work. Four active source calls,
  finite lock waits, bounded cache keys and a short failure cooldown prevent
  unlimited work or immediate retry storms. There is no automatic call retry.
- Source origins/methods are finite. HTTPS certificate checks, public-IP DNS
  validation, connection pinning, aggregate deadlines, response byte bounds and
  redirect denial reuse the existing secure outbound client.
- Country/package/version semantics are checked before networking. Public MCP
  schemas use the gateway's supported offline schema subset; its pattern/ref
  restrictions are preserved rather than weakened for these agents.
- No arbitrary URL, credential, email, private path or extra authority field is
  accepted as a search destination/input. Inbound session/cookie/authorization
  headers are not forwarded. Source author/contact/script fields are not exposed.
- Duplicate/non-finite/oversized source JSON, source errors, malformed MCP
  requests and quota exhaustion are denied safely. Raw errors and stack traces
  are not included in protocol responses.
- Source citations and timestamps are returned. First-party ownership never
  creates an evaluation grade, independent quality evidence or ranking boost.

## Verification and reproduction

From the project root with its existing Python environment:

```sh
.venv/bin/python -m scripts.verify_owned_data_agents --live \
  --output reports/owned-agents-verification-001
```

The output directory must be new. This command creates its own disposable
SQLite proof DB and in-process MCP transport, uses actual verified HTTPS for the
public source calls, and prepares a future bundle without registering it in the
operating catalog. It never starts or restarts the project server. It performs
six default agent calls, three graphs and six changed-input calls. A failed
source remains a failed verification; no mock results replace it.

The automated fixtures deliberately use controlled source JSON only in tests:

```sh
.venv/bin/python -m pytest -q tests/test_owned_data_agents.py \
  tests/test_owned_data_agents_browser.py
```

The browser test substitutes future recipes/definitions only inside its own
process and database, then executes four Testbench examples, three workflows
and three exported webapps against the current frontend/SDK contracts. It does
not publish those substitutions. The recorded final suite also covers existing
first-party retrieval, Testbench initialization, template execution, DNS
rebinding and oversized response refusal.

Evidence: `reports/owned-data-agents-2026-10-20/README.md` and
`verification.json`. Final selected suite: 75 passed, no failures/errors/skips;
new-code Ruff/Bandit findings: zero. Six actual source queries, three actual-data
workflow runs and six changed-input/source-result pairs succeeded. The MCP
transport was isolated ASGI, not a public deployment acceptance test.

## Operating rollout

The gateway server composes the frontend with `owned_data_agents_enabled=True`.
Its activation installer registers six finite source-backed capabilities, records
the locally declared schemas, creates three new versioned builtin templates and
retires only the old builtin templates in place. Startup executes actual source
lookups to establish readiness; it does not invent remote HTTP status, quality
grades or contract evidence. Subsequent normal collector observations remain
in force. Fresh data is served through the existing managed execution gateway.

The user's existing server must be restarted from their terminal to load the
new modules, route allowlist and installer. The coding task does not start or
restart the project server. A deployed-origin smoke check after restart remains
separate from isolated ASGI and live public-source acceptance. Search Console
indexing and real crawler/CDN acceptance are external outcomes, not test passes.

Current verification includes `scripts/verify_owned_agent_publication.py`: it
creates a new isolated DB and uses the actual activated frontend composition,
Testbench HTTP APIs, all six handlers and three connected workflows with real
public source HTTPS. It accepts no existing operating DB path. The older
`verify_owned_data_agents` script continues to verify the standalone MCP transport.

## Source references

- [Hacker News Search API](https://hn.algolia.com/api)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [World Bank country queries](https://datahelpdesk.worldbank.org/knowledgebase/articles/898590-country-api-queries)
- [World Bank API call structures](https://datahelpdesk.worldbank.org/knowledgebase/articles/898581-api-basic-call-structures)
- [npm registry API](https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md)
- [OSV API](https://google.github.io/osv.dev/api/)
