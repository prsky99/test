# HTTPS endpoint-control claims

`provider-https-control-v1` verifies a registered public HTTPS origin through an
explicit one-use challenge. It establishes control of that challenge location at
the observation time, not legal ownership, quality, factual accuracy, safe tool
execution or commercial rights.

Only a workspace owner with a current individual staff session can prepare,
verify or revoke. A customer login, visitor callback, administrator machine token
or unrelated global superadministrator does not grant workspace content access.
This management panel uses existing staff authentication; Google/GitHub customer
sign-in remains on the public frontend.

## End-to-end workflow

Routes are under
`/admin/api/workflow-workspaces/{ws}/provider-claims`:

1. `GET /options` and `GET` list the profile and bounded retained metadata.
2. `POST /prepare` accepts exactly `{resource_id}`. It reads the active registered
   source and creates a ten-minute challenge without contacting the provider.
3. The owner places the returned exact JSON `{profile,claim_id,nonce}` at
   `https://<registered-origin>/.well-known/agent-concierge-claim.json`.
4. `POST /verify` accepts exactly `{claim_id,revision,authorized:true,
   notice:"provider-https-control-v1"}`. The initially unchecked UI authorization
   permits one bounded HTTPS GET to that exact address.
5. `POST /{claim_id}/revoke` accepts one exact current revision. Revoked records
   remain as tombstones rather than being removed or silently reused.

The registered source must use credential-free public HTTPS. The caller cannot
supply another URL, path, headers or upstream credential. Server-side challenge
claims bind the workspace/session/member revisions, current resource binding and
observation generation, origin, nonce hash, purpose and expiry. These private
claims are HMAC-protected and never returned as a raw proof payload. The nonce
itself is displayed once for publication at the deliberate proof location.

Verification consumes the pending state before HTTP. The shared secure transport
uses an eight-second outbound budget, 4KiB response bound, public address checks,
TLS verification and no redirects. Duplicate JSON fields, an altered nonce,
another claim/purpose, extra proof fields, non-200 response and invalid bodies
fail closed. A failed/interrupted check is not retried automatically; the owner
must review a fresh nonce. The network request holds no database writer lock.

Immediately after the response, current staff session/owner/membership, source
binding/generation, expiry and claim revision are checked again inside a native
writer transaction. A changed connection or withdrawn authority cannot turn an
old HTTP result into a valid current claim. Verification and audit metadata are
committed together. A successful proof has a bounded 30-day maximum validity;
current resource generation/binding or workspace revision changes require fresh
review. A transferred domain or removed proof is not continuously monitored by
this unit, so periodic revalidation and explicit withdrawal remain necessary.

## Lifecycle and safety

`provider_control_claims` is separate from capability approvals, execution
evidence, recommendation quality and publication/deployment grants. Its status is
`pending`, `checking`, `verified`, `failed` or `revoked`, with monotonic revision
CAS. A lifetime workspace cap of 1,000 records and transport rate limits bound
work. The inventory view omits nonces, hashes, sessions, signatures, endpoints
and raw HTTP errors. Audit uses internal IDs; those are restricted metadata, not
an anonymity claim.

The internal current-claim check requires caller-owned transaction scope, active
workspace, unchanged workspace revision, active source and matching current
resource generation/binding. It does not approve any agent call. A restore can
set the independent `revoked` tombstone without rewriting old signed payloads;
no restored claim automatically becomes current again.

The UI prepares a proof, displays the exact address/JSON, then requests separate
authorization before verification. It renders text only, clears pending state on
close/session/selection changes and never automatically retries a mutation.
Ambiguous changes require recorded-state refresh. The existing public agent
registration and recommendation interfaces are unchanged.

Verification uses isolated registered resources, controlled HTTPS responses,
current real-style sessions, generation/membership/control races, strict request
guards and revocation. No operating endpoint, real provider, DNS challenge,
external legal ownership or production security certification is claimed.

## Explicit renewal, transfer and expiry

`POST /{claim_id}/rechallenge` takes the exact current revision. It atomically
retires the previous proof and prepares a different nonce against the current
registered origin/binding/generation. Even a verified, expired, revoked or
domain-changed historical record cannot supply successful evidence to the new
claim. Preparation makes no provider request; the owner must publish the fresh
nonce and separately authorize verification again.

`POST /{claim_id}/transfer` takes `{revision,target_workspace_id}`. A current
source owner may offer a current verified proof to a different active workspace.
The previous proof is retired immediately. The bounded ten-minute offer contains
only permission to prepare a new challenge; it is not a transferred verification,
quality approval, legal ownership transfer or execution grant.

`POST /transfers/{transfer_id}/accept` takes `{revision:1}` and requires the
current target workspace owner. The signed one-use offer must still match the
target workspace revision and current resource binding/generation. Acceptance
atomically consumes it and prepares a fresh target-owner nonce. The target must
then host that nonce and separately authorize a fresh HTTPS verification.
Concurrent acceptance, changed bindings, stale target revisions, tampering and
restored offers fail closed. Restore permanently blocks every pre-restore offer
without rewriting its signed historical payload.

`POST /expire` takes `{limit}` from 1 to 50 and explicitly records expired pending,
checking and verified claims as audited terminal tombstones. Current-claim checks
already reject expiry before this maintenance action runs. There is no background
HTTP, ownership inference or automatic marketing. The staff dialog exposes fresh
challenge, transfer offer/acceptance and explicit expiry controls; every mutation
retains its existing uncertain-outcome refresh requirement.

Claim status additionally includes `superseded`, `transferred` and `expired`.
Optional versioned signing keys support grace verification and revocation as
documented in [Private artifact keys](PRIVATE_ARTIFACT_KEYS.md). Endpoint or
domain-key changes require revalidation; control of the remote domain is not
continuously monitored by this module.
