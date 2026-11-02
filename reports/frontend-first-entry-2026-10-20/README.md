# Public frontend first-entry loading corrections

2026-10-20. The default published frontend has been rebuilt and verified on the
operating public domain. No project server was started, stopped or restarted.

## Corrections

- Test: the four owned example names and descriptions are present in the initial
  document, with disabled controls and an explicit availability-checking state.
  They are presentation previews, without resource IDs or a readiness assertion.
  Only the existing API's verified bindings enable the actual choices.
- Test: first-entry example/selected-connection reads precede the optional larger
  registered-agent catalog. Concurrent reads of the same selected connection
  share one in-flight request. Existing selection-version and late-response
  guards, input preservation and execution admission remain enforced.
- Test: Run Test and the tool selector remain disabled before the connection is
  loaded. The selector has a meaningful placeholder instead of an empty field.
  Failed example loading displays a retry action. No test is executed on entry.
- Workflows: successful or failed template refresh updates the selected workflow
  presentation even when a saved canvas was restored. Published steps and run
  details appear without clicking the active template again. Local draft edits
  remain intact; published inputs are still distinguished from editable drafts.
- Workflows: loading, failure/retry and genuinely empty states are separate.
  Loading does not falsely claim that no published workflows exist.
- Explore: the first request sets its status/busy state before presentation
  wrappers initialize, and clears it only for the current search revision.
- Home/Agent Status: snapshot refreshes expose an accessible busy state and
  retain factual recorded timestamps and existing error notices.
- Preview cards use the existing modern theme and responsive layout. The preview
  and ready examples keep comparable dimensions; delayed-data tests check both
  1440px and 390px widths and guard against horizontal overflow/layout jumps.

## Verification

- `final-regressions.xml`: 200 passing integration, public menu, input-race,
  execution/download, review-binding and dynamic security cases.
- `final-entry-and-execution.xml`: 25 passing final cold-entry and owned-agent
  execution cases, including fresh/restored/edited saved canvases, explicit retry,
  all nine public menus with held APIs, and desktop/mobile layout retention.
- `final-input-retention.xml`: final delayed catalog/input preservation checks.
  These supersede the earlier versions of those cases, rather than increasing
  the total by counting repeated checks again.
- `performance.xml`: isolated HTML loading, warm caching and compressed-size
  limits passed. These are local fixture thresholds, not a public-network SLA.
- `content.log`: 229 public frontend files checked, zero policy violations.
  `ruff.log`, `bandit.json`: scoped checks passed without findings. Generated
  operating and presentation JavaScript passed syntax checks. Existing CSP,
  escaping, input masking and execution authorization remain in place.
- `operating/verification.json`: actual public desktop visits verified all nine
  menus and their metadata, four example labels, selected default input, and three
  workflow steps on both a fresh page and a saved-default reload, without clicking
  a template. No execution POST or browser script error occurred.
- `operating-mobile-accepted/verification.json`: final mobile public visit returned
  HTTP 200, four examples, a ready selected connection and no horizontal overflow
  or page script errors. Existing CSP blocked injected optional edge scripts;
  this was not a frontend execution failure and CSP was not relaxed.
- `source-final.json`: final changed implementation, test and publication hashes.

## Operating-test cleanup and limits

Rapid full-document visits during the initial operating matrix triggered the
existing read limiter and its temporary test-client block. The first matrix's
final mobile step and the initial mobile retry therefore failed with HTTP 403;
the unsuccessful evidence remains preserved and is not relabelled as successful.

The rule was correlated with this check's headless-browser asset requests and
removed as a single test-generated temporary block through the authenticated
administrator UI. The audit/event history was retained. No persistent allowlist,
rate-limit increase, security-mode change or unrelated rule removal was applied.
The final independent mobile visit then succeeded. Future operating checks should
use ordinary SPA navigation or space full-document visits within existing limits.

Network and current binding checks still take time; initial previews communicate
that wait and do not assert availability. The retained embedded fallback source
is synchronized with `extracted_html.txt` and loads on the next ordinary user-run
server restart. The current default published frontend already serves the updated
static assets and was the operating acceptance target.

## User-run restart verification

The subsequent user-run restart was confirmed on a new operating process, with
no source drift from the verified publication. Final evidence is in
`after-restart-accepted/verification.json`: four checking-state example labels,
disabled unverified actions, a ready Technology News connection with two input
fields, the three default workflow steps and run details without clicking a
template, and four mobile examples without horizontal overflow. Browser script
errors, HTTP 403/429 responses and execution POSTs were all zero.

This check used one document and SPA tab transitions. Earlier local verification
harness attempts (`after-restart/` and `after-restart-final/`) are retained as
incomplete: request interception cleanup and the harness's default five-second
assertion prevented completion. The accepted check used real unmodified API
responses and explicit browser assertion timeouts; no product change was needed.
