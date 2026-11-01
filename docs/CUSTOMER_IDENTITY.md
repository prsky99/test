# Customer Google and GitHub sign-in

2026-10-19 development update: the user subsequently requested keeping the public
Workspace link hidden until development is confirmed complete.
`CUSTOMER_WORKSPACE_ACCESS_ENABLED=1` enables direct customer route testing;
`CUSTOMER_WORKSPACE_LINK_ENABLED=0` independently hides navigation and Home
advertising. Both are explicitly passed by the gateway host to the public app;
`0` remains the safe code/deployment-example default. The actual private launch
settings include the previously registered provider keys.
No server restart is performed by this development task. See
[launch verification](../reports/workspace-social-launch-2026-10-19/README.md)
for the current distinction between isolated and real-account tests. Earlier
registration and launch-hold entries below describe their historical state.

The English sign-in view explains first-login account creation and uses local
Lucide icons, theme-aware styles and nonce CSP. Account pages do not render raw
customer IDs, provider data or session secrets. Signed-in visitors opening the
sign-in page return to their account; signed-out visitors opening Workspace go
to sign-in. Initiation failures restore the provider buttons. Browser callback
cancellation/failure returns to a fixed retry page without echoing provider
diagnostics, while JSON API behavior is retained. Google documents two signed
ID-token issuer spellings; both are checked and then normalized to the canonical
issuer before subject hashing. Existing accounts therefore remain stable.

