-- Withdraw four test reports published 11-12 15:52 whose tool call answered but reported no useful result
-- (browser-url-ok {"ok":false} x3 on 52999/54555/54820, find_music_guides with an empty list on 289014).
-- One transaction; commits only when exactly these 4 reports (and their subject claims) are found.
-- Backup: gateway-data/backups/weak-reports-20261112/{reports,claims}.csv; restore: restore-weak-reports-20261112.sql
\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE weak ON COMMIT DROP AS
  SELECT id FROM agent_test_reports
   WHERE (id, resource_id, tool_name) IN ((21478, 289014, 'find_music_guides'), (21485, 52999, 'browser-url-ok'),
                                          (21486, 54555, 'browser-url-ok'), (21487, 54820, 'browser-url-ok'));
DO $$ BEGIN
  IF (SELECT count(*) FROM weak) <> 4 THEN RAISE EXCEPTION 'expected 4 reports, found %', (SELECT count(*) FROM weak); END IF;
END $$;
DELETE FROM test_report_subject_claims WHERE report_id IN (SELECT id FROM weak);
DELETE FROM agent_test_reports WHERE id IN (SELECT id FROM weak);
COMMIT;
\echo 'COMMIT 완료: 보고서 4건 비공개(삭제)'
