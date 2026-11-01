# Independent automation for published connections

2026-10-18 · `published-connection-automation-v1` · bounded administrative automation.

An already tested and published canonical news-to-documentation connection can
receive a separate automation grant. Publication, an SDK deployment and one
visitor run do not authorize unattended execution. Existing manual SDKs, public
pages, private drafts and controlled pairs retain their own purposes.

## Review and trigger scope

A current highest administrator reviews the fixed English news query, original
absolute UTC lower bound, result limit, exact documentation recipient and settings,
and the rule that forwards only the first verified safe news title from the same
run. The future title is unknown at approval time. The news lower bound never
silently becomes a rolling period. Source checkpoint/provenance checks still run
immediately before downstream dispatch; an invalid or uncertain title stops it.

The review also fixes one trigger, expiry and maximum admitted runs. Independent,
initially unchecked acknowledgements authorize future-title sharing and that
trigger. Supported triggers are:

- An interval schedule of 300–86400 seconds, with no catch-up burst.
- An authenticated administrator event with a stable opaque event ID and a fresh
  explicit event-action acknowledgement. This is not an external webhook API.

Grant duration is 300–86400 seconds, clipped to the publication and original
retained test validity; maximum admitted runs is 1–100. Scheduled activation must
fit before expiry. Event admissions have a minimum 60-second interval. A consumed
proposal nonce cannot issue another grant; grant issuance is bounded to 20 per
owner per hour. No trigger fires merely by opening options, reviewing, issuing an
event grant or reading history. A schedule waits until its first interval is due.

## Durable admission and current authority

The canonical definition stays manual and immutable. The independent automation
tables are `workflow_connection_automation` and
`workflow_connection_automation_admissions`; they do not turn on legacy schedules.
A server-signed purpose binds the grant, publication revision, original proof,
definition, rule, owner, trigger, exact slot/event ID and expiry. A fresh internal
execution principal is minted for each admission and expires no later than the
short run ticket. It carries independent automation scope; it cannot borrow a
manual visitor, SDK, delivery or private-pair permission.

The actual run insertion, quota increment, slot receipt and signed run authority
are committed in one SQLite writer transaction. Failed admission rolls them back
together. Repeating an accepted event ID identifies its retained run rather than
creating another run or consuming a quota slot. The UI resolves an ambiguous
submission through read-only history, without automatically retrying its POST or
generating a replacement event ID.

Admission, dispatch and recovery verify current publication, owner role, control
epoch, grant revision/expiry and exact signed connection. Execution retains the
standard absolute 25-second deadline, at most two tool calls, lease/fence,
checkpoints and conservative dispatch certainty. It has no fallback, credentials,
extended budget, result-delivery grant, advertising or notification permission.

An active or unknown admitted run blocks another admission under that grant.
Unknown external outcomes retain their receipt and are not automatically replayed.
A read-only history query does not invoke a provider or advance the scheduler and
does not require fresh provider eligibility. It remains a private administrative
inspection, not a public status capability or expert-quality assertion.

## Revocation, restore and operations

Current-revision withdrawal prevents new dispatch and requests cancellation of
unfinished runs for that exact automation identity. Publication withdrawal also
requests their cancellation. An already transmitted request may finish; revocation
does not promise exactly-once external execution. Restoring a backup deactivates
automation grants, increments their revisions and retains admission tombstones.
No old schedule, event or unknown outcome is automatically reactivated/replayed.

The existing worker/scheduler polls these separate interval grants. New backend
source requires the user's normal terminal restart; development never replaces or
restarts that server. Live grant issuance, provider execution and operating
acceptance require appropriately approved published data and explicit actions.

## Private API

All routes require current highest-administrator authentication. Mutations require
the existing same-origin/CSRF checks and strict bounded JSON. Responses are
no-store; internal exceptions and signed execution authority are not returned.
The base is
`/admin/api/workflow-publications/releases/{release_id}/automation`:

- `GET /options`, `GET /history`: readiness and retained grant/run metadata.
- `POST /prepare`: exactly `trigger`, `interval_seconds`, `max_runs`, `ttl_seconds`.
- `POST /issue`: signed proposal, separate `sharing_authority`/`sharing_notice`
  and `trigger_authority`/`trigger_notice`.
- `POST /grants/{grant_id}/revoke`: current integer `revision`.
- `POST /grants/{grant_id}/trigger`: stable `event_id`, explicit `authority` and
  the current event notice. It accepts no arbitrary tool input or destination.

Notices are `workflow-connection-automation-share-v1`,
`workflow-connection-automation-trigger-v1` and
`workflow-connection-automation-event-v1`. They are distinct from all manual and
deployment notices. Unsupported public webhook routes remain absent.

Broader events, rolling windows, dynamic inputs, arbitrary graphs, organization
delegation and result delivery require separate reviewed contracts. This bounded
release does not complete R-07, G0/G1, human quality evaluation or production HA.

Related: [public connections](WORKFLOW_PUBLIC_CONNECTIONS.md),
[manual connected SDK](WORKFLOW_CONNECTED_SDK13.md),
[read-only storage observations](WORKFLOW_STORAGE_OBSERVATION.md).
