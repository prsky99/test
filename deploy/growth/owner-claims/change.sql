-- Provider ownership proof and opt-out (성장·유통, 11-11, PM decision ②). No triggers, no functions,
-- nothing in public: the application checks public for exactly five triggers on every connection.
BEGIN;
CREATE SCHEMA IF NOT EXISTS agentcon_owner;
CREATE TABLE agentcon_owner.resource_owner_claims (
    host            text PRIMARY KEY CHECK (length(host) BETWEEN 3 AND 253 AND host = lower(host)),
    method          text NOT NULL CHECK (method IN ('well_known', 'dns_txt')),
    verified_at     double precision NOT NULL,
    last_checked_at double precision NOT NULL,
    hidden          boolean NOT NULL DEFAULT false,
    hidden_at       double precision,
    CHECK (hidden = (hidden_at IS NOT NULL))
);
CREATE INDEX resource_owner_claims_hidden ON agentcon_owner.resource_owner_claims (host) WHERE hidden;
COMMENT ON TABLE agentcon_owner.resource_owner_claims IS 'Hosts whose owner proved control with our token (well-known file or DNS TXT); hidden = opted out of listings. No e-mail, no password, no personal data.';
COMMIT;
