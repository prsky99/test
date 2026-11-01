# Private machine evidence updates

`workspace-machine-evidence-updates-v1` is a bounded staff workspace feature. It has no public webhook receiver, scheduler, advertising delivery, inherited visitor permission, or default external sender. The existing public task-update system remains independent.

Construct `MachineUpdates(access, evidence_source, destination_verifier=None, sender=None, provider_claims=None)` with trusted code. The evidence source is the actual `ReliabilityEvidence` object or its bound `get_agent_projection` method on the same access instance. Provider control uses the existing `ProviderClaims.current` check in the caller-owned transaction. Missing provider control or a current destination verifier blocks authorization; a missing sender blocks dispatch.

The destination callback returns a frozen `VerifiedDestination`, proving the exact workspace, opaque configured reference, audience, protocol, evidence-update purpose, revision, current observation/expiry and receipt verification key. It cannot be supplied by an HTTP boolean, URL, visitor token, task watch or marketing preference. The callback and `ConfiguredSender` must bound their own work and I/O. Supported delivery protocols are `webhook` and `a2a_inbox`; selecting one does not grant agent invocation permission.

## Consent and currentness

A named current workspace owner explicitly authorizes a subscription. It pins the current agent version/schema, provider claim, destination binding and separately authorized contract scope. Every notice preparation and every dispatch requires a new, initially unchecked consent. Dispatch rechecks the current session, owner/membership revisions, provider claim, exact prepared evidence, destination revision/key and expiry before committing the dispatch boundary.

The finite contract policy is:

- A concrete authorized contract permits that exact contract and neutral notices when qualification is lost. The same authorized contract can subsequently regain qualification.
- A neutral-only subscription remains neutral. A newly concrete contract, changed concrete contract or changed agent version/schema requires a fresh subscription.
- The wire always contains the actual current evidence projection. A neutral notice retains `null` contract fields; it never invents a current qualified contract from the stored consent scope.
- A new explicit preparation can supersede an older unsent notice after evidence changes. Repeated preparation of the same current state is refused, including an unknown delivery. Signed sequence/predecessor metadata permits a real loss/regain transition without replaying the earlier event.

Positive notices expire no later than the qualified evidence, provider proof, destination proof or five-minute delivery limit. The receiver independently rejects positive claims after evidence expiry. Negative expiry/unassessed notices can have a fresh delivery lifetime while carrying truthful old or unavailable evidence metadata.

## Delivery and receipts

The canonical versioned HMAC envelope contains opaque event/subscription/workspace references, current agent version/schema and contract metadata, evidence hash/time/qualification fields, reason, purpose, audience, protocol, dedupe key, nonce and expiry. It contains no prompt, output, customer profile, credential, raw provider URL or destination URL.

Trusted receiver provisioning uses `MachineUpdates.envelope_key(destination)` for the exact verified workspace, destination reference, audience, protocol, purpose and revision. The issuer's master derivation key never leaves the issuer. Changing any scoped field derives a different key; a master-key wire signature and a signature from another workspace or destination are rejected. Keys are server configuration, never admin form fields, API response fields or frontend assets. Receipt verification keys are provisioned separately. An HMAC key holder can authenticate that one provisioned receiver scope; it is not an independent quality assessor.

The event is committed as `dispatched` before calling the configured sender. A signed receipt must bind the exact event, audience, nonce, envelope hash and current receipt time. `accepted` confirms delivery receipt only; `task_completed` remains false. Exception, untyped acknowledgement, invalid receipt, uncertain transport or failed final receipt persistence produces `unknown`. An in-flight committed dispatch also reads as `unknown`. Neither event replay nor a fresh consent on the same event resends it.

Withdrawal independently stops future dispatches. A notice already past the committed dispatch boundary cannot be recalled. Historical notice metadata is not a current quality certification.

`verify_envelope` remains a pure, strict validator. `MachineReceiver` now implements the durable boundary described below; older in-memory receiver fixtures remain limited test helpers. Actual external key provisioning, separate private ingress/TLS deployment and real target acceptance remain unverified. The status continues to report `actual_target_acceptance=false`.

## Durable private receiver and concrete adapters

`MachineReceiver(access, bindings=(), enabled=False)` creates three private tables and remains disabled by default. Its frozen `ReceiverBinding` contains an exact workspace/destination/audience/protocol/purpose/revision, configuration expiry, environment and scoped envelope/receipt keys. A named current workspace owner separately activates a receiver authority with `workspace-machine-receiver-activate-v1`, a lifetime of at most 24 hours and an expiry no later than the configured binding. Activation neither registers a public callback nor enables a route.

On receipt, the receiver reopens the signed authority inside one write transaction, rechecks its current owner/session/membership, current immutable configuration, revocation, expiry and restore block, and strictly verifies the canonical signed envelope. The envelope must have been issued after that receiver authority was created: activate first, then prepare notices. A fresh grant after restore cannot admit a still-valid old packet whose claim was absent from an older backup. The receiver then claims the event, nonce and dedupe key before returning a signed receipt. The event is globally unique, and nonce/dedupe are unique per workspace and configured destination even across fresh receiver grants. SQLite's write transaction and native unique constraints serialize independent process connections. An ambiguous commit produces no receipt; a response lost after a successful commit leaves the durable replay claim intact. Replays never issue a second receipt or execute a business task.

