-- Restore for invalidate-wrong-execution-20261112.sql (run from the repository root with psql -f).
-- Puts back the 30 evidence expiries and the deleted eligibility rows from the CSV backup taken 11-12 08:26.
\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE r_ev (LIKE capability_evidence);
\copy r_ev FROM 'gateway-data/backups/wrong-execution-20261112/evidence.csv' CSV HEADER
UPDATE capability_evidence c SET expires = r.expires FROM r_ev r WHERE c.id = r.id;
CREATE TEMP TABLE r_el (LIKE capability_eligibility);
\copy r_el FROM 'gateway-data/backups/wrong-execution-20261112/eligibility.csv' CSV HEADER
INSERT INTO capability_eligibility SELECT * FROM r_el ON CONFLICT (resource_id) DO NOTHING;
COMMIT;
\echo restore done
