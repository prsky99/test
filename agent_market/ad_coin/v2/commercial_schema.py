"""Additive PostgreSQL model commercial tables and immutable revision records."""

from .contracts import MAX_ATOMS


def statements():
    def amount(name):
        return f"{name} NUMERIC NOT NULL CHECK ({name}=trunc({name}) AND {name} BETWEEN 1 AND {MAX_ATOMS})"

    return (
        "CREATE TABLE IF NOT EXISTS adc2_principals (id TEXT PRIMARY KEY REFERENCES adc2_authority_guards(guard_id), "
        "kind TEXT NOT NULL CHECK (kind IN ('human','agent','ops')), owner_id TEXT, capabilities_json TEXT NOT NULL, "
        "CHECK (((kind IN ('human','agent')) AND owner_id IS NOT NULL) OR (kind='ops' AND owner_id IS NULL)))",
        "ALTER TABLE adc2_principals DROP CONSTRAINT IF EXISTS adc2_principals_kind_check",
        "ALTER TABLE adc2_principals DROP CONSTRAINT IF EXISTS adc2_principals_check",
        "ALTER TABLE adc2_principals ADD CONSTRAINT adc2_principals_kind_check CHECK (kind IN ('human','agent','ops'))",
        "ALTER TABLE adc2_principals ADD CONSTRAINT adc2_principals_check CHECK "
        "((kind IN ('human','agent') AND owner_id IS NOT NULL) OR (kind='ops' AND owner_id IS NULL))",
        "CREATE TABLE IF NOT EXISTS adc2_advertisers (id TEXT PRIMARY KEY REFERENCES adc2_authority_guards(guard_id), "
        "commercial_tenant_id TEXT NOT NULL UNIQUE, available_account TEXT NOT NULL UNIQUE REFERENCES adc2_accounts(id), "
        "status TEXT NOT NULL CHECK (status IN ('active','suspended')))",
        "CREATE TABLE IF NOT EXISTS adc2_memberships (advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), "
        "principal_id TEXT NOT NULL REFERENCES adc2_principals(id), capability TEXT NOT NULL, "
        "active INTEGER NOT NULL CHECK (active IN (0,1)), epoch BIGINT NOT NULL CHECK (epoch>=1), "
        "PRIMARY KEY(advertiser_id,principal_id,capability))",
        "CREATE TABLE IF NOT EXISTS adc2_campaigns (id TEXT PRIMARY KEY, advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), "
        "current_revision_id TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL UNIQUE REFERENCES adc2_accounts(id), "
        "state TEXT NOT NULL CHECK (state IN ('draft','in_review','eligible','rejected','active','paused','suspended')), "
        "approval_status TEXT NOT NULL CHECK (approval_status IN ('unapproved','approved','invalidated')), "
        "version BIGINT NOT NULL CHECK (version>=1), dispatch_epoch BIGINT NOT NULL CHECK (dispatch_epoch>=1), "
        "funded INTEGER NOT NULL CHECK (funded IN (0,1)), total_window_id TEXT REFERENCES adc2_budget_windows(id), "
        "UNIQUE(id,advertiser_id), CHECK ((funded=0 AND total_window_id IS NULL) OR (funded=1 AND total_window_id IS NOT NULL)))",
        "CREATE TABLE IF NOT EXISTS adc2_campaign_revisions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, "
        "advertiser_id TEXT NOT NULL, revision_hash TEXT NOT NULL, payload_json TEXT NOT NULL, "
        "starts_ms BIGINT NOT NULL, ends_ms BIGINT NOT NULL CHECK (ends_ms>starts_ms), "
        + amount("total_atoms")
        + ", "
        + amount("daily_atoms")
        + ", "
        + amount("gross_atoms")
        + ", split_json TEXT NOT NULL, FOREIGN KEY(campaign_id,advertiser_id) REFERENCES adc2_campaigns(id,advertiser_id), "
        "UNIQUE(id,campaign_id,advertiser_id), CHECK (daily_atoms<=total_atoms AND gross_atoms<=daily_atoms))",
        """DO $$ BEGIN ALTER TABLE adc2_campaigns ADD CONSTRAINT adc2_current_revision_fk
        FOREIGN KEY(current_revision_id,id,advertiser_id) REFERENCES adc2_campaign_revisions(id,campaign_id,advertiser_id)
        DEFERRABLE INITIALLY DEFERRED; EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
        "CREATE TABLE IF NOT EXISTS adc2_reviews (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, advertiser_id TEXT NOT NULL, "
        "revision_id TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('pending','eligible','rejected')), "
        "version BIGINT NOT NULL CHECK (version>=1), reviewer_id TEXT REFERENCES adc2_principals(id), evidence_id TEXT, reason_code TEXT, "
        "FOREIGN KEY(revision_id,campaign_id,advertiser_id) REFERENCES adc2_campaign_revisions(id,campaign_id,advertiser_id), "
        "UNIQUE(id,revision_id,advertiser_id))",
        "CREATE UNIQUE INDEX IF NOT EXISTS adc2_pending_review ON adc2_reviews(revision_id) WHERE state='pending'",
        "CREATE TABLE IF NOT EXISTS adc2_review_evidence (id TEXT PRIMARY KEY, review_id TEXT NOT NULL, revision_id TEXT NOT NULL, "
        "advertiser_id TEXT NOT NULL, content_digest TEXT NOT NULL, "
        "FOREIGN KEY(review_id,revision_id,advertiser_id) REFERENCES adc2_reviews(id,revision_id,advertiser_id), "
        "UNIQUE(id,review_id,revision_id,advertiser_id))",
        """DO $$ BEGIN ALTER TABLE adc2_reviews ADD CONSTRAINT adc2_review_evidence_fk
        FOREIGN KEY(evidence_id,id,revision_id,advertiser_id) REFERENCES adc2_review_evidence(id,review_id,revision_id,advertiser_id)
        DEFERRABLE INITIALLY DEFERRED; EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
        "CREATE TABLE IF NOT EXISTS adc2_approvals (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, advertiser_id TEXT NOT NULL, "
        "revision_id TEXT NOT NULL UNIQUE, principal_id TEXT NOT NULL REFERENCES adc2_principals(id), principal_epoch BIGINT NOT NULL, "
        "membership_epoch BIGINT NOT NULL, fresh_action_id TEXT NOT NULL UNIQUE REFERENCES adc2_fresh_actions(id), "
        "operation_id TEXT NOT NULL REFERENCES adc2_idempotency_records(operation_id), expires_ms BIGINT NOT NULL, "
        "FOREIGN KEY(revision_id,campaign_id,advertiser_id) REFERENCES adc2_campaign_revisions(id,campaign_id,advertiser_id), "
        "UNIQUE(campaign_id,revision_id))",
        "CREATE TABLE IF NOT EXISTS adc2_commercial_control (id INTEGER PRIMARY KEY CHECK (id=1), "
        "model_activation_enabled INTEGER NOT NULL CHECK (model_activation_enabled IN (0,1)))",
        "INSERT INTO adc2_commercial_control VALUES (1,0) ON CONFLICT(id) DO NOTHING",
        """CREATE OR REPLACE FUNCTION adc2_immutable_commercial() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'adc2_immutable_commercial_record'; END $$""",
        *tuple(
            statement
            for table in (
                "principals",
                "campaign_revisions",
                "review_evidence",
                "approvals",
            )
            for statement in (
                f"DROP TRIGGER IF EXISTS adc2_immutable_commercial ON adc2_{table}",
                f"CREATE TRIGGER adc2_immutable_commercial BEFORE UPDATE OR DELETE ON adc2_{table} "
                "FOR EACH ROW EXECUTE FUNCTION adc2_immutable_commercial()",
            )
        ),
    )
