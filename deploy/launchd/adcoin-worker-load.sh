#!/bin/bash
# Replace the loaded AD Coin worker daemon job with a plist (called by install-adcoin-worker.sh; PM 11-15 09:5x).
# Usage: adcoin-worker-load.sh <label> <plist>      (RERUN = the command to tell the user to run again)
# 11-15 09:49: the daemon stopped cleanly in 3 s, but launchd kept listing the label past the old 30 s wait (the job
# has ExitTimeOut 60), so the script ended with the daemon down and only "not installing" printed. Now it waits
# longer than ExitTimeOut, asks launchd again every 30 s, retries the bootstrap, and whenever it gives up says
# plainly that the daemon is down and how to run again, with its own exit code:
#   0 running   3 the old job never finished unloading   4 bootstrap kept failing   5 not running after bootstrap
# 11-15 11:28 (PM): in a session where `sleep` returned at once, the 120-poll wait passed in 3 s and the script said
# the daemon was down. Every wait is now measured on the wall clock (date +%s), so an early-returning sleep only
# makes the loop poll more often, never shortens the wait.
set -uo pipefail
L=${1:?label}; P=${2:?plist}
LAUNCHCTL=${LAUNCHCTL:-launchctl}   # replaceable for tests
WAIT=${INSTALL_WAIT_SECONDS:-120}; SETTLE=${INSTALL_SETTLE_SECONDS:-15}; RETRY=${INSTALL_RETRY_SECONDS:-5}
POLL=${INSTALL_POLL_SECONDS:-1}; REBOOTOUT=${INSTALL_REBOOTOUT_SECONDS:-30}
SLEEP=${INSTALL_SLEEP:-sleep}      # replaceable for tests (an instant sleep reproduces 11:28)
TRIES=${INSTALL_BOOTSTRAP_TRIES:-3}; RERUN=${RERUN:-the same install command}
DOMAIN="gui/$(id -u)"
listed() { "$LAUNCHCTL" list | grep -q "[[:space:]]$L\$"; }
# 11-19 (unattended reinstall, PM 00:37): "listed" is enough to wait for an unload, but a job listed with no PID
# (launchd relaunching a daemon that keeps exiting) is not running; the final check needs a PID
running() { "$LAUNCHCTL" list | awk -v l="$L" '$3 == l && $1 ~ /^[0-9]+$/ {found = 1} END {exit !found}'; }
now() { date +%s; }
pause() {   # wait $1 seconds of wall-clock time, even if sleep comes back early
  [ "$1" -gt 0 ] || return 0
  local end=$(( $(now) + $1 ))
  "$SLEEP" "$1" 2>/dev/null || true
  while [ "$(now)" -le "$end" ]; do "$SLEEP" 1 2>/dev/null || true; done   # -le: at least $1 whole seconds
}
down() {
  echo "!! 데몬이 지금 꺼져 있습니다 (the AD Coin worker daemon is NOT running now)."
  echo "!! 1분 뒤 같은 명령을 다시 실행하세요: $RERUN"
}
"$LAUNCHCTL" bootout "$DOMAIN/$L" 2>/dev/null || true
start=$(now); again=$((start + REBOOTOUT))
while listed; do
  t=$(now)
  if [ "$t" -gt $((start + WAIT)) ]; then break; fi   # date +%s counts whole seconds: -gt guarantees a full WAIT
  if [ "$t" -ge "$again" ]; then "$LAUNCHCTL" bootout "$DOMAIN/$L" 2>/dev/null || true; again=$((t + REBOOTOUT)); fi
  pause "$POLL"
done
if listed; then
  echo "previous $L is still loaded after $(( $(now) - start ))s (limit ${WAIT}s)"; down; exit 3
fi
tries=1
until "$LAUNCHCTL" bootstrap "$DOMAIN" "$P"; do
  if [ "$tries" -ge "$TRIES" ]; then echo "bootstrap failed ${TRIES} times"; down; exit 4; fi
  echo "bootstrap failed; trying again in ${RETRY}s"; pause "$RETRY"; tries=$((tries + 1))
done
pause "$SETTLE"
if ! running; then echo "$L is not running after the bootstrap (no PID)"; down; exit 5; fi
exit 0
