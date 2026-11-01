# Global agent updates and permission design

Design date: 2026-10-17 (Asia/Seoul). Status: implemented in the working tree; deployment is controlled by the user. Source changes do not restart the user-operated server.

## 1. Product decision

Keep anonymous discovery as the primary service. Return one relevant, evidence-ranked agent before presenting any optional contact request. Then offer **Get updates for this task**. A visitor can receive narrowly scoped updates without creating an account or publishing their own agent in the directory.

Offer two delivery methods: a verified HTTPS webhook/A2A inbox, or authenticated polling for agents without a public inbound endpoint. Do not require an email address, personal name, company, country, payment details, or agent listing. Store a private notification relationship, not a presumed customer or marketing subscriber.

At launch, enable requested task updates only. Disable promotional campaigns, cross-task recommendations, sales invitations, and automatic migration into marketing audiences. Later marketing requires its own explicit purpose, operator authorization, consent record, and launch review. English-language targeting does not establish US incorporation or exempt the service from other countries' laws.

This is a conservative global product baseline, not a claim that every jurisdiction imposes identical rules or that every webhook is legally equivalent to email. Transport, recipient, content, operator location, targeting, and applicable law still matter.

## 2. Review basis and current gaps

Reviewed the current embedded frontend through `extracted_html.txt`, plus `agent_market/concierge/notify.py`, `memory.py`, and notification entry points. The public site returned HTTP 403 to a direct read during this review; deployed parity was not established. No production contacts, personal records, consent records, or delivery logs were inspected.

Current source has useful foundations: HTTPS callback validation, public-address checks at connection time, disabled redirects, bounded requests, six-digit endpoint verification, rate limits, and stop support. Verification proves access to the destination; it does not prove authority to consent for a person or organization.

The existing contact record and visitor `notify` flag do not encode separate purposes. The source also contains general nurture and `pro_sla_invitation` campaign paths, including an admin-triggered nurture entry point. This shows a reuse risk; it does not establish that those campaigns are currently being sent in production. All sender paths, including admin force-send paths, must use the same purpose authorization gate.

Footer issues in current source:

- **Notification Preferences** opens an old **FTC Click-to-Cancel & Subscription Terms** modal containing billing copy and a visitor-token input.
- Blanket **GDPR / CCPA Compliant**, **FTC Click-to-Cancel Ready**, **EU AI Act Transparent**, and accessibility compliance statements exceed what this review has verified.
- The Privacy Policy omits private callback addresses, delivery records, purpose-specific permissions, and deletion of pending contacts. Pseudonymous session/contact records should not be described as necessarily anonymous or non-personal.
- Statements that all global transmissions use SCCs, that rights are absolute, and that the operator is governed by Delaware law require correction and an actual factual/legal basis.
- AI disclosure mixes an evidence-based matching description with probabilistic/synthesized-output wording. Public wording should describe observable service behavior without internal runtime or model details.

## 3. English UX and interaction contract

### Protocol preference

The composer defaults to **Auto (from question)** and offers **Any protocol**,
**A2A**, **MCP**, and **x402**. An explicit selection takes precedence over the
question; Any protocol deliberately searches across all three. In Auto, one protocol
mentioned in the question becomes the filter. Multiple different protocols require
a single explicit choice; do not silently interpret an ambiguous request. Apply
quality, successful report freshness, and activity ordering inside the filter.
Never fall back to another protocol when no eligible candidate matches. A follow-up
such as `details 1` keeps the original protocol preference. Protocol-only follow-ups
can reuse the last task. An explicit selector can change it.

Store the requested protocol with the interest and the task watch. Keep it distinct
from delivery: choosing MCP for recommendations does not require an MCP callback.
Webhook, A2A inbox and polling remain independent delivery options. The admin
simulator has the same selector and engine. Visiting Agents shows the requested
protocol, active watches, purpose-choice history, expiry and sanitized delivery
records. Operators may pause, stop or delete a watch; they cannot create consent,
resume a revoked watch, or bypass authorization with manual campaigns.

### Recommendation

Keep the current fast recommendation path and existing safety eligibility checks. Rank relevant candidates by recorded quality grade, latest successful test evidence, and recent activity confirmation, without customer-tier influence. Render one agent with its purpose, public connection link, and recorded evidence dates. Do not invent a candidate or a successful test when evidence is missing.

The optional action appears after the result has rendered. No callback validation, consent lookup, or delivery request may block the recommendation. Contact collection does not change ranking, unlock a better answer, or automatically invoke the recommended agent.

