# Verified notification destinations

Implemented 17 October 2026. Discovery remains available without notification or
marketing choices. The public service uses English copy, local Lucide icons,
accessible controls, and the existing theme. Recommendation protocol is independent
of the notification delivery channel.

## Four separate decisions

1. The requester explicitly confirms operator authority for task updates and the
   task-update purpose notice. These controls are required and start unchecked.
2. The requester reviews the selected browser or exact dedicated HTTPS inbox before
   submitting. Merely reviewing the destination creates no server registration.
3. The service proves destination control before activating delivery. Selecting a
   delivery method or granting browser permission alone is insufficient.
4. An optional, unchecked marketing choice records a separate notice and purpose.
   It is not inferred from visiting, chat, a contact address, cookie choices,
   browser permission, task updates, or a legacy notification flag.

The release records marketing choices and exposes verified eligibility for admin
inspection. Advertising delivery, promotional composition, legacy nurture sends,
and bulk dispatch remain disabled. Task delivery never checks marketing flags.

## Browser notifications

The explicit destination confirmation click requests native notification permission.
The page requires a secure context, Service Workers, Notifications and PushManager;
there is no silent manual-polling fallback. The browser generates its subscription
using the service's public VAPID key. Users do not type a push-provider address.

The server validates the subscription's HTTPS push-provider endpoint, P-256 public
key, authentication secret and optional expiry before storing it encrypted. It
creates a pending request and sends a fixed, encrypted test notification containing
a one-time, 256-bit challenge. The service worker displays the confirmation
notification; selecting it calls the same-origin confirmation API. Only a valid,
unexpired challenge activates that request. Normal owner-authenticated six-digit
verification cannot activate a browser subscription. A replay is rejected.

Notification permission and subscription setup do not count as proof that a test
notification arrived. The API does not return its challenge to the page. Its public
configuration contains only the public VAPID key and current notice identifiers.

Actual task pushes use a fixed generic message, with no question, destination,
visitor profile or recommendation on the lock screen. Full task updates require
the authenticated session in Notification Preferences. Manual checks are a separate,
explicit option and send no browser notifications.

## Webhook and A2A inboxes

The page displays the exact typed address in a replay-masked review area. The
server accepts dedicated public HTTPS inboxes on port 443, without credentials,
query strings, fragments or common action-trigger endpoints. It validates public
addresses again at connection time. Private networks, DNS rebinding to a private
address, redirects and inherited session credentials are blocked.

The sole pre-activation delivery is a fixed verification challenge. The operator
must retrieve its six-digit code from the actual inbox and enter it in the current
authenticated session. Codes expire after one hour; five incorrect attempts fail
the request and erase its recoverable address. A2A card resolution must remain on
the origin reviewed by the requester. For a cross-origin card, the requester must
use the actual inbox URL and review it directly instead.

Task updates are sent only after verification and while the original task-purpose
permission is current, active and unexpired. Existing delivery signatures, evidence
checks, rate limits, leases, retries and stop capabilities still apply.

## Decline, withdrawal and expiry

A decline before submission creates no watch, address, task-purpose ledger or
marketing choice. Declining a pending request, closing its setup dialog, or using
the test notification's Decline action physically deletes the pending watch,
address checks, events and unverified purpose choices. An expired challenge cannot
activate delivery. Failed/expired registrations lose recoverable destinations in
lifecycle processing, with stale unverified metadata removed after the grace period.

Denied browser permission creates no new registration. The current session also
removes its known browser requests when permission is revoked and the page observes
the permission/visibility change. An offline deletion is queued by opaque watch ID
in session storage and retried online or when the page returns. It cannot be
reported as a completed server deletion until the API acknowledges it.

A verified request can be stopped or deleted from Notification Preferences. Minimal
consent/withdrawal records may remain for up to 24 months; the destination and task
scope are erased. Marketing can be withdrawn independently without stopping task
updates. Stopping/deleting a watch also withdraws its marketing permission. Marketing
expires after 90 days and is not extended by renewal of task updates.

Short-lived HMAC abuse counters survive physical deletion, so repeated create/decline
cycles cannot reset owner/global registration limits. They contain neither the raw
address nor the task and are purged after one day. Pending requests are never a
source of advertising or task-update delivery.

## Admin Visiting Agents integration

The authenticated visitor desk offers a verified + separately opted-in marketing
filter. Counts distinguish recorded choices, pending verification and current
eligible destinations. Details show the selected channel, task, protocol,
destination confirmation, verification, expiry, notice versions and purpose-choice
history. Consent request and withdrawal timestamps are available separately.

Webhook/A2A addresses are masked to their host. Browser subscriptions appear as a
status label; their provider URL and keys never reach the admin response. Operators
may remove consent, pause, stop or delete, but cannot grant, restore or invent
visitor permission. Admin actions are audited. Existing individual task-preview
and scoped delivery remain task updates, regardless of marketing eligibility.

## Operation and validation

The user operates the server in their terminal. Development did not restart it or
change production registrations. Source changes require its normal reload/restart;
new installations must install the updated requirements. The existing private
updates encryption key also derives a domain-separated VAPID signing key, so it
must persist with the database. No private signing key is exposed by the public API.

Real browser delivery additionally depends on HTTPS, an eligible browser/OS,
notification settings and access to its push provider. Chromium tests exercise the
actual service worker and confirmation HTTP round trip with an emulated OS display
and controlled push delivery; they do not establish production-provider delivery.
No notifications were sent to real recipients during verification.

See [verification report](../reports/security-2026-10-17-destination-verification/README.md).

API/browser behavior references: [PushManager.subscribe](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe),
[requestPermission](https://developer.mozilla.org/en-US/docs/Web/API/Notification/requestPermission_static),
[showNotification](https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerRegistration/showNotification),
[pywebpush](https://github.com/web-push-libs/pywebpush).
