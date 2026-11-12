#!/bin/bash
# Rehearsal of the weak-report withdrawal on a disposable copy (PM 11-12): withdraw -> restore -> withdraw again.
# Run only through scripts.db_change_rehearsal, which passes the copy's socket and port:
#   .venv/bin/python -m scripts.db_change_rehearsal run --data full \
#     --command "bash deploy/ops/rehearse-weak-reports-20261112.sh {socket} {port}"
# Every psql call goes to the copy given on the command line; nothing here names the production database.
set -euo pipefail
SOCKET=$1; PORT=$2
cd "$(dirname "$0")/../.."
P=(/opt/homebrew/opt/postgresql@18/bin/psql -h "$SOCKET" -p "$PORT" -U postgres -d postgres -X -q -At)
IDS='21478,21485,21486,21487'
count() { "${P[@]}" -c "SELECT count(*) FROM agent_test_reports WHERE id IN ($IDS)"; }
bound() { "${P[@]}" -c "SELECT count(*) FROM test_report_subject_claims WHERE report_id IN ($IDS)"; }
triggers() { "${P[@]}" -c "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname='public'"; }
digest() { "${P[@]}" -c "SELECT md5(string_agg(r::text, '|' ORDER BY r.id)) FROM (SELECT id,resource_id,slug,kind,agent_name,eval_grade,is_success,test_method,tool_name,executed_at,execution_finished_at,connection_version_id,evidence_scope,creation_subject_key,content_md FROM agent_test_reports WHERE id IN ($IDS)) r"; }
claims_digest() { "${P[@]}" -c "SELECT md5(string_agg(subject_key||':'||coalesce(report_id::text,'-'), '|' ORDER BY subject_key)) FROM test_report_subject_claims WHERE subject_key IN (SELECT creation_subject_key FROM agent_test_reports WHERE id IN ($IDS))"; }

fail() { echo "REHEARSAL FAILED: $*"; exit 1; }
echo "0 before: reports=$(count) claims=$(bound) triggers=$(triggers)"
[ "$(count)" = 4 ] || fail "the copy does not hold the 4 reports (backup older than 11-12 15:52?)"
before=$(digest); before_claims=$(claims_digest); t0=$(triggers)

"${P[@]}" -f deploy/ops/withdraw-weak-reports-20261112.sql >/dev/null || fail "withdraw 1"
echo "1 withdraw: reports=$(count) claims=$(bound) triggers=$(triggers)"
[ "$(count)" = 0 ] && [ "$(bound)" = 0 ] && [ "$(triggers)" = "$t0" ] || fail "after withdraw 1"

"${P[@]}" -f deploy/ops/restore-weak-reports-20261112.sql >/dev/null || fail "restore"
echo "2 restore: reports=$(count) claims=$(bound) triggers=$(triggers)"
[ "$(count)" = 4 ] && [ "$(bound)" = 4 ] && [ "$(triggers)" = "$t0" ] || fail "after restore"
after=$(digest); after_claims=$(claims_digest)
if [ "$after" = "$before" ] && [ "$after_claims" = "$before_claims" ]; then
  echo "2 restore: rows and claims identical to the copy before the withdrawal"
else
  echo "2 restore: content differs from the copy (the backup CSV was taken 11-12 16:4x; rows changed since?)"
  echo "   before=$before after=$after claims_before=$before_claims claims_after=$after_claims"
fi

"${P[@]}" -f deploy/ops/withdraw-weak-reports-20261112.sql >/dev/null || fail "withdraw 2"
echo "3 withdraw again: reports=$(count) claims=$(bound) triggers=$(triggers)"
[ "$(count)" = 0 ] && [ "$(bound)" = 0 ] && [ "$(triggers)" = "$t0" ] || fail "after withdraw 2"
echo "REHEARSAL PASSED (public triggers $t0)"
