#!/bin/bash
# PostgreSQL 18.6 -> 18.7 당일 실행(11-17 05:15~05:45, PM 실행, 운영·SRE 작성 11-15).
#   bash deploy/ops/pg187-upgrade-20261117.sh --dry-run   # 확인만 하고 바꾸는 것 없음(언제든 가능)
#   bash deploy/ops/pg187-upgrade-20261117.sh             # 실행(05:10~05:50만, 현황판 배포 잠금에 PM 줄 하나만 있을 때)
# 순서: 미리 확인 -> 앱 정지 -> 우리 DB 정지 -> 세 서버 모두 정지 확인(TMS 두 개는 TMS가 멈춤)
#       -> brew upgrade postgresql@18 -> 링크 확인 -> 우리 DB 시작 -> 확인 SQL -> 앱 시작 -> 상태 확인
# 단계마다 실패하면 그 자리에서 멈추고 되돌리는 명령을 출력한다. 기다림은 sleep 길이가 아니라 실제 시각(마감 시각)으로 판단한다.
# 시험용 바꿔치기: PG_PREFIX, BREW, AGENTCON, LAUNCHCTL, PG_RUNNING, INSTALL_NOW(HH:MM), BOARD, PG_DATA, PG_SOCKET,
#                PG_PORT, PG_DB, TOKEN_FILE, WAIT_SCALE(마감 시간 배수, 시험에서 0.01)
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD
PREFIX=${PG_PREFIX:-/opt/homebrew}
BREW=${BREW:-$PREFIX/bin/brew}
AGENTCON=${AGENTCON:-$ROOT/agentcon}
LAUNCHCTL=${LAUNCHCTL:-launchctl}
BOARD=${BOARD:-$ROOT/logs/ops/status-board.md}
DATA=${PG_DATA:-$ROOT/gateway-data/postgres18/data}
SOCKET=${PG_SOCKET:-$ROOT/gateway-data/postgres18/run}
PORT=${PG_PORT:-55432}
DB=${PG_DB:-agentcon_cutover_20261020_191757}
TOKEN=${TOKEN_FILE:-/Library/Application Support/com.cloudflare.cloudflared/token}
LINKS=${PG_LINKS:-$ROOT/logs/ops/pg187-20261117/links-18.6_1.tsv}
LOG=${PG_RUN_LOG_DIR:-$ROOT/logs/ops/pg187-20261117}/run-$(date +%Y%m%d-%H%M%S).log
NOW=${INSTALL_NOW:-$(date +%H:%M)}
SCALE=${WAIT_SCALE:-1}
NEW=18.7
OLD=18.6_1
OPT=$PREFIX/opt/postgresql@18
LABEL=biz.agentconcierge.postgres18
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

say() { echo "[$(date +%H:%M:%S)] $*"; }
undo_links="bash deploy/ops/pg187-restore-links.sh"
undo_db="launchctl kickstart gui/\$(id -u)/$LABEL"
undo_app="./agentcon start"
stop_here() {   # $1 = 이유, $2... = 되돌리기 명령(순서대로)
  say "멈춤: $1"
  shift
  if [ "$#" -gt 0 ]; then
    say "되돌리기(순서대로):"
    for c in "$@"; do echo "    $c"; done
  fi
  say "기록: $LOG"
  exit 1
}
pause() { /usr/bin/perl -e 'select(undef, undef, undef, 0.5)'; }
# wait_for <초> <설명> <명령...>: 명령이 성공할 때까지, 실제 시각 기준 마감까지 기다린다
wait_for() {
  local seconds=$1 what=$2; shift 2
  local deadline
  deadline=$(/usr/bin/python3 -c "import time;print(int(time.time()+$seconds*$SCALE))")
  local next_note=$(( $(date +%s) + 30 ))
  while true; do
    "$@" && return 0
    [ "$(date +%s)" -ge "$deadline" ] && { say "  마감 지남: $what"; return 1; }
    if [ "$(date +%s)" -ge "$next_note" ]; then say "  기다리는 중: $what"; next_note=$(( $(date +%s) + 30 )); fi
    pause
  done
}
running_servers() { ${PG_RUNNING:-pgrep -lf "postgres -D"} 2>/dev/null | grep -v pgrep || true; }
none_running() { [ -z "$(running_servers)" ]; }
ours_running() { [ -f "$DATA/postmaster.pid" ]; }
ours_ready() { "$OPT/bin/pg_isready" -q -h "$SOCKET" -p "$PORT" -d "$DB"; }
q() { PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
      "$OPT/bin/psql" -h "$SOCKET" -p "$PORT" -d "$DB" -X -A -t -v ON_ERROR_STOP=1 -c "$1"; }
