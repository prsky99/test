# Owned catalog observations and consistent read-only capture

2026-10-18 · v1.28 · explicit private adapter profile, no operating integration.

`catalog_observations.py` adds typed health, survey and evaluation commands over
caller-owned SQLite/PostgreSQL adapters. Constructors/imports open no database;
`OBSERVATION_SCHEMA` is explicit DDL for two private tables and a history lookup
index. Existing server imports, Store/collector methods, public frontend, SDK,
operating schema and backend selection are unchanged.

## Ownership and deliberate compatibility limits

Legacy health recording uses completion-time wall clock, has no expected resource
revision, and can write observed authentication and price/payee alongside health.
Legacy survey/usage and evaluation also lack owner-clock/CAS checks; usage may
retain a previous full schema after malformed input or equal compact hash.
Legacy evaluation can update trial state. These are observed source behaviors,
not claims of production incidents or changes to those operating methods.

The new private profile deliberately separates three owners:

- `HealthObservation(outcome, next_check_at=None)` accepts healthy/reachable/fail.
  Success resets the failure streak; failures become failing then down at three
  consecutive failures. First failure time and historical last success are
  preserved, including timestamp zero. There is no random retirement/backoff,
  automatic scheduling, auth observation, price/payee or registry update. Rolling
  24-hour counts use only this profile's committed health journal, never an
  invented merge with legacy health history.
- `SurveyObservation(tools_json='[]', guide_json='{}', full_tools_json=None,
  error_code=None)` accepts a strict compact tool list and guide object, optionally
  complete schemas with matching unique tool names. Lists are sorted by name;
  hashes use canonical JSON. Full schema normalization preserves schema keywords
  and rejects unsupported top-level tool fields, malformed/full-name mismatches
  and silent fallback. No full schema explicitly clears the previous full schema
  even when compact tools are unchanged. Empty success is distinct from failure.
  A failed survey uses only the fixed `survey_failed` code and default empty
  inputs; it preserves previous tool/guide payloads, clears `cap_checked_at` and
  records a failed owner head. It cannot certify the previous schema as fresh.
- `EvaluationObservation(score, grade, security)` records finite0–100,
  A/B/C/D/F/U and ok/review/quarantine/unknown. This records a trusted caller's
  bounded assessment, not independent quality, successful execution or a contract
  grade. It writes no trial state, approval or connection/evidence record.

Every accepted survey also clears evaluation freshness (`eval_at`) while keeping
its previous score/grade/security and independent evaluation clock. A subsequent
evaluation cannot predate the current survey head or retained resource survey stamp. Health time remains independent
from survey/evaluation time. All three owners preserve registry fields, stable
identity, first/last registry sighting, active status, raw registry content hash,
corpus/model identity and immutable connection/version/approval/evidence history.
Current eligibility is deleted, never synthesized. These commands are private
trusted boundaries; they do not authorize an untrusted caller or validate provider
provenance.

## Atomic operation, clocks and recovery

`CatalogObservations.record(resource_id, command, operation_id='ob_'+32 lowerhex,
expected_revision=..., observed_at=...)` takes keyword-only operation/revision/time.
Expected revision must be captured before the external observation begins; the
caller must not rebind an old result to a newly read revision after a conflict.
The API enforces the supplied generation, not the real-world time of data capture.

The existing explicit catalog write control is checked under the same SQLite
writer transaction or PostgreSQL control-row lock as registry writes. It is
private operational control, not public authentication. Replays require the same
resource, owner, payload, expected revision and finite UTC timestamp; changed
reuse is refused. A revision conflict is an immutable receipt with no owner
mutation. Missing resources are durable conflicts; unversioned existing resources
are refused rather than adopted. Stale observation errors create no receipt.

Each owner clock is strictly increasing for new accepted operations and also
respects an existing owned resource stamp. Cleared source stamps cannot reset the
owner high-water mark. Observations cannot predate the last registry sighting;
no claim is made that caller clocks are attested. Cross-owner clocks may differ.
The catalog revision increments on every accepted observation, including equal
content. The revision row's `updated_at` retains its existing registry-sighting
meaning and continues to equal `resources.last_seen`; owner times live separately.

One transaction owns resource changes, revision CAS, current-cache invalidation,
index head/job enqueue, owner clock and immutable operation receipt/payload. The
existing index head advances even when corpus text is unchanged, immediately
hiding an older artifact; an earlier materializer cannot acknowledge the newer
work. Current model/corpus hashes are reused, never silently switched. External
calls, model work and `Registry.current` are absent from this transaction.

Intermediate failure rolls everything back. A real commit followed by a lost
acknowledgement remains `commit_unknown` with an unusable adapter. A fresh
connection calls `reconcile(operation_id)` to inspect the durable result. Exact
caller replay returns the original receipt without a second mutation; there is
no automatic retry/reconnect. `current(resource_id, owner)` returns bounded private
clock/outcome metadata. Reprs omit private commands/results and raw journal data.

Payloads use strict canonical JSON: duplicate keys, nonfinite values, invalid
Unicode/NUL, depth/visited-value/size excess are refused. Survey payloads together
must fit12KiB, with at most100 unique named tools; complete schemas are not
truncated. Existing adapter parameter/result bounds and native transaction
contracts remain in force. Private journals have no new operating retention
activation; bounded retention and migration policy remain integration gates.

## Read-only capture

`catalog_capture.py` captures fixed selected catalog fields through explicit
adapters without opening database paths, Store, network or configuration. Each
source is captured in one native read-only repeatable snapshot. SQLite dirty
reads and TEMP shadows, PostgreSQL statement-level isolation and unsupported
schemas are refused. Legacy capture reads selected resource fields only;
candidate capture also reads the fixed revision/head/job/projection metadata.

The result is private, bounded and non-partial: limits match the supplied-snapshot
shadow (100 resources,500 metadata rows per kind,1000 total rows,2MiB per side,
16KiB per scalar). Adapter post-decoding/result bounds can be stricter. Invalid,
missing, oversized or unsafe captures remain incomplete with fixed aggregate
errors; no raw partial snapshot is reported. The pure shadow still does not
validate artifact bodies/search quality, owner heads/journal, worker authority or
upstream truth. Two source snapshots are individually consistent, not an atomic
shared instant across two databases. A report cannot authorize migration.

[Final verification](../reports/advancement-catalog-observations-2026-10-18/README.md)
records actual supported behavior and scope, including failed pre-fix evaluation
freshness reproduction. [Cutover contract](CATALOG_CUTOVER_CONTRACT.md) separates
these private source units from operating activation.