Real Google sign-in and service sign-out were observed after the user's restart.
GitHub authorization returned before its flow was consumed: the callback guard
previously rejected every GitHub `iss` field. GitHub's published authorization
issuer is exactly `https://github.com/login/oauth`, separate from the longstanding
`https://github.com` account namespace. The guard now validates that exact issuer
without changing stored account identity or accepting a cross-provider issuer.
See [GitHub discovery documentation](https://docs.github.com/en/apps/github-authentication-discovery-endpoints)
and [metadata](https://github.com/.well-known/oauth-authorization-server/login/oauth).
The corrective regression includes this real callback shape. After the user's
corrective restart, actual GitHub sign-in/sign-out and returning sign-in passed.
Read-only aggregates confirmed one identity per tested provider, reuse of the
GitHub identity and all test sessions signed out. The public link and Home
promotion were verified hidden in Chrome; direct customer sign-in remains
available for development. No further restart is requested for this verification.

`customer-oidc-bff-v1` supplies public-frontend customer sign-in and separate
customer workspace authorization. Administrator login remains the existing staff
session system. A Google/GitHub identity is never converted into a staff account,
visitor identity, provider owner or implicit organization member.

The host calls `customer_identity_for(store, key)` and shares that object with
the public identity router, private customer access adapter and app authorization
service. Public routes and staff link-management routes can be mounted separately
with `router_for(..., public=True, admin=False)` and the inverse. No settings are
discovered from a user-supplied URL. Missing or invalid configuration disables the
affected provider while preserving the rest of the site.

## Explicit configuration

Only these named settings are read by the factory:

- `GOOGLE_OIDC_CLIENT_ID`, `GOOGLE_OIDC_REDIRECT_URI`, `GOOGLE_OIDC_CLIENT_SECRET`.
- `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_REDIRECT_URI`, `GITHUB_OAUTH_CLIENT_SECRET`.

All three settings are required for the corresponding confidential web client.
Credentials and registered callbacks still need actual provider setup; isolated
tests do not establish an operating registration or consent-screen approval.
The secrets are used only in the fixed HTTPS token exchange, omitted from config
representations/DTOs and not stored in the customer database. A keyed config hash
binds flows and sessions; rotation invalidates sessions for that provider.

Google endpoints and issuer are fixed to its published HTTPS issuer,
authorization, token and JWKS locations. The code flow uses S256 PKCE, state and
nonce. RS256 signatures are checked against bounded RSA public JWKS, with exact
issuer/audience, authorized-party, nonce, subject and finite time validation. No
implicit flow, arbitrary algorithm, token-header key URL or remote schema is
accepted. See [Google's OIDC documentation](https://developers.google.com/identity/openid-connect/openid-connect)
and [published configuration](https://accounts.google.com/.well-known/openid-configuration).

GitHub uses its confidential OAuth web code flow and S256 PKCE. Its fixed token
endpoint is followed by `https://api.github.com/user` on every login. Only the
strict numeric user ID becomes the subject; Actions OIDC tokens, login names,
emails and profile roles do not establish identity or membership. Provider tokens
and refresh tokens are not retained. The current official flow documents PKCE
and this identity lookup in [GitHub's OAuth guide](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps).

## Browser flow and current authority

`/customer/sign-in` offers Google and GitHub only; unavailable providers remain
disabled. `/customer/workspaces` fetches an authenticated customer's own opaque
ID and explicit workspace links, and supports local sign-out. Both pages use
English text, local Lucide markup, text-node output, no-index metadata, no-store,
CSP nonces and frame denial. The account ID appears only after authenticated
session lookup and may be shared with an owner for explicit access approval.

- `POST /api/customer-auth/begin`: empty object for Google, or exact
  `{provider:"google"|"github"}`. Returns the fixed provider authorization URL
  and sets a Secure/HttpOnly host-only browser flow cookie.
- Google callback: `GET /api/customer-auth/callback`.
- GitHub callback: `GET /api/customer-auth/github/callback`.
- `GET /api/customer-auth/session`: current customer, expiry, CSRF value and
  active explicit workspace links. No provider tokens or subject strings.
- `POST /api/customer-auth/logout`: exact empty object and current customer CSRF.
- `POST /api/customer-auth/workspaces/{ws}/token`: exact `purpose:read|execute`
  and customer CSRF, producing an independently revocable opaque capability.

Every callback is bound to a five-minute, one-use server flow and its browser
cookie. PKCE material is encrypted at rest. State is consumed before token
exchange, so failed or interrupted exchanges require a new login. Provider
callback auxiliary fields are bounded and ignored for identity/authorization;
cancellation consumes the flow without returning raw provider errors. Browser
success navigates only to the fixed customer workspace page. JSON clients receive
an authenticated DTO and session cookie, never a raw session token in the body.
The callback clears the one-use query from its ASGI scope before validation or
response delivery, including refused and rate-limited requests. This prevents
Uvicorn's response-time access formatter from logging the code/state query. It
does not control earlier ingress proxy logs, provider logs or browser history.

Provider-specific issuer plus keyed subject identity is stable and separated;
accounts are not merged by shared email. Cookie session values and BFF bearer
tokens are stored only as keyed hashes. Local customer sessions last at most one
hour, bounded by Google token expiry where applicable. Sign-out revokes associated
BFF capabilities. It does not sign the user out of Google/GitHub, and upstream
account revocation is not an instant platform back-channel logout signal.

Staff workspace owners explicitly manage
`/admin/api/workflow-workspaces/{ws}/customers` with their current named staff
session. Staff-owned customer link roles remain `viewer` and `runner`; CAS
revisions/tombstones are retained. Global staff privileges are not inherited.
The separate [customer organization profile](CUSTOMER_ORGANIZATIONS.md) adds
explicit customer-owned creation, accepted owner/editor invitations, transfer,
leave and withdrawal without creating staff memberships. Expanded roles require
an active customer-owned sidecar; customers cannot change staff members.

BFF access is limited to five minutes, one workspace, exact audience and exact
`read` or `execute` purpose. `validate_token` and caller-transaction `authorize`
recheck current session, identity, workspace and customer link/revision. A typed
actor reconstructed for private execution retains `token_ref` so expiry and
revocation are checked at every dispatch. An execute-only generic token is not
silently broadened into a read token. App-specific code/PKCE/deployment capability
contracts remain independent and do not expose the customer cookie to an app.

## Storage, privacy and verification limits

Tables are `customer_oidc_flows`, `customer_identities`, `customer_sessions`,
`customer_workspace_links` and `customer_bff_tokens`. Private internal IDs and
subject hashes remain linkable identity data; omitting email is not anonymity.
Current customer identities/links are independent from `admin_users`,
`admin_sessions` and visitor marketing/notification preferences. No provider
quality evidence, payment, marketing, delivery or publication permission is
created by login or workspace membership.

HTTP work uses the bounded TLS/public-address transport with fixed destinations,
no redirect following or inherited proxy settings. The service enforces bounded
raw JSON, same-origin mutations, CSRF and separate per-IP request limits. Flow,
session, link and token counts are bounded. Restore must consume old flows,
revoke customer sessions/tokens and disable customer links; no automatic rights
reactivation is permitted. These hooks are integrated by the host's restore unit.

Final verification uses disposable SQLite, real RSA signatures, controlled
Google/GitHub HTTP responses and isolated API cookies/CSRF. The final customer
browser fixtures are offline before their first navigation, use the reserved
`customer.test` host and fulfill provider pages locally. They verify the API's
303 response, then use a fixture-only local navigation bridge; native browser
redirect-chain interception is not claimed.

An earlier browser fixture did not intercept a redirect follow-up reliably. An
unintended public GET attempt or reach to
`agentconcierge.biz/customer/workspaces`, and any resulting access-log or
automatic statistics effects, remain uncertain. No global zero-production-write
claim applies to those initial attempts. No intentional production mutation,
real identity-provider task or real credential was used. The initial artifacts
and final isolation scope are preserved in the
[identity verification record](../reports/advancement-completion-2026-10-18/identity-store-owned-review.json).

Google's confidential web client and the GitHub OAuth App were registered on
2026-10-19 through their provider consoles. Google declares only `openid` and
remains External / Testing; production publication, domain ownership and brand
verification are not claimed. The GitHub app has one exact callback, wildcard
matching and Device Flow disabled, and expiring access tokens enabled. Its login
request uses no additional scope. Both registered callbacks match the routes above.

The six issued settings are staged only in the Git-ignored private file
`gateway-data/oauth-registration/credentials.env` (file `0600`, dedicated directory
`0700`). Local validation confirmed both configuration loaders accept the settings,
the exact HTTPS callbacks, and the file's ignored/untracked status without printing
credential values. This file is not automatically loaded. The literal
`AGENTCON_ENV_FILE` parser now accepts these six explicit keys. Its
`--identity-check` mode validates a private file without opening any database,
constructing a service, or printing setting values. Complete provider settings
are required; a partial or invalid provider fails closed. Do not use shell
`source`/`eval` to load credentials. Selecting or merging the operator's actual
runtime profile remains a deployment step; the existing profile is not replaced.

Operating sign-in was not activated and no real provider login/callback acceptance
was performed. Protected real-provider login/callback and customer lifecycle
acceptance remain required development checks in the final completion plan;
isolated fixtures do not close them. The public customer portal remains disabled by its independent host feature
gate until explicitly opened. HTTPS provider control proof is independent of
customer login and does not establish legal ownership, execution quality or
callability.

## Pre-enrolled sole-owner recovery

The optional private recovery profile requires a current sole owner to enroll an
offline Ed25519 public key and an independently configured review authority.
Private keys stay with their holders. A new signed-in customer obtains one exact
claim bound to the organization, current owner/link/workspace/identity revisions,
new customer, evidence digest, nonce and seven-day expiry. Proofs must be submitted
within the separately signed one-hour submission window. Both the enrolled key
and independent reviewer must sign it. Staff sessions and email are not proofs.

Submitting valid proofs starts a fixed 24-hour dispute window and grants no
access. Current owners can inspect and contest requests; requesters can withdraw.
Finalization rechecks current authority and both signatures, invalidates old
sessions/BFF capabilities and outstanding invitations, changes the organization
owner, and consumes the enrollment. New enrollment is required after recovery.
Archived, restored, changed or withdrawn authority cannot be replayed. Restore
blocks all pre-restore policies/requests. This mechanism needs enrollment before
identity loss; it does not invent a recovery right for an unenrolled account.

The private page is `/customer/organizations/{workspace_id}/recovery`; the API
shares `/api/customer-auth/organizations/{workspace_id}/recovery`. Neither is
mounted without explicitly supplied independent authority public keys, and the
public Workspace gate is unchanged. Offline browser/API fixtures exercise proof,
dispute and revocation mechanics; actual independent custody and recovery review
acceptance remain required development evidence before completion is declared.
