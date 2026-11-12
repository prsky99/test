#!/bin/bash
# Run by the user (the Claude session's permission check refuses production data changes).
# Withdraws 4 weak test reports published 11-12 15:52 (PM 11-12 16:2x: tool answered but reported no useful
# result). Commits only when exactly those 4 are found. Restore: restore-weak-reports-20261112.sql
set -uo pipefail
cd "$(dirname "$0")/../.."
P=(/opt/homebrew/opt/postgresql@18/bin/psql -h "$PWD/gateway-data/postgres18/run" -p 55432 -d agentcon_cutover_20261020_191757 -X -q)
B=gateway-data/backups/weak-reports-20261112
echo "1/3 배포 잠금·백업 확인"
lock=$(awk '/^## 배포 잠금/{f=1;next} /^## /{f=0} f && NF' logs/ops/status-board.md | head -1)
[ "$lock" = "(비어 있음)" ] || { echo "    중지: 배포 잠금이 잡혀 있습니다: $lock"; exit 1; }
[ -s $B/reports.csv ] && [ "$(($(wc -l < $B/claims.csv) - 1))" = 4 ] || { echo "    중지: 백업이 없습니다($B)"; exit 1; }
echo "    통과"
echo "2/3 비공개 처리(한 트랜잭션, 정확히 4건일 때만 COMMIT)"
OUT=$("${P[@]}" -f deploy/ops/withdraw-weak-reports-20261112.sql 2>&1); rc=$?
echo "$OUT"
[ $rc -eq 0 ] && grep -q 'COMMIT 완료' <<<"$OUT" || { echo "    중지: 되돌렸습니다. 운영 DB는 바뀌지 않았습니다."; exit 4; }
echo "3/3 확인: 남은 보고서(0이어야 함), public 트리거 수(5여야 함)"
"${P[@]}" -At -c "SELECT '남은 보고서 ' || count(*) FROM agent_test_reports WHERE id IN (21478,21485,21486,21487)"
"${P[@]}" -At -c "SELECT 'public 트리거 ' || count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname='public'"
echo "끝: 되돌리려면 psql -f deploy/ops/restore-weak-reports-20261112.sql"
