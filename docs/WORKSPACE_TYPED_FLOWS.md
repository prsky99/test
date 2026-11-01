# Private typed workflows

`workspace-private-typed-flow-v1` is a separate private execution profile for one
to ten explicitly reviewed stateless read-only MCP steps. Existing public
workflows, private one-call execution, legacy SDKs, product compilation and SDK 2
release permissions retain their own profiles. Saving or running a typed graph
does not publish it, create a deployment, enable fallback, authorize result
delivery, schedule work, or certify provider facts.

## Definitions and immutable versions

Each definition contains exactly `nodes`. A node contains `id`, `resource_id`,
`contract_id`, literal `input`, named `bindings`, an `after` dependency list and
nullable `when`. Supported contracts are `news.search.v1`, `docs.search.v1`,
`products.compare.v1` and `products.compare.v2`. Nodes require exact registered
full input/output schemas (or an explicitly reviewed deterministic adapter
described in [CAPABILITY_ADAPTERS.md](CAPABILITY_ADAPTERS.md)), explicit read-only/non-destructive/idempotent
annotations, a complete immutable stateless connection version, current contract
approval and unexpired successful execution and contract evidence. Credentials,
stateful sessions and arbitrary connection URLs are refused.

Creation or a successful current-revision update atomically stores a separately
signed immutable version and current flow pointer. An editor or owner needs a
current individual staff session and current explicit workspace membership.
An unrelated global administrator cannot read or run the graph. Native writer
transactions and revision CAS reject stale saves; failed commits leave neither
partial versions nor an updated pointer. Flow editing creates a different version
and invalidates already prepared reviews. Disabled or restored flow identifiers
cannot simply be reactivated by a new login or an edited backup-owner row.

A binding maps one target input field to `{node_id,path}`. Paths contain one to
six fixed, schema-declared property names or bounded fixed array indices. The
source must be an explicit dependency and a supported primitive compatible with
the target input type. The resolved value must pass the full current target
schema at execution; oversized values are refused rather than truncated.
Whole objects, arbitrary headers, request URLs, session credentials, dynamic
paths, expressions, executable templates, arbitrary Python/JavaScript and shell
commands are unsupported. Literal and projected input undergo the same private
literal/secret restrictions before sharing.

Conditions contain exactly `{node_id,path,equals}`. They may compare a declared
boolean or finite schema enum with an exact typed value. A false condition skips
that step; a skipped dependency also skips its dependants. Missing projected
fields stop the graph instead of fabricating input. Dependencies are checked for
unknown/self edges and cycles and sorted deterministically before storage.

## Whole-graph review and single execution

Staff routes are under
`/admin/api/workflow-workspaces/{ws}/typed-flows`:

- `GET /options`, `GET` and `GET /{flow}` inspect bounded private metadata.
- `POST` creates or updates with `{flow_id,revision,name,definition}`. Creation
  uses `flow_id:null,revision:0`. Saving makes no provider call.
- `POST /{flow}/prepare` takes the exact current revision. Its five-minute
  one-use review shows every selected agent/tool, all literal inputs, named
  previous-output sharing, explicit dependencies/conditions and call/time limits.
- `POST /{flow}/runs` takes `{ticket_id,authorized:true,
  notice:"workspace-whole-graph-run-v1"}`. The initially unchecked consent covers
  the visible whole graph for one run. It is not synthesized from hidden
  per-node tickets, remembered consent or rewritten one-call snapshots.
- `GET /{flow}/runs` and `GET /{flow}/runs/{run}` inspect retained private history.
- `POST /{flow}/disable` takes the current revision, advances it and blocks
  pending/next dispatches. It cannot recall an external request already sent.

Review binds the current named session, user role, workspace/member revisions,
flow/version hashes, approval/resource generations and runtime control revision.
All are rechecked before every business dispatch, after every response and before
successful completion. The current resource/tool admission also validates the
actual resolved input. Withdrawing authority between steps prevents the next
request and hides any unaccepted output. Each node can dispatch once; at most ten
business calls fit the fixed 60-second deadline and individual 12-second outbound
budgets. No fallback or automatic retry occurs.

The runtime shares the existing four-slot private-execution semaphore and checks
current active private/typed runs in the database. A timeout retains its slot
until its original worker actually ends. Admission, one-use ticket consumption
and signed run state are committed before provider work. Each prepared step is
committed, then `dispatched` is committed by the existing transport's actual
business-dispatch hook before the packet is sent. No database writer lock is held
while waiting for HTTP.

Concurrent submissions of the same consent return the original run and cannot
start another provider call. Dispatched transport uncertainty, interruption,
authority changes and late results remain `unknown` when their external effect
cannot be established. A late worker cannot overwrite a terminal parent outcome
or start another step. Definite contract rejection stops the graph as a failed
typed result. There is no crash-resume worker that silently replays the graph.

## Output, accounting and restore

Outputs pass the existing private projection/masking boundary and contract
validation. Aggregate accepted outputs are limited to 64 KiB. Normal DTOs contain
step status/output only, not ticket claims, signing material, provider endpoints
or raw transport errors. Optional authenticated encryption seals newly retained
step output using independent purpose and version/run/node/input-hash additional
data. See [Private artifact keys](PRIVATE_ARTIFACT_KEYS.md) for key custody,
rotation, grace, revocation and accurate plaintext/default-storage limits.

When independently enabled by its current owner, the runtime simulation meter
records one logical graph admission and one attempt per actual dispatched node
in the same transactions. Skipped steps and replayed consent add no attempt.
Terminal success settles the authorized simulated units once; uncertain work
does not become successful usage. This remains `TEST_UNIT`, `actual_money:false`.

The staff editor offers a recorded agent/contract selector and local contract
step presets, then exposes the complete typed graph for explicit review. Editing
or closing the dialog clears pending consent. It never silently saves a changed
definition, retries uncertain submission or promotes contract evidence globally.

Backup restoration permanently blocks all old typed-flow identifiers, pauses
workspaces and current authority, and preserves signed historical graph/run/step
records. A fresh independent review requires a new definition and current
authorization. A restored uncertain run is never automatically submitted again.
No claim is made that this bounded unit supplies general durable distributed DAG
recovery, stateful MCP, A2A sessions, arbitrary connectors, public app deployment,
automatic payments or production throughput/SLA acceptance.

## Verification

Isolated tests exercise actual two-step MCP request/response projection, branch
skipping, unsupported graphs, consent and replay races, approval/session/resource
changes, timeout/late completion, native transaction rollback, restore blocks,
optional encryption and simulation accounting. Native Chromium tests use the
actual dashboard, private APIs and fixed synthetic providers with all browser
traffic intercepted. User operating servers and real provider/identity services
are outside that fixture scope. The completion report owns final source hashes
and unique regression counts.
