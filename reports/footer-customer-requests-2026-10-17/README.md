# Footer → Customer Requests user verification

Date: 2026-10-17. Tested local source using real Chromium, enforced application CSP,
isolated public/admin ASGI applications and shared temporary SQLite databases.
All names, email addresses, requests and destinations were synthetic. Requests to
external browser origins were blocked. The user's terminal server and live data
were not modified, stopped or restarted.

## Findings corrected

1. **Contact submissions failed from the browser.** The footer sent a serialized
   body without `Content-Type: application/json`, while the API required JSON.
   The real form returned `Invalid JSON payload` even though API-only tests passed.
   Contact and privacy submissions now use the existing API helper's `json` option.
   This also preserves the explicit privacy-choice payload instead of falling back
   to an empty body when its content type is absent.
2. **Receipt references were not searchable.** Inquiry, privacy and cancellation
   search now includes their receipt IDs. Cancellation search also includes IP,
   as promised by its existing input hint. Search remains parameterized.
3. **Current task withdrawals were missing from Customer Requests.** The footer
   and authenticated stop links previously revoked watches and recorded task
   permissions, but did not create a cancellation row. Successful stop/delete
   actions now record minimal cancellation evidence in the same transaction.
   Repeated stop requests do not create duplicates. Records omit task text,
   destination URLs, session tokens, token fragments and stop capabilities.
   Scoped task cancellations cannot be reactivated by an admin: the interface
   explains that a new customer request is required, and the API rejects revival.
4. **Mobile inquiry detail fields were clipped.** The admin detail grid now stacks
   on narrow screens and wraps long values. The response field follows the theme.
   The 390px screenshot was inspected after the fix; the receipt and email are
   readable without horizontal clipping.

## User flows covered

- Contact: all six current categories (general, technical, partnership,
  security/abuse, custom agent onboarding, billing), plus the mobile technical
  form. Verified the displayed receipt against the stored row; exact name, email,
  subject and multiline message in the admin detail; category/email search;
  resolved status and internal note; persistence after reloading the admin page.
- Privacy choice: desktop and mobile footer button, successful receipt, stored
  preference/proof, admin list, type/status filters and receipt search.
- Notification preferences: a task watch created through the actual Chat dialog,
  then stopped in the footer or through a fresh stop-link navigation. Verified
  revocation and matching Customer Requests cancellation entries/search.
- Failure handling: invalid email creates no request; a simulated 503 preserves
  the form and permits retry; failed privacy submission does not claim a server
  receipt, while the local optional-analytics choice stays disabled.
- Informational policy links and local cookie rejection do not create support
  requests. Opening preferences without submitting an action creates no request.
- Security: unauthenticated admin reads rejected; submitted markup remains inert;
  cross-visitor withdrawal and invalid stop capability create no audit entry;
  repeated withdrawals are idempotent; a simulated cancellation-write failure
  rolls back the watch mutation; scoped admin reactivation is denied.
- Search can find a request beyond the default first 50 records. Receipt search
  was tested with 55 inquiry records; SQL-like input does not broaden the query.

## Evidence and repeatable checks

- **166 tests passed:** 43 final browser tests (including 15 new footer journeys)
  and 123 API/storage/security tests (including 9 new targeted regressions).
- No failures or skipped tests in those two final runs.
- `browser-final.xml`: final Chromium user journeys and existing task/admin
  browser security regressions.
- `api-security.xml`: API and storage regressions covering Customer Requests,
  footer security, legal UI behavior, sanitization, destination verification,
  task updates and Visitor Desk.
- `contact-confirmed-390.png`, `contact-confirmed-1280.png`: browser receipts.
- `admin-contact-detail-390.png`, `admin-contact-detail-1280.png`: matching admin
  details and persisted internal note.
- `admin-privacy-390.png`, `admin-privacy-1280.png`: privacy receipt search.
- `admin-notification-stop.png`: scoped cancellation search and no admin revival.

Commands:

```sh
.venv/bin/pytest tests/test_footer_customer_requests_browser.py tests/test_task_updates_browser.py tests/test_admin_security_browser.py -q --tb=short --junitxml=reports/footer-customer-requests-2026-10-17/browser-final.xml
.venv/bin/pytest tests/test_footer_customer_requests_security.py tests/test_customer_requests_hub.py tests/test_front_footer_security.py tests/test_front_legal_compliance.py tests/test_needs_security.py tests/test_task_updates_security.py tests/test_destination_verification.py tests/test_visitor_desk.py -q --tb=short --junitxml=reports/footer-customer-requests-2026-10-17/api-security.xml
python3 scripts/check_front_content.py
```

The public content check covers 47 files with zero policy violations. Embedded
frontend HTML and `extracted_html.txt` were checked for exact equality. Modified
Python files and the new test modules were parsed successfully.

## Boundaries

These are automated user journeys in Chromium against the real application
routers, not tests of the deployed domain, ingress configuration or a remote
production database. No email, webhook, push or advertising was sent. The admin
response field saves a status/internal response record; it does not itself send
email. Clicking an official `mailto:` contact link opens an email client and does
not automatically create a Customer Requests row. General cookie preferences
remain local choices; explicit privacy requests are recorded separately.

Source changes require the user's normal server reload/restart if their server
does not reload automatically. No data migration or live-data rewrite was run.