apps_stopped() { "$AGENTCON" status 2>/dev/null | /usr/bin/python3 -c '
import json,sys
d=json.load(sys.stdin); s=d.get("services",{})
pids=[v.get("pid") for svc in s.values() for v in (svc.get("slots") or {}).values()] + [svc.get("pid") for svc in s.values() if "slots" not in svc]
sys.exit(0 if not any(pids) and not d.get("proxy_pid") else 1)'; }
apps_active() { "$AGENTCON" status 2>/dev/null | /usr/bin/python3 -c '
import json,sys
d=json.load(sys.stdin); s=d.get("services",{}); bad=[]
for role,svc in s.items():
    if "slots" in svc:
        if not svc["slots"][svc["active"]].get("pid"): bad.append(role)
    elif "pid" in svc and not svc.get("pid"): bad.append(role)
sys.exit(0 if not bad and d.get("proxy_pid") and d.get("phase")=="stable" else 1)'; }

[ "$DRY" = 1 ] && say "== 미리 보기(--dry-run): 확인만 하고 아무것도 바꾸지 않습니다 =="
say "PostgreSQL $OLD -> $NEW, 기록 $LOG"

# 0) 미리 확인 -------------------------------------------------------------------------
fail=0
check() { if eval "$2" >/dev/null 2>&1; then say "  확인 ok: $1"; else say "  확인 실패: $1"; fail=1; fi; }
hh=${NOW%%:*}; mm=${NOW##*:}; now_m=$((10#$hh * 60 + 10#$mm))
if [ "$now_m" -lt $((5 * 60 + 10)) ] || [ "$now_m" -gt $((5 * 60 + 50)) ]; then
  say "  시각: 지금 ${NOW}는 실행 시간(05:10~05:50) 밖입니다"; [ "$DRY" = 1 ] || fail=1
else say "  확인 ok: 시각 ${NOW}"; fi
check "지금 opt 링크가 $OLD" '[ "$(readlink "$OPT")" = "../Cellar/postgresql@18/$OLD" ]'
check "$OLD 폴더 있음" '[ -x "$PREFIX/Cellar/postgresql@18/$OLD/bin/postgres" ]'
check "링크 기록 1900개 이상" '[ "$(wc -l < "$LINKS")" -ge 1900 ]'
check "18.7 bottle 내려받음" '[ -s "$(HOMEBREW_NO_AUTO_UPDATE=1 "$BREW" --cache postgresql@18)" ]'
check "pgvector 고정됨" 'HOMEBREW_NO_AUTO_UPDATE=1 "$BREW" list --pinned | grep -qx pgvector'
check "터널 token 파일이 비어 있지 않음(터널은 재시작하지 않음)" '[ -s "$TOKEN" ]'
check "복원 스크립트 미리 보기" 'bash deploy/ops/pg187-restore-links.sh --dry-run'
check "04:30 백업이 끝남(scheduled_backup·pg_dump 없음)" '! ${PG_BACKUP_RUNNING:-pgrep -f "scheduled_backup|pg_dump"} >/dev/null'
locks=$("$ROOT/.venv/bin/python" - "$BOARD" <<'EOF'
import sys
sys.path.insert(0, 'scripts')
from service_deploy import board_locks
rows = board_locks(sys.argv[1]) or []
print(','.join(sorted({team or '?' for team, _ in rows})))
EOF
)
if [ "$locks" = "PM" ]; then say "  확인 ok: 현황판 배포 잠금 = PM 한 줄"
else say "  확인 실패: 현황판 배포 잠금이 PM 한 줄이 아님(지금: ${locks:-비어 있음})"; [ "$DRY" = 1 ] || fail=1; fi
say "  지금 돌고 있는 서버:"; running_servers | sed -E 's#^#    #'
if [ "$fail" = 1 ]; then stop_here "미리 확인 실패(바뀐 것 없음)"; fi
if [ "$DRY" = 1 ]; then
  say "미리 보기 끝. 실행 순서: agentcon stop --lock-owner PM -> pg_ctl stop -> 세 서버 정지 확인 -> brew upgrade postgresql@18 -> 링크 확인 -> kickstart -> 확인 SQL -> agentcon start"
  exit 0
fi

# 1) 앱 정지 ---------------------------------------------------------------------------
say "1) 앱 정지(./agentcon stop --lock-owner PM)"
"$AGENTCON" stop --lock-owner PM >/dev/null || stop_here "agentcon stop 실패" "$undo_app"
wait_for 150 "앱 프로세스 정지" apps_stopped || stop_here "앱이 150초 안에 멈추지 않음" "$undo_app"
say "  앱 정지 확인"

# 2) 우리 DB 정지 ---------------------------------------------------------------------
say "2) 우리 DB 정지(pg_ctl -m fast)"
"$OPT/bin/pg_ctl" -D "$DATA" -m fast -w -t 120 stop || stop_here "pg_ctl stop 실패" "$undo_db" "$undo_app"
wait_for 30 "우리 DB postmaster.pid 없어짐" bash -c "! test -f '$DATA/postmaster.pid'" || stop_here "우리 DB가 멈추지 않음" "$undo_db" "$undo_app"
say "  우리 DB 정지 확인(launchd는 정상 종료를 다시 띄우지 않음)"

# 3) 세 서버 모두 정지 ------------------------------------------------------------------
say "3) TMS 운영·개발 DB 정지를 기다림(최대 10분, TMS가 멈춤)"
wait_for 600 "모든 'postgres -D' 정지" none_running || {
  running_servers | sed -E 's#^#    남은 서버: #'
  stop_here "10분 안에 세 서버가 모두 멈추지 않음(설치하지 않음)" "$undo_db" "$undo_app"; }
say "  세 서버 모두 정지 확인"

# 4) 설치 -------------------------------------------------------------------------------
say "4) brew upgrade postgresql@18(내려받아 둔 bottle, 옛 폴더 유지)"
HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1 \
  "$BREW" upgrade postgresql@18 || stop_here "brew upgrade 실패" "$undo_links" "$undo_db" "$undo_app"

# 5) 링크 확인 --------------------------------------------------------------------------
say "5) 링크 확인"
bad=""
[ "$(readlink "$OPT")" = "../Cellar/postgresql@18/$NEW" ] || bad="$bad opt"
readlink "$PREFIX/lib/postgresql@18/plpgsql.dylib" | grep -q "postgresql@18/$NEW/" || bad="$bad plpgsql"
readlink "$PREFIX/lib/postgresql@18/vector.dylib" | grep -q "pgvector/0.8.2/" || bad="$bad vector"
[ -x "$PREFIX/Cellar/postgresql@18/$OLD/bin/postgres" ] || bad="$bad old-keg-removed"
"$OPT/bin/pg_config" --version | grep -q " $NEW" || bad="$bad pg_config"
[ -z "$bad" ] || stop_here "링크가 예상과 다름:$bad" "$undo_links" "$undo_db" "$undo_app"
say "  opt->$NEW, plpgsql->$NEW, vector->pgvector 0.8.2, $OLD 폴더 남음. TMS는 이제 자기 서버를 시작해도 됩니다"

# 6) 우리 DB 시작 -----------------------------------------------------------------------
say "6) 우리 DB 시작(launchctl kickstart)"
"$LAUNCHCTL" kickstart "gui/$(id -u)/$LABEL" || stop_here "kickstart 실패" "$undo_links" "$undo_db" "$undo_app"
wait_for 180 "DB 접속 가능" ours_ready || stop_here "DB가 180초 안에 받지 않음(server.log 확인)" \
  "pg_ctl -D $DATA -m fast stop" "$undo_links" "$undo_db" "$undo_app"

# 7) 확인 SQL(읽기 전용 세션) -----------------------------------------------------------
say "7) 확인 SQL"
v=$(q "SELECT current_setting('server_version')") ; say "  server_version: $v"
e=$(q "SELECT string_agg(extname||' '||extversion, ', ' ORDER BY extname) FROM pg_extension"); say "  확장: $e"
t=$(q "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal"); say "  public 트리거: $t"
u=$(q "SELECT unaccent('Crème')"); say "  unaccent: $u"
x=$(q "SELECT '[1,2]'::vector <-> '[1,3]'::vector"); say "  vector: $x"
s=$(q "SELECT count(*) >= 0 FROM pg_stat_statements"); say "  pg_stat_statements: $s"
p=$(q "DO \$\$BEGIN PERFORM 1; END\$\$; SELECT 'ok'" 2>&1 | tail -1); say "  plpgsql: $p"
[ "${v%% *}" = "$NEW" ] && [ "$e" = "pg_stat_statements 1.12, plpgsql 1.0, unaccent 1.1, vector 0.8.2" ] && [ "$t" = 5 ] \
  && [ "$u" = "Creme" ] && [ "$x" = 1 ] && [ "$s" = t ] && [ "$p" = ok ] \
  || stop_here "확인 SQL이 기대와 다름(앱은 아직 정지 상태)" "pg_ctl -D $DATA -m fast stop" "$undo_links" "$undo_db" "$undo_app"

# 8) 앱 시작 ---------------------------------------------------------------------------
say "8) 앱 시작(./agentcon start)"
"$AGENTCON" start >/dev/null || stop_here "agentcon start 실패(DB는 18.7로 떠 있음)" "./agentcon status 확인 뒤 ./agentcon start 다시"
wait_for 300 "모든 역할 활성(phase stable)" apps_active || stop_here "앱이 300초 안에 다 올라오지 않음" "./agentcon status 확인"
"$AGENTCON" status | /usr/bin/python3 -c '
import json,sys
d=json.load(sys.stdin)
for role,svc in d.get("services",{}).items():
    slot=svc.get("active"); rel=svc["slots"][slot]["release"] if "slots" in svc else svc.get("release")
    print(f"    {role}: {rel}")'
say "끝: PostgreSQL $NEW, 앱 시작됨. 남은 일: 공개 점검(user_slo 1회), TMS 시작 확인, 현황판·PM 보고"
say "  18.7 문제 시 되돌리기: ./agentcon stop --lock-owner PM -> pg_ctl stop(세 서버 모두) -> $undo_links -> $undo_db -> $undo_app"
exit 0
