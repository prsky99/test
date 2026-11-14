#!/bin/bash
# Daily USDC payment reconciliation (AI AD Coin F12, PM 11-14): reads the database and Base, writes nothing there.
#   launchd biz.agentconcierge.opsauto.paidreconcile (09:20 KST, after the house ad) -> this script
#   -> scripts.ad_coin_paid_reconcile for yesterday (UTC). Result: logs/ops/payment-reconcile/<day>.json.
# Exit 1 = a finding (money without a booking, a payment gone from the chain, served without impressions, missing
# KRW or export row): it goes to the ops alert, for AI AD Coin to look at the same day.
set -uo pipefail
cd "$(dirname "$0")/../.."
LOG_DIR=logs/ops/payment-reconcile
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"
value() { grep -E "^$1=" gateway-data/agentcon.env | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
DSN=$(value APPLICATION_POSTGRES_DSN_FILE); KEY=$(value APPLICATION_WORKFLOW_KEY_FILE)
if [ -z "$DSN" ] || [ -z "$KEY" ]; then
  echo "$(date '+%F %T') stop: agentcon.env has no DSN or key path" >> "$LOG"; rc=2
else
  env -u PGHOST -u PGPORT -u PGDATABASE -u PGUSER -u PGPASSWORD -u PGSERVICE \
    nice -n 10 .venv/bin/python -m scripts.ad_coin_paid_reconcile --dsn-file "$DSN" --key-file "$KEY" >> "$LOG" 2>&1
  rc=$?
fi
echo "$(date '+%F %T') exit $rc" >> "$LOG"
exit "$rc"
