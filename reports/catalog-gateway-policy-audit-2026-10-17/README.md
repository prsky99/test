# Whole-catalog compatibility and live Testbench examples

2026-10-17 · Internal development verification. The user controls the running server.

## Final result

- Read-only snapshot: **106,270 catalog resources** (33,224 MCP, 26,629 A2A,
  46,417 x402). All resources were checked against public admission metadata.
- **280,681 stored MCP tool definitions**, from 19,106 MCP resources, were checked
  against the old and corrected policies. No audit exception occurred. Missing
  capability definitions are not treated as successful executable-agent tests.
- **2,029 definition occurrences / 1,191 unique tool names** had confirmed noun
  collisions corrected. The same snapshot has **zero newly refused tools that
  passed the previous policy**. The classifier still conservatively refuses
  unsupported/unsafe or insufficiently described operations.
- **5,955 destructive name mutations** were refused. The full permanent corpus
  is retained in `tests/fixtures/catalog_readonly_tool_names.json`.
- **36,082 distinct schema/example validation cases** were evaluated offline.
  Across allowed definitions, 97,397 generic examples validated; 33,260 require
  manual inputs and 98 generated examples are rejected and must not be published
  as runnable samples. These counts describe stored schemas, not full live
  provider-schema pinning or task success.
- **305 final API/browser/security/TLS/workflow regression cases passed**, zero
  failures and skips, in `final-regression.xml`. Other XML files preserve earlier
  development iterations; they are not the final pass/fail decision.
- Public frontend content: **52 files, zero violations**. Embedded HTML and
  `extracted_html.txt` match. Workflow SDK and ZIP-builder source hashes remain
  unchanged from the prior repair.

The collector continued adding records during the investigation. Earlier scan
files/commentary have smaller counts; the figures above all come from the final
single read transaction in `catalog-audit.json`.

## Additional causes corrected

The first repair only exempted the noun `signals`. Whole-catalog inspection found
further collisions: `skills`/`kill`, `credit`/`edit`, `design`/`sign`, `posts`/`post`,
and query objects such as books, orders and claims. The shared guard now recognizes
complete words and camelCase, requires a declared read-only informational query
for new exceptions, and retains action checks elsewhere in the same name.
Conjunction/action combinations such as `getAndBookHotel`, `get_then_post`,
`getPlaceOrder`, delete operations and transaction signing remain refused. It does
not infer real provider safety solely from a declared hint.

The audit also found **144 stored definitions with a literal input field named
`pattern`**. The prior recursive validator confused property-map keys with JSON
Schema keywords. Ordinary field names now validate normally, including required
types; actual regex constraints and remote references remain refused. This does
not make all 144 definitions callable: their other admission/safety conditions
still apply. Workflow and Testbench now share the same bounded validator.

## The four Run Now cards

The user correctly observed `Demo only. No provider was contacted.` because the
four original cards were non-executing format demonstrations. That was intentional
simulation behavior, not a successful agent test or a provider outage.

The main cards now execute four reviewed live MCP recipes through positive
registered IDs: Technology news, Camera documentation, Racket comparison research,
and Famous train routes. Both API admission and inputs are checked when recipes
are resolved. Ineligible or missing bindings disable the relevant card; there is
no silent fallback to a negative demo ID. The old format demonstrations remain
clearly separate in the agent selector and legacy API `presets` array. Generic
A2A and x402 registered tests remain supported outside these four MCP recipes.

`Run Now` still runs the same managed execution service; no direct browser access
to upstream providers or provider credentials was added. Home/Test copy and
metadata were updated. The bootstrap cache is scoped to its backing store so a
separate app/store cannot supply the wrong example resource IDs.

## What actually ran

- Real public HTTPS providers, disposable DB: all four reviewed recipes returned
  completed, non-simulated results. Individual gateway times were approximately
  1.42s, 1.88s, 2.02s and 2.00s. These observations are not performance guarantees.
  The test did not mutate the production catalog or production execution history.
- Isolated Chromium: clicked each of the four actual Run Now buttons, observed
  one provider invocation per click and `Completed`, with `simulated=false`.
  The screenshot uses a controlled provider fixture, not production result data.
- Controlled dynamic requests covered the corrected noun families, managed MCP
  discovery/execution, Testbench, workflow and downloaded-app execution. Literal
  `pattern` input passed all three execution paths; real regex/reference schemas
  remained blocked. Existing SSRF/rebinding, credentials, destructive tools,
  schema drift, rate limits, CSP/XSS, capability authorization and TLS cases pass.

**All 106,270 external services were not invoked.** The exhaustive part is local
catalog/admission/schema compatibility. Credentialed, unsafe, inactive, schema-less,
unsupported and manual-ID tasks were not force-run. Their intentional refusals
are retained and counted. Testing arbitrary third-party side effects is outside
this verification; no payment, marketing or credential-bearing task was sent.

## Static review and activation

Bandit on changed execution/example/frontend/workflow/audit modules: High 0,
Medium 8, Low 11. Findings remain the pre-existing parameterized fixed-fragment
SQL and optional metadata/fallback handling in `front.py`. There is no additional
finding category/count against the prior scan; new/changed policy, examples,
workflow and audit modules have no findings. This is not a blanket certification
that the whole service is vulnerability-free.

The running local/public APIs still returned four format demos and no
`live_examples` at the last read-only deployment check. **Restart the existing
server in the user's terminal and reload the browser** to activate the new cards
and expanded policy/validator corrections. No project server was stopped, replaced,
restarted or launched by the agent; no security policy was disabled.

## Reproduce and evidence

Run the reusable non-network audit with:

```sh
.venv/bin/python -m scripts.audit_gateway_catalog gateway-data/collector.sqlite3 /tmp/catalog-audit.json
```

Evidence: `catalog-audit.json`, `live-examples-proof.json`, `final-regression.xml`,
`final-corpus.xml`, `bandit.json`, `deployed-state.json`, `verification.json`,
`source-snapshot.json`, `four-live-examples.png`. The initial scan and earlier XMLs
remain diagnostic history. No secrets or production result payloads are included.
