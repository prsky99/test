"""PostgreSQL schema for external agent ad distribution, A2A/MCP relay partners, and dispatches."""

from .contracts import MAX_ATOMS


def statements() -> tuple[str, ...]:
    def positive_amount(name: str) -> str:
        return f"{name} NUMERIC NOT NULL CHECK ({name}=trunc({name}) AND {name} BETWEEN 1 AND {MAX_ATOMS})"

    def non_negative_amount(name: str) -> str:
        return f"{name} NUMERIC NOT NULL CHECK ({name}=trunc({name}) AND {name} BETWEEN 0 AND {MAX_ATOMS})"

    return (
        "CREATE TABLE IF NOT EXISTS adc2_relay_partners ("
        "id TEXT PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "protocol TEXT NOT NULL CHECK (protocol IN ('a2a', 'mcp')), "
        "endpoint_url TEXT NOT NULL, "
        "fee_basis_points INTEGER NOT NULL CHECK (fee_basis_points BETWEEN 0 AND 3000), "
        "status TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'revoked')), "
        "operator_account_id TEXT NOT NULL REFERENCES adc2_accounts(id), "
        "created_at BIGINT NOT NULL, "
        "revoked_at BIGINT"
        ")",
        "CREATE TABLE IF NOT EXISTS adc2_relay_dispatches ("
        "id TEXT PRIMARY KEY, "
        "offer_id TEXT NOT NULL UNIQUE REFERENCES adc2_offers(id), "
        "partner_id TEXT NOT NULL REFERENCES adc2_relay_partners(id), "
        "owner_id TEXT NOT NULL, "
        "campaign_id TEXT NOT NULL, "
        "hop_count INTEGER NOT NULL CHECK (hop_count BETWEEN 1 AND 3), "
        "relay_token TEXT NOT NULL UNIQUE, "
        "status TEXT NOT NULL CHECK (status IN ('dispatched', 'consented', 'viewed', 'settled', 'expired', 'rejected')), "
        + positive_amount("user_reward_atoms") + ", "
        + non_negative_amount("relay_fee_atoms") + ", "
        "platform_viewer_url TEXT NOT NULL, "
        "created_at BIGINT NOT NULL, "
        "expires_at BIGINT NOT NULL CHECK (expires_at > created_at), "
        "consented_at BIGINT, "
        "settled_at BIGINT"
        ")",
        "CREATE INDEX IF NOT EXISTS adc2_relay_dispatches_owner ON adc2_relay_dispatches(owner_id, status)",
        "CREATE INDEX IF NOT EXISTS adc2_relay_dispatches_partner ON adc2_relay_dispatches(partner_id, status)",
    )
