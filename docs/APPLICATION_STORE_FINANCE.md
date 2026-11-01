# Native credential and virtual credit repositories

`PostgresFinanceMixin` supplies the 15 existing credential and virtual
credit/clearing Store methods through native PostgreSQL transactions. The
existing SQLite Store and its credential sidecar format remain unchanged.
No payment provider, blockchain client, payout, customer portal, or commercial
activation is added by this module.

## Credential custody

The caller must supply an explicit stable 32-byte `workflow_key` when constructing
the native Store. A purpose-specific HMAC derivation produces the credential AES
key. `CredentialVault.from_key` consumes that exact derived key without reading
files or generating a replacement key. Missing or incorrect keys, altered
ciphertext and a ciphertext moved to another credential name fail closed without
rewriting the row. Setting a credential validates every existing ciphertext before
writing, preventing a wrong key from replacing or mixing encrypted values. Deleting
an existing credential also verifies its authentication tag. Empty stored ciphertext
is rejected rather than treated as an absent secret. Restore and key custody must preserve the original root key;
this module cannot recover a lost key.

AES-GCM associated data binds the ciphertext to the credential name. The existing
administrative list returns the same masked value and metadata as SQLite; the
secret retrieval method remains an internal repository operation. Existing
dashboard authorization restricts credential inspection and changes to a
current authenticated superadmin. Public/customer authorization is not widened.

## Virtual ledger behavior

The legacy method signatures and account, ledger, account-alias and overview
result shapes are preserved. Integer deposits, reservations, virtual withdrawals
and finalizations use one native transaction. The Store's shared writer lock and
conditional account/terminal-status updates prevent lost deposits, over-reserving
funds, overdraws and multiple settlement/refund winners. A terminal reservation
rejects another settlement or refund; it is not debited twice. Failure to insert
a unique ledger ID rolls back the earlier account update.

Individual mutations accept positive integers through `10**12`; stored account
counters cannot overflow signed 64-bit integers. Receipts are bounded JSON objects
with finite values, valid UTF-8, at most 1,024 values/keys and 16 levels, and at
most 64 KiB serialized text. The SLA average preserves SQLite's ordinary numeric,
boolean and ordinary numeric-string-prefix conversion behavior. Aggregate-only
parsing excludes numeric prefixes longer than 64 characters, exponent fields
longer than three digits, and samples above `1e300` in absolute value. This avoids
numeric overflow and nonfinite HTTP responses while preserving the original
receipt unchanged. Corrupted non-JSON stored receipts fail closed; the module
does not silently repair forensic records. Finite text and pagination
limits apply before SQL execution. Every SQL statement is fixed source text and
every caller value is bound separately.

Expired-hold cleanup processes up to 1,000 eligible reservations per invocation.
It is incremental and can be invoked again. A reservation already finalized by
another worker is skipped. Database/commit uncertainty is propagated rather than
silently retried. Existing unknown workflow evidence and restored ledger rows
are not rewritten or automatically replayed by this module.

Deposits and reservations have no caller idempotency parameter in the legacy
interface: repeating those commands intentionally creates another operation.
Clients must not retry an ambiguous mutation as though it were known to have
failed. This compatibility batch adds no external payment-event qualification,
proof of external reserves, legal agreement or actual disbursement. The original
legacy ledger is not a signed external-payment evidence source. Finalization
checks nonnegative bounded integer fields, account conservation and its
outstanding-reservation sum before **every** fresh deposit, reservation, virtual
withdrawal, settlement and refund in the same writer transaction. A missing
account with retained ledger history cannot be recreated by a deposit. These
checks reject detected inconsistencies without repairing evidence;
this detects inconsistent stored reservations but is not a defense against a
fully privileged database owner rewriting a coherent history.

## Isolated verification

`tests/test_application_store_finance.py` verifies bounded inputs, explicit-key
requirements, name/purpose binding and the absence of external payment clients.
Existing vault and clearinghouse tests verify SQLite compatibility.

`scripts/rehearse_application_finance_postgres.py --run` creates a disposable
private Unix-socket PostgreSQL cluster and a clean child environment. It verifies
the transport before initialization, compares actual native Store behavior with
SQLite, races independent connections, tests unique-ledger rollback, credential
tampering and dashboard authorization, then stops and removes the cluster. It
accepts no DSN, account, credential or operating path. Source/catalog hashes must
remain unchanged during the run. Results are source-level synthetic evidence;
they do not authorize migration, load acceptance, commercial operation or portal
opening.
