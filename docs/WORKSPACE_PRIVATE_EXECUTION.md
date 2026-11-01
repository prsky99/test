# Private one-call MCP execution

`workspace-private-mcp-run-v1` adds an independently authorized manual execution
to the saved-data foundation in [WORKSPACE_ACCESS.md](WORKSPACE_ACCESS.md).
The first supported graph is one manual trigger, one registered informational
MCP tool, one edge and literal inputs. Saving or downloading a snapshot still
confers no executable release, deployment, publication or result-delivery grant.

This uses current individual **administrator database sessions**, not a customer
identity provider. Customer signup/OIDC, external organization/provider proof,
BFF/SDK2 token exchange, executable deployment releases and ownership recovery
remain separate work. No public execution route or new SDK is introduced.

## Private storage and HTTP scope

`workspace_private_tickets` and `workspace_private_runs` are separate from all
legacy workflow, run, version, authority, checkpoint and result-outbox tables.
Their identifiers are `wpt_` and `wpr_` followed by 32 lower-case hexadecimal
characters. No synthetic global workflow row is created. Existing global workflow
run/detail/recovery/comparison/export readers therefore have no private content
to retrieve. The global observation journal may record the registered resource,
protocol, outcome and timing; it receives no workspace, draft or snapshot IDs,
private inputs or private results.

All operations are nested under:

`/admin/api/workflow-workspaces/{ws}/drafts/{draft}/snapshots/{snapshot}/execution`

- `GET /options`: current supported shape, capabilities and limits.
- `POST /prepare`: exact `{snapshot_revision}`; returns a ticket ID and the exact
  tool/input preview without contacting an agent.
- `POST /runs`: exact `{ticket_id, authorized:true, notice:"workspace-private-run-v1"}`;
  admits at most one run for that ticket and returns the bounded result/status.
- `GET /runs`: the latest 30 verified run metadata records for this saved version.
- `GET /runs/{run}`: the exact scoped result; no agent call, queue wakeup or replay.

Existing X-Dashboard, individual bearer session, strict raw JSON/body/origin
protection and no-store responses apply. Machine ADMIN_TOKEN, visitor credentials,
public/deployment keys, loopback fallback and bare IDs cannot authenticate here.
Current owner/editor membership and a global writable administrator role are
needed to prepare/admit. Current members, including viewers and global operators,
can read permitted results. Provisioning a workspace grants no implicit content
access to a nonmember superadministrator.

## One reviewed purpose and live barriers

Preparation reserves a five-minute ticket with a server-side HMAC. Its signed
claims bind the exact session reference/current user role, workspace and member
revisions/role, immutable snapshot state and hashes, current registered
tool/binding hash (including stored full schema when available), resource
observation generation and execution-control revision. Raw
session references, signatures and server ticket claims never appear in DTOs.
The opaque ticket ID alone grants no authority.

The selected tool must have explicit `readOnlyHint:true`,
`destructiveHint:false` and `idempotentHint:true` annotations and pass the shared
registered-tool/input policy. Authenticated, inactive, unsafe or unavailable
connections are refused. Only the saved literal input is sent. Raw URL/headers,
credentials, input overrides, A2A/x402, connected input composition, fallback,
automation, payment and delivery fields cannot be added to this purpose.
This profile does not certify a complete semantic input/output contract or agent
quality. It preserves the shared proxy's registered hash and live-schema input
validation rules; a missing full survey is not represented as a full-schema pin.

The operator reviews the exact input and selected resource/tool, then checks an
initially unchecked authorization for **both that input transfer to the selected
external agent and one manual execution**. Private means organization-scoped
access to stored data; the input does leave the platform for that chosen agent.
This permission does not authorize marketing, notifications or result forwarding.

Admission, signature/state validation, ticket consumption, private run insertion
and the audit entry share a native SQLite writer transaction. The shared MCP
transport performs the remote schema handshake outside the DB lock. Immediately
before its business `tools/call`, a dispatch guard rechecks the real live session,
current membership, active parent/snapshot, pinned binding/generation, controls
and deadline, then commits `dispatched`. This is the last server barrier; it does
not promise atomic cancellation of a network packet already accepted by an
external provider. Output completion is rechecked and sanitized before storage.

## Bounded certainty and inspection

The logical run has a fixed 12-second deadline and one business tool dispatch.
The shared transport still makes bounded MCP discovery/schema protocol requests;
`max_calls:1` does not mean one HTTP packet. Four shared local worker slots and a
native DB active-run cap bound concurrency. A timed-out worker retains its slot
until it exits, and detached late output cannot overwrite the private result.
No DB lock is held during provider I/O. The 12-second execution budget is not a
guaranteed end-to-end HTTP response bound for arbitrary DB lock contention, nor
does it cancel a packet the provider has already accepted.

A ticket is consumed exactly once with a unique private run relationship. Reusing
it from its same still-authorized session reads that run; it never dispatches
again. A different session cannot reauthorize the old ticket. Current membership
can separately inspect accepted history after a fresh login.

The stored state is `prepared`, `dispatched`, `succeeded`, `failed`, `unknown` or
`denied`, with signed private state and sanitized output. Lost response/timeout or
unconfirmed dispatched outcomes remain `unknown`. Stale unfinished rows are
projected as unknown after their original deadline; they are never resumed by a
read or by the legacy workflow worker. Confirmed pre-dispatch rejection is denied.
This is bounded at-most-one dispatch per ticket, not an exactly-once outcome or
an availability guarantee. Explicit new requests are separate authorizations.

Run lists are metadata-only. Result output is bounded to the existing 64KiB tree
contract, passes credential/known binding projection, and is displayed as
untrusted text. Arbitrary new personal data/secrets cannot be universally detected;
HMAC provides integrity rather than encryption. Database/backup access remains a
separate privileged storage boundary.

The lifetime ticket limit is 1,000 per workspace, at most 20 pending tickets per
actor, and at most 100 admitted runs per workspace in a rolling day. Tombstones
are not silently recycled. Expired tickets and result-retention/reconciliation
operations need a separately reviewed future lifecycle; this profile does not
promise indefinite new admissions or delete audit evidence to bypass limits.

## Browser and restore behavior

The existing centered native snapshot dialog contains the execution review.
The new profile is checked separately: an older server's missing execution route
disables the new section while preserving saved JSON functions. Selection,
modal, workspace, tab, session and logout changes invalidate pending responses,
abort waits and clear reviewed inputs/consent/output. Consent expires with the
server ticket and is consumed before POST. There is no automatic POST retry.
Uncertain admission or a nonterminal/unknown result locks a new start in that
view and points to scoped history/status. Browsing history never sends input.
CSP and native accessible dialog behavior remain in force.

Restore revokes every private ticket, deletes old sessions and pauses workspaces
and memberships. Signed run rows are retained rather than rewritten without their
key. An unfinished run linked to a revoked ticket reads as unknown. The restore
inventory contains bounded ticket/object IDs and review guidance, without input,
output, endpoint, signature or session material. No automatic replay, ownership
repair or membership reactivation is provided.

Verification uses disposable SQLite, actual individual sessions, real shared MCP
transport with controlled HTTP providers, native concurrency/rollback/response-loss
cases and Chromium. It does not create an operating workspace, invoke a real
provider, restart the user's server or establish production/OIDC acceptance.
