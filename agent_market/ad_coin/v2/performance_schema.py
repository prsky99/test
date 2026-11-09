"""PostgreSQL indexes that retain transaction guards and bounded UI projections."""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS adc2_pending_journals ON adc2_journals(id) WHERE state<>'sealed'",
    "CREATE INDEX IF NOT EXISTS adc2_pending_commands ON adc2_idempotency_records(scope_hash) WHERE state<>'done'",
    "CREATE INDEX IF NOT EXISTS adc2_active_campaigns ON adc2_campaigns(id) WHERE state='active' AND approval_status='approved' AND funded=1",
    "CREATE INDEX IF NOT EXISTS adc2_advertiser_campaigns ON adc2_campaigns(advertiser_id,id)",
    "CREATE INDEX IF NOT EXISTS adc2_owner_wallets ON adc2_wallets(owner_id,id)",
    "CREATE INDEX IF NOT EXISTS adc2_active_memberships ON adc2_memberships(principal_id,advertiser_id,capability) WHERE active=1",
)
