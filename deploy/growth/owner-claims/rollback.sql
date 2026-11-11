-- Undo change.sql. Removes only the ownership schema; no public object is touched.
-- If owners have already verified, this drops their verification records (ask before running once data exists).
BEGIN;
DROP TABLE IF EXISTS agentcon_owner.resource_owner_claims;
DROP SCHEMA IF EXISTS agentcon_owner;
COMMIT;
