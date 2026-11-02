# Notification Preferences → Customer Requests

Implemented and verified on 2026-10-17 using isolated state. The user's terminal
server and live database were not stopped, restarted or changed.

## Where to inspect

Open **Admin → 고객 요청 → 알림 설정 및 이력**. This is an authenticated, read-only
view of the existing purpose-scoped task notification records, not a separate
customer profile database.

- Search by notification request ID or task; filter by current state and channel.
- Inspect protocol, manual polling/browser/Webhook/A2A delivery, masked
  destination, destination verification, expiry, current task permission and
  independent marketing permission.
- Open **상세 및 이력** to inspect application, address confirmation, pause,
  resume, renewal, manual check, stop, notification-data deletion and independent
  marketing withdrawal, with their actual times and notice versions.
- The list has 50-row pagination and sorts by the latest retained user action.
  The detail shows the most recent 100 permission actions with the retained total,
  and the most recent 20 generated/delivery records with status and attempts.
- Stopped/deleted requests remain stopped. Administrators cannot change purpose
  permissions or resume revoked tasks from this view. Advertising delivery stays
  disabled, including when separate permission and destination verification exist.

Unverified requests declined by the visitor are physically removed along with
their destination, marketing and permission records. They disappear on refresh;
their old detail URL returns 404. The interface explicitly explains this rather
than retaining a new identifying record of a declined registration.

## Implementation

- Added the authenticated list/detail routes under
  `/admin/api/needs/notifications`, with bounded inputs, allowlisted state/channel
  filters, parameterized literal search and bounded pagination/history.
- Reused the existing task watches, consent history and private-destination
  masking. The response projection excludes visitor IDs, visitor tokens,
  ciphertext, destination hashes, verification codes, signing secrets, push
  subscriptions, raw event payloads and private inbox paths.
- Added an authenticated `check` action for the footer's **Check for updates**
  button so successful manual checks appear in the same purpose history. Existing
  machine `GET .../events` clients retain their interface. A manual check does not
  send a notification or advertising message.
- Added an index on the existing permission history for request/time lookup.
  It is created idempotently during normal Store initialization; no live data
  migration or backfill was run in this task. Existing retained permission
  records are immediately available to the new view after source reload.
- Kept the public frontend English and synchronized its embedded HTML source.

## Verification

**199 distinct tests passed:** 69 Chromium/browser regressions and 130
API/storage/security regressions. This includes 12 new Notification Preferences
browser cases and 7 new API cases. See `browser-final.xml` and `api-security.xml`.
`user-browser.xml` records the final focused UI rerun after the manual-check
verification label was clarified: all 12 cases passed again. These repeated
cases are not added to the 199 distinct-test count.

The new user journeys cover:

- Desktop and 390px mobile: pause, resume, extend by 90 days, manual check with no
  changes, stop and delete; exact persisted state and action history in admin.
- A new successful report: manual check opens the updated recommendation in Chat
  and records both the check and generated event, without automatic delivery.
- Webhook and A2A: pending request recovery through the footer, incorrect code
  rejection, correct destination confirmation, independent marketing withdrawal,
  admin state/channel/ID filters and persistence after reload.
- Pending Webhook/A2A/browser decline: both frontend preferences and admin lists
  remove the request, and an old admin detail lookup fails safely.
- Browser notification confirmation: native Chromium Service Worker logic and a
  test notification click are exercised with an emulated OS notification and fake
  push provider. Admin reads confirm pending/verified/paused/resumed/withdrawn/
  stopped states and history. This is not a real user's push-provider delivery.
- Empty preferences, action failure, admin list failure, stale detail clearing,
  stored markup escaping, unauthorized access, cross-visitor rejection,
  unsupported filters, SQL-like/wildcard searches, pagination beyond 50 rows,
  expiry and bounded history.

The related regressions also exercise existing Customer Requests/footer flows,
destination verification, Visitor Desk, admin CSP/XSS, notification isolation,
withdrawal rollback and scoped reactivation denial. The public frontend content
check covers 47 files with zero violations. Embedded HTML equality and Python
source parsing were checked.

Screenshots use synthetic data only:

- `admin-history-390.png`, `admin-history-1280.png`
- `admin-verified-webhook.png`, `admin-verified-a2a.png`

## Reproduction

```sh
.venv/bin/pytest tests/test_notification_preferences_hub_browser.py tests/test_footer_customer_requests_browser.py tests/test_task_updates_browser.py tests/test_admin_security_browser.py tests/test_destination_verification_browser.py tests/test_visitor_desk_browser.py -q --tb=short --junitxml=reports/notification-preferences-2026-10-17/browser-final.xml
.venv/bin/pytest tests/test_notification_preferences_hub.py tests/test_footer_customer_requests_security.py tests/test_customer_requests_hub.py tests/test_front_footer_security.py tests/test_front_legal_compliance.py tests/test_needs_security.py tests/test_task_updates_security.py tests/test_destination_verification.py tests/test_visitor_desk.py -q --tb=short --junitxml=reports/notification-preferences-2026-10-17/api-security.xml
python3 scripts/check_front_content.py
```

Chromium runs against the real application routers with isolated ASGI transports
and SQLite databases; external browser traffic is blocked. The browser-push test
uses an isolated loopback fixture. No real visitor, email, Webhook, A2A, push or
advertising recipient was contacted. These checks do not attest to a deployed
domain's ingress configuration or remote production data. Source changes require
the user's normal reload/restart if their server does not reload automatically.
