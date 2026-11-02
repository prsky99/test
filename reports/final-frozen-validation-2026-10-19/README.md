# Final review candidate — 2026-10-19

**The fixed review candidate passed its composed code verification:320 selected
modules,5796 unique candidate cases,0 remaining failures/errors/skips.**
This does not claim a fresh5796-case invocation on the final tree, whole-design
completion, or acceptance of later changes in the working/public version.

Source ID: `c0b3b72e4d0504a68813182ac5a3ec22e80d1d4ee0434c4d6ccf7bb106aa680c`.
[Source archive](candidate-source.zip) · [case-level evidence](case-evidence.json) ·
[verification](verification.json) · [source manifest](isolated-candidate.json).

## Exact verification method

The complete319-module baseline ran four nonoverlapping file shards:5786 cases,
5782 passed and4 failed. None of the earlier historical whole runs was reused.
Its failures were report badge wording, lost historical-unavailable presentation,
a non-isolated read-limit test, and an old automatic-dialog assumption.

Separate frontend/generator/test changes continued after source confirmation.
To stop repeating whole runs on a moving folder, a1511-file review snapshot was
captured without credentials, operating databases, logs or runtime profiles.
Its fixed selection contains320 modules/5796 case IDs:the baseline corpus plus
10 user-click journeys. The snapshot was not changed while tested.

Complete affected modules on that copy passed400 cases; additional click
journeys passed10 and workflow/browser-security cases passed18. Of these428,
409 belong to the candidate corpus and19 are supplemental Redis dependency
checks. Retaining5387 baseline cases without identified impact and replacing
409 candidate cases gives5796 passes. Cases are matched by module/name/parameters;
counts are not summed blindly. No target case is missing. All4 initial failures
have passing replacement evidence. See verification.json and case-evidence.json.

## Repairs and retained changes

- Restored `Historical entry · unavailable` on compact Explore cards. Historical
  listings cannot show a current execution badge. Report existence remains
  separate from current callability. Visible report-badge presence is asserted
  rather than the superseded `Report available` phrase.
- The read-limit HTTP test now explicitly selects the real local fallback,
  checks the default120 limit, then asserts an exact smaller configured quota,
  429 responses and Retry-After. Production rate policy is unchanged. The old
  isolated test passed and the full failure took1.232s, so timer expiry was not
  the observed cause. The precise environmental mechanism is not asserted;
  host Redis availability was previously uncontrolled.19 separate controlled
  Redis runtime/review cases passed.
- Gateway download verification explicitly opens details from the inline result
  before closing the dialog. Outcome, provider path and downloaded-app execution
  assertions remain. Other completed source fixes (staged publication and
  public-content/regression inventory coverage) remain in the candidate.
- Late template ordering, initial example, protocol bridge and input-layout
  changes were retained and tested in the immutable copy; they were not silently
  described as unchanged parts of the original snapshot.

## Security and source integrity

On the fixed copy:217 public frontend files checked,0 policy violations; embedded
HTML equals its mirror; SQL catalog3473 statements/223 tables matches source.
Critical Ruff:0 findings. Bandit on agent_market/scripts/new:High0/Medium239/Low1468,
scan errors0. Existing warnings and3 additional fixed-path local QA XML contexts
are reviewed in bandit-review.json; no warning was suppressed. These automated
counts are not a security certificate. Dynamic browser/API regressions cover
CSP/XSS, input/output handling, consent, isolation, retries and denial paths with
isolated/synthetic transports. Source comparison after testing found0 changes
across the1511 declared candidate files.

## Actual service observations and deployment boundary

Local operating HTML/presets/templates returned200 with CSP/no-store/nosniff;
unauthenticated customer session returned401 and admin controls403. Public
browser-like homepage requests returned200 with operating HTML and security
headers. Default Python urllib was denied with Cloudflare1010, while the explicit
AgentConcierge-Acceptance/1.0 client retrieved discovery successfully. See
[edge evidence and official references](edge-observation.md). Edge settings were
not changed; generic library-client compatibility needs operator policy review.

The served operating.js matched the fixed copy, but served pearl-ui.js did not.
The latter received further request-field validation changes after capture;
see working-copy-publication-diff.json and served-candidate-comparison.json.
The running/public publication is therefore **not accepted as identical to the
verified candidate**. Do not overwrite later work with this archive. Review the
difference and select the release version explicitly.

## Original conditions still outside code verification

Actual protected HTTPS/SDK deployment; verified receivers and physical Push test
click; independent recovery key custody; approved long-task A2A and independent
corpus/evaluator/qualifier/trust evidence; designated PostgreSQL HA/load/RPO/RTO;
eligible payment TEST account; hosted-provider approval/customer isolation and
acceptance; hosted CI and peer signoff remain tied to the original42 requirements.
ChatGPT actual inference remains on the user's separate quota hold. No new
inference, payment, advertising, credential change or project-server restart ran.
Public Workspace navigation remains hidden. Code verification does not imply
these original actual-target conditions passed.

[Peer handoff](peer-handoff.md) · [finite remaining conditions](../../docs/DEVELOPMENT_REMAINING_AFTER_RESTART.md).
