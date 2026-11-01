# Private workspace drafts and saved snapshots

The `workspace-private-snapshots-v1` profile is an administrator-managed private
workspace foundation. It stores workspace membership, editable drafts and
immutable saved content snapshots. A saved snapshot is not a tested result,
publication, executable release, deployment or permission to contact an agent.

This profile has no public signup, OIDC integration, external organization
identity verification, SDK2 runtime or provider ownership claim. It does not
insert private objects into the existing `agent_workflows` namespace. Existing
public templates, Chat, gateway calls and SDK1.0/admin1.1/literal1.2/connected1.3
retain their separate contracts and authority checks.

## Identity and membership

Access requires an actual unexpired `admin_sessions` record for a current active
administrator. Session references are server-side `sha256:` references to bearer
tokens. A workspace ID, display author, browser selection, visitor token,
deployment key, loopback fallback or configured `ADMIN_TOKEN` is not a workspace
session credential. The API does not accept an actor ID or owner identity as an
authentication substitute.

The core accepts `SessionActor(user_id, session_ref)` from the authenticated
transport and checks its joined session and current administrator row for each
operation. Session expiry, logout, user deactivation or role changes affect
subsequent requests. Workspace and membership activity are checked separately.

Workspace roles are `owner`, `editor` and `viewer`. Owners manage membership and
revocation; editors edit drafts and save snapshots; viewers read authorized
content. The global `operator` role imposes a read-only ceiling even when a
workspace membership has a stronger role. Provisioning belongs to the platform
superadministrator control plane. It does not automatically grant access to
another workspace's private draft content.

Every nested object lookup is scoped to its workspace and, for a saved version,
its draft. Possessing an opaque `ws_`, `wd_` or `wv_` identifier is not sufficient
for access. Lists, details, version history, audit views and JSON downloads must
use the same server-side authorization boundary. Client-side hidden buttons are
only presentation.

## Storage and mutation boundary

The tables are `organization_workspaces`, `workspace_memberships`,
`workspace_drafts`, `workspace_versions` and `workspace_access_audit`. They are
separate from the existing global workflow, run, publication and deployment
tables. The core uses an explicitly supplied signing key; no key, model, provider
or operating database is discovered by the profile itself.

The HMAC protects integrity; it does not encrypt saved content. SQLite files and
backups contain the private data and require restricted operator access. This
profile's HTTP membership boundary is not storage encryption or protection from
an administrator who can directly read or replace the database and signing key.

Writes acquire SQLite's native writer reservation before checking the current
session, user, membership and expected revision. Authorization and the actual
mutation share that transaction. Revision checks reject stale edits and
concurrent policy changes. Membership changes must not remove the final usable
owner through parallel requests. Archive and revocation retain their records;
they do not silently transfer authority or revive a prior version.

A draft contains bounded `name`, `description` and `definition` fields. A blank
`{"nodes":[],"edges":[]}` definition is valid as a non-executable draft. Supported
manual graph validation is a storage/input boundary, not evidence that a tool is
safe, callable, compatible or authorized for execution. Credential binding,
automatic triggers, result delivery and private-runtime authority are not
provided by saving a draft.

A saved version freezes `{name, description, definition}` and binds it to its
workspace, draft, ordinal and draft revision. Later edits to the draft do not
rewrite the prior saved content. Version revocation is an independent current
policy state; a content digest or saved artifact cannot override it. The response
explicitly identifies `saved_snapshot: true`, `executable: false`,
`deployable: false` and `published: false`.
Snapshot history contains verified metadata only. Reading saved content requires
the separately scoped snapshot detail or artifact request, and a revoked version
cannot disclose its content through the history list. Revocation blocks later
server reads; it does not erase a previously downloaded copy. Draft archive is
owner-only and also blocks content reads for its saved versions, even when an
individual version remains active. Metadata history and immutable stored bytes
are retained.

## Private HTTP and browser boundary

The private route prefix is `/admin/api/workflow-workspaces`. Requests carry
`X-Dashboard: 1` and an individual session in the `Authorization: Bearer` header.
`GET /options` returns the current user's presentation capabilities;
`GET /` lists that user's workspaces and `POST /` provisions one when permitted.
For a workspace, the API exposes detail, `/members`, `/audit` and `/drafts`.
Archive is a separate `POST /{workspace_id}/archive` operation.

Draft detail is `/{workspace_id}/drafts/{draft_id}`. Updates use the drafts
collection with the exact draft ID and revision. The draft has `/archive` and
`/snapshots` operations. A saved snapshot is read at
`/{workspace_id}/drafts/{draft_id}/snapshots/{version_id}`; `/revoke` and `/artifact`
are separate operations. These paths are private administrator APIs, not public
workflow or deployment routes.

Workspace HTTP operations use the existing administrator origin/body protections
and a stricter profile parser. Duplicate fields, nonfinite values, oversized
payloads and unexpected mutation fields are refused. Successful responses,
authorization refusals and other private error responses use `Cache-Control:
no-store`. JSON artifacts are authorized downloads, not bearer capabilities.
The attachment contains the profile, opaque object IDs, draft revision, content
hash, saved content and explicit non-executable status fields. It contains no
signing key, integrity signature, runtime principal or deployment credential.

The administrator UI renders workspace and draft text as text, keeps workspace
selection separate from identity, and clears inaccessible content when access
changes. Responses for a previous selection must not repopulate the current
workspace after a later selection or logout. Membership withdrawal is enforced
on the server rather than inferred from cached UI permissions.

## Separate follow-up gates

The existing global workflow endpoints are administrator-wide interfaces with
their own contracts. A display `author` field is not an organization ownership
key. Private objects must not be copied into those tables and called isolated
unless every legacy detail, list, run, history, export and capability alias is
also covered by the new scope.

The separate [private one-call MCP profile](WORKSPACE_PRIVATE_EXECUTION.md)
provides explicit manual input sharing/execution and scoped one-ticket replay.
It does not change this saved-data artifact contract. Immutable executable
releases, deployment credentials, OIDC/BFF token exchange, organization proof
and provider claims remain later work. None is inferred from workspace
membership or a saved JSON snapshot. Existing public and deployed
run capabilities do not become private workspace credentials.

The existing backup restore path deletes restored administrator sessions, pauses
all restored workspaces, and makes their memberships inactive with increased
revisions. A fresh login therefore does not restore the old membership's content
access. Draft and snapshot records remain data; no automatic reactivation or
owner repair endpoint is provided. The private restore inventory identifies the
workspace records that need a separately reviewed recovery process. An isolated
restore fixture does not establish an operating migration or cutover.

Security verification uses disposable databases, actual administrator sessions,
two-workspace access cases and controlled concurrency. It does not contact
providers or operate the user's server. Verification counts and precise limits
belong to the completed batch report; this contract does not claim production
approval, an external security certification or reviewed organization identity.
