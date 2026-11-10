#!/bin/bash
# Install the AI AD Coin v2 worker daemon (option B: one launchd job, one DB connection). Run by the user.
# Usage: deploy/launchd/install-adcoin-worker.sh <release>   e.g. v2-on-frontend-20261110-r1
# Checked 11-10 by 운영·SRE: --health ready, --once processed 0 with no errors.
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
spec = {'Label': L,
        'ProgramArguments': [f'{R}/.venv/bin/python', '-B', f'{R}/scripts/ad_coin_worker_daemon.py',
                             '--dsn-file', DSN, '--key-file', KEY, '--key-dir', KD, '--interval', '5'],
        'WorkingDirectory': R, 'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
        'ThrottleInterval': 30, 'ExitTimeOut': 60, 'Umask': 0o077, 'ProcessType': 'Background',
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin', 'PYTHONUNBUFFERED': '1', 'PYTHONPATH': R,
                                 'AD_COIN_V2_ENABLED': '1'},
        'StandardOutPath': f'{ROOT}/logs/services/{L}.log', 'StandardErrorPath': f'{ROOT}/logs/services/{L}.log'}
with open(P, 'wb') as f: plistlib.dump(spec, f)
os.chmod(P, 0o600)
PY
launchctl bootout "gui/$(id -u)/$L" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$P"
sleep 15
launchctl list | grep "$L" || { echo "not running"; exit 1; }
tail -5 "$ROOT/logs/services/$L.log" || true
echo "installed $L from $REL"
