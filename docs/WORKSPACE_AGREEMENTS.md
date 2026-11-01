# Provider agreement versions and simulated settlement

`workspace-provider-agreement-v1` implements immutable structured provider terms
and deterministic conserved settlement/refund code for the current design. It
uses only integer `TEST_UNIT` amounts. Commercial execution, payment and provider
payout flags are always false. A platform HMAC signature protects record
integrity; it is not a provider's legal signature, a contract acceptance record,
or an operating G2/payment approval.

## Current owner, endpoint control and immutable terms

`WorkspaceAgreements(access, claims)` uses the shared current workspace owner
access and `ProviderClaims` source. A new agreement requires the exact current
verified control claim ID/revision, active registered resource binding and
monotone observation generation, current proof owner's active membership/role
revision, and a fresh authorized workspace-owner session. The agreement's owner
membership/workspace epochs are pinned separately. Expired/revoked/rechallenged
proof, resource/member ABA, paused workspace, changed owner, or permanent restore
block denies new quotes/captures and settlement changes.

The terms record is immutable. Each resource has a CAS head revision. A changed
agreement creates a new ordinal, retains the original signed terms unchanged,
and advances the signed prior state to superseded. Signed state revisions allow
explicit revocation and the shared audit records creation/revocation/simulation
actions. Revoking an agreement stops new admission. A previously recorded
simulation may still be refunded under its original terms if the exact control
proof and current owner authority remain valid; revocation alone does not erase
an existing obligation. Expired/changed control or restored records require
independent review rather than replaying a refund automatically.

Terms are exact structured fields:

- `asset: TEST_UNIT`, `scale: 0`, `provider_bps: 7000`, `platform_bps: 3000`.
- `base: gross_less_processing_then_tax`.
- `deductions`: processing rate (0–2500 basis points), processing fixed units
  (0–1,000,000,000,000), and tax rate (0–5000 basis points).
- `refund_responsibility: proportional_original_components`.
- `rounding: floor_provider_platform_remainder`.
- A bounded document reference and SHA-256, never a fetched URL, document body,
  legal party identity, provider token or signature credential.

The document hash/reference remains declared and legally unverified. The
endpoint proof establishes only current endpoint control. Neither creates legal
ownership, provider assent, quality certification, an accepted real payment
contract or an operating readiness proof. Actual contracts, provider/payment
integration and external G2 approval remain separate requirements.

## Integer allocation and refund policy

For a gross amount G, processing deduction P is the smaller of G and
`floor(G * processing_bps / 10000) + processing_fixed_units`. Tax T is
`floor((G - P) * tax_bps / 10000)`. Distributable base B is `G - P - T`.
Provider allocation is `floor(B * 7000 / 10000)` and the platform receives B
minus that amount, including the integer remainder. Amounts are exact bounded
integers; floats, booleans, negative values and currency substitutions fail.

Refunds are cumulative and always refer to the original allocation. They do not
apply a new fixed deduction or separately round independent refund fragments.
For remaining gross L after a cumulative refund:

1. Remaining processing is `floor(original_processing * L / original_gross)`.
2. Remaining tax is the floor of its original proportion of the remaining
   after-processing balance (zero when the original denominator was zero).
3. Remaining provider allocation is the floor of its original proportion of the
   remaining distributable balance; platform receives the remainder.

Each original component is monotone and nonnegative as refunds accumulate. Each
refund posts the difference between the previous and newly calculated remaining
balances, and a full refund returns every component exactly to zero. Thus the
same cumulative refund produces the same remaining balances regardless of how
it is split. Original capture uses the exact 7:3 integer rule; refunds preserve
that original rounded allocation rather than inventing a new charge split.

A capture records five signed `TEST_UNIT` entries: simulated customer (negative
G), processing P, tax T, provider, and platform. A refund reverses the corresponding
component differences and credits the simulated customer. Every event sums to
zero. No provider HTTP call, wallet, payment or payout occurs.

## Event deduplication, concurrency and integrity

The caller supplies an opaque `sim_...` event reference. It is unique per
workspace. The exact command hash binds action, agreement/settlement, amount,
revision and authorization notice. Replaying that command returns its recorded
settlement; reusing the reference with different content is a conflict. Admission,
event insertion, all entries, signed current balance and audit commit atomically.

Refunds require the current settlement revision. Concurrent requests against the
same revision admit only one. Cumulative refunded gross cannot exceed captured
gross. The final allowed event slot requires a full remaining refund, so repeated
partial refunds cannot consume every slot while leaving a stranded balance.
The bounded profile allows 100 agreement versions, 100 settlements and 100 events
per settlement per workspace.

Events form a signed hash chain referenced by the signed settlement state. Reads
validate exact scope, state revision/event count, linked event hashes, all five
signed entries, expected component changes and conservation. Missing, changed,
reordered or extra retained events/entries fail closed. These checks are not an
external monotone database rollback witness. The restore tool permanently blocks
all restored agreement IDs and preserves signed terms/ledger evidence; restored
historical state cannot automatically resume settlement.

## Private integration contract

The root advancement transport integrates these methods behind existing staff
origin/session/owner and bounded JSON checks. No public portal route is added.
All DTOs carry `simulation: true`, `actual_money: false`, `commercial_enabled:
false`, `payment_enabled: false`, `provider_payout_enabled: false`, and
`legal_verification: unverified`.

- `options(ws, actor)`: notice, fixed split/asset and limits.
- `versions(ws, actor)`: immutable versions, current eligibility and head revisions.
- `create(ws, body, actor)`: resource/claim IDs and revisions, current head
  `revision` (0 initially), expiry, exact terms, `authorized: true`, notice.
- `revoke(ws, agreement_id, {revision}, actor)`.
- `quote(ws, agreement_id, {gross_units}, actor)`: deterministic allocation and
  quote hash; no ledger mutation.
- `settle(ws, agreement_id, body, actor)`: event reference, gross units, quote
  hash, agreement state revision, explicit authorization and notice.
- `refund(ws, settlement_id, body, actor)`: event reference, incremental refund
  units, settlement revision, explicit authorization and notice.
- `summary(ws, actor)`: verified bounded ledger balances and settlement history.

The notice is `workspace-agreement-simulation-v1`. New agreement expires no later
than its current control proof or 30 days. No user flag can enable real commerce.

## Verification and limits

Isolated tests use a synthetic HTTPS control responder, current synthetic staff
sessions and disposable SQLite. They cover immutable CAS versions, exact
7:3/deduction arithmetic, randomized monotone cumulative refunds, deterministic
quotes, command deduplication, concurrent over-refund prevention, old obligation
refunds, signature/entry tampering, owner/workspace isolation, current proof/
expiry/ABA/restore denial and simulation-only flags. No real contract, legal
party data, payment provider, agent business call or operating database is used.
See the [verification record](../reports/workspace-agreements-2026-10-18/verification.json).
