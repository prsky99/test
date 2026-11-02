# Gateway execution compatibility repair

2026-10-17 · Internal implementation and verification record.

## Cause and observed failures

The additional shared admission check used `usage._DENY.search(tool_name)` even
when a registered provider explicitly marked a tool read-only. The signing verb
`sign` matched the noun in `get_latest_signals`, `search_signals` and `get_signal`.
Consequently, the managed MCP listing omitted these tools and Testbench / shared
MCP proxy execution refused them before contacting the provider. The published
news workflow uses that proxy; downloaded apps call the same workflow API, so both
inherited the failure. An operational history read confirmed three recent failed
news runs at the first agent node and an earlier successful run. No operational
workflow, resource, security rule or historical run was altered.

The prior restart check covered metadata, initialization and rejection paths. It
did not execute production provider tasks, and a valid empty tool list did not
expose this execution regression. This repair adds actual recipe-name and workflow
coverage rather than treating metadata reachability as task success.

Two frontend mismatches compounded test failures: hardcoded weather/search/ping/
echo shortcuts added names that were not registered on the selected live agent;
most registered tools received `{}` even when they required inputs. Also, late
asynchronous detail responses could overwrite a newer agent selection, and Run
could read a selection before loading finished.

## Changes

- `execution_policy.py`: one shared safety predicate distinguishes only the
  complete informational noun `signal`/`signals` from signing operations. Existing
  read-only classification remains required. Destructive verbs elsewhere in a
  name, signing operations, required credentials, malformed metadata and unknown
  tools remain refused. Full-schema required fields also participate in the
  credential check. No broad dangerous-name bypass was introduced.
- `managed_gateway.py`: MCP tool listings use the same safety predicate as
  execution, so the advertised safe tools agree with admission.
- `front.py`: detail tools use the same allowed set; generic samples are generated
  from public schemas and validated. Provider defaults, stored examples and private
  trial arguments are discarded. Identifiers without a safe example stay manual.
- Embedded frontend and `extracted_html.txt`: shortcuts reflect registered tools,
  required fields are explained, invented shortcut tool names are refused, and
  versioned asynchronous selection prevents stale responses from replacing the
  current selection. Run waits for loading, and history retains the executed
  agent rather than a later selection.
- Public workflow SDK / ZIP builder and admin export implementation are unchanged.
  The shared server executor fixes workflow and existing connected-app execution
  without restoring direct upstream URLs or changing package contracts.

## Verification

- Passing suites: 154 general regression cases, 48 browser/security/TLS cases,
  then 137 final core cases after the final safety guard changes. These represent
  **188 distinct passing cases / 339 passing executions**, with no skips in those
  suites. `news-regression.xml` preserves an earlier test-development iteration
  whose download assertion incorrectly compared text to bytes; the assertion was
  corrected and subsequent runs passed. It is not included in the passing totals.
- Chromium under enforced CSP: registered news/search execution; required example
  input; stale selection response; published two-agent news workflow; ZIP download,
  separate customer origin hosting, SDK run and completed output. Existing API,
  SSRF/rebinding, hash drift, destructive tool, credentials, XSS and TLS regressions
  also pass. Screenshots contain synthetic fixture data.
- Separate real-provider proof, with a disposable DB and unchanged TLS/public-IP/
  schema-pinning checks: all three currently published recipes succeeded in the
  Testbench API, both workflow agent steps and ZIP generation. First-step gateway
  times were approximately 1.4 seconds (news), 2.0 seconds (documentation) and 1.9
  seconds (rackets). These are individual observations, not latency guarantees.
  Only registered read-only requests ran; no payment or marketing delivery ran.
- Public content check: 51 files, zero violations. Embedded HTML matches the
  extracted source. SDK and ZIP-builder hashes match their earlier baseline.
- Bandit on the three changed Python modules: High 0, Medium 8, Low 11. These are
  retained pre-existing fixed-fragment parameterized-SQL and optional metadata/
  fallback findings; no additional finding category/count versus the earlier
  snapshot. The shared admission and managed handler modules have no findings.
  This is scoped static review, not a claim that the entire product is certified
  vulnerability-free.

## Activation and limits

The user runs the project server in their own terminal. It was not stopped,
restarted, replaced or competed with. Final read-only checks returned 200 from
both local and public services, but the new controls and sample fields were not
loaded. **The user must restart their server and reload the browser** to activate
this repair. Do not interpret isolated new-code success as a deployed-code success.

Runtime health, changing provider schemas/data, unavailable endpoints,
authorization requirements, unsupported schemas and input errors can still cause
truthful refusals. Those safeguards and eight-second managed / twenty-five-second
workflow budgets remain. Full G0 and the advanced roadmap remain open as recorded
in the platform design; this bug fix does not implement automatic fallback.

## Artifacts

- `verification.json`, `source-snapshot.json`, `bandit.json`
- `isolated-live-diagnostic.json`, `provider-readonly-schema.json`
- `real-provider-proof.json`, `deployed-state.json`
- `regression.xml`, `browser-security.xml`, `final-regression.xml`
- `testbench-completed.png`, `workflow-completed.png`,
  `downloaded-app-completed.png`
