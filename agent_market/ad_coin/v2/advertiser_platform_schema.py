"""PostgreSQL schema for advertiser platform advancement: multi-stage rewards, A/B experiments, conversions."""


def statements():
    return (
        "CREATE TABLE IF NOT EXISTS adc2_stage_claims ("
        "id TEXT PRIMARY KEY, "
        "offer_id TEXT NOT NULL REFERENCES adc2_offers(id), "
        "campaign_id TEXT NOT NULL, "
        "advertiser_id TEXT NOT NULL, "
        "owner_id TEXT NOT NULL, "
        "stage_type TEXT NOT NULL CHECK (stage_type IN ('click','feedback','watch_complete','conversion')), "
        "reward_atoms NUMERIC NOT NULL CHECK (reward_atoms >= 0), "
        "evidence_json TEXT NOT NULL, "
        "status TEXT NOT NULL CHECK (status IN ('claimed','verified','rejected','settled')), "
        "created_at BIGINT NOT NULL, "
        "settled_at BIGINT, "
        "UNIQUE(offer_id, stage_type))",
        "CREATE INDEX IF NOT EXISTS adc2_stage_claims_campaign ON adc2_stage_claims(campaign_id, stage_type)",
        "CREATE INDEX IF NOT EXISTS adc2_stage_claims_owner ON adc2_stage_claims(owner_id)",
        "CREATE TABLE IF NOT EXISTS adc2_campaign_experiments ("
        "id TEXT PRIMARY KEY, "
        "campaign_id TEXT NOT NULL, "
        "advertiser_id TEXT NOT NULL, "
        "name TEXT NOT NULL, "
        "status TEXT NOT NULL CHECK (status IN ('draft','active','paused','completed')), "
        "variants_json TEXT NOT NULL, "
        "created_at BIGINT NOT NULL, "
        "updated_at BIGINT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS adc2_campaign_experiments_camp ON adc2_campaign_experiments(campaign_id)",
        "CREATE TABLE IF NOT EXISTS adc2_conversions ("
        "id TEXT PRIMARY KEY, "
        "advertiser_id TEXT NOT NULL, "
        "campaign_id TEXT NOT NULL, "
        "offer_id TEXT NOT NULL, "
        "owner_id TEXT NOT NULL, "
        "conversion_event TEXT NOT NULL, "
        "value_atoms NUMERIC NOT NULL DEFAULT 0, "
        "order_id TEXT, "
        "attribution_window_seconds INTEGER NOT NULL DEFAULT 2592000, "
        "created_at BIGINT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS adc2_conversions_campaign ON adc2_conversions(campaign_id)",
        "CREATE INDEX IF NOT EXISTS adc2_conversions_advertiser ON adc2_conversions(advertiser_id)",
    )
