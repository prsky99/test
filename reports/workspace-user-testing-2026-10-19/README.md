# Workspace development user test — 2026-10-19

## Result and scope

Actual customer Workspace screens were tested with Chrome computer use against the running HTTPS service. The public Workspace link remains hidden. Google and GitHub accounts were used separately; no credentials or customer references are retained in this report.

A step-reference defect was reproduced and corrected in source. The corrected source passes isolated Chromium/API regressions; its live retest requires the user-operated server to reload the source. This report does not certify complete live workflow execution or exported app operation.

## Actual computer-use observations

- Google sign-in reached customer organization management.
- Blank organization-name submission was rejected. A synthetic organization was created and renamed to **Workspace QA Review 2026-10-19**; owner access appeared correctly.
- An empty draft was created. Cancelling an edit retained its original name and revision 1. Saving a subsequent edit produced **Workspace QA Draft Reviewed**, revision 2.
- Save snapshot produced **Snapshot 1**, which was selectable in the private task builder. The organization name and draft revision persisted after leaving and reopening the screen.
- The archive confirmation dialog was centered (both center offsets measured zero), and Cancel preserved the organization. No permanent account or organization removal was performed.
- Preparing the empty draft was blocked. Reading current history restored the controls and showed **No recorded tasks for this snapshot.** Run, release and deployment remained unavailable without their prerequisites.
- The typed studio initialized with two steps, stopped additions at six steps, and returned matching service guidance for a workflow review search.
- Removing a middle step and adding another generated a duplicate `step_6`. This was the confirmed defect addressed below.
- Both Google and GitHub sign-out returned to the sign-in screen. The test ended signed out. Public navigation and Home each contained zero Workspace links.
- GitHub returning sign-in worked. Its organization list did not contain the Google-owned test organization. Opening that organization's direct builder address was denied with a generic session/access response, without exposing organization data.

## Source correction

`agent_market/customer_typed_authoring_view.py` now selects an unused default step reference from the current editor inputs. Existing step references, including user edits, remain unchanged, so existing prior-output bindings are not silently rewritten.

The browser regression now reaches the six-step cap, edits an existing reference, removes a middle step, adds a replacement and checks uniqueness/preservation before completing its normal reviewed workflow journey.

## Verification

- **52 passed, 0 failed, 0 errors, 0 skipped** across customer organizations, single-task authoring and typed authoring API/browser suites. See [regression.xml](regression.xml).
- Public content: **92 files, 0 violations**.
- Critical Ruff selection E9/F63/F7/F82: **0 findings**.
- Bandit: **0 High, 1 Medium, 0 Low**. The Medium B608 finding has Low confidence and points at the embedded HTML/JavaScript template. Manual review confirms this view performs no SQL construction/execution; it is a false positive, not a removed or suppressed finding. See [bandit.json](bandit.json).
- PostgreSQL statement catalog: **no drift**, 3,472 statements / 223 tables.
- Initial sandboxed Chromium startup was denied by macOS MachPort restrictions; the same complete suite passed after scoped approval using isolated databases and mocked providers. The initial environment failure is not counted as a product pass.

## Actual limits

No approved typed agent task or approved long A2A binding was available in this live test organization. Actual provider execution, successful release, deployment authorization and live exported app operation were therefore not performed. Equivalent success/uncertainty/security journeys passed with synthetic providers in isolated browser tests.

The empty-draft preflight error uses conservative generic uncertain-action copy. The history confirmed there was no retained task. This wording observation is not evidence of an actual dispatched request or duplicate call.

Live invitations, ownership transfer, destructive account withdrawal and permanent organization archive were not exercised. Isolated regressions cover invitation/role transitions, output escaping and account withdrawal.

## Handoff

The clearly named synthetic organization, revision-2 draft and snapshot 1 remain available in the Google account for colleague review. They were not deleted. The public Workspace link remains hidden. The server was not stopped or restarted by this task.

After the user restarts their existing server, retest only the corrected middle-step removal/addition journey; the current live process still contains the old view code.

Evidence: [final signed-out screen](screenshots/signed-out.jpg), [public link hidden](screenshots/public-link-hidden.jpg), [snapshot/history](screenshots/snapshot-history.jpg), [studio before correction](screenshots/studio-editing-before-fix.jpg). Source hashes: [source.json](source.json). Machine-readable scope: [verification.json](verification.json).
