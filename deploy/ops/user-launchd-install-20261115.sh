#!/bin/bash
# 11-15 사용자 실행 launchd 5건을 한 번에 설치한다(운영·SRE, PM 10:0x 지시; 12:4x 시험 보고서 일괄 실행 고정 폴더 추가).
#   bash deploy/ops/user-launchd-install-20261115.sh --dry-run   # 무엇을 할지 보기만 함(바꾸는 것 없음)
#   bash deploy/ops/user-launchd-install-20261115.sh             # 설치
# 건마다: 미리 확인(파일·실행 대상) -> 이미 같은 내용으로 올라 있으면 건너뜀 -> 설치 -> 확인 출력.
# 실패하면 그 건에서 멈추고 되돌리는 명령을 출력한다. 앞 건은 이미 끝난 상태로 남는다.
# 시험용 바꿔치기: LAUNCHCTL, LAUNCH_AGENTS, INSTALL_NOW(HH:MM), INSTALL_UID, INSTALL_WAIT_SECONDS, INSTALL_BACKUP_DIR
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD
LAUNCHCTL=${LAUNCHCTL:-launchctl}
AGENTS=${LAUNCH_AGENTS:-$HOME/Library/LaunchAgents}
UID_=${INSTALL_UID:-$(id -u)}
WAIT=${INSTALL_WAIT_SECONDS:-30}
NOW=${INSTALL_NOW:-$(date +%H:%M)}
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=${INSTALL_BACKUP_DIR:-$ROOT/logs/ops/launchd-backup/$STAMP}
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

# 이름|저장소 plist|종류(new=새로 설치, replace=설치된 것을 교체)|실행 전에 있어야 하는 파일
ITEMS=(
  "biz.agentconcierge.opsauto.ofac|deploy/launchd/ops/biz.agentconcierge.opsauto.ofac.plist|new|deploy/ops/ofac-refresh-daily.sh"
  "biz.agentconcierge.opsauto.watchstale|deploy/launchd/ops/biz.agentconcierge.opsauto.watchstale.plist|new|deploy/ops/watch-stale-check.sh"
  "biz.agentconcierge.opsauto.housead|deploy/launchd/ops-pinned/biz.agentconcierge.opsauto.housead.plist|replace|gateway-data/ops-code/current/deploy/ops/house-ad-daily.sh"
  "biz.agentconcierge.backup|deploy/launchd/ops-pinned/biz.agentconcierge.backup.plist|replace|gateway-data/ops-code/current/scripts/scheduled_backup.py"
  "biz.agentconcierge.opsauto.testreports|deploy/launchd/ops-pinned/biz.agentconcierge.opsauto.testreports.plist|replace|gateway-data/ops-code/current/scripts/batch_report_runner.py"
  "biz.agentconcierge.opsauto.paidreconcile|deploy/launchd/ops/biz.agentconcierge.opsauto.paidreconcile.plist|new|deploy/ops/payment-reconcile-daily.sh"
)

say() { echo "$*"; }
loaded() { "$LAUNCHCTL" print "gui/$UID_/$1" >/dev/null 2>&1; }