`status` exposes bounded receipt metadata only. It does not expose key material, nonces, dedupe hashes, prompts, outputs or raw envelopes. Up to 50 receiver authorities and 1,000 immutable replay claims per workspace are retained; exceeding a limit refuses new work rather than deleting replay protection. Revocation independently blocks new receipts. The receipt confirms persisted delivery metadata, not task execution, recommendation correctness, independent quality or marketing permission.

`VerifiedWorkflowDestinations` reuses an existing verified `workflow_destinations` endpoint-control proof and the genuine encrypted target. A separate frozen `DestinationBinding` explicitly authorizes the new `evidence_update` purpose in one workspace, binding its configured reference/audience/protocol/revision to an exact workflow destination and sealed-value hash. The original workflow result proof is not itself evidence-update consent. Every subscription and dispatch still requires current named-owner consent and provider control in `MachineUpdates`. Pending/revoked/restored proofs, changed sealed targets, unexpected channels/notices, configuration expiry or mismatched receipt keys fail closed. No duplicate challenge mechanism or inherited visitor/advertising permission is introduced.

`SecureMachineSender` resolves only the exact current configured target and sends one bounded HTTPS request through the existing public-address-pinned, TLS-verified transport. It disables redirects and environment proxies, bounds elapsed time/response bytes, and forwards neither cookies nor authorization credentials. Explicit `httpx.MockTransport` injection is accepted only for isolated bindings. There is no automatic retry, fallback URL, background sender or automatic activation.

The webhook profile sends the canonical envelope and `X-Agent-Evidence-Signature`; the response must be canonical receipt JSON with `X-Agent-Evidence-Receipt-Signature`. The narrow A2A profile uses synchronous JSON-RPC 2.0 `message/send` with one A2A 0.3 data part (`machine-evidence-inbox-data-v1`) containing the envelope and signature. The immediate response is one agent data message containing `machine-evidence-inbox-receipt-v1`, the canonical receipt and its signature. The JSON-RPC ID and message ID equal the event ID. A2A 1.0, streaming, returned tasks, long-running status/cancel and arbitrary provider response shapes are intentionally not accepted by this profile.

`workspace_machine_receiver_service.router_for(receiver, enabled=False, allowed_hosts=())` is empty unless trusted app code explicitly enables it on a separate protected private app. The normal public frontend/server router does not mount this ingress. Its only route, `POST /private/machine-inbox/{receiver_id}`, requires HTTPS, an exact configured host, no query string, strict signature headers, bounded canonical JSON and no browser origin/cookies/authorization. Wrapper protocol must match the configured receiver protocol. Error and receipt responses are no-store and omit exception details. There is no anonymous receipt/status lookup or public enablement switch. A separate real ingress deployment still requires actual TLS/isolation and target acceptance.

## Staff transport and restore

The named-session, origin-checked, no-store API is under `/admin/api/workflow-workspaces/{workspace_id}/machine-updates`:

- `GET /status`
- `POST /subscriptions`
- `POST /events/prepare`
- `POST /events/dispatch`
- `POST /subscriptions/withdraw`
- `GET /receivers/status`
- `POST /receivers/activate`
- `POST /receivers/revoke`

Requests use exact bounded JSON fields and purpose-specific notice identifiers. The desktop dialog renders opaque references with text nodes, resets consent when inputs change, prevents repeated uncertain commands and discards stale replies after workspace/session changes.

Restoring signed rows does not restore permission. Before any restored subscription/event becomes eligible, the restore process retains tombstones for every restored subscription and event identifier in `workspace_machine_update_restore_blocks`. The finite SQL recipe is two independent statements:

```sql
INSERT OR IGNORE INTO workspace_machine_update_restore_blocks SELECT id FROM workspace_machine_subscriptions;
INSERT OR IGNORE INTO workspace_machine_update_restore_blocks SELECT id FROM workspace_machine_update_events;
```

These blocks and independent signed withdrawals are never cleared by this feature. Restored objects remain blocked; a current owner must authorize new objects. The core creates only its four new private tables and leaves Store/connection ownership with its caller. Maximum retained scope is 50 subscriptions and 100 events per workspace; exceeding it refuses new state instead of silently deleting delivery or withdrawal history.

Receiver restore additionally copies all restored authority IDs to `workspace_machine_receiver_restore_blocks`. Replay claims and signed receipt history are preserved without re-signing or deleting them. Configured keys and a formerly valid authority do not bypass that tombstone; only a fresh explicit authority can admit new events, and previously claimed event/nonce/dedupe values remain blocked.

## Isolated evidence

Tests cover actual signed provider claims, the genuine reliability projection, qualification loss/regain, positive/negative expiry, destination contraction, exact consent, revocation/restore, concurrent dispatch, signed receipts, ambiguous acknowledgement and browser stale-state/XSS boundaries. All fixture provider checks and deliveries are in process. A guarded helper exercises the same paths against the parent-owned Unix-only PostgreSQL fixture without opening a connection or accepting an operating address.

The durable receiver suite adds file-backed restart/reopen, eight concurrent receivers on independent SQLite connections with one winner, each replay key across renewed grants, scoped-key/master-key forgery rejection, current session/membership/configuration/receiver withdrawal and restore fences, and strict private HTTP input caps. Concrete sender-to-ASGI receiver roundtrips exercise both webhook and canonical A2A response bytes. Lost acknowledgement after a committed receiver claim leaves sender `unknown`; redirects, invalid receipts and fresh consent cannot resend that event. These isolated tests do not establish an actual external delivery, production TLS/ingress configuration or a browser Push notification click.
