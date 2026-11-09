"""PostgreSQL schema statements for AI AD Coin v2 real-value issuance, reserves, and blockchain redemptions."""


def statements() -> tuple[str, ...]:
    return (
        """CREATE TABLE IF NOT EXISTS adc2_fiat_deposits (
            id TEXT PRIMARY KEY,
            wallet_id TEXT NOT NULL,
            payer_owner_id TEXT NOT NULL,
            amount_atoms NUMERIC NOT NULL CHECK (amount_atoms > 0),
            currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'KRW', 'USDC')),
            external_tx_ref TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'failed', 'rejected')),
            created_at NUMERIC NOT NULL,
            settled_at NUMERIC
        )""",
        """CREATE TABLE IF NOT EXISTS adc2_custody_reserves (
            id TEXT PRIMARY KEY,
            custodian_name TEXT NOT NULL,
            vault_address TEXT NOT NULL,
            reported_atoms NUMERIC NOT NULL CHECK (reported_atoms >= 0),
            attestation_hash TEXT NOT NULL,
            reported_at NUMERIC NOT NULL,
            created_at NUMERIC NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS adc2_onchain_withdrawals (
            id TEXT PRIMARY KEY,
            wallet_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            destination_chain TEXT NOT NULL CHECK (destination_chain IN ('ethereum', 'base', 'polygon', 'arbitrum')),
            chain_id BIGINT NOT NULL,
            destination_address TEXT NOT NULL CHECK (destination_address ~ '^0x[0-9a-fA-F]{40}$'),
            amount_atoms NUMERIC NOT NULL CHECK (amount_atoms > 0),
            fee_atoms NUMERIC NOT NULL CHECK (fee_atoms >= 0),
            status TEXT NOT NULL CHECK (status IN ('pending', 'relayed', 'confirmed', 'failed', 'cancelled')),
            tx_hash TEXT,
            created_at NUMERIC NOT NULL,
            settled_at NUMERIC
        )""",
        "CREATE INDEX IF NOT EXISTS adc2_fiat_deposits_wallet ON adc2_fiat_deposits(wallet_id)",
        "CREATE INDEX IF NOT EXISTS adc2_custody_reserves_created ON adc2_custody_reserves(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS adc2_onchain_withdrawals_wallet ON adc2_onchain_withdrawals(wallet_id)",
        "CREATE INDEX IF NOT EXISTS adc2_onchain_withdrawals_owner ON adc2_onchain_withdrawals(owner_id)",
    )
