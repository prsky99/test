#!/bin/bash
# Launch the AgentValCon house campaign without touching bookings already made (PM 11-15 10:40). User-run.
#   bash deploy/ops/house-ad-rebrand-keep-booked.sh          # check: shows the plan, writes nothing
#   bash deploy/ops/house-ad-rebrand-keep-booked.sh apply    # launches the campaign (ledger write, user approval)
# Bookings already made on the old "Agent Concierge" campaign run out as they are; the daily job (09:10) then books
# every new day on the AgentValCon campaign. Result: logs/ops/house-ad/rebrand-<time>.json
set -uo pipefail
cd "$(dirname "$0")/../.."
value() { grep -E "^$1=" gateway-data/agentcon.env | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
DSN=$(value APPLICATION_POSTGRES_DSN_FILE); KEY=$(value APPLICATION_WORKFLOW_KEY_FILE); KEYDIR=$(value AD_COIN_V2_KEY_DIR)
[ -n "$DSN" ] && [ -n "$KEY" ] && [ -n "$KEYDIR" ] || { echo "agentcon.env has no DSN, key or key dir path"; exit 2; }
MODE=--check; [ "${1:-}" = apply ] && MODE=--i-have-approval
OUT=logs/ops/house-ad/rebrand-$(date +%Y%m%d-%H%M%S).json
env -u PGHOST -u PGPORT -u PGDATABASE -u PGUSER -u PGPASSWORD -u PGSERVICE \
  .venv/bin/python -m scripts.ad_coin_house_ad rebrand --keep-booked "$MODE" \
    --dsn-file "$DSN" --key-file "$KEY" --key-dir "$KEYDIR" | tee "$OUT"
