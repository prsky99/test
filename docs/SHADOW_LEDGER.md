# Workspace simulated usage and ledger

`workspace-shadow-ledger-v1` is an explicitly authorized private simulation. It
does not charge a customer, transfer funds, authorize x402, settle a provider,
apply a revenue split or turn existing observation counts into bills.

The current entry point uses an individual administrator database session and
current workspace membership. Only a writable workspace owner can approve or
change simulation accounting. Current members may inspect permitted summaries.
Customer identity adapters remain a separate integration boundary.

An owner approves an exact `slop_` logical-operation ID, integer quantity and
declared asset. Supported labels are `TEST_UNIT`, `USD_CENT` and `EUR_CENT`;
these are simulation units, not a complete currency, payment or tax contract.
Quantities are exact integers from one through one trillion. No floating money,
FX, minor-unit inference or automatic 70/30 allocation is performed.

The approval binds its named session, current role, workspace/member revisions
and one-hour expiry. A new simulation outcome needs separate explicit purpose
authorization. `slev_` event deduplication is independent of logical-operation
deduplication: reusing an event for another operation or payload is refused.
Completed outcomes settle the approved quantity; partial outcomes require a
strictly smaller positive quantity. Unknown settles nothing until an authorized
current owner records completed, partial or not-received reconciliation.

Settled usage creates two fixed simulation-account entries with opposite signed
integer quantities in the same asset. A full reversal creates opposite entries
exactly once; it preserves the original event. An unknown is not silently
converted to success and no provider is called during reconciliation. A current
owner can reconcile or reverse after the original approval session expires;
that is a newly audited simulation decision, not restored execution authority.

Three new private tables store operations, immutable events and entries. HMAC
binds operation state and the ordered audit chain; entry identities and content
are verified against their event. Native SQLite writer reservation, current
authorization, operation revision, event ID, entries and the workspace audit
record share a transaction. Actual accepted-SQL failure rolls the bundle back.
On an unconfirmed commit response, the caller must read current state; it must
not invent another billable operation. The same exact recorded event is a
read-only replay. There is no automatic retry or actual payment.

The lifetime limit is 200 operations per workspace, with bounded history
verification. Current summaries verify signed events, orphan-entry absence and
per-asset balance. This is accounting integrity for the declared simulation,
not proof of correct commercial policy, external payment, provider debt or
financial certification. HMAC does not encrypt private database/backup data.

HTTP lives under the existing workspace path plus `/advancement/ledger` and
requires the exact named-session, origin, body and no-store boundaries. The
native admin dialog displays selected quantities/states, never a raw response
dump. Explicit unchecked authorization is consumed for each mutation. Failed
or uncertain submissions are not automatically retried.

Real commerce still needs verified identity/ownership, a defined billable
operation, asset/precision and partial-failure policy, actual contract/tax/refund
and payout responsibilities, signed external-event adapters, operational
reconciliation and a separate explicit activation decision. This module creates
none of those approvals.
