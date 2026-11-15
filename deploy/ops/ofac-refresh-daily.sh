#!/bin/bash
# OFAC SDN digital-currency address refresh for USDC payer screening, run by launchd at 06:20 KST
# (precision review R06, 11-15: it was a Claude scheduled task and stopped whenever the model's usage limit hit).
#   biz.agentconcierge.opsauto.ofac -> this script -> scripts.ad_coin_ofac_refresh (no database connection)
# One retry after 5 minutes. Every run appends one line to logs/ops/ofac-refresh.md (same format as before). When it
# fails and gateway-data/ofac/eth_addresses.txt is older than 6 days, one hand-off line goes to the status board.
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=gateway-data/ofac/eth_addresses.txt
LOG=logs/ops/ofac-refresh.md
mkdir -p logs/ops/ofac
RUN=logs/ops/ofac/run-$(date +%Y%m%d-%H%M%S).log
attempt() { nice -n 10 .venv/bin/python -m scripts.ad_coin_ofac_refresh > "$RUN.json" 2>> "$RUN"; }
attempt; rc=$?
if [ "$rc" -ne 0 ]; then sleep "${OFAC_RETRY_SECONDS:-300}"; attempt; rc=$?; fi
.venv/bin/python - "$rc" "$RUN.json" "$OUT" "$LOG" <<'PY'
import json, os, sys, time
sys.path.insert(0, 'scripts')
rc, report_path, out, log = int(sys.argv[1]), *sys.argv[2:]
try:
    report = json.loads(open(report_path).read().strip().splitlines()[-1])
except (OSError, ValueError, IndexError):
    report = {}
stamp = time.strftime('%Y-%m-%d %H:%M')
if rc == 0 and report.get('ok'):
    added, removed = report.get('added', 0), report.get('removed', 0)
    change = '변동 없음' if not (added or removed) else '변동'
    line = f"- {stamp} ok {report.get('addresses')} addresses ({change}: +{added}/-{removed})"
else:
    line = f"- {stamp} failed {str(report.get('problem') or ('exit %d' % rc))[:120]}"
with open(log, 'a', encoding='utf-8') as fh:
    fh.write(line + '\n')
print(line)
if line.split()[3] == 'failed':
    age_days = (time.time() - os.path.getmtime(out)) / 86400 if os.path.exists(out) else 999
    if age_days > 6:
        from heavy_slot import board_lock
        board = 'logs/ops/status-board.md'
        with board_lock():
            text = open(board, encoding='utf-8').read().split('\n')
            i = text.index('## 넘기는 일')
            text.insert(i + 1, f'- {stamp} OFAC 갱신(launchd) → AI AD Coin **제재 주소 목록이 {age_days:.0f}일째 갱신 실패**: '
                               f'{line[2:]} | 대기')
            open(board, 'w', encoding='utf-8').write('\n'.join(text))
PY
exit "$rc"
