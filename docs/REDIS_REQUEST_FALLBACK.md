# Redis request fallback and exact counters

2026-10-18 · v1.31 · internal runtime contract.

The current Redis client is pinned to the exercised `redis==8.1.0`. This does
not install or configure a Redis server. No operating Redis instance or cluster
is used by the regression suite.

## Request boundary

An unavailable hub returns immediately to the existing local fallback. After its
monotonic cooldown, one daemon worker reserves a reconnect epoch and probes in
the background. Concurrent requests do not each create a connection or wait for
that worker. Explicit initial construction can perform one bounded socket probe;
healthy-client commands retain their configured socket timeouts. This contract
does not promise zero latency for every DNS, startup or network operation.

The client uses `Retry(NoBackoff(), 0)` and no retry-on-error list. It therefore
does not multiply a short socket timeout with the library's default exponential
retry delays. The original full regression reproduced a 6,759 ms MCP search and
a workflow dialog timeout; their existing timing thresholds were preserved.

Probe epochs, closed state and client identity fence completion. Reset invalidates
an outstanding probe before closing its pools. A late probe cannot publish after
reset, and an old command cannot revive or disable a replacement client. Failed,
replaced and abandoned pools are closed. The fixed public Python method APIs and
the existing local rate-limit/cache fallback remain available.

## Lua identity

Sorted-set scores remain observation timestamps. Members are fresh cryptographic
nonces for each logical call, supplied as the fourth script argument. A timestamp
is not a request identity: identical timestamps previously collapsed multiple
requests/violations into one member, allowing a limit or jail threshold to be
missed. Both Lua scripts retain atomic prune/count/admit/expiry behavior and now
count those calls separately. Public callers cannot select the nonce or script.

This is not an exactly-once distributed request protocol. Client clock agreement,
multi-node outage policy, Redis authentication/TLS, failover and operating cluster
capacity require separate deployment acceptance. During an outage the fallback
is local to each application process, not a shared distributed quota.

## Evidence and operating reflection

The new runtime tests use refused/delayed disposable loopback endpoints and
controlled clients. Independent tests run the actual Lua on a temporary private
Redis process, including same-time collisions, script reload and window expiry,
plus single-flight/reset/stale-client races. They stop their own process and do
not connect to the operating Redis port. Initial failures, environmental bind
limits and test harness corrections are retained separately.

The focused runtime/native/browser/MCP checks passed before the final frozen
affected suite. [Final evidence](../reports/advancement-legacy-vector-index-2026-10-18/README.md)
records exact counts and scanner scope. The previously observed user server
predates this Redis source change; the user controls the final restart.

[Platform design](PLATFORM_ADVANCEMENT_DESIGN.md) ·
[Vector publication boundary](LEGACY_VECTOR_INDEX_GUARDS_PLAN.md) ·
[Remaining batches](REMAINING_WORK_BATCHES.md).
