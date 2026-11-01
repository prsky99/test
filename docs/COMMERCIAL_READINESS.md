# Commercial readiness evidence and declarations

`workspace-commercial-readiness-v1` exposes a private checklist and signed
declaration audit. It never enables a payment, provider payout, advertisement,
commercial execution or automatic G2/G3 promotion.

The required categories are identity, provider ownership, quality, storage/DR,
support, ledger, contract, payment integration and operations. An owner can
record a bounded opaque reference, claimed SHA-256 and expiry as
`declared_unverified`. The tool does not open that referenced material, verify
its hash, certify a contract or turn an administrator checkbox into evidence.
All missing/unverified categories keep the result `not_ready`.

Actual current evidence can enter only through trusted server-owned readonly
source adapters. HTTP callers cannot submit evidence objects or mark a check
verified. The typed adapter result binds the exact workspace/category, source,
content hash, source audit hash, observation time, expiry and operating environment. Wrong scope,
expired/nonfinite/malformed data, isolated fixtures and source errors fail
closed. Missing adapters remain explicitly unconfigured. No adapter is
configured implicitly by adding this module.

Adapters run outside the DB lock and must neither contact providers nor mutate
state during this inspection. The checklist checks current named session and
membership before and after gathering evidence, rejecting a changed scope.
Integrators must verify each source's actual signature, role, revocation and
provenance before returning an evidence object. A source adapter is trusted code,
not a substitute for those domain checks or independent human evidence.

Even a complete current checklist returns
`evidence_complete_review_required`, with `commercial_enabled:false`,
`payment_enabled:false` and `automatic_gate_promotion:false`. An independent
authorized release/activation process remains required. A missing external IdP,
provider claim, expert review, contract or actual DR acceptance cannot be filled
with a synthetic record to make the interface green.

Declared records and current check states are workspace-scoped, integrity signed
where persisted, audited and no-store. Current members may inspect the checklist;
only writable owners may add declarations. The administrator dialog shows fixed
category/state facts and explicitly labels declarations as unverified. Current
individual database sessions are not claims of customer OIDC or provider identity.

Remaining real-world inputs include the actual counterparties and qualified
reviewers, applicable contracts/tax/refund/payout terms, payment integration,
representative load/recovery and operator evidence, ownership/identity setup and
an independently approved commercial decision. This implementation provides
honest gap inspection and auditable preparation without fabricating those inputs.
