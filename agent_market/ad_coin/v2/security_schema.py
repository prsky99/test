"""Database schema for operational audit logging and review appeals."""

STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_audit_log ("
    "id TEXT PRIMARY KEY, "
    "timestamp_ms BIGINT NOT NULL, "
    "event_type TEXT NOT NULL, "
    "actor_principal_id TEXT, "
    "actor_owner_id TEXT, "
    "target_id TEXT, "
    "client_ip TEXT, "
    "user_agent TEXT, "
    "status TEXT NOT NULL CHECK (status IN ('succeeded', 'denied', 'failed')), "
    "details_json TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS adc2_audit_log_time ON adc2_audit_log(timestamp_ms)",
    "CREATE INDEX IF NOT EXISTS adc2_audit_log_target ON adc2_audit_log(target_id, event_type)",
    "CREATE TABLE IF NOT EXISTS adc2_review_appeals ("
    "id TEXT PRIMARY KEY, "
    "review_id TEXT NOT NULL REFERENCES adc2_reviews(id), "
    "advertiser_id TEXT NOT NULL, "
    "campaign_id TEXT NOT NULL, "
    "reason_text TEXT NOT NULL, "
    "evidence_ref TEXT, "
    "state TEXT NOT NULL CHECK (state IN ('pending', 'accepted', 'rejected')), "
    "decision_reason TEXT, "
    "reviewer_id TEXT REFERENCES adc2_principals(id), "
    "created_ms BIGINT NOT NULL, "
    "decided_ms BIGINT, "
    "version BIGINT NOT NULL CHECK (version>=1))",
    "CREATE INDEX IF NOT EXISTS adc2_review_appeals_state ON adc2_review_appeals(state, created_ms)",
)


def statements():
    return STATEMENTS
