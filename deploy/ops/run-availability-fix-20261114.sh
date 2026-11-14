#!/bin/bash
# Correction of the public availability rows the brand change marked as failures (PM 11-14 09:0x; run by the user
# after approval). After the 05:27 brand deploy /status.json answered service "AgentValCon"; the minute check accepted
# only "Agent Concierge", so every check from 05:28:15 to 09:14:17 KST was stored ok=0 although the page answered 200.
# The fix b2633065 (jobs avail-jobs-20261114-r1, 09:15:38) accepts both names.
#
# What it changes: public_availability_checks rows with checked_at in [05:28:00, 09:15:38) KST AND status_code=200
# AND ok=0 -> ok=1. Nothing else (a real failure has another status code or none; there were 0 in this window).
# Evidence: in the 30 days before 05:27 there was not one row with status_code=200 and ok=0.
#
#   bash deploy/ops/run-availability-fix-20261114.sh            # dry run: counts and the backup CSV only (read-only)
#   bash deploy/ops/run-availability-fix-20261114.sh --apply    # backup CSV, then the update in one transaction
#   bash deploy/ops/run-availability-fix-20261114.sh --rollback # put ok=0 back on exactly the rows in the backup CSV
set -uo pipefail
cd "$(dirname "$0")/../.."
# FIX_PG_HOST/FIX_PG_PORT/FIX_PG_DB only for the rehearsal on a throwaway cluster; the defaults are production.
PSQL=(/opt/homebrew/opt/postgresql@18/bin/psql -h "${FIX_PG_HOST:-$PWD/gateway-data/postgres18/run}" -p "${FIX_PG_PORT:-55432}" -d "${FIX_PG_DB:-agentcon_cutover_20261020_191757}" -v ON_ERROR_STOP=1 -At)
START="extract(epoch from timestamptz '2026-11-14 05:28:00+09')"
END="extract(epoch from timestamptz '2026-11-14 09:15:38+09')"
WHERE="checked_at >= $START AND checked_at < $END AND status_code = 200 AND ok = 0"
EXPECTED=224
BACKUP=${FIX_BACKUP:-gateway-data/backups/availability-fix-20261114.csv}
LOG=${FIX_LOG:-logs/ops/availability-fix-20261114.log}
exec > >(tee -a "$LOG") 2>&1
mode=${1:-dry-run}
date "+시작 %F %T ($mode)"

n=$("${PSQL[@]}" -c "SET default_transaction_read_only=on; SELECT count(*) FROM public_availability_checks WHERE $WHERE" | tail -1)
other=$("${PSQL[@]}" -c "SET default_transaction_read_only=on; SELECT count(*) FROM public_availability_checks WHERE checked_at >= $START AND checked_at < $END AND ok = 0 AND status_code IS DISTINCT FROM 200" | tail -1)
echo "대상(200인데 ok=0): $n건 (예상 $EXPECTED), 같은 구간의 실제 실패(200 아님): $other건(그대로 둠)"

if [ "$mode" = "--rollback" ]; then
  [ -s "$BACKUP" ] || { echo "중지: 백업 $BACKUP 이 없습니다"; exit 1; }
  rows=$(wc -l < "$BACKUP" | tr -d ' ')
  echo "되돌리기: 백업의 $rows건을 ok=0으로 되돌립니다"
  "${PSQL[@]}" <<SQL
BEGIN;
CREATE TEMP TABLE fix_backup (checked_at double precision, ok bigint, status_code bigint, latency_ms double precision) ON COMMIT DROP;
\copy fix_backup FROM '$BACKUP' WITH (FORMAT csv)
UPDATE public_availability_checks p SET ok = 0 FROM fix_backup b WHERE p.checked_at = b.checked_at AND p.ok = 1 AND p.status_code = 200;
COMMIT;
SQL
  echo "되돌리기 끝 (종료 코드 $?)"; exit 0
fi

if [ "$n" != "$EXPECTED" ]; then echo "중지: 대상 수가 예상($EXPECTED)과 다릅니다: $n"; exit 1; fi
mkdir -p gateway-data/backups
"${PSQL[@]}" -c "\\copy (SELECT checked_at, ok, status_code, latency_ms FROM public_availability_checks WHERE $WHERE ORDER BY checked_at) TO '$BACKUP' WITH (FORMAT csv)"
echo "백업: $BACKUP ($(wc -l < "$BACKUP" | tr -d ' ')행)"
[ "$mode" = "--apply" ] || { echo "dry run 끝: 바꾼 것 없음. 실행하려면 --apply"; exit 0; }

"${PSQL[@]}" <<SQL
BEGIN;
DO \$\$
DECLARE changed integer;
BEGIN
  UPDATE public_availability_checks SET ok = 1 WHERE $WHERE;
  GET DIAGNOSTICS changed = ROW_COUNT;
  IF changed <> $EXPECTED THEN RAISE EXCEPTION 'expected $EXPECTED rows, changed %', changed; END IF;
END
\$\$;
COMMIT;
SQL
rc=$?
echo "정정 끝 (종료 코드 $rc)"
"${PSQL[@]}" -c "SET default_transaction_read_only=on; SELECT 'after: 200인데 ok=0 남은 행 '||count(*) FROM public_availability_checks WHERE $WHERE" | tail -1
echo "되돌리기: bash deploy/ops/run-availability-fix-20261114.sh --rollback"
