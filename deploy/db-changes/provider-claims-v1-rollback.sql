-- Rollback of provider-claims-v1.sql: removes the claims schema and everything in it (no other schema is touched).
DROP SCHEMA IF EXISTS provider_claims CASCADE;
