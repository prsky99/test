#!/bin/bash
# The house ad as an agent offer on MCP, A2A and REST answers (PM 11-15). User-run, after:
#   1. bash deploy/ops/house-ad-rebrand-keep-booked.sh apply     (the AgentValCon campaign exists)
#   2. migrate-night-1115 applied                               (the offer tables exist)
# Then:
#   bash deploy/ops/house-ad-agent-offer.sh            # check: shows the offer, the exact agent line, writes nothing
#   bash deploy/ops/house-ad-agent-offer.sh apply      # submits and approves it (database write, user approval)
#   bash deploy/ops/house-ad-agent-offer.sh verify     # public check: MCP, A2A, REST carry it, also with ads=none;
#                                                       # organic results are the same with and without it
# The ad is paid with free AD Coin only (the house bookings). Results: logs/ops/house-ad/offer-<time>.json and
# logs/ops/house-offer-verify/<time>.json. Ads show only on days the AgentValCon campaign is booked.
set -uo pipefail
cd "$(dirname "$0")/../.."
if [ "${1:-}" = verify ]; then exec .venv/bin/python -m scripts.ad_coin_house_offer_verify; fi
value() { grep -E "^$1=" gateway-data/agentcon.env | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
DSN=$(value APPLICATION_POSTGRES_DSN_FILE); KEY=$(value APPLICATION_WORKFLOW_KEY_FILE); KEYDIR=$(value AD_COIN_V2_KEY_DIR)
[ -n "$DSN" ] && [ -n "$KEY" ] && [ -n "$KEYDIR" ] || { echo "agentcon.env has no DSN, key or key dir path"; exit 2; }
MODE=--check; [ "${1:-}" = apply ] && MODE=--i-have-approval
OUT=logs/ops/house-ad/offer-$(date +%Y%m%d-%H%M%S).json
env -u PGHOST -u PGPORT -u PGDATABASE -u PGUSER -u PGPASSWORD -u PGSERVICE \
  .venv/bin/python -m scripts.ad_coin_house_ad offer "$MODE" \
    --dsn-file "$DSN" --key-file "$KEY" --key-dir "$KEYDIR" | tee "$OUT"
