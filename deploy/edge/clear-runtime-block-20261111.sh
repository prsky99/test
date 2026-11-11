#!/bin/bash
# User-run (PM approved 11-11): lift the edge Worker runtime block that has stood since 10-31.
# Evidence: Cloudflare analytics 10-28..11-11 show 2 Worker exceptions (11-10, old version 2d9e2799)
# and 0 CPU-limit hits; Worker 38857ee9 is deployed. One transaction: clear + audit row.
# After this, health is re-confirmed by the edge monitor within ~5 minutes, then Worker execution resumes.
set -euo pipefail
cd /Users/kingstonelee/workspace/A2A_Discovery
PSQL=(/opt/homebrew/opt/postgresql@18/bin/psql -h "$PWD/gateway-data/postgres18/run" -p 55432 -d agentcon_cutover_20261020_191757 -At -v ON_ERROR_STOP=1)
echo "before: $("${PSQL[@]}" -c "select revision,mode,cpu_blocked from edge_gateway_policy")"
"${PSQL[@]}" -c "WITH p AS (UPDATE edge_gateway_policy SET revision=revision+1, cpu_blocked=0, health_day='', health_at=0 WHERE id=1 AND cpu_blocked=1 RETURNING revision) INSERT INTO edge_gateway_host_audit SELECT revision, 'clear-runtime-block', 'host-operator', 'PM-approved 11-11: block stood since 10-31; 2 Worker exceptions in 11 days, 0 CPU-limit hits; worker 38857ee9 deployed', extract(epoch from now()) FROM p RETURNING revision, action"
echo "after: $("${PSQL[@]}" -c "select revision,mode,cpu_blocked from edge_gateway_policy")"
