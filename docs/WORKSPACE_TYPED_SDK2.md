# Conditional typed-DAG SDK 2 export

This separate `workspace-typed-sdk-v2` profile exports an already tested immutable
private MCP graph of two to ten steps. It keeps the existing single-tool SDK 2
profile and public 1.x packages compatible. Public Workspace access remains
closed by default; adding this source does not open customer or app routes.
No identity provider, provider endpoint, notification system or payment sandbox
is activated by these controls.

## Release and authority

`WorkspaceTypedReleases` accepts the exact current typed graph version only after
a retained signed successful whole-graph run. It pins the flow revision, immutable
version ID/hash, every current connection/tool binding and the existing contract
approval/evidence checks. Registered product compositions still need their
separate reviewed release contract and are denied here. Creation performs no
provider call. A saved JSON graph alone is never execution permission.

A current workspace owner issues a separately revocable, origin-bound deployment
with bounded TTL and per-minute/per-day run admission. Existing release/deployment
state signatures, CAS revocation, restore blocks, short-lived code/PKCE exchange,
app token audiences and current customer membership/session checks are reused.
Typed and single-tool deployments use distinct public path namespaces; a typed
release cannot be executed through the single-tool profile.

The `CustomerTypedFlows` adapter retains opaque customer IDs and uses customer
read/execute authorization. It never converts a customer to staff and rejects
save/disable calls. Its release guard runs before admission, every external
packet dispatch and successful final completion. Revocation, graph revision,
changed binding/generation, expired evidence, removed approval, paused controls,
expired tokens or restore blocks deny further dispatch. A change after dispatch
preserves an unknown outcome and suppresses output; an external request already
sent cannot be recalled. No automatic replay or fallback occurs.

## Whole-graph review and downloaded package

The signed fixed graph is executed on the routing gateway. The ZIP contains only
static app/release identity, local SDK assets and a customer BFF, with no staff
credential, embedded bearer token, source upstream endpoint or customer identity.
The BFF holds short-lived capabilities in memory behind HttpOnly SameSite
cookies and CSRF checks. Restarting it signs app users out.

Preparation discloses every agent reference, contract/tool, literal input,
selected primitive prior-output path, dependency and branch. Future projected
values are not fabricated before the first agent responds. Fresh unchecked
whole-graph consent covers the declared sharing for one ticket only; the client
cannot mutate the graph or input in a run request. The bounded graph uses at most
ten calls within sixty seconds, twelve seconds per node, and a seventy-five
second SDK/BFF response budget. The single-tool profile keeps its fifteen-second
transport budget.

A ticket is admitted once. Replays cannot call providers again; if a later
current-evidence check denies submission, retained history remains the way to
inspect that accepted run. Unknown outcomes remain unknown. Per-run status
capabilities are audience/run/app/customer/session-bound. History reads metadata
without decrypting outputs; authorized retained status decrypts only a successful
run's output. The browser renders untrusted outputs as text, stores no tokens in
local/session storage and never retries ambiguous submissions automatically.

## Integration

Construct `CustomerTypedFlows(app_execution)` and then
`WorkspaceTypedReleases(typed_flows, customer_identity=identity,
customer_flows=app_typed_flows)`. Register
`workspace_typed_release_service.router_for(typed_releases, public=False)` in the
staff router. Register the public counterpart with `admin=False` only inside the
existing explicit Workspace feature gate.

Administrative paths are
`/admin/api/workflow-workspaces/{ws}/typed-flows/{flow}/versions/{version}/release-v2`.
Customer app paths are `/workspace-flow-apps-v2/{app}/authorize` and
`/api/workspace-flow-apps-v2/{app}/...`.
The desktop asset exposes `WorkspaceTypedReleaseAdmin.open(ws,flow,version)`,
`leave()` and `onSession()`. Its centered native dialog uses text nodes, current
workspace/session/request epochs, fresh deployment consent and explicit CAS
revocation. Ambiguous changes require a current read before another command.

No new tables are introduced. Existing release/deployment/code/token/link and
typed-flow tables retain their restore invalidation and unknown evidence rules.
Operating IdP acceptance, real provider acceptance, public activation, production
BFF hosting and PostgreSQL operating cutover remain separate acceptance work.
