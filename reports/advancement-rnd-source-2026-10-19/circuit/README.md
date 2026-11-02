# Configured private circuit source

The new `ReliabilityCircuit` is trusted-server disabled by default. It provides
private core methods only: configuration, signed-source ingestion, explicit
probe binding, explicit result refresh, status and one shared evidence composer.
There is no route, UI, scheduler, new executor or automatic provider call.

The owner must supply every failure/unknown threshold, observation window,
validity period, cooldown, probe validity period, environment and expiry.
Limits of 50 circuits, 500 permanently consumed source references and 100
in-window samples per workspace/circuit are capacity bounds, not operating
thresholds. Capacity exhaustion excludes the source. Historical source claims
are not deleted to make old jobs eligible again.

Closed circuits can open from current signed dispatched private-run outcomes or
current signed trusted-adapter evaluation observations. Local denials before the
dispatch guard do not count as provider failures. Time, ordinary successes and
configuration changes never close an open circuit. Reapproval after withdrawal,
expiry, pin change or restore requires a fresh probe.

A probe is an existing, separately approved evaluation job reserved after the
open episode. Binding it changes metadata to half-open without scheduling or
dispatching it. The existing evaluation engine and gateway perform any separately
authorized test. A successful refresh requires the same job, current owner,
plan/control/corpus/pin, post-binding times, current qualified base evidence and
the exact trusted MCP adapter's contract-validated response marker in the
original signed job. A generic `completed` result or client-supplied marker
cannot supply this proof. Unknown and failed probes stay open, with no replay.

The marker describes a trusted adapter observation after the existing dispatch
authorization guard; it does not prove network receipt merely because a
pre-dispatch record exists. It does not assert independent business quality.

Routing and admission use the same composer. The unconfigured composer preserves
the base projection exactly. Configured state/revisions/episode/hash are included
in both decision source hashes and current admission checks. Half-open and
quarantined hosts are excluded along with open hosts. The existing execution
engine retains one call and zero replacements, and retained results stay
readable after circuit withdrawal.

Permanent restore markers cover circuit generations and source references;
signed history is preserved. The bounded scope registry is verified before a
resource is matched so an unsigned resource locator cannot hide its circuit.

## Verification artifacts

- `pytest-final.xml`: final isolated core, API, concurrency and integration tests.
- `bandit.json`: static scan of the four changed core modules and native helper.
- `baseline.json`: pre-change hashes of the existing evaluator/worker/router.
- `verification.json`: final counts and source hashes.

The parent-owned native helper is `scripts/rehearse_circuit_postgres.py`.
It rejects non-fixtures before database access, accepts only the fixed synthetic
key, graph and MockTransport destinations, and uses a separate disposable
workspace. Its two tool calls remain inside MockTransport. Actual native
PostgreSQL execution and whole-project aggregation belong to the parent run.

No operating target, production threshold, real provider, notification, payment,
payout, advertising or public Workspace activation was used or enabled.
