#!/bin/bash
# Run by the user (the Claude session's permission check refuses production data changes).
# Invalidates the 30 execution-evidence rows the report batch wrote at 11-12 02:31~02:34 from connection-only
# probes, and the 25 capability_eligibility rows built on them (PM 08:3x, user approval "무효화 승인").
# Commits only when exactly 30 / 25 rows change; otherwise rolls back. Restore: restore-wrong-execution-20261112.sql
set -uo pipefail
cd "$(dirname "$0")/../.."
P=(/opt/homebrew/opt/postgresql@18/bin/psql -h "$PWD/gateway-data/postgres18/run" -p 55432 -d agentcon_cutover_20261020_191757 -X -q)
B=gateway-data/backups/wrong-execution-20261112
echo "1/4 배포 잠금·백업 확인"
lock=$(awk '/^## 배포 잠금/{f=1;next} /^## /{f=0} f && NF' logs/ops/status-board.md | head -1)
[ "$lock" = "(비어 있음)" ] || { echo "    중지: 배포 잠금이 잡혀 있습니다: $lock"; exit 1; }
[ "$(($(wc -l < $B/evidence.csv) - 1))" = 30 ] && [ -s $B/eligibility.csv ] || { echo "    중지: 백업이 없습니다($B)"; exit 1; }
echo "    통과"
echo "2/4 무효화(한 트랜잭션, 근거 30 / 자격 25일 때만 COMMIT)"
OUT=$("${P[@]}" -f deploy/ops/invalidate-wrong-execution-20261112.sql 2>&1); rc=$?
echo "$OUT"
[ $rc -eq 0 ] && grep -q 'COMMIT 완료' <<<"$OUT" || { echo "    중지: 되돌렸습니다. 운영 DB는 바뀌지 않았습니다."; exit 4; }
echo "3/4 확인: public 트리거 수(5여야 함), 새 연결, 51727 자격 행"
"${P[@]}" -At -c "SELECT 'public 트리거 ' || count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname='public'"
"${P[@]}" -At -c "SELECT '새 연결 정상, 51727 자격 행 ' || count(*) FROM capability_eligibility WHERE resource_id=51727"
echo "4/4 공개 탐색 3회(결과 0건이면 안 됨)"
for q in "weather api" "translate pdf" "send email"; do
  curl -s -m 10 -H 'X-Agentcon-QA: sre_invalidate_check' "https://agentconcierge.biz/api/explore?q=${q// /%20}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('    $q:', d.get('total'))"
done
echo "끝: 문제가 있으면 psql -f deploy/ops/restore-wrong-execution-20261112.sql 로 되돌립니다."
