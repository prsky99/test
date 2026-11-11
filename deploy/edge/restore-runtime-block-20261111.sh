#!/bin/bash
# Rollback for clear-runtime-block-20261111.sh: send every public gateway execution back to Origin.
set -euo pipefail
cd /Users/kingstonelee/workspace/A2A_Discovery
PSQL=(/opt/homebrew/opt/postgresql@18/bin/psql -h "$PWD/gateway-data/postgres18/run" -p 55432 -d agentcon_cutover_20261020_191757 -At -v ON_ERROR_STOP=1)
"${PSQL[@]}" -c "WITH p AS (UPDATE edge_gateway_policy SET revision=revision+1, cpu_blocked=1 WHERE id=1 AND cpu_blocked=0 RETURNING revision) INSERT INTO edge_gateway_host_audit SELECT revision, 'block-runtime', 'host-operator', 'Rollback 11-11: Worker execution worse than Origin during the first hour', extract(epoch from now()) FROM p RETURNING revision, action"
echo "after: $("${PSQL[@]}" -c "select revision,mode,cpu_blocked from edge_gateway_policy")"
