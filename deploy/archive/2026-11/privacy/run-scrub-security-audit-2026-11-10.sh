#!/bin/bash
# Run by the user (the Claude session's permission check refuses production data changes).
# 11-11 rewrite (운영·SRE): the check result is shown instead of discarded, a fresh backup of the two
# tables is written right before the change, and the change commits only when no unreduced address is
# left; otherwise it rolls back. SQL: deploy/privacy/scrub-security-audit-2026-11-10.sql.
set -uo pipefail
cd "$(dirname "$0")/../.."
SQL="$PWD/deploy/privacy/scrub-security-audit-2026-11-10.sql"
BIN=/opt/homebrew/opt/postgresql@18/bin
DB=(-h "$PWD/gateway-data/postgres18/run" -p 55432 -d agentcon_cutover_20261020_191757)

echo "1/4 리허설 확인 (사본에서 24시간 안에, 지금 운영 중인 버전으로 통과했는지)"
if ! out=$(.venv/bin/python -m scripts.db_change_rehearsal check --sql "$SQL" 2>&1); then
  echo "    중지: 리허설 확인 실패 -> $out"
  echo "    운영 DB는 바뀌지 않았습니다. 운영·SRE에 리허설을 다시 요청하세요."
  exit 1
fi
echo "    통과: $out"

STAMP=$(date +%Y%m%d-%H%M%S)
DIR="gateway-data/backups/privacy-scrub-$STAMP"
echo "2/4 백업: $DIR/security-audit-before.dump"
(umask 077 && mkdir -p "$DIR") || { echo "    중지: 백업 폴더를 만들 수 없습니다"; exit 1; }
if ! (umask 077 && "$BIN/pg_dump" "${DB[@]}" -Fc -t security_events -t admin_audit_logs -f "$DIR/security-audit-before.dump"); then
  echo "    중지: 백업 실패. 운영 DB는 바뀌지 않았습니다."
  exit 1
fi
echo "    백업 크기: $(wc -c < "$DIR/security-audit-before.dump") bytes"

echo "3/4 정리 실행 (한 트랜잭션, 남은 주소가 0일 때만 COMMIT)"
RESULT=$("$BIN/psql" "${DB[@]}" -X -q -v ON_ERROR_STOP=1 2>&1 <<EOF
\\pset footer off
BEGIN;
SELECT count(*) FILTER (WHERE ip !~ '/(24|48)\$' AND ip <> 'unknown') AS se_before FROM security_events \\gset
SELECT count(*) FILTER (WHERE ip IS NOT NULL AND ip !~ '/(24|48)\$') AS al_before FROM admin_audit_logs \\gset
\\echo '    전: security_events 축약 안 된 행' :se_before '/ admin_audit_logs' :al_before
\\i $SQL
SELECT count(*) FILTER (WHERE ip !~ '/(24|48)\$' AND ip <> 'unknown') AS se_after FROM security_events \\gset
SELECT count(*) FILTER (WHERE ip IS NOT NULL AND ip !~ '/(24|48)\$') AS al_after FROM admin_audit_logs \\gset
\\echo '    후: security_events 축약 안 된 행' :se_after '/ admin_audit_logs' :al_after
SELECT (:se_after = 0 AND :al_after = 0) AS clean \\gset
\\if :clean
COMMIT;
\\echo '    COMMIT 완료'
\\else
ROLLBACK;
\\echo '    ROLLBACK: 남은 행이 있어 되돌렸습니다(운영 DB 변화 없음)'
\\endif
EOF
)
rc=$?
echo "$RESULT"
if [ $rc -ne 0 ]; then
  echo "    중지: SQL 오류(종료 코드 $rc). 트랜잭션은 되돌려졌습니다. 운영 DB는 바뀌지 않았습니다."
  exit $rc
fi
if ! grep -q 'COMMIT 완료' <<<"$RESULT"; then
  echo "4/4 실패: 되돌렸습니다. 운영 DB는 바뀌지 않았습니다. 위 출력을 운영·SRE에 전달하세요."
  exit 4
fi
echo "4/4 끝: 정상 완료('후' 줄이 0 / 0)."
