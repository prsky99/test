#!/bin/bash
# Daily house ad booking (AI AD Coin, user approval 11-12 via PM): run by launchd at 09:10 KST.
#   biz.agentconcierge.opsauto.housead -> this script -> scripts.ad_coin_house_ad daily
# HOUSE_AD_DRY=1 runs the same thing with --check (reads only, writes nothing to the ledger).
# The switch is gateway-data/house-ad.env (AD_COIN_HOUSE_AD_DAILY=1); without it the run records the plan only.
# Exit 1 from the script is a stop alert (budget under 7 days, ledger off, not exactly one house campaign):
# it goes to the status board for AI AD Coin and to the run log.
set -uo pipefail
cd "$(dirname "$0")/../.."
LOG_DIR=logs/ops/house-ad
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"
value() { grep -E "^$1=" gateway-data/agentcon.env | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
DSN=$(value APPLICATION_POSTGRES_DSN_FILE); KEY=$(value APPLICATION_WORKFLOW_KEY_FILE); KEYDIR=$(value AD_COIN_V2_KEY_DIR)
if [ -z "$DSN" ] || [ -z "$KEY" ] || [ -z "$KEYDIR" ]; then
  echo "$(date '+%F %T') stop: agentcon.env has no DSN, key or key dir path" >> "$LOG"; rc=2
else
  MODE=--i-have-approval; [ "${HOUSE_AD_DRY:-0}" = 1 ] && MODE=--check
  # PG* variables from a login shell must not redirect the connection (AI AD Coin request).
  env -u PGHOST -u PGPORT -u PGDATABASE -u PGUSER -u PGPASSWORD -u PGSERVICE \
    nice -n 10 .venv/bin/python -m scripts.ad_coin_house_ad daily \
      --dsn-file "$DSN" --key-file "$KEY" --key-dir "$KEYDIR" "$MODE" >> "$LOG" 2>&1
  rc=$?
fi
echo "$(date '+%F %T') exit $rc" >> "$LOG"
if [ "$rc" -ne 0 ]; then
  gateway-data/ops-llm-venv/bin/python - "$rc" "$LOG" <<'PY' >> "$LOG" 2>&1
import sys
sys.path.insert(0, 'scripts')
import ops_auto
ops_auto.TEAM['house_ad'] = 'AI AD Coin'
code, log = sys.argv[1], sys.argv[2]
reason = '멈춤 경보(예산 7일치 미만·원장 이상·자사 캠페인 1개 아님)' if code == '1' else '실행 실패'
ops_auto.board_handoff('house_ad', f'자사 광고 매일 예약 {reason}, 종료 코드 {code}, 로그 {log}')
PY
fi
exit "$rc"
