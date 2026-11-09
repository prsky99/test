"""Explicit model-only schema. Never migrates on module import or service startup."""

from .contracts import MAX_ATOMS

VERSION = 10
# v2 lives in its own schema; the application store owns "public" (see store.ModelStore.postgres).
SCHEMA = "ad_coin_v2"


def statements():
    def uint(name, positive=False):
        return (
            f"{name} NUMERIC NOT NULL CHECK ({name}=trunc({name}) AND "
            f"{name}>={1 if positive else 0} AND {name}<={MAX_ATOMS})"
        )

    delta = (
        f"delta_atoms NUMERIC NOT NULL CHECK (delta_atoms=trunc(delta_atoms) AND "
        f"delta_atoms<>0 AND delta_atoms BETWEEN -{MAX_ATOMS} AND {MAX_ATOMS})"
    )
    budget_check = "reserved_atoms+spent_atoms<=limit_atoms"
    remaining_check = "remaining_atoms<=initial_atoms"
    result = [
        "CREATE SCHEMA IF NOT EXISTS " + SCHEMA,
        "CREATE TABLE IF NOT EXISTS adc2_schema (id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER NOT NULL, "
        "environment TEXT NOT NULL CHECK (environment='model'), real_value INTEGER NOT NULL CHECK (real_value=0))",
        "CREATE TABLE IF NOT EXISTS adc2_assets (id TEXT PRIMARY KEY, namespace TEXT NOT NULL CHECK (namespace='model'), "
        "decimals INTEGER NOT NULL CHECK (decimals=6), CHECK (id='model:aiac:v2'))",
        "CREATE TABLE IF NOT EXISTS adc2_accounts (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, "
        "asset_id TEXT NOT NULL REFERENCES adc2_assets(id), purpose TEXT NOT NULL CHECK (purpose IN "
        "('external_clearing','advertiser_available','campaign_available','offer_hold','user_available',"
        "'user_locked','provider_payable','operator_payable','direct_cost','platform_revenue')), "
        "beneficial INTEGER NOT NULL CHECK (beneficial IN (0,1)), "
        + (
            f"balance_atoms NUMERIC NOT NULL CHECK (balance_atoms=trunc(balance_atoms) AND "
            f"balance_atoms BETWEEN -{MAX_ATOMS} AND {MAX_ATOMS}), "
        )
        + "version INTEGER NOT NULL CHECK (version>=1), UNIQUE(id,asset_id), "
        "CHECK ((purpose='external_clearing' AND beneficial=0) OR (purpose<>'external_clearing' AND beneficial=1)), "
        + "CHECK (beneficial=0 OR balance_atoms>=0))",
        "CREATE TABLE IF NOT EXISTS adc2_journals (id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES adc2_assets(id), "
        "economic_key TEXT NOT NULL, payload_hash TEXT NOT NULL, kind TEXT NOT NULL, "
        "state TEXT NOT NULL CHECK (state IN ('pending','sealed')), created_ms BIGINT NOT NULL, "
        "UNIQUE(asset_id,economic_key), UNIQUE(id,asset_id))",
        "CREATE TABLE IF NOT EXISTS adc2_postings (journal_id TEXT NOT NULL, line_no INTEGER NOT NULL CHECK (line_no>=0), "
        "asset_id TEXT NOT NULL, account_id TEXT NOT NULL, "
        + delta
        + ", PRIMARY KEY(journal_id,line_no), "
        "FOREIGN KEY(journal_id,asset_id) REFERENCES adc2_journals(id,asset_id), "
        "FOREIGN KEY(account_id,asset_id) REFERENCES adc2_accounts(id,asset_id))",
        "CREATE INDEX IF NOT EXISTS adc2_postings_account ON adc2_postings(account_id,journal_id)",
        "CREATE TABLE IF NOT EXISTS adc2_budget_windows (id TEXT PRIMARY KEY, source_account TEXT NOT NULL, "
        "asset_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('total','day')), starts_ms BIGINT NOT NULL, "
        "ends_ms BIGINT NOT NULL CHECK (ends_ms>starts_ms), "
        + uint("limit_atoms", True)
        + ", "
        + uint("reserved_atoms")
        + ", "
        + uint("spent_atoms")
        + ", version INTEGER NOT NULL CHECK (version>=1), "
        "UNIQUE(source_account,kind,starts_ms), UNIQUE(id,asset_id), "
        "FOREIGN KEY(source_account,asset_id) REFERENCES adc2_accounts(id,asset_id), CHECK ("
        + budget_check
        + "))",
        "CREATE TABLE IF NOT EXISTS adc2_budget_holds (id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, "
        "source_account TEXT NOT NULL, hold_account TEXT NOT NULL UNIQUE, total_window TEXT NOT NULL, "
        "day_window TEXT NOT NULL, payload_hash TEXT NOT NULL, expires_ms BIGINT NOT NULL, "
        + uint("initial_atoms", True)
        + ", "
        + uint("remaining_atoms")
        + ", state TEXT NOT NULL CHECK (state IN ('held','partial','consumed','released','review_pending')), "
        "FOREIGN KEY(source_account,asset_id) REFERENCES adc2_accounts(id,asset_id), "
        "FOREIGN KEY(hold_account,asset_id) REFERENCES adc2_accounts(id,asset_id), "
        "FOREIGN KEY(total_window,asset_id) REFERENCES adc2_budget_windows(id,asset_id), "
        "FOREIGN KEY(day_window,asset_id) REFERENCES adc2_budget_windows(id,asset_id), CHECK ("
        + remaining_check
        + "))",
        "CREATE TABLE IF NOT EXISTS adc2_budget_events (hold_id TEXT NOT NULL REFERENCES adc2_budget_holds(id), "
        "event_key TEXT NOT NULL, payload_hash TEXT NOT NULL, journal_id TEXT NOT NULL REFERENCES adc2_journals(id), "
        "kind TEXT NOT NULL CHECK (kind IN ('consume','release')), "
        + uint("amount_atoms", True)
        + ", PRIMARY KEY(hold_id,event_key))",
        "CREATE TABLE IF NOT EXISTS adc2_idempotency_records (scope_hash TEXT PRIMARY KEY, "
        "request_digest TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE, "
        "state TEXT NOT NULL CHECK (state IN ('running','done')), result_json TEXT, "
        "CHECK ((state='running' AND result_json IS NULL) OR (state='done' AND result_json IS NOT NULL)))",
        "CREATE TABLE IF NOT EXISTS adc2_outbox (id TEXT PRIMARY KEY, logical_key TEXT NOT NULL UNIQUE, "
        "payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL, available_ms BIGINT NOT NULL, "
        "state TEXT NOT NULL CHECK (state IN ('pending','leased','done')), lease_owner TEXT, "
        "lease_until_ms BIGINT, generation BIGINT NOT NULL CHECK (generation>=0), attempts INTEGER NOT NULL CHECK (attempts>=0), "
        "CHECK ((state='leased' AND lease_owner IS NOT NULL AND lease_until_ms IS NOT NULL) OR "
        "(state<>'leased' AND lease_owner IS NULL AND lease_until_ms IS NULL)))",
        "CREATE INDEX IF NOT EXISTS adc2_outbox_due ON adc2_outbox(state,available_ms,lease_until_ms)",
        "CREATE TABLE IF NOT EXISTS adc2_inbox (source_id TEXT NOT NULL, audience TEXT NOT NULL, event_id TEXT NOT NULL, "
        "payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(source_id,audience,event_id))",
        "CREATE TABLE IF NOT EXISTS adc2_authority_guards (guard_id TEXT PRIMARY KEY, epoch BIGINT NOT NULL CHECK (epoch>=1), "
        "status TEXT NOT NULL CHECK (status IN ('active','revoked')))",
        "CREATE TABLE IF NOT EXISTS adc2_fresh_actions (id TEXT PRIMARY KEY, principal_id TEXT NOT NULL "
        "REFERENCES adc2_authority_guards(guard_id), owner_id TEXT NOT NULL, credential_epoch BIGINT NOT NULL, "
        "session_hash TEXT NOT NULL, action TEXT NOT NULL CHECK (action IN "
        "('set_ad_preferences','approve_offer','approve_campaign')), target_id TEXT NOT NULL, "
        "revision_hash TEXT NOT NULL, semantic_digest TEXT NOT NULL, precondition TEXT, "
        "challenge_hash TEXT NOT NULL UNIQUE, expires_ms BIGINT NOT NULL, consumed_by_operation TEXT "
        "REFERENCES adc2_idempotency_records(operation_id))",
        "CREATE TABLE IF NOT EXISTS adc2_attention_windows (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, "
        "scope_kind TEXT NOT NULL CHECK (scope_kind IN ('global','advertiser','campaign')), scope_id TEXT NOT NULL, "
        "day_start_ms BIGINT NOT NULL CHECK (day_start_ms>=0 AND day_start_ms%86400000=0), "
        "count_limit INTEGER NOT NULL CHECK (count_limit BETWEEN 1 AND 10000), "
        "time_limit_ms BIGINT NOT NULL CHECK (time_limit_ms BETWEEN 15000 AND 86400000), "
        "started_sessions INTEGER NOT NULL CHECK (started_sessions>=0 AND started_sessions<=count_limit), "
        "reserved_ms BIGINT NOT NULL CHECK (reserved_ms>=0), observed_ms BIGINT NOT NULL CHECK (observed_ms>=0), "
        "version BIGINT NOT NULL CHECK (version>=1), UNIQUE(owner_id,scope_kind,scope_id,day_start_ms), "
        "CHECK (reserved_ms+observed_ms<=time_limit_ms), CHECK (scope_kind<>'global' OR scope_id=owner_id))",
        "CREATE TABLE IF NOT EXISTS adc2_attention_sessions (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, "
        "payload_hash TEXT NOT NULL, reserved_ms BIGINT NOT NULL CHECK (reserved_ms BETWEEN 15000 AND 30000), "
        "state TEXT NOT NULL CHECK (state IN ('active','closed')), settlement_hash TEXT, "
        "CHECK ((state='active' AND settlement_hash IS NULL) OR (state='closed' AND settlement_hash IS NOT NULL)))",
        "CREATE UNIQUE INDEX IF NOT EXISTS adc2_attention_active_owner ON adc2_attention_sessions(owner_id) WHERE state='active'",
        "CREATE TABLE IF NOT EXISTS adc2_attention_reservations (session_id TEXT NOT NULL REFERENCES adc2_attention_sessions(id), "
        "window_id TEXT NOT NULL REFERENCES adc2_attention_windows(id), "
        "reserved_ms BIGINT NOT NULL CHECK (reserved_ms BETWEEN 15000 AND 30000), "
        "consumed_ms BIGINT CHECK (consumed_ms>=0 AND consumed_ms<=reserved_ms), PRIMARY KEY(session_id,window_id))",
    ]
    result += [
        """CREATE OR REPLACE FUNCTION adc2_account_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='DELETE' OR (NEW.id,NEW.owner_id,NEW.asset_id,NEW.purpose,NEW.beneficial)
            IS DISTINCT FROM (OLD.id,OLD.owner_id,OLD.asset_id,OLD.purpose,OLD.beneficial)
            THEN RAISE EXCEPTION 'adc2_immutable_account_identity'; END IF;
          RETURN NEW;
        END $$""",
        "DROP TRIGGER IF EXISTS adc2_account_identity ON adc2_accounts",
        "CREATE TRIGGER adc2_account_identity BEFORE UPDATE OR DELETE ON adc2_accounts "
        "FOR EACH ROW EXECUTE FUNCTION adc2_account_identity()",
        """CREATE OR REPLACE FUNCTION adc2_validate_journal() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE header adc2_journals%ROWTYPE; n BIGINT; total NUMERIC;
        BEGIN
          SELECT * INTO header FROM adc2_journals WHERE id=NEW.id;
          SELECT count(*),coalesce(sum(delta_atoms),0) INTO n,total FROM adc2_postings WHERE journal_id=NEW.id;
          IF header.state<>'sealed' OR n<2 OR total<>0 THEN RAISE EXCEPTION 'adc2_unbalanced_journal'; END IF;
          RETURN NULL;
        END $$""",
        """CREATE OR REPLACE FUNCTION adc2_immutable_journal() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='DELETE' OR OLD.state='sealed' THEN RAISE EXCEPTION 'adc2_immutable_journal'; END IF;
          IF (NEW.id,NEW.asset_id,NEW.economic_key,NEW.payload_hash,NEW.kind,NEW.created_ms)
             IS DISTINCT FROM (OLD.id,OLD.asset_id,OLD.economic_key,OLD.payload_hash,OLD.kind,OLD.created_ms)
             THEN RAISE EXCEPTION 'adc2_immutable_journal'; END IF;
          RETURN NEW;
        END $$""",
        """CREATE OR REPLACE FUNCTION adc2_immutable_posting() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE journal_state TEXT;
        BEGIN
          IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'adc2_immutable_posting'; END IF;
          SELECT state INTO journal_state FROM adc2_journals WHERE id=NEW.journal_id FOR UPDATE;
          IF journal_state<>'pending'
             THEN RAISE EXCEPTION 'adc2_closed_journal'; END IF;
          RETURN NEW;
        END $$""",
        "DROP TRIGGER IF EXISTS adc2_balance_commit ON adc2_journals",
        "CREATE CONSTRAINT TRIGGER adc2_balance_commit AFTER INSERT OR UPDATE ON adc2_journals "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc2_validate_journal()",
        "DROP TRIGGER IF EXISTS adc2_journal_immutable ON adc2_journals",
        "CREATE TRIGGER adc2_journal_immutable BEFORE UPDATE OR DELETE ON adc2_journals "
        "FOR EACH ROW EXECUTE FUNCTION adc2_immutable_journal()",
        "DROP TRIGGER IF EXISTS adc2_posting_immutable ON adc2_postings",
        "CREATE TRIGGER adc2_posting_immutable BEFORE INSERT OR UPDATE OR DELETE ON adc2_postings "
        "FOR EACH ROW EXECUTE FUNCTION adc2_immutable_posting()",
    ]
    from .commercial_schema import statements as commercial_statements
    from .p1_schema import statements as p1_statements
    from .auth_schema import statements as auth_statements
    from .security_schema import statements as security_statements
    from .agent_payment_schema import statements as agent_payment_statements
    from .ad_relay_schema import statements as ad_relay_statements
    from .advertiser_platform_schema import statements as advertiser_platform_statements
    from .real_value_schema import statements as real_value_statements
    from .performance_schema import INDEXES
    from .economy_schema import statements as economy_statements

    return (
        *result,
        *commercial_statements(),
        *p1_statements(),
        *auth_statements(),
        *security_statements(),
        *agent_payment_statements(),
        *ad_relay_statements(),
        *advertiser_platform_statements(),
        *economy_statements(),
        *real_value_statements(),
        *INDEXES,
    )
