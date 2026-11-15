#!/bin/bash
# Watches the watch (precision review R53, 11-15): run by launchd every 5 minutes, independent of ops_auto.
# When logs/ops/watch.jsonl has not changed for 25 minutes (the 10-minute ops watch stopped), one line goes to the
# desktop alert file and to logs/ops/pm-escalations.md, at most once an hour. Reads files only; no network, no DB.
set -uo pipefail
cd "$(dirname "$0")/../.."
WATCH=${WATCH_FILE:-logs/ops/watch.jsonl}
DESKTOP=${DESKTOP_FILE:-"$HOME/Desktop/Agent Concierge 메일 알림.txt"}
STATE=logs/ops/watch-stale-state
LIMIT=${STALE_MINUTES:-25}
now=$(date +%s)
if [ -f "$WATCH" ]; then age=$(( (now - $(stat -f %m "$WATCH")) / 60 )); else age=99999; fi
[ "$age" -lt "$LIMIT" ] && { rm -f "$STATE"; exit 0; }
last=$(cat "$STATE" 2>/dev/null || echo 0)
[ $(( now - last )) -lt 3600 ] && exit 0
line="$(date '+%Y-%m-%d %H:%M') [격상 watch_stopped] 10분 감시(ops_watch) 기록이 ${age}분째 멈춤 — launchd biz.agentconcierge.opsauto.watch 확인(운영·SRE)"
{ echo "$line"; [ -f "$DESKTOP" ] && head -49 "$DESKTOP"; } > "$DESKTOP.tmp" && mv "$DESKTOP.tmp" "$DESKTOP"
mkdir -p logs/ops && echo "- $line" >> logs/ops/pm-escalations.md
echo "$now" > "$STATE"
echo "$line"
