-- Provider self-service claims v1 (docs/PROVIDER_SELF_CLAIM.md 6). Own schema, no triggers or functions.
-- Generated from agent_market/provider_self_claims.postgres_schema_statements(); tests compare the two.
-- Procedure: scripts.db_change_rehearsal run --sql this file, rollback SQL ready, user approval, check = 0.
-- Run as the application's database role, so the application owns the schema and its tables.
BEGIN;
CREATE SCHEMA IF NOT EXISTS provider_claims;
SET LOCAL search_path TO provider_claims;
CREATE TABLE IF NOT EXISTS provider_self_claims(id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, method TEXT NOT NULL, origin TEXT NOT NULL, resource_id BIGINT, scope_key TEXT NOT NULL, nonce_hash TEXT NOT NULL, status TEXT NOT NULL, revision BIGINT NOT NULL, created DOUBLE PRECISION NOT NULL, expires DOUBLE PRECISION NOT NULL, verified_at DOUBLE PRECISION, next_check DOUBLE PRECISION, fail_count BIGINT NOT NULL DEFAULT 0, last_error TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS provider_self_claims_live ON provider_self_claims(customer_id, scope_key) WHERE status IN ('pending','checking','verified');
CREATE INDEX IF NOT EXISTS provider_self_claims_origin ON provider_self_claims(origin, status);
CREATE INDEX IF NOT EXISTS provider_self_claims_due ON provider_self_claims(status, next_check);
CREATE TABLE IF NOT EXISTS provider_self_claim_checks(claim_id TEXT NOT NULL, customer_id TEXT NOT NULL, origin TEXT NOT NULL, at DOUBLE PRECISION NOT NULL, started_by TEXT NOT NULL, outcome TEXT NOT NULL, http_status BIGINT, ms BIGINT, PRIMARY KEY(claim_id, at));
CREATE INDEX IF NOT EXISTS provider_self_claim_checks_customer ON provider_self_claim_checks(customer_id, at);
CREATE INDEX IF NOT EXISTS provider_self_claim_checks_origin ON provider_self_claim_checks(origin, at);
CREATE TABLE IF NOT EXISTS provider_correction_requests(id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, customer_id TEXT NOT NULL, resource_id BIGINT NOT NULL, field TEXT NOT NULL, proposed TEXT NOT NULL, evidence_url TEXT, status TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, decided_at DOUBLE PRECISION, decided_by TEXT, decision_note TEXT);
CREATE INDEX IF NOT EXISTS provider_correction_requests_status ON provider_correction_requests(status, created);
CREATE TABLE IF NOT EXISTS provider_claim_schema(id BIGINT PRIMARY KEY, version BIGINT NOT NULL);
INSERT INTO provider_claim_schema(id,version) VALUES(1,1) ON CONFLICT(id) DO NOTHING;
COMMIT;
