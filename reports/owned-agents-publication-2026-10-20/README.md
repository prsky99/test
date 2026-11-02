# Owned agents, workflow examples and public search metadata

2026-10-20 KST. The user authorized activation of the previously staged six
owned agents. Source and generated English frontend changes are complete.
The coding agent did not stop, start or restart the user's project server and
did not directly mutate the operating DB. The operating composition installs
the reviewed profile when the user restarts the server with this source.

## Implemented behavior

- Testbench uses Technology News, Research Papers, Country Profile and Package
  Metadata. The sources are Hacker News Search by Algolia, Crossref, World Bank
  and the npm public registry. Economic Indicators and Package Security
  Advisories add World Bank annual observations and OSV version-specific lookup.
- Three connected templates use all six tools: Daily Tech News & AI Research
  Digest, Country & Economic Indicator Brief, Package Metadata & Advisory Review.
  Later inputs bind to actual prior structured outputs. The news template keeps
  the existing default name. Downloads continue to use the managed workflow
  gateway; raw provider invocation endpoints are not embedded in exported apps.
- Activation is explicit in the operating server composition and idempotent.
  Previous builtin template rows, definitions and run history are retained in
  place with their template/active flags retired. User-created workflows and
  templates remain intact. No fixture IDs, invented quality grade or copied
  execution evidence are installed. Declared schemas and actual startup source
  checks are distinct from external MCP transport and independent grading.
- The existing gateway dispatches exact registered owned bindings in process.
  Resource admission, pinned compact/full schemas, authority, kill switches,
  durable dispatch/fence/cancellation checks and execution observation remain
  in force. A modified binding fails closed. Public source fetching still uses
  fixed HTTPS destinations, public-IP validation, TLS, response limits and
  bounded caches. No edge-security exception was added.
- Product labels and output notices are English. Source prose with non-Latin
  characters can be translated by the configured local translator, with a
  separate short budget. Unavailable translations omit affected records and
  mark partial coverage or use an English notice for optional prose; they do
  not fabricate English facts. URLs and identifiers keep their original meaning;
  international URL characters are encoded. Source contact/secret-like strings
  are masked. Latin-script language detection is heuristic; proper names and
  every third-party title cannot be certified linguistically English.
- All 43 published HTML documents have title/description, canonical URL, Open
  Graph/Twitter metadata and preview image. Nine operating public pages have
  unique descriptions and factual JSON-LD. Account/reference screens stay
  noindex and outside the sitemap. Runtime menu metadata matches initial HTML.
- The sitemap uses nine real page URLs, without hash fragments or invented
  modification dates. Public HTML links and the requested panel are available
  before script execution. Robots rules consistently exclude private account
  and invocation paths for every listed crawler. The llms guides describe the
  real examples and preserve accurate public machine-interface documentation.
- Added a local 1200×630 PNG social preview and its editable SVG source. No new
  personal contacts, private model details, deployment configuration or tokens
  are published. Workspace navigation settings are preserved.

## Verification evidence

- `activated-live/verification.json`: actual activated composition in an
  isolated DB; Testbench HTTP execution 4/4, owned handlers 6/6 and connected
  workflows 3/3 passed with real public source HTTPS. The frontend transport is
  isolated ASGI and owned dispatch is in process. This is not an externally
  deployed MCP or current operating-origin acceptance claim.
- `live-sources-network/verification.json`: six actual source calls, three
  standalone MCP workflow runs and six changed-input/source-result variants
  passed. This older standalone run retains the pre-activation news title;
  the activated run verifies the final default title.
- The first `live-sources/` attempt was run inside restricted networking and
  failed all source requests. Its failures are retained. The permitted public
  HTTPS rerun above passed; no mocked records replaced those failures.
- Browser regression covers four Run Now actions, three workflow executions,
  three downloads and the downloaded webapps' gateway execution. Separate
  cases cover private-data masking, XSS/CSP, managed routing boundaries,
  schema tampering, execution controls, account noindex, metadata consistency,
  crawler rules and existing frontend journeys. Test sources are isolated
  controlled responses, distinguished from the actual HTTPS proofs above.
- `final-regressions.xml` / `final-regressions.log`: 315 passed, zero failures/errors/skips in 132.04 seconds. All 69 selected source/publication hashes remained unchanged during this final suite.
- `content.txt`: 229 selected public source/artifact files, zero policy
  violations. The public inventory now also covers the owned agent modules.
- `ruff.json` and `bandit.json`: zero findings in the changed owned modules and
  shared metadata module; Ruff also covers the new verification script/tests.
  This is a scoped source check, not a claim that every repository dependency or
  unrelated module is free of vulnerabilities.
- PostgreSQL statement catalog regenerated with the new activation/dispatch
  statements. `postgres-source-coverage.log` records seven source/dialect
  coverage checks; this publication task did not repeat native PostgreSQL or DR
  acceptance. The catalog check reports no uncommitted generation delta.
- `source-before-final.json` and `source-final.json` record the frozen source
  and generated page/runtime hashes. Intermediate regression failures concerned
  changed copy/canonical selectors and were corrected before the final run.

## Operating boundary

The user must restart the existing project server from their own terminal and
refresh the browser. That loads the new modules, owned route/asset allowlist,
installer and readiness checks. Operating-origin/crawler/CDN acceptance after
that restart is distinct from the completed isolated development acceptance.
The local translation endpoint was unavailable in this session; translation and
failure behavior were exercised with controlled tests, not real model inference.
Public sources can still be unavailable or have partial coverage; caches retain
honest retrieval ages and the service never manufactures successful source data.

Google/AI search preparation does not guarantee crawling, indexing, ranking or
AI citations. Search Console submission and verified crawler observations were
not performed. `llms.txt` is a useful public guide, not a special Google indexing
requirement. The implementation follows Google's documented standard SEO and
visible-content consistency practices:

- [AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- [Canonical URL guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)
- [Structured data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)
