# Individual visitor desk: implementation and security verification

2026-10-17. Implemented in the working tree for the user's selected scope:
**individual consultation/response management and requested task updates**.
No advertising-consent collection or promotional sending was added.

The user-operated server was left running. Verification used isolated ASGI apps,
in-memory/temporary databases, synthetic agents and fake/intercepted couriers.
No production contact, encryption key or production database was inspected or
modified, and no real contact received a test message. This is source and isolated
runtime verification, not a production penetration-test certificate.

## Delivered behavior

- Visiting Agents defaults to registered external contacts from live visits.
  Accurate filters/counts distinguish new task inboxes, valid scoped authority,
  pending verification, legacy contacts and authenticated polling. Protocol,
  response status, source, name/ID/latest-task search and pagination share the
  same filter predicates. Visitor tier is descriptive and never ranks agents.
- A visitor case has an internal status, assignee, follow-up date and notes.
  Notes do not send messages. Version checks reject conflicting edits.
- Each newly recorded Chat reply links to its exact question, selector mode,
  resolved protocol and original one-agent evidence snapshot. Report IDs/times,
  grade, public connection and activity confirmation remain historical even when
  the catalog changes. Current preview evidence is labeled separately.
- Inspect one task's permission/destination and preview it before processing.
  Destinations show only the host. Admin review is bound to visitor, watch,
  administrator, expiry, destination state and exact evidence/queued payload.
  Only that reviewed watch is processed. No custom advertising content is accepted.
- Removed the manual bulk UI. The old bulk endpoint returns 403; legacy digest
  and campaign routes cannot send. The scheduled worker continues only explicit,
  verified, purpose-scoped task watches under existing cadence and egress limits.
- Pause/stop/delete and purpose/delivery history remain available per watch.
  A newer stopped-record history cannot hide the active relationships in the desk.

## Verification results

- Full suite: **880 passed**, zero failures/errors/skips; one existing warning,
  **265.05 seconds** (`regression.xml`).
- Final focused API/security tests after the last data-integrity and permission
  refinements: **53 passed** (`focused-regression.xml`).
- Final real Chromium desk/task-update/admin security regressions:
  **30 passed** (`browser-regression.xml`). These runs overlap the full suite;
  their counts must not be added together.
- Public frontend content check: **45 files, zero policy violations**. Embedded
  and extracted public HTML are identical. All checked public/admin inline scripts
  parse, and changed Python modules compile.
- Installed dependency audit: **53 packages, zero known vulnerabilities returned**,
  no skipped dependencies (`dependency-audit.json`). This does not establish the
  absence of undisclosed vulnerabilities.
- Bandit scan over concierge modules and gateway dashboard/store/server/desk:
  **0 high, 56 medium, 47 low warnings** (`bandit.json`). Medium warnings comprise
  54 SQL-construction heuristics and two public-bind warnings. The new desk has
  two B608 heuristics: both compose fixed predicates and bind every request value.
  Injection-shaped search and protocol inputs are covered dynamically. No findings
  were reported in `task_updates.py` or `fast_chat.py`. Broader low warnings are
  exception handling, protocol labels and non-security jitter. Scanner warnings
  are retained in the artifact and are not described as zero findings.

## Security cases exercised

- Authentication, operator read-only behavior, same-origin write protections,
  invalid bodies/text/status/date bounds and SQL injection-shaped filters.
- Exact historical question/response pairing, non-retroactive snapshots, safe
  destination-command logging, bounded valid JSON and explicit evidence gaps.
- Stored untrusted question/agent/note content renders as text in Chromium;
  injected elements do not execute. Admin CSP and existing regression controls
  remain in force. Narrow 390px and wide 1280px layouts retain drawer/table access.
- New vs legacy contacts, pending vs active permissions, polling exclusion from
  external-contact counts, protocol/source filters, pagination and follow-up counts.
- Conflicting case updates, internal-only notes, audit attribution and no implicit
  grant or outbound effects from case saves.
- Preview GET has no send/queue side effects. Another visitor/watch/actor,
  tampered/expired/replayed token, withdrawal, expired permission, changed notice,
  disabled outbound and changed recommendation/connection information block processing.
- Only the selected visitor/watch creates a delivery event. A catalog change
  between review and event preparation requires another review. Stale queued
  evidence is cancelled by the worker rather than sent. No arbitrary promotional
  message supplied to the processing API is used.
- Existing destination validation/SSRF, verification, encrypted-secret handling,
  HMAC transport, quotas, stop/delete and notification/browser regressions pass.

## Operational and historical limits

The user must restart their server normally to load the code. `Store` creates the
new case/note tables idempotently at initialization. No data migration promotes
old contacts to consent. Keep the existing task-update encryption key and normal
backup controls; this work did not rotate or recover production keys.

Legacy messages lack structured recommendation evidence and cannot prove a past
selector/report/grade. They are displayed as legacy records rather than inferred
from today's catalog. Conversation history remains bounded to the latest 200
messages; notes retain at most 100 entries with the latest 50 displayed. Missing
questions or oversized metadata are marked unavailable. Internal case notes use
the existing visitor lifecycle, not a newly asserted universal retention period.

A delivery already claimed or in flight can arrive after a withdrawal; later
queued attempts are blocked. Scheduler/runtime deployment parity, external
recipient infrastructure, live configuration and real-world deliverability were
not tested. No blanket vulnerability-free or legal-compliance certification is made.

Design: `docs/INDIVIDUAL_VISITOR_DESK_DESIGN.md`. Machine evidence and synthetic
390px/1280px screenshots are stored beside this report.