Public action: **Get updates for this task**.

### Optional update sheet

Use a compact responsive sheet/dialog with local Lucide `Bell`, `Webhook`, `RefreshCw`, `ShieldCheck`, `Check`, and `X` icons, following the existing theme. Preserve keyboard focus, dialog labeling, focus return, live status announcements, both color themes, and reduced-motion preferences. Use visible text alongside icons.

Exact proposed product copy:

> **Get updates for this task**  
> Receive an update when the recommended agent changes or new verification evidence affects this task.  
> **Delivery method**: Webhook / A2A inbox / Check for updates  
> **Webhook URL** or **A2A inbox URL**  
> Use an endpoint you control. Do not include credentials or personal information.  
> **Task**: a short, editable, non-sensitive task label  
> Updates stop after 90 days unless you renew them. You can stop them at any time.  
> Unchecked required authorization: **I control this endpoint or am authorized by its operator to request these task updates.**  
> Unchecked requested-purpose choice: **Send updates for this task to this endpoint.**  
> **Verify endpoint** / **Not now**  
> **Privacy Policy** · **Notification Preferences**

For polling, replace endpoint fields with: **Check for updates from this browser or your agent client. No public inbox is required.** Use **Enable task updates** and an appropriate operator-authority statement without claiming endpoint control. Keep authentication/session capabilities in transport; never display identity tokens, raw API output, developer setup examples, or private URLs in Chat.

The full callback is transient input in the protected form only. Mask it after submission and exclude it from Chat history, analytics, screenshots/session replay, error reports, exports, and the public registry. This reconciles required private collection with the public-content restriction.

Verification status: **Verification sent. Confirm it from your endpoint to enable updates.**

Success: **Task updates are on.** Actions: **Manage updates** and **Done**.

Failure: **We could not verify this endpoint. Check the address or choose Check for updates.** Do not expose resolved IPs, network diagnostics, stack traces, or internal errors.

There is no launch marketing checkbox, upsell, customer-tier label, or commercial language in Chat. Future optional marketing belongs in a separate preference center with clear content, sender, channel, frequency, withdrawal, and independent authorization; it must not be hidden behind “updates” or “stay connected.”

### Preference center

Footer **Notification Preferences** opens the same center as **Manage updates**. Show task label, delivery method, masked destination, state, expiry, and controls: **Pause updates**, **Resume updates**, **Stop updates**, **Remove contact details**, and **Delete notification data**. Stop is immediately available without login, a questionnaire, or a reason. More sensitive operations require the current authenticated session or a fresh endpoint-control challenge.

Distinguish stop from deletion. Stop immediately prevents future outbound delivery. Deletion removes contact/task/delivery data according to the disclosed policy, with narrow documented retention exceptions. Show a receipt describing what was deleted and what limited records remain, without private identifiers.

An expired or missing browser session must not require the user to paste a visitor token. Allow recovery through a fresh endpoint challenge or a purpose-limited management link. Avoid contact-enumeration responses. A destructive delete challenge must not be sent after an arbitrary unverified address submission.

### Home and metadata

When implemented, update Home with: **Find one agent for your task, backed by recorded quality checks. Choose task updates when you want to hear about meaningful changes.**

Suggested page description after release: **Find a relevant agent using recorded quality checks and recent verification evidence. Choose optional updates for your task.** Keep title, social tags, structured metadata, and actual behavior consistent. Do not claim the update feature exists before release. Do not add personal profile, consent state, callback, or task data to metadata or URLs.

## 4. Permission and identity model

Treat four facts independently:

1. **Endpoint control**: a pending destination completed a challenge bound to its contact record, session, and expiry.
2. **Operator authorization**: the requester is authorized to act for that endpoint/operator for the specified scope.
3. **Requested task permission**: an affirmative request covers one task, delivery channel, and stated event set.
4. **Optional marketing permission**: absent at launch; a future separate affirmative choice covers specific promotional content and channel.

Do not equate a public agent card, bot visit, domain, successful POST, or six-digit code with operator-approved marketing. An automated client can request task updates only under an operator policy/delegation covering that action. Record the delegation reference and scope when supplied; a mere self-assertion is not independent proof. If organizational authority is disputed or materially uncertain, require operator confirmation before enabling outbound delivery. Future marketing requires an explicit operator-approved workflow, not an agent inventing consent.

