# Webhook and A2A inbox implementation and verification

Verified 17 October 2026. Implemented a reusable, loopback-only HTTPS test inbox
with webhook, A2A 0.3 and A2A 1.0 routes, protected receipt reads, bounded in-memory
storage, HMAC verification and replay handling. It runs on temporary ports and
cleans up its temporary TLS certificate and key on exit.

The user's existing terminal server, database and deployment configuration were not
changed. Tests sent only synthetic task-verification and task-update messages to
our own local receiver. Advertising delivery remains disabled.

## Results

- **101 passed**: actual HTTPS inbox integration, task-update security, destination
  verification, and concierge compatibility; zero failures or skipped tests.
- **84 passed**: real Chromium Chat registration against the HTTPS inbox, existing
  task-update UI, frontend security, concierge language/transport compatibility and
  A2A protocol regressions; zero failures or skipped tests.
- **47 public frontend files checked**, zero content-policy violations. The embedded
  HTML and extracted HTML remain synchronized; the removed Home paragraph stays removed.
- Python compilation and the standalone receiver's CLI help check passed.
- Bandit over the new receiver and modified Courier: **zero findings**. No new
  dependencies were introduced; the receiver uses the project's existing runtime.

## Actual delivery and dynamic security

The real Courier fetched the receiver's A2A cards and sent messages over
certificate-verified HTTPS/TCP sockets. Four success paths were exercised:
webhook, A2A 0.3 card, A2A 1.0 card and direct A2A 0.3 inbox URL. Each path received
a challenge, remained inactive before verification, accepted its received code,
then received one signed update after new synthetic evidence was added. Stopping
the watch prevented later delivery and erased its recoverable destination.

Chromium exercised the actual Chat form, destination review, code confirmation,
separate marketing choice and Notification Preferences for all three inbox formats.
It confirmed actual receiver delivery and displayed the updated recommendation.
Private inbox addresses and verification codes were not rendered in Chat replies.

Security checks covered missing/corrupted signatures, tampered transport bytes,
stale timestamps, duplicate delivery, valid retries with fresh timestamps, changed
content under a reused event ID, receipt-token authorization, cross-origin access,
oversized/invalid/non-JSON/compressed bodies, untrusted TLS certificates, inherited
cookie/authorization stripping and unchanged rejection of private callback URLs.

Controlled receiver failures verified 503 retry with the same event and 410
revocation, including withdrawal of marketing eligibility. An HTTP 200 response
without an A2A result was not counted as successful task delivery.

## Interoperability bugs found and fixed

The first strict live-receiver run accepted the webhook but rejected the A2A
verification messages. The Courier used the server/response role for outgoing
client requests. It now sends `user` for 0.3 and `ROLE_USER` for 1.0 for both
verification messages and updates. Its 1.0 verification data part also had an
extra `data` wrapper; it now uses the same direct structured-data form as updates.
The live 0.3 and 1.0 paths pass after those corrections.

These changes are limited to outgoing notification messages. The public A2A
service's response roles and protocol formats remain covered by compatibility tests.
References: [A2A specification](https://a2a-protocol.org/latest/specification/),
[A2A 0.3](https://a2a-protocol.org/v0.3.0/specification/).

## Scope and artifacts

The application API is exercised in an isolated ASGI app; the browser runs real
Chromium. Receiver traffic uses real loopback TLS sockets. A fixture substitutes
logical DNS for `inbox.example` and maps that host to its own temporary listener;
no public DNS/Internet delivery or production deployment was tested. TLS verification
is enabled using a private test trust context; system trust is unchanged. Product
private-address/HTTPS validation is not relaxed.

This is a development receiver, not an externally reachable production inbox or a
complete A2A server implementation. The receiver's unsigned verification bootstrap
is intended only for these isolated tests, and must not be publicly exposed. No test
server is left running after the tests finish.

Artifacts: `integration.xml`, `browser-compatibility.xml`, `bandit.json`,
`verification.json`, and synthetic screenshots `webhook-chat-confirmed.png`,
`a2a-v03-chat-confirmed.png`, `a2a-v1-chat-confirmed.png`.

[Run instructions and design](../../docs/NOTIFICATION_TEST_INBOX.md).
