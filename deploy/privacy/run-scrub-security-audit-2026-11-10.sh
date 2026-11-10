#!/bin/bash
# Run by the user (the Claude session's permission check refuses production data changes).
# Prepared 11-10 by 운영·SRE: backup gateway-data/backups/privacy-scrub-20261110/security-audit-before.dump,
# rehearsal passed (logs/ops/db-rehearsal/scrub-security-audit-2026-11-10.json).
set -euo pipefail
cd "$(dirname "$0")/../.."
.venv/bin/python -m scripts.db_change_rehearsal check --sql deploy/privacy/scrub-security-audit-2026-11-10.sql >/dev/null
P=(/opt/homebrew/opt/postgresql@18/bin/psql -h "$PWD/gateway-data/postgres18/run" -p 55432 -d agentcon_cutover_20261020_191757 -v ON_ERROR_STOP=1 -At)
Q="select 'security_events', count(*), count(*) filter (where ip !~ '/(24|48)\$' and ip <> 'unknown') from security_events union all select 'admin_audit_logs', count(*), count(*) filter (where ip is not null and ip !~ '/(24|48)\$') from admin_audit_logs;"
{ echo "BEGIN;"; echo "$Q"; cat deploy/privacy/scrub-security-audit-2026-11-10.sql; echo "$Q"; echo "COMMIT;"; } | "${P[@]}" -f - | grep -vE '^(UPDATE|BEGIN|COMMIT)'
echo "done: the second pair of lines must show 0 unreduced addresses"
