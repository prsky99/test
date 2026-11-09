"""PostgreSQL schema for AI AD Coin v2 agent payment mandates and execution escrow."""


def statements():
    return (
        "CREATE TABLE IF NOT EXISTS adc2_mandates ("
        "id TEXT PRIMARY KEY, "
        "owner_id TEXT NOT NULL, "
        "agent_principal_id TEXT NOT NULL, "
        "total_atoms NUMERIC NOT NULL CHECK (total_atoms=trunc(total_atoms) AND total_atoms>=0), "
        "per_task_atoms NUMERIC NOT NULL CHECK (per_task_atoms=trunc(per_task_atoms) AND per_task_atoms>=0), "
        "spent_atoms NUMERIC NOT NULL DEFAULT 0 CHECK (spent_atoms=trunc(spent_atoms) AND spent_atoms>=0), "
        "providers JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "expires_at BIGINT NOT NULL, "
        "revoked_at BIGINT, "
        "created_at BIGINT NOT NULL, "
        "CHECK (spent_atoms<=total_atoms))",
        "CREATE INDEX IF NOT EXISTS adc2_mandates_owner ON adc2_mandates(owner_id)",
        "CREATE INDEX IF NOT EXISTS adc2_mandates_agent ON adc2_mandates(agent_principal_id)",
        "CREATE TABLE IF NOT EXISTS adc2_executions ("
        "id TEXT PRIMARY KEY, "
        "owner_id TEXT NOT NULL, "
        "provider_id TEXT NOT NULL, "
        "task_ref TEXT NOT NULL, "
        "price_atoms NUMERIC NOT NULL CHECK (price_atoms=trunc(price_atoms) AND price_atoms>0), "
        "status TEXT NOT NULL CHECK (status IN ('held','settled','refunded','partial')), "
        "mandate_id TEXT REFERENCES adc2_mandates(id), "
        "user_account_id TEXT NOT NULL REFERENCES adc2_accounts(id), "
        "hold_account_id TEXT NOT NULL REFERENCES adc2_accounts(id), "
        "provider_account_id TEXT NOT NULL REFERENCES adc2_accounts(id), "
        "result_digest TEXT, "
        "created_at BIGINT NOT NULL, "
        "finished_at BIGINT)",
        "CREATE INDEX IF NOT EXISTS adc2_executions_owner ON adc2_executions(owner_id)",
        "CREATE INDEX IF NOT EXISTS adc2_executions_status ON adc2_executions(status)",
    )
