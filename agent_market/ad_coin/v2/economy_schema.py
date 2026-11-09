"""Coin economy tables (docs/AD_COIN_COIN_ECONOMY.md): Sponsored day bookings paid in coins."""

STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_sponsored_bookings ("
    "id TEXT PRIMARY KEY, "
    "advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), "
    "campaign_id TEXT NOT NULL REFERENCES adc2_campaigns(id), "
    "day_ms BIGINT NOT NULL CHECK (day_ms>=0 AND day_ms % 86400000 = 0), "
    "task_category TEXT NOT NULL, "
    "region TEXT NOT NULL, "
    "price_atoms NUMERIC NOT NULL CHECK (price_atoms>0 AND price_atoms=trunc(price_atoms)), "
    "journal_id TEXT NOT NULL REFERENCES adc2_journals(id), "
    "state TEXT NOT NULL CHECK (state IN ('booked','served','refunded')), "
    "refund_journal_id TEXT REFERENCES adc2_journals(id), "
    "created_ms BIGINT NOT NULL, "
    "UNIQUE(campaign_id, day_ms, task_category, region))",
    "CREATE INDEX IF NOT EXISTS adc2_sponsored_bookings_day ON adc2_sponsored_bookings(day_ms, task_category, region, state)",
)


def statements():
    return STATEMENTS
