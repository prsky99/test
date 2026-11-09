-- 11-10 draft (NOT run on production; needs user approval as a data deletion).
-- Removes visitor personal data kept before the no-collection change. Rows stay; only the
-- personal columns are cleared, so counts and audit trails remain. Rehearse first:
--   .venv/bin/python -m scripts.db_change_rehearsal run --command "/opt/homebrew/opt/postgresql@18/bin/psql -v ON_ERROR_STOP=1 -1 -f deploy/privacy/scrub-visitor-personal-data-2026-11-10.sql"

-- counts before (rows that still hold a value)
SELECT 'customer_inquiries' AS t, COUNT(*) FILTER (WHERE name<>'' OR email<>'' OR ip IS NOT NULL OR user_agent IS NOT NULL) AS rows_with_personal_data, COUNT(*) AS rows FROM customer_inquiries
UNION ALL SELECT 'privacy_requests', COUNT(*) FILTER (WHERE email IS NOT NULL OR ip IS NOT NULL OR user_agent IS NOT NULL), COUNT(*) FROM privacy_requests
UNION ALL SELECT 'cancellation_requests', COUNT(*) FILTER (WHERE ip IS NOT NULL OR user_agent IS NOT NULL), COUNT(*) FROM cancellation_requests
UNION ALL SELECT 'needs.ip', COUNT(*) FILTER (WHERE ip IS NOT NULL), COUNT(*) FROM needs
UNION ALL SELECT 'agent_visitors', COUNT(*) FILTER (WHERE name IS NOT NULL OR user_agent IS NOT NULL OR fingerprint IS NOT NULL), COUNT(*) FROM agent_visitors
UNION ALL SELECT 'agent_hits.user_agent', COUNT(*) FILTER (WHERE user_agent IS NOT NULL), COUNT(*) FROM agent_hits
UNION ALL SELECT 'agent_contexts.fingerprint', COUNT(*) FILTER (WHERE fingerprint IS NOT NULL), COUNT(*) FROM agent_contexts;

UPDATE customer_inquiries SET name='', email='', ip=NULL, user_agent=NULL WHERE name<>'' OR email<>'' OR ip IS NOT NULL OR user_agent IS NOT NULL;
UPDATE privacy_requests SET email=NULL, ip=NULL, user_agent=NULL WHERE email IS NOT NULL OR ip IS NOT NULL OR user_agent IS NOT NULL;
UPDATE cancellation_requests SET ip=NULL, user_agent=NULL WHERE ip IS NOT NULL OR user_agent IS NOT NULL;
UPDATE needs SET ip=NULL WHERE ip IS NOT NULL;
UPDATE agent_visitors SET name=NULL, user_agent=NULL, fingerprint=NULL WHERE name IS NOT NULL OR user_agent IS NOT NULL OR fingerprint IS NOT NULL;
UPDATE agent_hits SET user_agent=NULL WHERE user_agent IS NOT NULL;
-- agent_hits.fingerprint (primary key) and agent_contexts.fingerprint hold the old unsalted IP+UA hash;
-- deleting agent_hits rows and clearing agent_contexts.fingerprint removes it (counters restart, old
-- contexts then need the visitor token).
DELETE FROM agent_hits;
UPDATE agent_contexts SET fingerprint=NULL WHERE fingerprint IS NOT NULL;
