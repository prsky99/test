#!/bin/bash
# Replace the loaded AD Coin worker daemon job with a plist (called by install-adcoin-worker.sh; PM 11-15 09:5x).
# Usage: adcoin-worker-load.sh <label> <plist>      (RERUN = the command to tell the user to run again)
# 11-15 09:49: the daemon stopped cleanly in 3 s, but launchd kept listing the label past the old 30 s wait (the job
# has ExitTimeOut 60), so the script ended with the daemon down and only "not installing" printed. Now it waits
# longer than ExitTimeOut, asks launchd again every 30 s, retries the bootstrap, and whenever it gives up says
# plainly that the daemon is down and how to run again, with its own exit code:
#   0 running   3 the old job never finished unloading   4 bootstrap kept failing   5 not running after bootstrap
set -uo pipefail
L=${1:?label}; P=${2:?plist}
LAUNCHCTL=${LAUNCHCTL:-launchctl}   # replaceable for tests
WAIT=${INSTALL_WAIT_SECONDS:-120}; SETTLE=${INSTALL_SETTLE_SECONDS:-15}; RETRY=${INSTALL_RETRY_SECONDS:-5}
POLL=${INSTALL_POLL_SECONDS:-1}
TRIES=${INSTALL_BOOTSTRAP_TRIES:-3}; RERUN=${RERUN:-the same install command}
DOMAIN="gui/$(id -u)"
listed() { "$LAUNCHCTL" list | grep -q "[[:space:]]$L\$"; }
down() {
  echo "!! 데몬이 지금 꺼져 있습니다 (the AD Coin worker daemon is NOT running now)."
  echo "!! 1분 뒤 같은 명령을 다시 실행하세요: $RERUN"
}
"$LAUNCHCTL" bootout "$DOMAIN/$L" 2>/dev/null || true
waited=0
while listed && [ "$waited" -lt "$WAIT" ]; do
  sleep "$POLL"; waited=$((waited + 1))
  if [ $((waited % 30)) -eq 0 ]; then "$LAUNCHCTL" bootout "$DOMAIN/$L" 2>/dev/null || true; fi
done
if listed; then
  echo "previous $L is still loaded after ${WAIT}s"; down; exit 3
fi
tries=1
until "$LAUNCHCTL" bootstrap "$DOMAIN" "$P"; do
  if [ "$tries" -ge "$TRIES" ]; then echo "bootstrap failed ${TRIES} times"; down; exit 4; fi
  echo "bootstrap failed; trying again in ${RETRY}s"; sleep "$RETRY"; tries=$((tries + 1))
done
sleep "$SETTLE"
if ! listed; then echo "$L is not running after the bootstrap"; down; exit 5; fi
exit 0
