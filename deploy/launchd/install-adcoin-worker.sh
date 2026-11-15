#!/bin/bash
# Install the AI AD Coin v2 worker daemon (option B: one launchd job, one DB connection). Run by the user.
# Usage: deploy/launchd/install-adcoin-worker.sh <release>   e.g. v2-on-frontend-20261110-r1
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
L=biz.agentconcierge.498590e0b3.adcoin-worker; P=$HOME/Library/LaunchAgents/$L.plist
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
"$ROOT/.venv/bin/python" -c 'import sys; sys.path.insert(0, sys.argv[1]); from scripts.adcoin_worker_env import pin_release; pin_release(sys.argv[2], sys.argv[3]); print("pinned", sys.argv[3])' \
  "$ROOT" "$ROOT/gateway-data/services/pinned-releases.txt" "$REL"
# 11-15: the bootout/bootstrap step lives in adcoin-worker-load.sh (longer wait, retries, and a plain "daemon is
# down, run again" message with its own exit code when it gives up)
RERUN="bash deploy/launchd/install-adcoin-worker.sh $REL" bash "$ROOT/deploy/launchd/adcoin-worker-load.sh" "$L" "$P" || exit $?
tail -5 "$ROOT/logs/services/$L.log" || true
echo "installed $L from $REL"
