# Notification preference detail modal

Date: 2026-10-17. Isolated Chromium/ASGI/SQLite verification; no live server or
production-data changes.

## Fix

The previous implementation rendered `notificationDetail` inside the list panel
and explicitly hid it at the start of `loadNotificationPreferences()`. The global
10-second timer calls that loader, which dismissed the detail while it was read.

- Moved detail into an independent native modal dialog under `document.body`.
- Centered the dialog with a backdrop, responsive width, fixed header and an
  internally scrolling body. Keyboard focus stays within the modal.
- List refreshes and filter/page loads no longer invalidate or hide detail.
  Background refresh keeps running without replacing the open dialog's contents.
- Added a dialog-local refresh button for explicitly updating the selected
  request. It preserves scrolling and returns focus to that button after loading.
- Closing with the button, Escape or the backdrop invalidates pending detail
  responses and restores focus to the current row button, even when automatic
  refresh replaced that row. Missing rows fall back to the search control.
- Errors or deleted requests are shown inside the dialog on an explicit refresh;
  the dialog remains open. List errors do not remove the previously opened detail.

No API, notification permission or delivery behavior was changed.

## Verification

**68 tests passed:** 38 browser regressions and 30 API/storage/security
regressions, with no failures or skips in the final runs.

New browser tests cover:

- Centering, viewport bounds, modal semantics and internal scrolling at 390px and
  1280px viewport widths.
- Two cycles of the application's actual 10,000ms refresh interval, advanced
  deterministically with Playwright's clock. Each cycle must produce a real list
  API response; the opened detail ID, markup, scroll position and keyboard focus
  must remain unchanged, with no implicit detail refetch.
- Escape/focus return after list rows are replaced; explicit dialog refresh;
  close while a response is pending; late-response rejection; reopening; backdrop
  dismissal; stored markup escaping and failure handling.

The existing Notification Preferences user journeys now use the modal and verify
deleted-request errors through the dialog-local refresh. Related admin browser
security checks continue to exercise enforced CSP and XSS boundaries. API/security
regressions cover notification reads, withdrawal isolation, sanitization and
reactivation denial. Public frontend content validation checks 47 files with zero
violations, although this fix changes only the admin presentation.

Final results and captures:

- `browser-final.xml`: notification modal, notification user journeys and admin
  browser security regressions.
- `api-security.xml`: related API/storage/security regressions.
- `centered-390.png`, `centered-1280.png`: the open modal after two timer cycles,
  preserving its reading position.

```sh
.venv/bin/pytest tests/test_notification_preferences_modal_browser.py tests/test_notification_preferences_hub_browser.py tests/test_admin_security_browser.py -q --tb=short --junitxml=reports/notification-preferences-modal-2026-10-17/browser-final.xml
.venv/bin/pytest tests/test_notification_preferences_hub.py tests/test_footer_customer_requests_security.py tests/test_needs_security.py -q --tb=short --junitxml=reports/notification-preferences-modal-2026-10-17/api-security.xml
python3 scripts/check_front_content.py
```

The user's terminal server was left running. Reload/restart it normally if it
does not automatically load source changes, then refresh the admin browser page.
