# Proxy attribution and blocked-request observability remediation

Implemented source changes only. No running process, live database, private environment file, current security rule, or proxy configuration was changed. Existing dirty changes were preserved.

## Changes

- `agent_market/gateway/deployment_security.py`: one shared ingress policy parses explicit IPv4/IPv6 addresses and CIDRs, rejects wildcard/trust-all/interface-scoped settings, validates every X-Forwarded-For element, bounds chains to 16 hops/2,048 characters, and selects the rightmost untrusted hop. Missing/malformed chains fall back to the actual socket peer. Vendor address headers are ignored.
- An outer `TrustedIngressMiddleware` applies the validated client and trusted scheme before all application identity/rate-limit consumers. Its internal ASGI scope marker prevents a second parser from consuming client-supplied prefixes. It passes lifespan scopes through unchanged. `SecurityManager` uses the same policy for direct isolated app instances.
- `agent_market/gateway/server.py`: both actual server configurations wrap their app in that middleware and disable Uvicorn's independent proxy-header rewrite. Both also use `log_config=None`, preserving the central logging queue's timestamps, redaction, and level controls provided by the parent task.
- `agent_market/concierge/front.py`: only the existing banned-address branch in `guarded_request` now invokes blocked-request recording before the same HTTP 403 response. HTML and other presentation changes belong to the parent task.
- `agent_market/concierge/security.py`: all banned-address requests increment an exact process-local counter. Detailed samples are bounded to one per peer per minute and 30 per minute per process, with a 1,024-peer cache. Durable rule hit updates batch previously suppressed hits when another sample is permitted. Samples do not wait for an occupied Store lock or commit a caller-owned transaction. SQLite sample persistence temporarily uses a 50-ms busy timeout and restores the original timeout. Counter/sample decisions and successful/unsuccessful persistence counts are separate fields in the existing administrative security status API.
- `deploy/Caddyfile`: explicitly enables strict right-to-left upstream parsing and forwards Caddy's validated `{client_ip}` rather than its raw transport peer. The default policy trusts no external upstream network, and still removes CF-Connecting-IP and X-Real-IP. No provider address ranges or exemptions were automatically added.
- `deploy/gateway.env.example` documents optional `CADDY_TRUSTED_UPSTREAMS`; `deploy/SECURITY.md` documents policy, sampling, rollout, and limits. These are examples, not edits to real runtime settings.

## Verification

The isolated regression file is `tests/test_front_ingress_observability.py`. It covers shared-proxy clients with independent bans, forged vendor/XFF/protocol headers from untrusted peers, IPv4/IPv6 CIDR chains, duplicate headers, malformed/oversized/scoped addresses, explicit empty trust, one-time identity resolution, blocked counters, global/cache limits, batched hits, a busy Store lock, caller-owned transaction preservation, timeout restoration, and an actual isolated SQLite writer lock.

Validation command (no project server):

```sh
REDIS_PORT=6399 .venv/bin/python -m pytest -q tests/test_front_ingress_observability.py tests/test_front_ddos_and_admin_security.py tests/test_front_hardening_followup.py -k 'not real_slow_drip_socket'
```

Final result: **65 passed, 1 deselected** in 14.20 seconds, including 28 new ingress/observability cases; see `proxy-final.log`. An initial broader run identified an unrelated empty-catalog bootstrap SQL ambiguity, which the parent task repaired; the CSP regression is included in the final run. The single deselected test is `test_real_slow_drip_socket_cannot_extend_the_total_deadline`, whose local ephemeral socket bind is denied by the execution sandbox. The parent task can run it with the appropriate isolated-socket permission.

Python syntax compilation passed. The project interpreter has no Bandit module; a focused scan ran with the isolated security environment supplied by the parent task. `proxy-bandit.json` contains no high-severity finding. Existing medium findings are a temporary-path string used only to isolate test Redis namespaces and parameterized security-query construction from fixed SQL clauses; they do not introduce attacker-controlled SQL. The parent task owns the consolidated secure-coding scan. Caddy is not installed and the Docker daemon is unavailable, so executable Caddy configuration validation was not performed here. No public/live malicious-input probes were run.

## Rollout and remaining limits

1. The operator must restart the application normally to load the changed middleware and counters. No restart was performed. Direct process deployments use their explicitly audited `FORWARDED_ALLOW_IPS`; Compose continues to trust its fixed Caddy ingress only.
2. Caddy configuration requires version 2.8 or newer for strict parsing. Run `caddy validate --config deploy/Caddyfile --adapter caddyfile` against the intended environment, then use the operator's normal authorized reload/redeploy. Changing source alone does not alter today's serving process.
3. If a CDN/tunnel precedes Caddy, audit its current ingress ranges, origin restrictions and XFF overwrite/append behavior before setting `CADDY_TRUSTED_UPSTREAMS`. Do not treat arbitrary CF-Connecting-IP or other caller-supplied headers as identity. The default does not automatically trust Cloudflare. If an upstream already discarded the original client, code alone cannot recover it.
4. Validate independent clients behind the same verified ingress using an isolated environment before rollout. Existing proxy-address bans are retained; inspect and remove an obsolete ban only through authorized administration after attribution is verified.
5. Exact blocked counters are process-local and reset on restart. Scanner triggering incidents remain distinct from subsequent banned-address rejections. Durable detailed events are samples, and persistent rule hits are lower bounds when tails remain unflushed, cache entries are evicted, database writes fail, or the process restarts. The sample counters expose persistence loss rather than implying that all samples were committed. Non-SQLite backends retain their native transaction timeout policy; the 50-ms bound is SQLite-specific.
6. HTTP/client attribution improvements do not establish real-user identity, complete business outcomes, or an uptime SLO. Production access and business-outcome reconciliation still require the parent task's consolidated rollout and verification.

Caddy semantics were checked against its [official trusted-proxy documentation](https://caddyserver.com/docs/caddyfile/options#trusted-proxies) and [strict chain-parsing guidance](https://caddyserver.com/docs/caddyfile/options#trusted-proxies-strict).
