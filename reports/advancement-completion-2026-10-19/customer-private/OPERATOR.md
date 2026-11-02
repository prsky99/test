# Private customer and evidence-update composition

`workspace_private_bootstrap.compose_private(front, configuration)` is a trusted
server-code entrypoint. Supply a fresh, caller-owned Front and a typed
`PrivateDeployment(PrivateIntegrations(...), customer_origin=..., receiver_origin=...)`.
It returns `runtime.customer` and `runtime.receiver` ASGI applications. The caller
chooses its existing ASGI/TLS host; this entrypoint starts no listener and reads
no environment or credential file. Configuration after a platform graph exists
is rejected. Do not mutate an already running public Front.

The two private surfaces require distinct exact HTTPS origins. The receiver
contains only signed machine ingress, not staff/customer authentication routes.
Customer identity remains Google/GitHub only, separate from staff identities.
The public frontend keeps its default Workspace setting disabled. Each private
ASGI lifespan acquires a shared runtime lease; configured workers stop only when
the last private surface closes. An enable flag alone grants no workspace,
provider, destination, quality or delivery authority.

The SDK gateway stays fixed to `https://agentconcierge.biz`, preserving existing
SDK packages. Actual private SDK acceptance therefore also requires the approved
`.biz` customer/gateway paths through the selected protected ingress and exact
provider redirect registrations. A separate test-host authoring page alone does
not establish that deployment. No DNS, TLS, proxy, IdP account, key or actual
receiver has been provisioned by this change.

The customer build page is `/customer/organizations/{workspace}/build`. Editors
may create a bounded read-only one-tool draft/snapshot; owners, editors and
runners may review/test. Only owners may issue an immutable release, authorize an
exact origin, download its existing SDK2 package and withdraw the release. The
same existing gateway/executor handles deployed app runs. Retained deployments
can be downloaded after reopening without creating another deployment. Every
task/deployment still requires fresh explicit consent. Unknown tasks and lost
acknowledgements are inspected in history; no automatic business retry occurs.

Machine subscriptions remain manual unless an owner separately authorizes
`workspace-evidence-change-delivery-grant-v1`. The bounded grant lasts at most
24 hours and allows at most 20 changed-metadata notices. The original staff
session is not reused by the consumer: a purpose-only GrantActor is checked
against current owner/member/workspace revisions, provider control and the exact
verified destination before the existing event/dispatch boundary. The original
WorkspaceAccess and business executor do not accept that actor. The existing
evidence plane is read through its current-transaction local projection; the
consumer does not warm a remote judge or invoke a business provider. A signed
receipt indicates delivery acceptance only. Unknown notices are not resent,
and withdrawal, restoration quarantine or changed authority stops new dispatch.

The trusted consumer is default off. With
`machine_updates_worker_enabled=True`, its shared lifespan polls a bounded page
every 15 seconds. An operator may call the same `tick()` for an isolated check.
No purpose grant is issued by starting the worker. Capacity remains bounded by
the existing subscription/event limits; history/tombstones are not silently
deleted to create capacity. Advertising remains disabled.

Actual Google/GitHub, HTTPS/BFF, independent quality, private TLS receiver and
native Push click round trips need designated approved targets. A lost sole-owner
identity still requires a separately defined independently verified recovery
policy; matching emails, enabling a second provider or rewriting signed rows is
not a recovery procedure.
