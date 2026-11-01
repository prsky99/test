# Individual visitor response desk

Implemented 2026-10-17 in the working tree. The user selected individual consultation/response management and requested task updates. Advertising consent, promotional sends and conversion campaigns are outside this release.

## Operator workflow

Open Visiting Agents. The default scope is registered external contacts from actual visits; authenticated polling remains available under All visitors. Filter by contact permission, last requested protocol, case status, source, visitor tier or name/ID/latest task. Counts and pagination use the same predicates. Visitor tier never affects recommendation ranking.

Select one visitor. Review their exact recorded questions, selector mode, effective protocol filter, returned agent and evidence at the time of the reply. Record an internal case status, optional assignee, follow-up time and note. These records do not send messages. Closing/archiving clears follow-up dates. Updates use an optimistic version so two administrators cannot silently overwrite one another.

Inspect each task relationship independently: requested task, recommendation protocol, delivery method, host-only destination, verification, current authority/purpose notice, expiry and permission state. Polling is not counted as an external contact. Legacy callback registration is shown separately and never authorizes delivery.

For a specific watch, preview the current recommendation and processing reason. The preview does not enqueue or send. If eligible, process only that visitor/watch with a signed, actor-bound review valid for five minutes. The server chooses the payload; an administrator cannot submit a custom promotion. Polling prepares a read-only event, while a verified inbox can receive the reviewed task update. No manual bulk button remains; the bulk endpoint returns 403 and old digest/campaign paths cannot send.

The existing scheduler still handles explicitly requested task watches under the same verification, purpose, expiry, cadence, retry and egress boundaries. It does not send advertising.

## Data and historical accuracy

- `agent_messages.id` links each new answer to its exact question. Store selector mode separately from the resolved recommendation filter and returned agent kind.
- Store one public recommendation snapshot: ID/name/protocol, public connection information, quality grade/score, report ID/time and recent successful activity confirmation. Later catalog edits do not rewrite this evidence.
- Keep existing bounded conversation retention: latest 200 messages per visitor. Answers whose questions fall outside retention explicitly say the question is unavailable. Legacy messages without structured metadata are not retrospectively paired or assigned current evidence.
- Oversized metadata stays valid JSON and explicitly marks the evidence gap instead of saving truncated invalid JSON.
- `agent_visitor_cases` stores status/assignee/follow-up/version; `agent_visitor_case_notes` stores internal author/time/body. Keep at most 100 notes and show the latest 50. Internal notes follow the existing visitor lifecycle; there is no new claim of a universal time-based deletion policy. The existing idle visitor cleanup protects live task relationships and open cases, and removes case/note rows when it removes an eligible visitor.
- Destination ciphertext, signing secrets, challenge codes and visitor tokens are excluded from the response desk. Only the HTTPS destination host is shown. Contact/verification commands are stored as a generic destination request rather than a callback/code in Chat history.
- Counts represent visitor records and registered task relationships, not a deduplicated person, organization or advertising audience. A shared destination does not merge two visitor sessions.

## Security boundaries

Existing administrator authentication, same-origin protections, body bounds and role checks apply to every added route. Operators can read; admin/superadmin roles can change cases or process a watch. All query values are parameterized; composed SQL fragments are fixed predicates.

Case text is bounded, sanitized and token-redacted; browser output is escaped. An internal note cannot influence outbound payloads or recommendation ranking. Optimistic version conflicts require reload. Case saves and individual processing outcomes enter the existing administrator audit trail without note bodies or secrets.

Preview tokens bind visitor, watch, administrator, expiry, current authority state and the exact reviewed recommendation/queued payload. Processing rejects another actor/watch, a modified token, expiry, withdrawal, changed evidence, replay and unsuitable cadence/retry states. Evidence is checked again during preparation and at the actual send claim, including connection fields. Stale queued recommendations are cancelled rather than sent. A request already claimed or in flight may still arrive after a withdrawal, as disclosed in the existing notification design.

Outbound delivery retains HTTPS/public-address validation, connection-time SSRF controls, disabled redirects, authenticated destination challenge, encrypted secrets, HMAC signatures, per-destination budgets, bounded concurrency and the outbound kill switch. The desk does not expose a generic HTTP client or arbitrary recipient/message field.

## Deployment and verification

New tables are created idempotently through `Store` initialization at the user's normal restart. No existing contact is promoted to permission, no historical snapshot is invented, and no active production DB was edited during verification. The user-operated server is left running unchanged.

Regression and security evidence is recorded in `reports/security-2026-10-17-visitor-desk/README.md`. Tests use synthetic catalogs, temporary/in-memory databases, intercepted browser requests and fake couriers. They do not establish deployed parity or certify a production environment.
