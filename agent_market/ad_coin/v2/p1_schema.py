"""Additive PostgreSQL model P1, wallet, receipt, operation, and reporting tables."""

from .contracts import MAX_ATOMS


def statements():
    def positive_amount(name):
        return f"{name} NUMERIC NOT NULL CHECK ({name}=trunc({name}) AND {name} BETWEEN 1 AND {MAX_ATOMS})"

    return (
        "CREATE TABLE IF NOT EXISTS adc2_agent_bindings (id TEXT PRIMARY KEY REFERENCES adc2_authority_guards(guard_id), "
        "owner_id TEXT NOT NULL, agent_principal_id TEXT NOT NULL REFERENCES adc2_principals(id), "
        "operator_id TEXT NOT NULL, capabilities_json TEXT NOT NULL, "
        "active INTEGER NOT NULL CHECK (active IN (0,1)), epoch BIGINT NOT NULL CHECK (epoch>=1), "
        "UNIQUE(id,owner_id), UNIQUE(agent_principal_id))",
        "CREATE TABLE IF NOT EXISTS adc2_ad_preferences (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE, "
        "receive_offers INTEGER NOT NULL CHECK (receive_offers IN (0,1)), context_fields_json TEXT NOT NULL, "
        "max_offers_per_day INTEGER NOT NULL CHECK (max_offers_per_day BETWEEN 0 AND 100), "
        "max_ads_per_campaign_day INTEGER NOT NULL CHECK (max_ads_per_campaign_day BETWEEN 0 AND 3), "
        "max_ads_per_day INTEGER NOT NULL CHECK (max_ads_per_day BETWEEN 0 AND 10), "
        "max_ad_ms_per_day BIGINT NOT NULL CHECK (max_ad_ms_per_day BETWEEN 0 AND 600000), "
        "version BIGINT NOT NULL CHECK (version>=1), revision_hash TEXT NOT NULL, effective_ms BIGINT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS adc2_wallets (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, "
        "manager_binding_id TEXT REFERENCES adc2_agent_bindings(id), asset_id TEXT NOT NULL REFERENCES adc2_assets(id), "
        "available_account TEXT NOT NULL UNIQUE REFERENCES adc2_accounts(id), "
        "locked_account TEXT NOT NULL UNIQUE REFERENCES adc2_accounts(id), "
        "operator_account TEXT NOT NULL REFERENCES adc2_accounts(id), UNIQUE(id,owner_id))",
        "CREATE TABLE IF NOT EXISTS adc2_operations (id TEXT PRIMARY KEY, "
        "principal_id TEXT NOT NULL REFERENCES adc2_principals(id), owner_id TEXT, agent_binding_id TEXT, "
        "command_type TEXT NOT NULL, "
        "state TEXT NOT NULL CHECK (state IN ('pending','running','review_pending','succeeded','failed','no_offer')), "
        "resource_id TEXT, resource_type TEXT NOT NULL CHECK (resource_type IN ('offer','exposure','award','none')), "
        "receipt_id TEXT, review_deadline_ms BIGINT, version BIGINT NOT NULL CHECK (version>=1))",
        "CREATE TABLE IF NOT EXISTS adc2_offers (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, "
        "revision_id TEXT NOT NULL, advertiser_id TEXT NOT NULL, owner_id TEXT NOT NULL, agent_binding_id TEXT, "
        "wallet_id TEXT NOT NULL, hold_id TEXT NOT NULL UNIQUE REFERENCES adc2_budget_holds(id), "
        "quote_hash TEXT NOT NULL, quote_json TEXT NOT NULL, "
        "state TEXT NOT NULL CHECK (state IN "
        "('reserved','consented','exposing','evidence_pending','review_pending','awarded','declined','expired','cancelled','rejected')), "
        "version BIGINT NOT NULL CHECK (version>=1), expires_ms BIGINT NOT NULL, created_ms BIGINT NOT NULL, "
        "FOREIGN KEY(revision_id,campaign_id,advertiser_id) REFERENCES adc2_campaign_revisions(id,campaign_id,advertiser_id), "
        "FOREIGN KEY(wallet_id,owner_id) REFERENCES adc2_wallets(id,owner_id), UNIQUE(id,owner_id))",
        "CREATE INDEX IF NOT EXISTS adc2_offers_owner_day ON adc2_offers(owner_id,created_ms)",
        "CREATE TABLE IF NOT EXISTS adc2_human_consents (id TEXT PRIMARY KEY, offer_id TEXT NOT NULL UNIQUE, "
        "owner_id TEXT NOT NULL, quote_hash TEXT NOT NULL, "
        "fresh_action_id TEXT NOT NULL UNIQUE REFERENCES adc2_fresh_actions(id), "
        "operation_id TEXT NOT NULL REFERENCES adc2_idempotency_records(operation_id), "
        "version BIGINT NOT NULL CHECK (version>=1), created_ms BIGINT NOT NULL, revoked_ms BIGINT, "
        "FOREIGN KEY(offer_id,owner_id) REFERENCES adc2_offers(id,owner_id), UNIQUE(id,offer_id,owner_id))",
        "CREATE TABLE IF NOT EXISTS adc2_exposure_sessions (id TEXT PRIMARY KEY, offer_id TEXT NOT NULL UNIQUE, "
        "owner_id TEXT NOT NULL, consent_id TEXT NOT NULL, consent_version BIGINT NOT NULL CHECK (consent_version>=1), "
        "state TEXT NOT NULL CHECK (state IN "
        "('active','evidence_pending','review_pending','completed','cancelled','expired','rejected')), "
        "next_sequence INTEGER NOT NULL CHECK (next_sequence BETWEEN 0 AND 301), "
        "next_nonce TEXT NOT NULL, next_nonce_hash TEXT NOT NULL, startup_deadline_ms BIGINT NOT NULL, "
        "first_signal_ms BIGINT, last_signal_ms BIGINT, "
        "last_elapsed_claim_ms INTEGER NOT NULL CHECK (last_elapsed_claim_ms BETWEEN 0 AND 30000), "
        "active_deadline_ms BIGINT, evidence_deadline_ms BIGINT NOT NULL, cutoff_ms BIGINT, "
        "collected_valid_ms INTEGER NOT NULL CHECK (collected_valid_ms BETWEEN 0 AND 30000), "
        "qualified_ms BIGINT, max_view_ms INTEGER NOT NULL CHECK (max_view_ms BETWEEN 15000 AND 30000), "
        "quota_reservation_id TEXT NOT NULL REFERENCES adc2_attention_sessions(id), "
        "version BIGINT NOT NULL CHECK (version>=1), "
        "FOREIGN KEY(offer_id,owner_id) REFERENCES adc2_offers(id,owner_id), "
        "FOREIGN KEY(consent_id,offer_id,owner_id) REFERENCES adc2_human_consents(id,offer_id,owner_id))",
        "CREATE TABLE IF NOT EXISTS adc2_evidence_chunks (session_id TEXT NOT NULL REFERENCES adc2_exposure_sessions(id), "
        "sequence INTEGER NOT NULL CHECK (sequence BETWEEN 0 AND 300), nonce_hash TEXT NOT NULL, "
        "server_received_ms BIGINT NOT NULL, elapsed_claim_ms INTEGER NOT NULL CHECK (elapsed_claim_ms BETWEEN 0 AND 30000), "
        "visible INTEGER NOT NULL CHECK (visible IN (0,1)), foreground INTEGER NOT NULL CHECK (foreground IN (0,1)), "
        "canonical_hash TEXT NOT NULL, issued_next_nonce TEXT NOT NULL, "
        "PRIMARY KEY(session_id,sequence), UNIQUE(session_id,nonce_hash))",
        "CREATE TABLE IF NOT EXISTS adc2_receipts (id TEXT PRIMARY KEY, "
        "journal_id TEXT NOT NULL UNIQUE REFERENCES adc2_journals(id), offer_id TEXT NOT NULL UNIQUE, "
        "owner_id TEXT NOT NULL, agent_binding_id TEXT, asset_id TEXT NOT NULL REFERENCES adc2_assets(id), "
        + positive_amount("user_reward_atoms")
        + ", quote_hash TEXT NOT NULL, issued_ms BIGINT NOT NULL, "
        "signature_state TEXT NOT NULL CHECK (signature_state IN ('pending','signed')), key_id TEXT, jws TEXT, "
        "FOREIGN KEY(offer_id,owner_id) REFERENCES adc2_offers(id,owner_id), "
        "CHECK ((signature_state='pending' AND key_id IS NULL AND jws IS NULL) OR "
        "(signature_state='signed' AND key_id IS NOT NULL AND jws IS NOT NULL)))",
        "CREATE TABLE IF NOT EXISTS adc2_receipt_keys (kid TEXT PRIMARY KEY, "
        "status TEXT NOT NULL CHECK (status IN ('active','verify_only','revoked')), "
        "not_before_ms BIGINT NOT NULL, verify_until_ms BIGINT NOT NULL CHECK (verify_until_ms>not_before_ms), "
        "public_x TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS adc2_reporting_obligations (id TEXT PRIMARY KEY, "
        "advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), campaign_id TEXT NOT NULL, "
        "period_start_ms BIGINT NOT NULL, period_end_ms BIGINT NOT NULL CHECK (period_end_ms>period_start_ms), "
        "expected_ms BIGINT NOT NULL, "
        "state TEXT NOT NULL CHECK (state IN ('waiting','available','delayed','action_required')), "
        "current_revision INTEGER CHECK (current_revision IS NULL OR current_revision>=1), report_id TEXT, "
        "FOREIGN KEY(campaign_id,advertiser_id) REFERENCES adc2_campaigns(id,advertiser_id), "
        "UNIQUE(campaign_id,period_start_ms,period_end_ms), "
        "CHECK ((state='available' AND current_revision IS NOT NULL AND report_id IS NOT NULL) OR state<>'available'))",
        "CREATE TABLE IF NOT EXISTS adc2_report_revisions (id TEXT NOT NULL, "
        "revision INTEGER NOT NULL CHECK (revision>=1), "
        "obligation_id TEXT NOT NULL REFERENCES adc2_reporting_obligations(id), "
        "advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), campaign_id TEXT NOT NULL, "
        "content_digest TEXT NOT NULL, supersedes_revision INTEGER, generated_ms BIGINT NOT NULL, "
        "data_through_ms BIGINT NOT NULL, complete INTEGER NOT NULL CHECK (complete IN (0,1)), "
        "metrics_json TEXT NOT NULL, PRIMARY KEY(id,revision), "
        "FOREIGN KEY(campaign_id,advertiser_id) REFERENCES adc2_campaigns(id,advertiser_id))",
        "ALTER TABLE adc2_report_revisions ADD COLUMN IF NOT EXISTS source_manifest_json TEXT NOT NULL DEFAULT '[]'",
        "CREATE TABLE IF NOT EXISTS adc2_report_consumptions (id TEXT PRIMARY KEY, "
        "advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), "
        "principal_id TEXT NOT NULL REFERENCES adc2_principals(id), report_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL CHECK (revision>=1), "
        "state TEXT NOT NULL CHECK (state IN ('received','missing','unreadable','content_mismatch')), "
        "observed_digest TEXT, recorded_ms BIGINT NOT NULL, "
        "FOREIGN KEY(report_id,revision) REFERENCES adc2_report_revisions(id,revision))",
        *tuple(
            statement
            for table in (
                "human_consents",
                "evidence_chunks",
                "report_revisions",
                "report_consumptions",
            )
            for statement in (
                f"DROP TRIGGER IF EXISTS adc2_immutable_commercial ON adc2_{table}",
                f"CREATE TRIGGER adc2_immutable_commercial BEFORE UPDATE OR DELETE ON adc2_{table} "
                "FOR EACH ROW EXECUTE FUNCTION adc2_immutable_commercial()",
            )
        ),
    )
