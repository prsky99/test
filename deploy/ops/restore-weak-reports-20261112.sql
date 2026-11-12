-- Restore the four withdrawn reports from the backup taken before withdraw-weak-reports-20261112.sql.
-- The application_report_creation trigger admits a report only while its subject claim is reserved
-- (report_id NULL), so: reserve the claims, insert the reports, then bind the claims to them.
\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE claims_backup (subject_key text, report_id bigint) ON COMMIT DROP;
\copy claims_backup FROM 'gateway-data/backups/weak-reports-20261112/claims.csv' CSV HEADER
INSERT INTO test_report_subject_claims(subject_key, report_id) SELECT subject_key, NULL FROM claims_backup;
\copy agent_test_reports FROM 'gateway-data/backups/weak-reports-20261112/reports.csv' CSV HEADER
UPDATE test_report_subject_claims c SET report_id = b.report_id FROM claims_backup b WHERE c.subject_key = b.subject_key;
DO $$ BEGIN
  IF (SELECT count(*) FROM agent_test_reports WHERE id IN (21478,21485,21486,21487)) <> 4 THEN
    RAISE EXCEPTION 'restore incomplete';
  END IF;
END $$;
COMMIT;
\echo 'COMMIT 완료: 보고서 4건 복구'
