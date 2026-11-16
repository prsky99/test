#!/bin/bash
# Move seven launchd operations jobs from the shared working tree to gateway-data/ops-code/current (PM 11-16 source
# review 4.1; run by PM on 11-17 after the topic publication). Usage:
#   bash deploy/ops/launchd-ops-code-switch-20261117.sh check      # what would change, nothing touched
#   bash deploy/ops/launchd-ops-code-switch-20261117.sh switch     # back up, bootout (waiting), copy, bootstrap, verify
#   bash deploy/ops/launchd-ops-code-switch-20261117.sh rollback   # the backed-up plists again, same waiting
# 11-15: a bootstrap right after bootout failed (bootout returns before the job is gone; the tunnel was down 97 s),
# so every bootout waits until launchctl no longer knows the label (at most 60 s) before the bootstrap.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
ROOT=$PWD
DOMAIN="gui/$(id -u)"
AGENTS="$HOME/Library/LaunchAgents"
BACKUP="$HOME/agentcon-plist-backup-20261117"
LABELS="opensearch-sync opsauto.netpath opsauto.ofac opsauto.paidreconcile opsauto.pearltests opsauto.watch opsauto.watchstale"
MODE="${1:-check}"

say() { echo "$(date '+%H:%M:%S') $*"; }

gone() {   # wait until the label is unloaded
  local label=$1 i
  for i in $(seq 1 60); do
    launchctl print "$DOMAIN/$label" >/dev/null 2>&1 || return 0
    sleep 1
  done
  return 1
}

swap() {   # swap <label> <plist to install>
  local label=$1 plist=$2
  launchctl bootout "$DOMAIN/$label" 2>/dev/null
  if ! gone "$label"; then say "STOP $label: still loaded after 60 s, not bootstrapped"; return 1; fi
  cp "$plist" "$AGENTS/$label.plist" || return 1
  if ! launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"; then
    sleep 3
    launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist" || { say "STOP $label: bootstrap failed twice"; return 1; }
  fi
  say "ok $label: $(launchctl print "$DOMAIN/$label" 2>/dev/null | grep -m1 'working directory' | sed 's/^[[:space:]]*//')"
}

blocked_now() {   # :55-:10 measurement, 06:00-07:00 and 10:00-11:00 gate rounds, 09:05-09:30 pearl tests and reconcile
  local hm m
  hm=$((10#$(date +%H%M))); m=$((10#$(date +%M)))
  if [ "$m" -ge 55 ] || [ "$m" -lt 10 ]; then echo "measurement window (:55-:10)"; return 0; fi
  if [ "$hm" -ge 600 ] && [ "$hm" -lt 700 ]; then echo "topic gate round 1"; return 0; fi
  if [ "$hm" -ge 1000 ] && [ "$hm" -lt 1100 ]; then echo "topic gate round 2"; return 0; fi
  if [ "$hm" -ge 905 ] && [ "$hm" -lt 930 ]; then echo "pearl tests 09:12 / reconcile 09:20"; return 0; fi
  return 1
}

case "$MODE" in
  check)
    .venv/bin/python -m scripts.ops_code status | head -5
    for f in tests reports; do [ -L "gateway-data/ops-code/current/$f" ] && echo "link $f ok" || echo "MISSING link $f (install a commit with ops_code DATA_LINKS tests/reports)"; done
    for l in $LABELS; do
      new="deploy/launchd/ops-pinned/biz.agentconcierge.$l.plist"
      [ -f "$new" ] || { echo "MISSING $new"; continue; }
      echo "== $l"; diff <(plutil -convert xml1 -o - "$AGENTS/biz.agentconcierge.$l.plist") <(plutil -convert xml1 -o - "$new") | grep '^[<>]' | head -6
    done
    why=$(blocked_now) && echo "now: wait ($why)" || echo "now: allowed"
    ;;
  switch)
    if why=$(blocked_now); then say "not now: $why"; exit 75; fi
    [ -L gateway-data/ops-code/current/tests ] || { say "STOP: ops-code/current has no tests link; install the commit first"; exit 2; }
    mkdir -p "$BACKUP"
    for l in $LABELS; do cp -n "$AGENTS/biz.agentconcierge.$l.plist" "$BACKUP/" 2>/dev/null; done
    say "backup in $BACKUP: $(ls "$BACKUP" | wc -l | tr -d ' ') files"
    rc=0
    for l in $LABELS; do swap "biz.agentconcierge.$l" "deploy/launchd/ops-pinned/biz.agentconcierge.$l.plist" || { rc=1; break; }; done
    [ $rc -eq 0 ] && say "all seven switched" || say "stopped part way: run rollback"
    exit $rc
    ;;
  rollback)
    rc=0
    for l in $LABELS; do
      [ -f "$BACKUP/biz.agentconcierge.$l.plist" ] || { say "no backup for $l, skipped"; continue; }
      swap "biz.agentconcierge.$l" "$BACKUP/biz.agentconcierge.$l.plist" || rc=1
    done
    exit $rc
    ;;
  *) echo "usage: $0 check|switch|rollback"; exit 2 ;;
esac