# 피할 시각: 매시 :55~:10(감시·배포), 04:20~04:40(백업 04:30), 09:00~09:25(광고 원장 09:10, 결제 대조 09:20)
hh=${NOW%%:*}; mm=${NOW##*:}; hh=$((10#$hh)); mm=$((10#$mm)); now_m=$((hh * 60 + mm))
busy=""
if [ "$mm" -ge 55 ] || [ "$mm" -lt 10 ]; then busy="매시 :55~:10"; fi
if [ "$now_m" -ge $((4 * 60 + 20)) ] && [ "$now_m" -lt $((4 * 60 + 40)) ]; then busy="04:30 백업 앞뒤"; fi
if [ "$now_m" -ge $((9 * 60)) ] && [ "$now_m" -lt $((9 * 60 + 25)) ]; then busy="09:10 광고 원장·09:20 결제 대조 앞뒤"; fi
if [ -n "$busy" ]; then
  say "지금(${NOW})은 피하는 시간입니다: ${busy}. :10~:50 사이(04:20~04:40, 09:00~09:25 제외)에 다시 실행해 주세요."
  [ "$DRY" = 1 ] || exit 3
  say "(--dry-run이라 계속 보여 줍니다)"
fi
[ "$DRY" = 1 ] && say "== 미리 보기(--dry-run): 아무것도 바꾸지 않습니다 =="

n=0
for item in "${ITEMS[@]}"; do
  IFS='|' read -r label src kind needs <<< "$item"
  n=$((n + 1))
  dest=$AGENTS/$label.plist
  say ""
  say "[$n/${#ITEMS[@]}] $label ($kind)"
  # 1) 미리 확인
  if [ ! -f "$src" ]; then say "  멈춤: 저장소 파일이 없습니다: $src"; exit 1; fi
  if ! plutil -lint "$src" >/dev/null 2>&1; then say "  멈춤: plist 형식 오류: $src"; exit 1; fi
  if [ ! -e "$needs" ]; then say "  멈춤: 실행 대상이 없습니다: $needs"; exit 1; fi
  if [ "$kind" = replace ] && [ ! -f "$dest" ]; then
    say "  멈춤: 교체할 설치본이 없습니다: $dest (교체 대상인데 설치돼 있지 않음, 운영·SRE에 알려 주세요)"; exit 1
  fi
  if [ -f "$dest" ] && cmp -s "$src" "$dest" && loaded "$label"; then
    say "  건너뜀: 같은 내용으로 이미 올라 있습니다"; continue
  fi
  if [ "$DRY" = 1 ]; then
    [ -f "$dest" ] && say "  할 일: 설치본을 ${BACKUP}에 보관 -> 내리기 -> 교체 -> 올리기" \
                   || say "  할 일: $dest 로 복사 -> 올리기"
    continue
  fi
  # 2) 설치
  undo="launchctl bootout gui/\$(id -u)/$label; rm -f $dest"
  if [ -f "$dest" ]; then
    mkdir -p "$BACKUP" && cp -p "$dest" "$BACKUP/" || { say "  멈춤: 설치본 보관 실패"; exit 1; }
    undo="launchctl bootout gui/\$(id -u)/$label; cp $BACKUP/$label.plist $dest; launchctl bootstrap gui/\$(id -u) $dest"
    if loaded "$label"; then
      "$LAUNCHCTL" bootout "gui/$UID_/$label" 2>/dev/null || true
      for _ in $(seq 1 "$WAIT"); do loaded "$label" || break; sleep 1; done
      if loaded "$label"; then say "  멈춤: 기존 작업이 ${WAIT}초 안에 내려가지 않았습니다(바뀐 것 없음, 설치본 그대로)"; exit 1; fi
    fi
  fi
  if ! cp "$src" "$dest"; then say "  멈춤: 복사 실패"; say "  되돌리기: $undo"; exit 1; fi
  if ! "$LAUNCHCTL" bootstrap "gui/$UID_" "$dest"; then
    sleep 5
    if ! "$LAUNCHCTL" bootstrap "gui/$UID_" "$dest"; then
      say "  멈춤: 올리기(bootstrap) 실패"; say "  되돌리기: $undo"; exit 1
    fi
  fi
  # 3) 확인 출력
  if ! loaded "$label"; then say "  멈춤: 올린 뒤 목록에 없습니다"; say "  되돌리기: $undo"; exit 1; fi
  "$LAUNCHCTL" print "gui/$UID_/$label" 2>/dev/null | grep -E "^\s*(state|path|program) =" | sed 's/^/  /'
  say "  끝: $label"
  say "  되돌리기(필요할 때만): $undo"
done

say ""
if [ "$DRY" = 1 ]; then
  say "미리 보기 끝. 설치하려면 --dry-run 없이 다시 실행해 주세요."
else
  say "모두 끝났습니다(${n}건 확인). 남은 일: Claude 앱 예약 작업 두 개 끄기"
  say "  - agentconcierge-ofac-daily-refresh (OFAC은 이제 launchd가 06:20에 함)"
  say "  - agentconcierge-daily-test-reports (launchd testreports가 02:30에 같은 일을 함)"
  [ -d "$BACKUP" ] && say "교체 전 설치본 보관: $BACKUP"
fi
exit 0
