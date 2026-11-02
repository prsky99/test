# Workspace AI generation — three-case test result

**The requested three AI-generated workflows could not be created. New saved workflows: 0/3. This is a failed feature test, not completion of AI workflow creation.** The existing ten real workflow samples remain saved and unchanged.

## Current workspace UI

Chrome was used in the existing Google-owned customer workspace. Public objectives for research discovery, software-security research and customer-support research were entered separately, with explicit model-input consent. `Suggest a workflow for review` remained disabled in all three cases. Other editing controls remained available. The UI enables this button only when the current factory reports a configured model proposer; trusted runtime integrations default this proposer to `None`. The operating workspace therefore does not currently expose a connected AI proposer.

See [three UI observations](ui-cases.json), [disabled generation screenshot](ai-generation-unavailable.jpg), and [final retained state](final-ui-state.json).

## Actual local AI attempts

The already running local AI service was available. No project server or model server was launched or restarted. The existing concrete `OllamaGraphProposer` was called independently of the disabled customer UI, using the same public-objective envelope, approved resource 34807 / `docs.search.v1`, declared contract schemas and node limits. No account identifiers, session, email, credential, private graph or private file was supplied.

- **Research Discovery:** the proposer rejected the response after approximately 2.029 seconds. No usable proposal was returned. [Attempt 01](attempt-01.json).
- **Security Research:** the response arrived after approximately 1.852 seconds, but its nodes used numeric IDs and contract IDs, string inputs, and omitted required graph fields. The actual typed-definition validator rejected it. A raw JSON response is not a valid workflow. [Attempt 02](attempt-02.json).
- **Customer Support Research:** the proposer rejected the response after approximately 2.006 seconds. No usable proposal was returned. [Attempt 03](attempt-03.json).

The concrete transport uses a two-second HTTP read limit, a six-second body limit and an eight-second factory limit. Two rejections occurred near the read limit, suggesting a timeout constraint; the public `WorkspaceInvalid` exception does not retain a diagnostic code in these saved attempts, so timeout is not asserted as their definitively proven cause. The exact malformed output in the security case is preserved separately.

No result was manually repaired and labelled as AI success. No invalid draft was saved, no target agent was invoked, and no release or web app credential was created. Model inference is advisory and does not imply workflow execution authorization.

## Verification and test correction

The two relevant isolated suites passed **52 tests**, with zero failures/errors/skips: [security-regression.xml](security-regression.xml). They cover unconfigured access denial, bounded transport, private-data rejection, unapproved agent/contract/authority injection, source changes, malformed responses and separate review/save authorization.

An older regression assumed eight generated nodes exceeded the maximum. The runtime now supports ten nodes, so that fixture was corrected to construct a value above the declared limit dynamically. This changes `tests/test_workspace_model_proposal.py` only; no operating product source or private configuration was changed.

## Required to complete the requested creation

1. Supply the explicit trusted model-proposer connection to the operating workspace factory; preserve the hidden public Workspace link and current customer permissions.
2. Stabilize actual model output using an exact typed JSON Schema and approved candidate choices. Preserve all post-generation validation; do not coerce or invent agent bindings.
3. Measure cold/warm inference and align bounded generation time limits with that observation. Preserve concurrency, output-size, authority rechecks and no automatic execution/retry.
4. Re-run these same three objectives through the customer AI button, review and save valid proposals, then separately authorize their real read-only tests.

These are the concrete blockers for this request. A server restart alone cannot supply the missing integration. Existing ten workflows and their successful retained history were rechecked; pending model consent and the unsaved test objective were cleared.

Machine-readable result: [verification.json](verification.json).
