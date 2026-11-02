# Ten-workflow development verification — 2026-10-19

## Outcome and boundary

Ten research workflow scenarios were created and executed in an isolated customer Workspace with ten distinct synthetic MCP agents. Chrome computer use created all ten workflows through the actual customer editor, reviewed their exact inputs, granted fresh per-run consent and confirmed successful step results. A separate input-change control copy also succeeded.

These are data-flow tests, not evidence of external provider accuracy. **The live service currently exposes zero eligible typed-agent connections to the test organization. No ten-workflow production run, provider approval, public launch or production test-data insertion is claimed.** The previous step-reference correction was confirmed after the user's restart. New ten-step support requires a further user-operated restart because it was implemented during this task.

## Ten scenarios

These are illustrative common research use cases, not market-share rankings. All use the currently supported `docs.search.v1` input/output contract and explicitly declared prior-output bindings; no unsupported summarizer, trading, email or publishing action is invented.

1. Daily Technology Research — 2 agents.
2. Stock News Context Research — 3 agents; public terminology/source research, no trading or investment action.
3. Security Advisory Research — 4 agents.
4. API Integration Research — 5 agents.
5. Competitive Product Research — 6 agents.
6. Ecommerce Operations Research — 7 agents.
7. Sustainability Research — 8 agents.
8. Learning Resource Research — 9 agents.
9. Product Launch Research — 10 agents.
10. Customer Support Research — 10 agents.

Reviewable scenario specifications are in [scenarios/](scenarios/). They deliberately use **unresolved resource slots**, rather than IDs that could accidentally refer to a production resource. They are not executable imports until every slot is resolved to a currently verified and explicitly approved connection.

## What was verified

The first step receives literal `query`, `language: en` and `limit`. Each later step binds its `query` to the immediately preceding step's `items[0].title`; its own language/result limit remain explicit literals. Before execution, the whole graph and every destination are reviewed and authorized once.

For each of the ten automated scenarios:

- The original input ran successfully with one result per step.
- Each recorded downstream request exactly matched its declared prior output. Each synthetic agent produced a new title derived from that received input.
- Changing the initial query focus changed every downstream request and final output.
- Changing `limit` from 1 to 2 changed the number of returned items at every step.
- Reusing the same consumed ticket returned the retained run without additional provider calls.

This evidence run contains **20 successful executions and 128 synthetic tool calls**. Full request/result pairs are in [input-output-evidence.json](input-output-evidence.json). The two ten-step scenarios also passed the signed execution-evidence snapshot reader with all ten recorded steps.

Independently, Chrome computer use created the ten original workflows and one revised-input control copy: **11 successful executions, 74 synthetic tool calls**. The original and revised ten-step support-research outputs visibly differ; the latter contains two results per agent. See [cua-results.json](cua-results.json), [cua-fixture-trace.json](cua-fixture-trace.json), [workflow list screenshot](screenshots/workflow-list.jpg) and [final ten-agent output](screenshots/ten-agent-final-output.jpg).

A rapid UI sequence encountered an unconfirmed pre-dispatch request. Retained history showed that no run had been accepted. The request volume was consistent with the existing 60-per-minute customer authoring limit; the exact HTTP status was not captured in that CUA observation. After waiting and reading history, a fresh input review and explicit consent produced exactly one seven-step execution. No automatic resubmission was used. Separately, deterministic API/browser tests verified the HTTP 429 path and its Retry-After response.

## Development changes

- Typed graph execution now supports **10 nodes / 10 calls**, including up to nine declared predecessors, while preserving fixed schema-path validation, contracts, current approvals, credentials policy, signed authority and once-only dispatch.
- Customer editor, admin typed editor, explicit plan reviews, model envelope validation, support patch indices, intent bounds, evidence reader and typed web-app package copy now agree on the ten-step cap. The separate legacy single-task/graph profiles retain their own limits.
- Existing step references are preserved when another step is removed or added.
- The customer editor now displays ordered, confirmed per-step results. Output values are inserted as text; markup is not interpreted, and source URLs are plain text.
- Authoring rate limits return `Retry-After: 60`. The typed editor gives a clear wait/history message, discards the pending UI ticket and never retries automatically.
- User-facing copy and guides remain English. The public Workspace link remains hidden.

Runtime bounds remain **60 seconds overall, 12 seconds per node**, with the existing concurrency, daily quota, input/output size, authority and unknown-outcome controls. Ten slow remote agents may exceed the total deadline; the synthetic success cases are not a remote-latency guarantee.

## Regression and security verification

**134 distinct targeted regressions passed; no product-test failures, errors or skips remain.** The first integrated run passed 130 cases. After the final rate-message/renderer changes, affected browser tests and new scenario/security cases were run again; repeated cases are counted once.

Evidence: [integrated regression](regression.xml), [final affected cases](final-affected.xml), [scenario and rate API cases](scenarios.xml), [output security browser case](output-security.xml), [verification scope](verification.json).

The cases cover ten-step success, rejection of eleven steps, invalid object projection, fresh consent, same-ticket replay, current permission checks, unknown outcomes, release/SDK compatibility, typed evidence, proposal boundaries and browser rendering. An HTML-shaped string was passed through all ten agents and persisted through history reload: **no script/image/iframe was created, no unexpected browser outbound request occurred, and history caused no additional tool call**.

- Public content check: **92 files, 0 violations**.
- Critical Ruff selection E9/F63/F7/F82: **0 findings**.
- Bandit: **0 High / 1 Medium / 0 Low**. B608 is Low confidence on the embedded HTML/JavaScript template. Manual review confirms the view constructs no SQL and executes no database queries; the finding is retained as a false positive, not suppressed. See [bandit.json](bandit.json).
- PostgreSQL SQL catalog: 3,472 statements / 223 tables. SQL/schema/behavioral fields were compared before refreshing only source hashes and source line labels; the final drift check passed. No native PostgreSQL runtime test is claimed for this task.
- Tracked source hashes: [source.json](source.json).

## Live service and cleanup

Actual Chrome sign-in reached the Google-owned test organization through its normal menus. The restarted live editor generated unique references after middle-step deletion/readdition. Its approved agent selector contained no eligible candidate. Direct address navigation was refused by the session/origin boundary; that response alone is not treated as proof of object-level authorization.

No synthetic agent was added to the live catalog, no live connection was approved merely to obtain a passing test, and the live customer session ended signed out. The user-operated server was not stopped or restarted. The temporary loopback fixture was stopped and its temporary database/keyring removed.

To review the same synthetic scenarios in an isolated local browser later, run the dedicated fixture from the repository using `.venv/bin/python`, with `PYTHONPATH=.` and `--preload`:

```sh
PYTHONPATH=. .venv/bin/python reports/workspace-ten-workflows-2026-10-19/ui_fixture.py --preload
```

It prints a loopback-only URL and creates a new temporary synthetic environment. It never reads or mounts the operating application database or credentials. Stop that dedicated fixture with Ctrl-C after review. This is a test harness, not a deployment server.
