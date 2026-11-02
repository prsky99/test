# Protocol choice and scoped task updates: implementation verification

2026-10-17. The user operates the service from their terminal. This work did not stop,
restart, replace or send test traffic to that server. All functional/security tests
used isolated applications, synthetic catalogs, temporary databases and controlled
couriers/transports. This report is not a production penetration-test certificate.

## Delivered behavior

- Chat defaults to **Auto (from question)**. One protocol named in the question
  filters candidates. Explicit **Any protocol**, **A2A**, **MCP**, or **x402** takes
  priority. Multiple protocols in Auto require a choice. Quality grade, successful
  report freshness and recent successful activity determine the winner within the
  requested protocol. No unrelated protocol is substituted when there is no match.
- Recommendation renders before optional collection. **Get updates for this task**
  opens a separate English form. Operator authorization and purpose choices are
  unchecked by default. Recommendation protocol and polling/webhook/A2A delivery
  are independent. No membership or email address is required.
- Scoped watches, encrypted destinations, bounded challenges, expiry, polling,
  pause/resume, explicit renewal, stop/delete, delivery records and purpose history
  share one backend. Legacy contact/nurture commands cannot bypass the new scope.
- Admin **Visiting Agents** shows requested protocol, watches, expiry, notice
  version, purpose choices and sanitized events. Operators can pause, stop or delete;
  they cannot grant permission, enable marketing or resume a revoked watch.
- Footer Notification Preferences opens actual controls without token entry or a
  required cancellation reason. Old billing copy and unsubstantiated compliance
  badges were replaced. Home, page/social descriptions and agent metadata were
  updated. Callback input never becomes a chat message or public directory field.

## Validation evidence

- Full regression: **860 passed**, zero failures/errors; one existing warning.
- After the final protocol-follow-up, visitor-scoping and credential/header fixes,
  **101 focused API/browser/egress/security regressions passed**. This overlaps the
  full suite and includes the last added scoping test; do not add the counts.
- Public frontend policy check: **45 files, zero violations**. Embedded and
  extracted HTML remain synchronized; public copy/comments contain no literal Hangul.
- JavaScript syntax: all three executable public scripts and the admin script parse.
  Real Chromium tests enforce CSP, reject injected script/event handlers, exercise
  both narrow/wide layouts, keyboard focus, endpoint verification, polling, stop links,
  deletion and the actual admin detail-to-stop interaction.
- Installed dependency audit: **53 packages**, zero known vulnerabilities returned
  by the queried advisory service. This does not predict undisclosed vulnerabilities.
- Bandit: **zero high-severity warnings** and no findings in the new protocol/watch
  modules. The broader scan retained 53 SQL-construction heuristics, two public-bind
  warnings, and 47 low-severity warnings. SQL warning sites use parameterized values
  and constant/allowlisted fragments or identifiers; public binds belong to serving
  endpoints and retain authentication/network boundaries. Low warnings include
  compatibility exception handling, public protocol labels and non-security jitter.
  These scanner warnings were not silently described as zero findings.
- The AES import warning was reviewed: maintained **PyCryptodome**, explicitly
  required by the project, provides `Crypto.Cipher.AES`; deprecated PyCrypto is not
  the dependency. Its documented namespace warning has a narrow explanatory suppression.

Measured on an isolated 600-row synthetic catalog, 18 ASGI chat requests with normal
rate limits and a reused session: processing p95 **20.390 ms**, ASGI round-trip p95
**35.013 ms**. No external endpoint or production data was used. These are local
measurements, not internet latency, load capacity or an advertised SLA.

## Security controls checked

- Session ownership, cross-visitor denial, explicit boolean authority/purpose,
  notice version, cross-origin rejection, replayed/exhausted/expired challenges,
  protocol allowlisting and selection precedence.
- HTTPS/public destination boundaries, blocked loopback/private/metadata/IPv6
  inputs, prohibited credentials/query/fragment/automation URLs, bounded transport,
  redirects disabled and connection-time public-address enforcement.
- AES-GCM authentication bound to the watch, private persistent key permissions,
  encrypted callback/signing material, no callback or signing key in API summaries,
  no raw token entry or persistent browser token after migration to session storage.
- Exact-byte HMAC signatures, stable per-key identifiers, event IDs/timestamps,
  suppression after stop, queue leases/retries, persistent failure pause, 410 stop,
  per-destination and global budgets, fair watch scanning, temporary-record cleanup,
  and an outbound kill switch. Injected client cookies and default HTTP auth do
  not leave notification requests.
- Stop links carry a purpose-limited capability in a fragment, stripped before
  analytics/routing. GET does not stop delivery; explicit POST is idempotent and
  cannot read private data or subscribe. A request already claimed/in flight can
  arrive after stop; queued future attempts are blocked.

## Runtime and deployment boundaries

- Install the updated requirements before the user's normal restart. The existing
  environment already contains the required maintained encryption library.
- A disk-backed DB uses a private adjacent `.updates-key`, or an environment-supplied
  `AGENT_UPDATES_KEY`. Keep it private and recoverable; do not delete or rotate it
  without a migration. It is excluded from Git. No production key was generated or read
  for this verification.
- `AGENT_TASK_UPDATES_OUTBOUND=0` stops inbox verification/delivery while retaining
  polling. The existing scheduler checks watches independently of the catalog rescan.
  Do not run competing schedulers or restore a DB while writers are active.
- Before restoring an old DB, keep outbound off and reconcile subsequent withdrawals
  and deletions using trusted operational records. An old DB alone cannot prove
  that restored permissions are still current. Backup rotation and independent
  network egress isolation are deployment controls, not claims established here.
- Actual operator identity, monitored business contacts, processor/hosting locations,
  applicable legal scope and international-transfer arrangements still require
  operator-specific facts. Footer wording avoids asserting blanket certification.

Files: `verification.json`, `regression.xml`, `focused-regression.xml`, `dependency-audit.json`, `latency.json`,
and synthetic narrow/wide UI captures. The detailed design is
`docs/GLOBAL_AGENT_UPDATES_DESIGN.md`.