Consent records are server-side, versioned, and purpose-specific. Cookie/analytics consent does not grant contact permission; contact permission does not grant analytics or marketing permission. For EU/UK personal-data processing, document the actual lawful basis for each purpose; an explicit product request need not imply that consent is the only possible GDPR basis. When relying on consent, make withdrawal as easy as agreement. [EDPB lawful-processing guidance](https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en)

States:

`pending_verification -> active -> paused / revoked / expired`

Failed/expired challenges never activate permission. Paused delivery needs an explicit resume; revocation or expiry needs a new affirmative request. Changing the endpoint requires a new control challenge; changing the purpose requires a new permission decision. Do not silently widen a task watch.

Conceptual internal records:

- `notification_contacts`: private contact ID, channel, encrypted callback/resolved endpoint, keyed destination fingerprint, verification state/times, encrypted signing material, key ID, and expiry.
- `task_watches`: private watch ID, owner/session relation, sanitized task label and minimal matching scope, purpose, event set, status, expiry, cadence, last evidence snapshot, and permission version.
- `permission_events`: append-only grant/withdrawal events with purpose, channel, notice version/hash, affirmative action, timestamp, subject/contact/watch relation, actor kind, authority/delegation reference, and relevant policy basis. Do not routinely retain IP addresses or full prompts as evidence.
- `delivery_events`: unique event ID, watch ID, evidence version, enqueue/attempt times, minimal status, retry count, and sanitized error category. No raw callback, message body, or response body in general logs.
- `revocation_records`: minimal keyed contact fingerprint/scope and revocation time where justified; never use suppression data as a prospect list.

An ordinary unkeyed hash of a low-entropy callback or label does not make it anonymous. Recoverable addresses need authenticated encryption and restricted worker access; hashes are for lookup/deduplication, not delivery.

## 5. Useful updates, speed, and delivery

Watch the existing recommendation evidence locally. Emit an event only for a material change: the top eligible agent changes, a successful report changes the supported confidence, or the selected agent's latest check establishes a relevant failure/recovery. Mere timestamp refreshes, unrelated catalog growth, unchanged results, and lack of user activity do not create events. Do not mix advertising into these messages or assume that the label “task update” settles their legal classification; review the actual content and context.

Each update contains one recommendation or a factual status change, the short task label, the evidence date, an official service return link, and management/stop actions. Keep private visitor IDs, raw prompts, previous conversations, unrelated recommendations, provider amounts, runtime details, and executable instructions out of the display payload. Structured protocol adapters may retain required truthful machine fields with appropriate access control; public Chat rendering still follows its existing restrictions.

Use a background outbox/worker. The Chat recommendation request finishes independently. Proposed engineering targets, to be measured rather than advertised: p95 local recommendation processing <=250 ms in a documented reference environment; watch registration acknowledgement <=300 ms excluding asynchronous endpoint verification; event enqueue within five minutes of new evidence. These are acceptance targets, not observed performance or uptime guarantees.

Default maximum one task-update event per watch per 24 hours, with coalescing of changes. Verification and a user-requested stop receipt are separate operational messages with their own abuse limits. Apply an endpoint-wide cap across watches. No customer-tier differences. A critical delivery/security incident may require a separate, narrowly justified operational notice; it is not a marketing bypass.

Before each attempt, the worker rechecks active purpose, expiry, revocation, destination verification, and allowed event type. Admin actions cannot bypass these checks. Use a versioned permission fence when claiming a queued send; cancellation atomically revokes it and removes queued retries. A network request already in flight at cancellation can still arrive; disclose this narrow race and prohibit further retries.

Delivery is at-least-once. Use unique event IDs, deduplication, and receiver idempotency. Sign exact transmitted bytes with per-contact HMAC, timestamp, event ID, and key ID; receivers enforce a short acceptance window and replay cache. Use a challenge-bound authenticated exchange to provision the signing secret to the authorized endpoint/client, never a normal Chat bubble. Poll clients authenticate through session/capability transport, with ETag/304, pagination/cursors and rate limits; do not expose watch data through guessable IDs.

Retry transient failures with jitter and a maximum five attempts over 24 hours; pause after persistent failure. Treat 410 as revocation and stop; do not retry redirects or rejected/private destinations. Respect bounded Retry-After within the retry budget. Recovery requires explicit action and endpoint verification if ownership or address changed. Do not send keep-alive campaigns or reactivation promotions.

## 6. Security boundaries

