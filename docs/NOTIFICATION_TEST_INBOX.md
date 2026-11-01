# Local webhook and A2A notification inbox

This development receiver lets the project test real HTTPS notification delivery
without contacting an external recipient or changing the user's running server.
It supports the application's task-verification challenge and signed task-update
messages, with webhook, A2A 0.3 JSON-RPC and A2A 1.0 JSON-RPC routes. It is not a
public hosted inbox or a general-purpose A2A agent server.

## Run the receiver

From the project root with the project's existing requirements installed:

```sh
.venv/bin/python -m scripts.notification_test_inbox
```

The receiver selects an unused temporary loopback port. `--port 8766` selects a
specific local port if available. It prints the exact URLs, temporary certificate
path and a randomly generated receipt-read token in the local terminal.

Routes:

- `POST /webhook`: task verification and signed task updates.
- `GET /.well-known/agent-card.json`: A2A 0.3 card for `/a2a`.
- `GET /.well-known/agent-card-v1.json`: A2A 1.0 card for `/a2a-v1`.
- `POST /a2a`: `message/send`, legacy `kind` fields and client role `user`.
- `POST /a2a-v1`: `SendMessage`, `A2A-Version: 1.0`, direct structured data and
  client role `ROLE_USER`.
- `GET /receipts`: requires `Authorization: Bearer <local receipt-read token>`.

The receipt endpoint returns verification codes and minimal event metadata to its
local operator, never signing secrets or raw notification payloads. It accepts no
browser Origin and exposes no CORS grant. Do not share its token or expose this
listener with a tunnel or reverse proxy.

The certificate is self-signed and trusted only explicitly by the test client;
system trust is not changed. For a manual receipt read, use the printed certificate:

```sh
curl --cacert '<certificate path>' \
  -H 'Authorization: Bearer <local receipt-read token>' \
  'https://127.0.0.1:<port>/receipts'
```

Ctrl-C stops the receiver. Certificates and private keys are temporary and cleaned
up when it exits. The private key has mode 0600 in a private temporary directory.
Registrations, signing secrets and receipts exist only in process memory; restarting
the receiver discards them. Re-register and verify new test watches after a restart.

## Reproduce end-to-end tests

```sh
.venv/bin/pytest -q tests/test_notification_inbox_integration.py \
  tests/test_notification_inbox_browser.py
```

These tests automatically start and stop the receiver on temporary ports. They use
the real Courier, a temporary catalog/session, public task-update APIs, a real
Chromium page, and real certificate-verified HTTPS requests to the receiver.

The product intentionally rejects loopback addresses and nonstandard callback ports.
Do not paste the local receiver URL into the running public service or weaken that
validation. The fixtures use `https://inbox.example` as a synthetic logical public
origin and map that origin only to their own temporary TLS listener. DNS preflight
is substituted only for that logical host; no actual public host is contacted.
The TLS client explicitly trusts the temporary certificate. Product validation and
production transport code retain their default security settings.

The test flow starts with a question and a destination review, receives the challenge
at the actual listener, reads the code with the local operator token, confirms it
through Chat/API, adds new synthetic verification evidence, and receives a signed
update. The browser also opens Notification Preferences and retrieves the new
recommendation. Marketing eligibility is recorded only after proof; no advertising
messages are sent.

## Receiver security behavior

- Bind exclusively to `127.0.0.1`; reject non-loopback clients and browser Origins.
- Require JSON, enforce a 64 KiB request limit and bounded body-read time, and reject
  compressed requests. Receipt reads require the random operator token.
- Limit registrations/events to 100 each. A duplicate challenge cannot replace an
  existing watch's secret, destination route or code.
- Verify HMAC-SHA256 over the exact timestamp and transport bytes before accepting
  a task update, with constant-time comparison and a five-minute timestamp window.
- Require matching event identifiers and bind signing keys to their receipt route.
- Acknowledge valid identical event retries without storing or processing them twice,
  including retries signed with a fresh timestamp. Reject changed content under an
  existing event ID. Do not evict replay evidence to accept an unbounded sender.
- Follow no links and perform no outbound actions from a received message.

Actual network tests cover corrupted/missing signatures, stale timestamps,
conflicting and legitimate retries, TLS trust failure, 503 retry, 410 stop/revocation,
malformed A2A acknowledgements, private-address rejection and credential stripping.
These are local development checks; public DNS, deployment routing and Internet
reachability require separate validation.

Protocol references: [A2A 0.3 specification](https://a2a-protocol.org/v0.3.0/specification/),
[A2A specification](https://a2a-protocol.org/latest/specification/).

Results: [notification inbox verification report](../reports/security-2026-10-17-notification-inboxes/README.md).
