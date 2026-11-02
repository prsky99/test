# Native finance and credential compatibility verification

The new `PostgresFinanceMixin` completes 15 existing Store methods for encrypted platform credentials and the legacy virtual credit/clearing ledger. SQLite behavior remains covered by the existing vault and clearinghouse tests. No public customer portal or real financial integration is opened.

The final affected batch passed **55 unique pytest cases**, with zero failures, errors or skips. One required native test verifies **39 actual PostgreSQL contracts**; those nested checks are not additional unique pytest cases. Bandit reports zero findings/errors in the two implementation modules. Exact source hashes and scope are in `finance-verification.json`.

The native fixture used a disposable private Unix socket, checked transport before initialization, rebuilt the child environment, blocked Python IP socket creation and made no provider/payment/payout calls. Concurrent independent connections preserve deposits, prevent over-reservation/overdraw and admit one terminal settlement/refund winner. Unique-ledger insertion failure rolls back the earlier account update. Credential tests cover stable-key reopening, missing/wrong keys, purpose/name binding, tag tampering, empty ciphertext, and denial of wrong-key overwrite/delete/mixed-key writes.

Additional adversarial coverage checks large-exponent/20,000-digit/large-float latency samples, finite actual dashboard responses, corrupted reservation amount/status denial and malformed receipt preservation. Twenty-five fresh mutation attempts against negative-held, held-sum, deposit-conservation, negative-balance and negative-spent corruption leave exact account/ledger rows unchanged; an orphan ledger account cannot be silently recreated. Original records are never silently repaired. Administrator credential and virtual-finance requests retain current superadmin/origin boundaries.

The original virtual ledger has no deposit/hold caller idempotency key or authenticated external-payment history. Commercial collection/disbursement, reserves, operating migration, performance/HA acceptance and public portal opening remain separate.
