#!/bin/bash
# Install the AI AD Coin v2 worker daemon (option B: one launchd job, one DB connection). Run by the user.
# Usage: deploy/launchd/install-adcoin-worker.sh <release>   e.g. v2-on-frontend-20261110-r1
# Exit codes (11-19, for the unattended deploy runner): 0 installed; 2 release has no daemon script or .venv;
#   3/4/5 load failed with no earlier release (see adcoin-worker-load.sh); 6 load failed, rolled back to the earlier
#   release and it runs; 7 rollback failed too, the daemon is down; 9 another install holds the lock.
# Checked 11-10 by 운영·SRE: --health ready, --once processed 0 with no errors.
# 11-11: AD_COIN_PAID_* and AD_COIN_OFAC_LIST come from gateway-data/sponsored.env (scripts/adcoin_worker_env.py);
# the daemon re-reads that file when it changes, so switching USDC bookings on needs no reinstall.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD; REL=${1:?release name}; R=$ROOT/gateway-data/services/releases/$REL
ENV=$ROOT/gateway-data/agentcon.env
DSN=$(grep '^APPLICATION_POSTGRES_DSN_FILE=' "$ENV" | cut -d= -f2-)
KEY=$(grep '^APPLICATION_WORKFLOW_KEY_FILE=' "$ENV" | cut -d= -f2-)
KD=$(grep '^AD_COIN_V2_KEY_DIR=' "$ENV" | cut -d= -f2-)
[ -n "$KD" ] || { echo "AD_COIN_V2_KEY_DIR is not set in agentcon.env"; exit 1; }
L=biz.agentconcierge.498590e0b3.adcoin-worker; P=${ADCOIN_PLIST:-$HOME/Library/LaunchAgents/$L.plist}
[ -d "$R" ] && [ -f "$R/scripts/ad_coin_worker_daemon.py" ] && [ -x "$R/.venv/bin/python" ] \
  || { echo "release $REL has no daemon script or .venv; not installing"; exit 2; }
# 11-19 (unattended reinstall by the deploy runner, PM 00:37): one install at a time; the lock is a directory
LOCK=$ROOT/gateway-data/ops/adcoin-install.lock
mkdir "$LOCK" 2>/dev/null || { echo "another AD Coin daemon install holds $LOCK; not installing"; exit 9; }
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
# the release the daemon runs now (its plist's WorkingDirectory) and a copy of that plist: the rollback target
PREV=$("$ROOT/.venv/bin/python" -c 'import plistlib,sys,os; print(os.path.basename(plistlib.load(open(sys.argv[1],"rb"))["WorkingDirectory"]))' "$P" 2>/dev/null || true)
[ -f "$P" ] && cp -p "$P" "$P.prev"
"$ROOT/.venv/bin/python" - "$R" "$DSN" "$KEY" "$KD" "$P" "$L" "$ROOT" <<'PY'
import plistlib, sys, os
R, DSN, KEY, KD, P, L, ROOT = sys.argv[1:]
sys.path.insert(0, ROOT)
from scripts.adcoin_worker_env import daemon_environment
ENVFILE = os.path.join(ROOT, 'gateway-data/sponsored.env')   # Sponsored and USDC settings (11-11), not agentcon.env
env = daemon_environment(R, open(ENVFILE).read() if os.path.exists(ENVFILE) else '', ENVFILE)
# paid-booking settings come from sponsored.env as written (switch off unless it says so); names only, no values
print('daemon env:', ', '.join(sorted(k for k in env if k.startswith('AD_COIN_PAID_') or k == 'AD_COIN_OFAC_LIST')) or 'no paid settings')
spec = {'Label': L,
        'ProgramArguments': [f'{R}/.venv/bin/python', '-B', f'{R}/scripts/ad_coin_worker_daemon.py',
                             '--dsn-file', DSN, '--key-file', KEY, '--key-dir', KD, '--interval', '5'],
        'WorkingDirectory': R, 'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
        'ThrottleInterval': 30, 'ExitTimeOut': 60, 'Umask': 0o077, 'ProcessType': 'Background',
        'EnvironmentVariables': env,
        'StandardOutPath': f'{ROOT}/logs/services/{L}.log', 'StandardErrorPath': f'{ROOT}/logs/services/{L}.log'}
with open(P, 'wb') as f: plistlib.dump(spec, f)
os.chmod(P, 0o600)
PY
# 11-15: pin the daemon's release so the post-deploy prune never removes the folder it runs from
pin() {   # pin $1 as the daemon's release and $2 (may be empty) as the rollback target
  "$ROOT/.venv/bin/python" -c 'import sys; sys.path.insert(0, sys.argv[1]); from scripts.adcoin_worker_env import pin_release; pin_release(sys.argv[2], sys.argv[3], sys.argv[4] or None); print("pinned", sys.argv[3], "previous", sys.argv[4] or "-")' \
    "$ROOT" "$ROOT/gateway-data/services/pinned-releases.txt" "$1" "${2:-}"
}
pin "$REL" "$PREV"
# 11-15: the bootout/bootstrap step lives in adcoin-worker-load.sh (longer wait, retries, and a plain "daemon is
# down, run again" message with its own exit code when it gives up)
set +e
RERUN="bash deploy/launchd/install-adcoin-worker.sh $REL" bash "$ROOT/deploy/launchd/adcoin-worker-load.sh" "$L" "$P"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  # 11-19: without a person, a failed load must not leave the daemon down: put back the plist it ran before, once
  if [ -n "$PREV" ] && [ "$PREV" != "$REL" ] && [ -f "$P.prev" ] && [ -d "$ROOT/gateway-data/services/releases/$PREV" ]; then
    echo "load of $REL failed (rc $rc); rolling back to $PREV"
    cp -p "$P.prev" "$P"
    pin "$PREV" ""
    set +e
    RERUN="bash deploy/launchd/install-adcoin-worker.sh $PREV" bash "$ROOT/deploy/launchd/adcoin-worker-load.sh" "$L" "$P"
    back=$?
    set -e
    if [ "$back" -eq 0 ]; then echo "rolled back: $L runs $PREV again (rc 6)"; exit 6; fi
    echo "rollback to $PREV failed too (rc $back): the daemon is down (rc 7)"; exit 7
  fi
  echo "load of $REL failed (rc $rc) and there is no earlier release to go back to"; exit "$rc"
fi
tail -5 "$ROOT/logs/services/$L.log" || true
echo "installed $L from $REL (previous ${PREV:--})"
