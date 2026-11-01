# Public frontend security deployment

For the current Mac terminal deployment, see the [Cloudflare dashboard guide](CLOUDFLARE_NATIVE_SETUP.ko.md) and the [native runtime guide](NATIVE_RUNTIME.ko.md). The [Caddy setup guide](CADDY_SETUP.ko.md) covers a separate deployment option. Native Cloudflare Tunnel deployments and the Compose/Caddy network have different trusted peers.

The Compose profile sets `DEPLOYMENT_MODE=production`. It trusts only Caddy's fixed address (`CADDY_PROXY_IP`, default `172.30.90.2`) on the dedicated `PROXY_SUBNET` network. Never set `FORWARDED_ALLOW_IPS=*` or a trust-all CIDR. If the subnet conflicts with existing infrastructure, override both settings together when rendering Compose.

Only Caddy publishes ports 80/443. The administrative API remains bound to host loopback on 8200, accessible through an authenticated SSH tunnel. Port 8400 is not published. Caddy overwrites forwarded client/protocol headers and removes unverified vendor address headers. The default profile trusts no external hop before Caddy.

## Client attribution and blocked-request records

Caddy 2.8 or newer parses `X-Forwarded-For` from right to left with `trusted_proxies_strict`, then sends its validated `{client_ip}` as a single upstream header. `CADDY_TRUSTED_UPSTREAMS` is a space-separated list of explicitly audited addresses/CIDRs before Caddy; the example trusts loopback only. If a CDN or another proxy is added, verify its current address ranges, restrict origin access to that ingress, and confirm that it overwrites or appends the actual connecting address. This is an operator-controlled configuration change, not an automatic provider allowlist. Do not add `private_ranges`, trust-all ranges, or arbitrary vendor headers as a shortcut. `CF-Connecting-IP` and `X-Real-IP` are removed and are never used as independent proof of identity.

The application's `FORWARDED_ALLOW_IPS` trusts its immediate ingress, which remains Caddy's fixed address in Compose. A single outer ASGI middleware validates every XFF address, caps the chain at 16 hops/2,048 characters, and resolves the rightmost untrusted hop. IPv4 and IPv6 CIDRs are supported; malformed chains fall back to the socket peer. It supplies that identity to all application consumers, while Uvicorn's separate proxy parser is disabled to prevent double parsing. Direct process deployments must explicitly configure their own ingress chain. Updating code alone cannot recover client information that an upstream proxy discarded.

Banned-address requests now increment an exact process-local `blocked_403` counter before returning HTTP 403. Detailed `blocked_ip_403` events are sampled at most once per peer per minute and 30 times per minute per process. `blocked_403_sampled` and `blocked_403_suppressed` describe sample decisions; `blocked_403_persisted_samples` and `blocked_403_unpersisted_samples` separately expose durable sample outcomes. Samples skip a busy Store lock or caller-owned transaction; SQLite sample writes use a temporary 50-ms busy timeout and restore the original timeout. The peer sample cache is capped at 1,024 entries. Persistent rule hit counts are batched when a new sample is allowed and are lower bounds: quiet tails, cache eviction, failed writes, and restarts may leave counts unflushed. Process counters reset on restart. Scanner trigger events remain distinct from subsequent banned-address requests. These limits prevent a blocked-request flood from causing one database write per request.

After an authorized rollout, verify two independent clients through the same audited ingress: a scanner client's jail must not block the other client. Verify that an untrusted direct peer cannot choose its identity or HTTPS scheme using forwarded headers. Keep production tests read-only; use isolated apps and databases for malicious-input regressions. Existing bans are not rewritten or removed by this change. Inspect and remove any obsolete proxy-address ban only after confirming attribution through the authorized administration interface.

Application changes require the operator's normal server restart. Caddy configuration/environment changes require its normal validated reload or redeploy. No running service or private environment file is changed by source edits. The configuration semantics follow the [official Caddy trusted-proxy documentation](https://caddyserver.com/docs/caddyfile/options#trusted-proxies) and its [strict chain parsing guidance](https://caddyserver.com/docs/caddyfile/options#trusted-proxies-strict).

## Before startup

