# Customer-owned organizations

`customer-organizations-v1` implements customer organization authority and
account withdrawal for the current advancement design. The public customer
portal remains disabled by the host's default feature gate; this source is not a
public launch or an operating identity-provider acceptance. Administrator login
remains the existing individual staff session system.

## Authority and ownership

A current Google OIDC or GitHub OAuth customer session may explicitly create a
private organization. Signing in alone creates no membership. The organization
uses the existing private workspace/draft/snapshot store, a separate
`customer_organizations` authority record, and customer memberships. It creates
no staff account or `workspace_memberships` row. The legacy workspace creator
column contains the non-staff sentinel `0`; the actual opaque customer creator
is recorded in the customer sidecar and signed audit records.

Roles have distinct current permissions:

- Owner: read, edit, run, invite, manage members, transfer and archive.
- Editor: read, edit private drafts, create snapshots and run.
- Runner: read and use separately authorized execution; no draft editing.
- Viewer: read only.

Owner/editor roles require an active customer-owned sidecar. Existing staff-owned
workspace links remain viewer/runner only. A global staff role gives no access to
a customer-owned organization. Customer ownership does not grant staff access,
publication, delivery, marketing, provider ownership or release authority.
Generic customer BFF tokens remain read/execute only; edit/manage require the
current native customer cookie session and customer CSRF.

`CustomerDraftAccess` reuses bounded signed private draft/snapshot storage under
an independent customer edit check and delegates signature creation/verification
to the shared artifact signer for configured key rotation. A runner cannot
obtain editing through the execution adapter. Attribution retains opaque `cu_`
identities and does not convert customers into integer staff identities.
Existing private execution constraints remain unchanged.

## Exact-identity invitations

The owner enters an existing customer's opaque invitation reference and role.
The recipient signs in with that exact issuer/subject identity and accepts the
pending invitation. No email lookup/merge, display-name lookup, automatic email
message, shareable bearer invite or staff identity conversion is used. The
recipient reference is shown only after authentication.

Invitations expire after seven days. Acceptance binds the recipient identity
revision, current active organization and issuing owner's exact membership
revision. Removed, transferred or changed issuing-owner authority cannot approve
an old pending invitation. Accept/decline/revoke are one-use CAS transitions;
invitation possession alone grants nothing. Decline and expiry create no
membership. A current owner can revoke pending invitations.

Each organization admits at most 50 pending and 500 retained invitations, with
100 retained memberships and 10 active owned organizations per customer. Creating
another invitation removes at most 50 resolved invitation records older than 90
days; signed audit records remain. This is bounded logical cleanup, not physical
database or backup erasure.

Owners can change/remove an accepted member with CAS. Ownership cannot be
imposed through silent role promotion. A recipient first accepts an owner
invitation; transfer then demotes the previous owner to editor atomically. The
last active owner cannot leave, demote or remove themselves. Owners whose
identity provider is currently unconfigured do not satisfy the remaining-owner
check. Concurrent leave attempts retain one current owner.

Membership/organization authority changes advance the shared workspace revision
and revoke generic BFF capabilities. Private execution rechecks these epochs
before the external business call. Signed unknown evidence is never rewritten
or automatically retried by membership actions.

## Withdrawal, archival and restore

Leaving immediately withdraws the membership. Archival requires explicit
`ARCHIVE` confirmation and the current organization revision; it deactivates the
organization, customer links and pending invitations. This profile has no
archived-organization reactivation API.

Account withdrawal requires current CSRF, account revision and explicit `DELETE`
confirmation. The user first transfers sole ownership or explicitly requests
archival of organizations for which they are the only owner. Other owners'
organizations remain active. The transaction revokes local sessions/BFF grants,
withdraws memberships and sent/received pending invitations, deactivates the
identity, advances its revision and records a signed withdrawal receipt.

No provider token, email or display name was stored in this identity namespace.
The keyed issuer/subject tombstone and opaque customer references remain linkable
personal data; they are not anonymous. They prevent a withdrawn identity silently
reactivating old access. Signed run/checkpoint evidence, especially unknown
external outcomes, is preserved. Existing backups are not erased by logical
withdrawal. Storage retention, legal erasure requests, external IdP account
deletion and backup expiry require separate operating policies and are not
claimed complete.

Restore deactivates customer organization authority and revokes pending
invitations alongside existing workspace/session/BFF/link quarantine. Signed
audit/deletion receipts and unknown runs remain unchanged. Restored owner rows
or a new login do not reactivate organization access. Recovery after lost
external identity access requires independent ownership evidence; automatic
recovery and cross-issuer email merge are not provided.

## Transport and authenticated page

When explicitly enabled, `/customer/organizations` offers English responsive
organization/team management with local Lucide SVG, native centered confirmation
dialogs, accessible labels/focus, and light/dark themes. It supports creation,
rename, invitations, member roles, accepted-owner transfer, leave/archive,
private draft create/edit/snapshot, and explicit account withdrawal. Empty draft
creation does not imply a callable agent or published workflow. User names use
text-node output and never become HTML.

The fixed `/api/customer-organizations` routes implement the same lifecycle.
Exact bounded JSON rejects duplicate/nonfinite/deep inputs. Mutations require
current customer CSRF and same-origin checks, with separate per-IP limits. Data
queries bind request values. All member/draft/invitation lookups check the current
organization and exact actor. Pages/responses are no-store/noindex; frames are
denied; scripts/styles use response nonces. No third-party page dependency or
raw session/provider token is displayed.

The organization router is included only by public customer transport;
`public=False` retains the staff customer-link API without customer organization
pages/APIs. The host's public portal feature gate is an independent default-off
boundary.

## Verification

The [isolated verification record](../reports/customer-organizations-2026-10-18/verification.json)
contains 88 passing cases across organization core/API, legacy Google/GitHub
identity, current customer runtime, public/staff namespace integration and native
offline Chromium. Native organization cases cover invitation acceptance,
transfer, editor draft changes/snapshot, leave, mobile layout, text-node XSS
protection and confirmed withdrawal. API/core cases include CSRF/IDOR, one-use
invitation CAS, expiry, stale identity/owner epochs, last-owner race, distinct
roles and retention of an actual signed unknown private run without retry.

Chromium is offline before navigation and every request is fulfilled from the
isolated ASGI app on reserved `customer.test`. OAuth exchanges use controlled
synthetic responses with real test signatures. These tests do not operate the
development server, open an operating database, call a live agent/IdP, deliver
marketing, use a real customer identity or modify production authority.
