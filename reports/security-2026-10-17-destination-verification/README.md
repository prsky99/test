# Destination verification and separate marketing permission

Implemented and verified on 17 October 2026 with isolated databases, synthetic
agent listings and controlled notification transports. The user's terminal server,
production registrations and deployment keys were not changed. No notifications
or promotional messages were sent to real recipients.

## Implemented behavior

- Browser delivery uses native notification permission, PushManager subscription,
  encrypted Web Push and a service worker. Activation requires selecting the actual
  test notification carrying a one-time challenge. Permission alone is insufficient.
- Webhook/A2A registration requires a destination review and a code received at the
  dedicated inbox. A2A resolution cannot silently switch to an unreviewed origin.
- Declining an unverified request removes the pending registration, encrypted
  destination, verification data, queued events and unverified purpose choices.
  Denied browser permission creates no new request. Observed permission revocation
  removes the session's existing browser registrations.
- Optional marketing permission starts unchecked, has its own notice/purpose and
  becomes eligible only after destination verification. Withdrawal is independent
  of task updates. Admins can inspect/filter verified, separately opted-in contacts,
  but cannot grant permission. Advertising and bulk delivery remain disabled.
- Home, page/social metadata, machine discovery descriptions, Privacy Policy and
  Notification Preferences match the implemented behavior. Public source remains
  English; private destinations and subscription keys are masked in admin output.

## Dynamic security coverage

The regression artifacts below record API and Chromium tests. The new browser
fixture serves the actual application on an ephemeral loopback port and executes
its actual service worker and confirmation HTTP round trip. Native OS display and
push-provider delivery are emulated. Browser pages have external network requests
blocked; callbacks and push delivery use controlled transports.

Verified cases include:

- No activation or normal delivery before destination proof; no browser activation
  through the six-digit inbox API; expired, forged or replayed challenges rejected.
- Browser permission denial, review decline, setup close, notification Decline,
  and later permission revocation; unverified registrations and choices removed.
- Browser confirmation at mobile/desktop widths; independent marketing withdrawal;
  actual webhook and A2A code flows; runtime error details hidden from the interface.
- Cross-session ownership and cross-origin confirmation boundaries; invalid push
  hosts, private/link-local/loopback addresses, forged keys and expired subscriptions.
- Real AES128GCM payload encryption/decryption and VAPID headers, with inherited
  cookies/authorization stripped; connection-time private-DNS resolution blocked.
- Duplicate rejection; queued work after deletion cannot recreate a watch; short-lived
  HMAC abuse counters prevent create/decline cycles resetting registration limits.
- Admin eligibility filters exclude pending or withdrawn permission, mask private
  routing paths, reject attempts to grant permission, and retain withdrawal history.
- Existing recommendation, Chat privacy/CSP, scoped task delivery, RBAC, escaping,
  visitor desk and workflow regressions remain included in the broad regression run.

Broad regression: **932 passed**. Final targeted regression: **103 passed**.
Final browser verification: **14 passed**. No failures, errors or skipped tests.
The broad run started before the final hidden-control/deletion-budget refinements;
the final focused/browser runs validate those final changes.

## Static review and dependencies

The public frontend content check scanned 47 files with zero violations. Embedded
HTML matches `extracted_html.txt`. Inline JavaScript and the service worker pass
Node syntax checks; the changed Python modules compile.

`pip-audit` checked 70 installed project packages against the public advisory
service and reported zero known vulnerabilities. This includes the new maintained
`pywebpush`, `py-vapid`, `http-ece` and `cryptography` dependencies. The project
requirements declare Web Push and cryptography dependencies.

Bandit reports 0 high, 56 medium and 47 low severity warnings over the broad
concierge/admin scope, unchanged in count from the preceding review. New
`browser_push.py` and `task_updates.py` have no scanner findings. The two visitor-desk
B608 warnings assemble fixed SQL filter fragments and bind user values; API tests
exercise search/filter injection. Existing broad-scope warnings are retained in
`bandit.json`, not suppressed or described as zero findings. A passing scanner or
regression suite is not proof that all vulnerabilities are absent.

Review also confirmed encrypted destination/key storage, constant-time challenge
comparison, bounded TLS/public-only outbound transport, no redirect following,
response-size/time/concurrency limits, current task-purpose checks before delivery,
and minimal fixed pre-activation/lock-screen messages. The worker caches no pages
and stores no visitor session token. CSP permits only same-origin workers.

## Artifacts and reproducibility

- `regression.xml`: broad project regression result.
- `final-focus.xml`: final destination, consent, frontend policy, task security and
  visitor-desk API/browser regressions, after the hidden-control and deletion-budget
  refinements.
- `final-browser.xml`: final service-worker/consent browser checks and fresh screenshots.
- `verification.json`: counts, scope, limitations and source hashes.
- `dependencies.json` and `bandit.json`: tool outputs.
- `browser-confirmed-390.png`, `browser-confirmed-1280.png`,
  `admin-verified-consent.png`: synthetic browser screenshots.

Commands used: `.venv/bin/pytest -q --disable-warnings --junitxml=...`,
`python3 scripts/check_front_content.py`, `node --check`, `python3 -m compileall`,
Bandit over concierge/admin sources, and `pip-audit --path
.venv/lib/python3.11/site-packages`.

## Operational limits

The source is ready for the user's normal terminal-server reload/restart. Updated
requirements must be installed in each runtime; they were installed in this local
project virtual environment. No server restart was performed here.

Real provider delivery, browser/OS notification UI and production HTTPS/reverse-proxy
behavior have not been established by these isolated tests. They depend on browser
support, user permission, provider access and deployment settings. Advertising
message delivery is intentionally unavailable; recorded eligibility does not send
an advertisement. Offline deletion is retried and cannot be guaranteed while the
server is unreachable. An already in-flight notification cannot be recalled.

Implementation design: [verified destinations](../../docs/VERIFIED_NOTIFICATION_DESTINATIONS.md).
Browser/API references: [PushManager.subscribe](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe),
[notification permission](https://developer.mozilla.org/en-US/docs/Web/API/Notification/requestPermission_static),
[showNotification](https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerRegistration/showNotification),
[pywebpush](https://github.com/web-push-libs/pywebpush).