- Permit HTTPS only, initially port 443. Reject URL userinfo, fragments, malformed/ambiguous hosts, unsupported schemes, and known embedded credentials; allowlist permitted query keys only if required by a reviewed integration. Prefer a dedicated notification inbox. Reject known chat/workflow execution webhook patterns unless a safe notification adapter is explicitly supported; do not blindly POST into arbitrary automation triggers.
- Normalize and validate the host; reject localhost, private, loopback, link-local, reserved and cloud-metadata destinations for both IPv4 and IPv6, including mapped/encoded forms. Validate every DNS answer and the actual connection address on every attempt. Disable redirects. Apply the same rules to A2A cards and their resolved endpoints. DNS prechecks alone are insufficient. [OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- Use a separate egress worker with no access to the admin network, cloud credentials, or sensitive metadata services; network policy must reinforce application checks. Bound DNS/connect/read/total time, bytes, concurrency, and queue depth. Verify TLS. Never forward platform cookies, session headers, or operator credentials.
- Prefer a 128-bit one-time machine challenge bound to the exact contact/request. For browser manual fallback, retain a one-hour maximum six-digit code, five attempts, and strict distributed rate limits. Store only challenge hashes and invalidate on success, replacement, exhaustion, or expiry. Do not fetch an inbox repeatedly to verify it.
- The first outbound challenge itself can be abused. Require an initiated request plus the authorization choice, use a small fixed verification-only payload, no arbitrary user-controlled message or task text, per-session/destination/host/global limits, cooldowns, and duplicate suppression. Endpoint verification reduces abuse; it does not eliminate unsolicited challenge risk.
- Same-origin authenticated browser mutations need CSRF/Origin controls; explicit bearer API clients use scoped credentials. Enforce object ownership, bounded input, CSP, escaping, input masking, and no-store responses. Preserve existing public/admin separation.
- Management links use an independent scoped capability, not the session token. A GET only opens a preference landing page; an explicit idempotent POST stops updates, preventing link scanners from mutating state. Strip/exchange URL capabilities immediately, use no-referrer/no-store, and exclude third-party analytics. Stop capability cannot read private data, change endpoints, or subscribe. Stronger actions require session authentication or re-verification.
- Treat catalog descriptions, callback responses, and notification text as untrusted data; never interpret them as instructions, run code, or automatically trigger an agent action. Keep endpoint details out of search indexes and public APIs.

## 7. Retention specification

These are proposed launch defaults, not statutory retention periods. Publish only the periods actually enforced, and adjust documented exceptions for applicable obligations before release.

- Verification challenge: expires after one hour; purge unverified callback/task records within 24 hours.
- Active task watch: 90 days from affirmative creation/renewal. Browsing, polling, delivery, and visitor tier do not silently extend it. Show the expiry and allow explicit renewal.
- Stop/expiry: suppress sends immediately; erase recoverable callback, signing material, and matching scope within 24 hours unless the operator has another independently authorized active watch on that destination.
- Notification-data deletion: remove remaining task/contact/delivery payload data within 24 hours, subject to a documented narrow legal/security hold. Do not apply this promise to unrelated records outside the notification feature.
- Sanitized delivery metadata: 30 days. Raw response bodies are not retained. Proposed notification-specific operational/security logs: maximum 72 hours, with narrowly scoped incident holds. Audit the rest of the existing platform separately before making a site-wide 72-hour claim.
- Minimal permission/revocation evidence: proposed 24 months after the final stop/expiry, access-restricted and without recoverable endpoint or prompt content. Validate the need and period against actual operator obligations; shorten if unnecessary, retain longer only for an identified obligation/hold. Never use it for outreach.
- Encrypted backups: a proposed maximum 30-day rotation. A restore must replay revocations/deletions before any sender starts, so stopped watches cannot return. State the backup deletion delay in the policy.

Run expiry/purge jobs with failure alerts and age-based checks. Retention periods must also cover exports, replicas, support tools, session replay, and subprocessors, not just the primary database.

## 8. Footer and global policy contract

Keep a compact English footer with **Terms of Service**, **Privacy Policy**, **Cookie Preferences**, **Your Privacy Choices**, **Notification Preferences**, **Accessibility**, **Automated Service Disclosure**, and **Contact**. Retain the existing explicit **Do Not Sell or Share My Personal Information** entry where applicable, as a clear direct option within or beside Privacy Choices; do not replace a required link with vague wording.

Replace unsupported compliance badges with ordinary links to factual practices. Do not use a legal acronym as a certification. Describe tested accessibility scope and known limitations; use WCAG 2.2 AA as an engineering target, not a claim of certification or universal legal compliance. Only publish response-time commitments that the support team actually meets.

Required policy corrections:

1. **Privacy Policy**: name the actual controller/operator and business contact; describe private callbacks, pseudonymous session data, task scope, verification, purpose choices, delivery, retention, recipients, data location, applicable rights and verification. State actual lawful bases, not a universal consent theory or “absolute rights.” Public business identity/contact information required by law is compatible with keeping private personal details out of product screens.
2. **International transfers**: map actual hosting, processors, support access and import/export roles. Apply valid EU/UK transfer mechanisms where needed, with actual agreements and assessments. Remove the claim that all global transmissions use SCCs. Sending to a recipient-selected endpoint does not by itself resolve the platform's own processor or transfer obligations.
3. **Cookies/GPC**: keep analytics off until the applicable choice permits it. Honor applicable sale/share opt-outs and GPC. A browser-local preference is not proof of server-side contact consent, a permanent cross-device preference, or a completed deletion request. GPC must not silently cancel a separately requested task watch. Classify essential storage by actual function, not convenience.
4. **Notification Preferences**: replace the old subscription/billing modal and raw-token form with the actual watch-management center. Remove claims of FTC rule compliance; keep easy stopping as a product behavior. The 2024 expanded rule was vacated in July 2025 and the FTC restored the prior rule in February 2026. Other applicable laws still remain. [FTC notice published 2026-10-14](https://www.govinfo.gov/content/pkg/FR-2026-10-14/html/2026-20971.htm)
5. **Terms**: verify operator identity, jurisdiction and contracting flow. Do not infer Delaware governance from an English service or claim mere API access is universally affirmative clickwrap. Separate service terms from optional contact permission. Review arbitration, liability limits, and mandatory local consumer rights with the actual operator facts.
6. **Automated Service Disclosure**: use public behavior wording such as **Agent Concierge uses recorded verification evidence to recommend an agent for your task. Results reflect the latest available checks and may change.** Avoid unsupported generative-output claims, blanket EU AI Act certification, and internal model/runtime disclosures. Assess legal AI-system classification and transparency duties separately.
7. **Contact**: distinguish support from notification enrollment and public catalog submission. Verify that published privacy/accessibility/support inboxes are monitored. Do not require a personal name/email to activate a webhook watch. Do not carry obsolete billing language into Chat-accessible preference dialogs.

Regional launch approach:

- **EU/EEA and UK**: determine territorial applicability and lawful bases; purpose separation, minimization, rights and applicable storage/marketing rules. UK PECR distinguishes individual and corporate subscribers; sole traders are not automatically corporate. The service chooses an explicit opt-in baseline instead of relying on every possible exception. [ICO electronic-mail guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-direct-marketing-using-electronic-mail/how-do-we-comply-with-the-pecr-electronic-mail-marketing-rules/)
- **United States**: CAN-SPAM rules concern covered commercial email and classify mixed messages by their primary purpose; do not assert that it grants permission for arbitrary webhooks. Keep sender identification and easy opt-out, and evaluate state privacy/consumer laws by applicability. [FTC CAN-SPAM guide](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business)
- **California**: evaluate business thresholds and practices; honor applicable rights and GPC for sale/sharing. Do not equate a cookie toggle with a deletion workflow or claim certification from the presence of a footer link. [California DOJ guidance](https://oag.ca.gov/privacy/ccpa)
- **Canada**: assess CASL's application to the actual electronic address/message and commercial purpose. For covered commercial messages, consent, sender identification and unsubscribe duties apply; a marketing message asking for consent is not a general workaround. [CRTC guidance](https://crtc.gc.ca/eng/com500/guide.htm)
- **Australia**: assess the Spam Act's actual message/channel and Australian link. Covered commercial messaging needs consent, identification and unsubscribe; don't send promotional re-permission messages to opted-out contacts. [ACMA guidance](https://www.acma.gov.au/avoid-sending-spam)
- **Other markets, including the operator's home jurisdiction**: assess actual obligations before targeted promotion. English is the interface language, not a jurisdiction filter. Do not infer residence from a domain or IP, collect citizenship for this feature, or promise worldwide legal compliance. For unknown regions use the same conservative purpose baseline.

## 9. Legacy migration and future membership

Never convert `verified` or `notify=1` into marketing consent. Mark imported records `legacy_unscoped`. Preserve only the original scope when supported by recorded evidence; otherwise pause outbound delivery and request a new choice when the visitor next returns. Do not mass-send a re-permission campaign to unproven contacts.

Place the authorization gate under the shared delivery layer, not only in the UI or scheduler. Apply it to legacy commands, scheduled digests, nurture paths, direct dispatch, admin manual sends and force flags. Marketing remains denied by default even for privileged callers.

Keep anonymous visitors, contact relationships, public catalog agents, future member accounts and any future commercial entitlements separate. Linking a watch to a future account requires fresh proof of control and an explicit choice. Linking neither widens purpose nor publishes the callback nor enrolls anyone in a commercial service. Losing the browser session is not permission to fingerprint the visitor or match them by IP.

## 10. Release sequence and acceptance criteria

Implement in this order:

1. Correct footer/modal/policy inconsistencies and verify operator/processor facts. Build server-side purpose records and a deny-by-default send gate before exposing the CTA.
2. Add endpoint challenge, polling, scoped preferences, stop/delete, encryption and retention jobs. Migrate legacy records conservatively; dry-run the sender with no external delivery.
3. Add the English optional CTA, sheet and accessible states; update Home and metadata only when the feature works. Keep the embedded HTML and extracted file synchronized.
4. Run content, browser, authorization, egress and lifecycle checks. Release task updates gradually with bounded queues and an operational kill switch. Keep marketing disabled.

Acceptance requires evidence for:

- Existing one-agent relevance/quality behavior and measured response-time distribution remain intact; no contact field is required to receive an answer.
- No literal Hangul in public frontend copy/comments, commercial wording on Chat, private token/profile/URL leakage, runtime diagnostics, or raw JSON. Existing content check and relevant browser/security regressions pass.
- Both delivery methods, mobile/desktop, keyboard/screen reader, dark/light and reduced-motion flows work; cancel closes cleanly without enrollment.
- Wrong/expired/replayed challenges, cross-session verification, reused endpoints, cross-watch access and unauthorized account linking fail safely.
- Public-to-private DNS changes, redirects, IPv6/mapped IPs, metadata hosts, URL parser ambiguity, A2A endpoint substitution, huge/slow bodies and queue flooding are blocked.
- Duplicate events, retries, receiver replay checks, stop during queued delivery, expiry, deletion, backup restore and 410 all preserve authorization. No send begins after revocation is committed; already-in-flight requests cannot be recalled.
- Every admin/direct/legacy sender denies missing purpose and revoked/expired permission. Merely setting `notify=1` cannot authorize a send; marketing is denied at launch.
- GPC/cookie preferences, task consent and future marketing choices remain independent. No analytics or contact collection occurs through optional UI before the relevant affirmative choice.
- Retention age checks prove deletion in primary storage and the documented backup cycle. No full callback/prompt leaks into logs or analytics.

Before publication, resolve actual legal operator identity/contact, data/processor locations and transfer arrangements, and policy/legal applicability. These are factual release gates, not reasons to delay preparing the design. This document finalizes the product and engineering approach; it does not certify security, legal compliance or current production behavior.


## Working-tree implementation and operational notes

Implemented modules: `protocols.py`, `task_updates.py`, the public task-update REST
routes and English UI, and the admin Visiting Agents detail/actions/simulator.
The scheduler uses the same purpose-scoped sender as admin checks. Legacy contact
commands and nurture campaign sends cannot grant or bypass task permission.

Runtime requires maintained PyCryptodome (not the obsolete PyCrypto package).
Each disk-backed database uses a private adjacent `.updates-key` encryption key,
or a 32-byte URL-safe-base64 `AGENT_UPDATES_KEY` supplied through the environment.
Do not rotate/remove this key without a migration. Protect it separately from the
DB and restore it only in a trusted environment. No key is sent to public clients.
`AGENT_TASK_UPDATES_OUTBOUND=0` disables inbox verification/delivery while leaving
polling available. Do not start a second scheduler against the same DB.

Delivery is bounded inside the existing scheduler/background task infrastructure;
separate network egress isolation remains a deployment control. Before any backup
restore, set outbound delivery off and reconcile post-backup revocations/deletions
from trusted operational records before re-enabling it. The application cannot
reconstruct a revocation erased by restoring an old DB. Backup rotation, incident
holds, actual controller identity, processors and cross-border arrangements need
operator-specific records; this implementation does not certify those facts.

The user runs the server directly in a terminal. Development and security checks
use isolated applications, synthetic catalogs, temporary databases and test
couriers; do not stop or restart the user's server. After reviewing the changes,
the user can restart it to load the new code and schema.
