"""Database schema for persistent credentials, sessions, and reviewer mTLS."""

STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_human_sessions ("
    "session_hash TEXT PRIMARY KEY, "
    "csrf_secret_hash TEXT NOT NULL, "
    "principal_id TEXT NOT NULL REFERENCES adc2_principals(id), "
    "owner_id TEXT NOT NULL, "
    "epoch BIGINT NOT NULL CHECK (epoch>=1), "
    "created_at DOUBLE PRECISION NOT NULL, "
    "expires_at DOUBLE PRECISION NOT NULL, "
    "revoked_at DOUBLE PRECISION)",
    "CREATE INDEX IF NOT EXISTS adc2_human_sessions_owner ON adc2_human_sessions(owner_id, revoked_at)",
    "CREATE TABLE IF NOT EXISTS adc2_agent_tokens ("
    "token_hash TEXT PRIMARY KEY, "
    "principal_id TEXT NOT NULL REFERENCES adc2_principals(id), "
    "owner_id TEXT NOT NULL, "
    "agent_binding_id TEXT NOT NULL REFERENCES adc2_agent_bindings(id), "
    "epoch BIGINT NOT NULL CHECK (epoch>=1), "
    "created_at DOUBLE PRECISION NOT NULL, "
    "expires_at DOUBLE PRECISION NOT NULL, "
    "revoked_at DOUBLE PRECISION)",
    "CREATE INDEX IF NOT EXISTS adc2_agent_tokens_owner ON adc2_agent_tokens(owner_id, revoked_at)",
    "CREATE TABLE IF NOT EXISTS adc2_reviewer_credentials ("
    "token_hash TEXT PRIMARY KEY, "
    "principal_id TEXT NOT NULL REFERENCES adc2_principals(id), "
    "cert_fingerprint_sha256 TEXT, "
    "epoch BIGINT NOT NULL CHECK (epoch>=1), "
    "created_at DOUBLE PRECISION NOT NULL, "
    "expires_at DOUBLE PRECISION NOT NULL, "
    "revoked_at DOUBLE PRECISION)",
)


def statements():
    return STATEMENTS
