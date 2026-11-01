# Private integration preparation

`workspace-operating-preparation-v1` is a read-only administrator view of current
server configuration. Configuration availability, submitted readiness evidence,
and actual operating acceptance are separate facts. This module does not connect
to an identity provider, payment provider, notification destination or database.
It does not read environment variables, discover credentials or change settings.

The default constructor has `sources=None`. Every purpose without a trusted
source reports `missing_configuration`. The current deployment supplies no real
private IdP/SDK2 environment or approved provider, notification or payment sandbox;
isolated fixtures are the available verification scope.

## Trusted source boundary

Server code may inject a mapping of purpose names to callables through
`OperatingPreparation(..., sources=...)`. The integrated administrator router
receives that mapping from the explicitly assigned
`front._workspace_preparation_sources` attribute. There is no HTTP endpoint for
installing a source or declaring a configuration complete.

Supported purposes are `sdk2`, `storage_recovery`, `provider_quality`,
`notifications`, `support` and `payment`. A source receives the selected workspace
and current administrator actor and must return the exact `ConfigurationCheck`
dataclass. A plain dictionary, claimed boolean or saved reference is insufficient.
The result must bind the same workspace and purpose, a boolean `configured`, one
of `isolated`/`sandbox`/`operating`, and finite observation/expiry timestamps with
at most five minutes of validity. Missing, malformed, stale or failing sources
report missing configuration without returning raw diagnostic text. All sources
return and current membership is rechecked before response-time expiry validation.
An earlier configuration or operating-evidence check that expires during a later
callback is downgraded. This is a post-return freshness check; trusted callbacks
must perform their own bounded work; this interface does not terminate
an arbitrary blocking Python function.

Current named administrator authority and workspace membership are checked before
the report and again after sources return. A role, membership or workspace
revision change rejects the report. Only fixed status fields are projected;
credentials, callback results, submitted proof values and runtime diagnostics are
not displayed. Google/GitHub availability is separately read from the existing
identity service's current options; it does not turn on customer access.

Every configured item still returns `operating_verified=false`. The report's
`configuration_is_operating_evidence=false`,
`sandbox_is_operating_acceptance=false` and `automatic_gate_promotion=false`
remain unchanged. The existing `AdvancementReadiness` evidence checks are read
separately; this view neither stores nor withdraws readiness declarations, and a
submitted reference does not become independently verified operating evidence.

## Administrator desktop

The existing private workspace tools dialog offers **Integration preparation**.
Its authenticated GET endpoint is:

`/admin/api/workflow-workspaces/{workspace_id}/advancement/operating-preparation`

The dialog shows identity-provider availability, each purpose's current status,
and separate operating-evidence checks. It offers a link to the signed event
sandbox when that source module is available. There are no configuration write,
credential upload, backend switch or release buttons in this view. Public
Workspace access stays default off regardless of configured IdP options.

## Signed event sandbox

`workspace_sandbox_payments.py` implements an in-process, server-signed
**TEST_UNIT simulation** over the existing agreement and balanced simulation
ledger. It is not a real payment-provider integration or a public payment webhook.
No financial institution is contacted and no real charge, payout or refund occurs.

Preparing an exact capture/refund intent, dispatching it, and withdrawing a
prepared intent require separate current owner authorization and consent. Event
expiry, current agreement/provider-control authority, replay deduplication and
withdrawal are rechecked. The immutable receipt, agreement event, ledger entries
and audit share one transaction; failure rolls the write back. An unconfirmed
response is inspected through retained history and is never automatically sent
again. Restore permanently blocks old intents and does not replay, refund or
reactivate them.

The administrator desktop has **Signed event sandbox** for these isolated
operations. Source availability is not proof that a real provider sandbox has
been approved. Actual IdP/independent hosting, provider ownership and evaluation,
notification destinations, payment-provider transport signatures, legal terms,
reconciliation and operating load/DR acceptance each need their own authorized
external environment and evidence. Commercial, payment, provider-payout and
public-launch flags remain false.

## Verification boundary

See the current batch's isolated test and security artifacts under
`reports/advancement-batch7-2026-10-19/`. The final immutable affected run, focused
component proofs and historical baselines must be reported separately rather than
summed. No operating server, key, configuration, database or external account was
changed to create this view. A source import is applied only by the user's final
server restart after the development batch is verified.

## Full mounted administrator acceptance

The next integration batch exercises the actual mounted dashboard rather than
only individual feature routers. Seven API cases cover thirteen private feature
reads, current staff/member role ceilings, membership/session withdrawal, SDK
policy write/read/CAS/audit, current script bytes and CSP nonces. Two intercepted
Chromium cases open all four current private feature dialogs through their real
workspace buttons, verify native centered modality and refresh persistence, and
verify private-state cleanup after session withdrawal. Thirty existing preparation
and CI-partition cases also pass. See
`reports/advancement-phase2-integration-2026-10-19/acceptance/acceptance.json`.

The desktop reliability controls now show configured/running worker state and
current plan activation. Activation and deactivation each need fresh explicit
owner consent; missing configuration, a stopped worker or an unapproved plan
keeps activation disabled. The machine-updates dialog separately manages a
configured receiver's opaque reference, audience, protocol and bounded lifetime.
Editing those fields clears the activation consent. Each receiver revocation
requires its own authorization and preserves receipt history and replay claims.
Neither form accepts an address or key, configures a server integration, mounts
public ingress or certifies independent provider quality.

These are isolated development acceptance receipts. The designated private
operating workspace, actual customer/provider/receiver environment, representative
storage/recovery acceptance and hosted CI run still require their own current
receipts. The CI runner includes the new modules exactly once across four file
shards; listing or locally executing those shards does not establish that hosted
CI ran. No operating server control or external integration was performed.