1. Copy `gateway.env.example` to the ignored `gateway.env` and set its permissions to `600`.
2. Set `ADMIN_TOKEN` to a random secret of at least 32 characters (`openssl rand -hex 24` generates a suitable value). Set `ADMIN_BOOTSTRAP_PASSWORD` to a different secret of at least 16 characters for a fresh database. Do not place either secret in Git, command-line arguments, logs or reports.
3. For an existing database, change the default administrator password through the authenticated local administration interface before enabling production mode. `ADMIN_BOOTSTRAP_PASSWORD` does not overwrite an existing account. Startup deliberately rejects active default administrator credentials.
4. Keep `ALLOW_PRIVATE_AGENT_URLS=0`. Set `AGENT_FRONT_URL` to the actual public HTTPS origin. The Compose profile sets `SSL_ENABLED=0` because Caddy obtains and renews publicly trusted certificates. It does not use development self-signed certificates.
5. From `deploy`, validate with `docker compose --env-file gateway.env config --quiet` and `caddy validate --config Caddyfile --adapter caddyfile`. These commands validate configuration, not a live deployment. Keep `--env-file gateway.env` on Compose build/deploy commands so interpolation and container settings use the same file. Then build/redeploy during the appropriate operational window.

The image installs the reviewed hashed build-tool lock, then the hashed production lock without unpinned build isolation, and removes build-only tools. The gateway drops Linux capabilities and disallows privilege escalation. Validate the resulting image/package inventory; a local environment audit does not inspect previously built images.

Direct application TLS, if separately configured, requires provisioned certificate/key files that load successfully. Production startup does not create or renew development self-signed certificates. The public HTTPS check below remains necessary to verify the actually served chain, hostname and expiry.

## Verify after rollout

From the repository root:

```sh
.venv/bin/python -m scripts.check_front_deployment --url https://agentconcierge.biz/
.venv/bin/python -m scripts.audit_stored_tokens --db gateway-data/gateway.sqlite3
```

The HTTPS tool performs one read-only request with certificate verification. Its report contains no cookies, bearer values or response body. Expect a verified chain, HSTS/nosniff/frame protection, a nonce-based `script-src`, `script-src-attr 'none'`, and no inline/eval script allowance. Inline CSS remains permitted for the existing layout; JavaScript event attributes are blocked.

The HTML nonce is fresh on each response. UI events use fixed callbacks selected by inert data attributes; no runtime code evaluation is used. Downloaded standalone apps have their own nonce-based CSP meta policy and no network access.

## Outbound budgets

Public registration inspection/health probing, MCP discovery/execution, REST specification fetching/calls and notification responses now use bounded transports. Synchronous operations share a 25-second absolute socket/stream budget across their requests, limit each response to 1 MiB, and allow at most 16 requests. Notifications retain their stricter 256 KiB card and 64 KiB reply limits. Preflight DNS checks have a separate maximum of five seconds and a bounded four-worker resolver. Testbench operations retain a 25-second async deadline and a 1 MiB response limit.

Every connection validates and pins its resolved public IPs. Environment proxies and redirects are disabled, TLS verification is enabled, and every socket read/write/TLS handshake is clamped to the remaining operation time. Clients request identity encoding; compressed upstream responses are rejected to avoid decompression bombs. APIs that insist on compression must be adapted explicitly rather than weakening this policy.

## Existing token hygiene

The inventory tool defaults to read-only counts. It never prints token values. To scrub legacy visitor token text in an explicitly selected database:

```sh
.venv/bin/python -m scripts.audit_stored_tokens --db gateway-data/gateway.sqlite3 --apply --backup-dir gateway-data/security-backups
```

The backup directory must be owner-only (`700`); rollback files are created as `600` and excluded from Git. They contain original credentials and must remain private. Scrubbing masks token text in messages/reports and hashes inquiry references; it preserves visitor token hashes, identities, balances and context/session ownership. It is idempotent. This is a logical scrub, not a forensic erasure of historical WAL pages, filesystem snapshots or backups.

New administrator sessions are stored as prefixed SHA-256 hashes. Existing raw administrator sessions are upgraded when their owners authenticate through the new code, without changing their bearer token. Stored hashes cannot be used as bearer tokens. Deploy the new version consistently across workers before relying on migration; the inventory reports the number of legacy rows still requiring upgrade. Do not force a bulk live migration while old workers are still using raw session keys.

See [dependency maintenance](DEPENDENCY_MAINTENANCE.md) for the separated profiles, project-local patched runtimes and release inventory checks.
