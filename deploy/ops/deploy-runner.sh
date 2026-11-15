#!/bin/bash
# Deploy runner template (precision review R55, 11-15; from the one-off logs/ops/night-*/ runners of 11-14..15).
# One release of one role: reserve under '## 배포 대기', package from a commit on the active release, run the release
# gate (heavy slot), then deploy only inside :10-:50 with the board lock empty and the base still active, with the
# lock line stamped at that moment. The deploy tool itself checks the policy hash night rule, the registered SQL list
# and reuses the gate pass (R54); the packaged release pins itself until it is deployed (R60).
#
#   deploy/ops/deploy-runner.sh <role> <release> <commit> <base> [not-before HH:MM] [deadline YYYY-MM-DD HH:MM]
#   e.g. deploy/ops/deploy-runner.sh frontend day16-frontend-20261116-r1 abc1234 day15-frontend-20261115-r1 09:10 "2026-11-16 17:50"
#   Start it detached:  (nohup bash deploy/ops/deploy-runner.sh ... > logs/ops/runners/<release>.log 2>&1 &)
#   RUNNER_TEAM (default 운영·SRE), RUNNER_CHECKS (space-separated public paths to check after the deploy).
set -uo pipefail
cd "$(dirname "$0")/../.."
ROLE=${1:?role}; REL=${2:?release}; COMMIT=${3:?commit}; BASE=${4:?base release}
NOT_BEFORE=${5:-00:00}; DEADLINE_AT=${6:-$(date -v+12H '+%Y-%m-%d %H:%M')}
TEAM=${RUNNER_TEAM:-운영·SRE}
D=logs/ops/runners; mkdir -p "$D"
. deploy/ops/runner-lock.sh
RL_TEAM=$TEAM; RL_KEY=$REL; RL_WHAT="$ROLE $REL ($COMMIT on $BASE)"
DEADLINE=$(date -j -f "%Y-%m-%d %H:%M" "$DEADLINE_AT" +%s)
say() { echo "$(date '+%m-%d %H:%M:%S') $*"; }
active() { .venv/bin/python -c "
import json,sys; s=json.load(open('gateway-data/services/state.json'))['services'][sys.argv[1]]
print(s['slots'][s['active']] if 'slots' in s else s['release'])" "$1"; }
lockfree() { .venv/bin/python -c "
t=open('logs/ops/status-board.md',encoding='utf-8').read(); i=t.index('## 배포 잠금\n')+len('## 배포 잠금\n'); j=t.index('\n## ',i); raise SystemExit(0 if t[i:j].strip()=='(비어 있음)' else 1)"; }
window_ok() { local m; m=$(date +%M); m=${m#0}; [ "$m" -ge 10 ] && [ "$m" -lt 50 ]; }
not_before() { [ "$(date +%H:%M)" \> "$NOT_BEFORE" ] || [ "$(date +%H:%M)" = "$NOT_BEFORE" ]; }
over() { [ "$(date +%s)" -ge "$DEADLINE" ]; }
finish() { rl_unreserve; say "reservation removed"; }
trap finish EXIT

case "$ROLE" in frontend|admin) DEPLOY=deploy ;; jobs|execution) DEPLOY=worker-deploy ;; *) say "stop: unknown role $ROLE"; exit 2 ;; esac
say "runner pid $$: $ROLE $REL ($COMMIT on $BASE), not before $NOT_BEFORE, deadline $DEADLINE_AT"
rl_reserve && say "reserved under 배포 대기"
until not_before; do over && { say "deferred: deadline before the start time"; exit 75; }; sleep 60; done

for i in $(seq 1 30); do   # the deployment lock file is busy while another deploy or package runs
  ./agentcon package "$REL" --commit "$COMMIT" --base "$BASE" > "$D/$REL-package.log" 2>&1 && break
  grep -q BlockingIOError "$D/$REL-package.log" || { say "stop: package failed"; tail -3 "$D/$REL-package.log"; exit 1; }
  say "package lock busy, retry in 2 min"; sleep 120
done
[ -d "gateway-data/services/releases/$REL" ] || { say "stop: package never ran"; exit 1; }
say "packaged $REL"

while :; do
  over && { say "deferred: no heavy slot in time"; exit 75; }
  window_ok || { sleep 60; continue; }
  .venv-tests/bin/python -m scripts.heavy_slot --team "$TEAM" --what "release_gate $REL" --minutes 30 -- \
    .venv-tests/bin/python -m scripts.release_gate "$REL" > "$D/$REL-gate.log" 2>&1; rc=$?
  [ $rc -ne 75 ] && break
  say "heavy slot busy, retry in 5 min"; sleep 300
done
tail -3 "$D/$REL-gate.log" | while read -r l; do say "gate: $l"; done
[ $rc -eq 0 ] || { say "stop: release_gate exit $rc"; exit 1; }

until lockfree && window_ok; do over && { say "deferred: lock or window not free in time"; exit 75; }; sleep 60; done
[ "$(active "$ROLE")" = "$BASE" ] || { say "stop: active $ROLE changed to $(active "$ROLE")"; exit 1; }
rl_take || { say "stop: lock taken meanwhile"; exit 1; }
trap 'rl_release; say "lock released"; finish' EXIT
say "lock taken (stamped now); $DEPLOY $ROLE $REL"
./agentcon $DEPLOY "$ROLE" "$REL" --no-prune --lock-owner "$TEAM" > "$D/$REL-deploy.log" 2>&1; rc=$?
rl_release; trap finish EXIT; say "lock released"
say "deploy exit $rc; active $ROLE $(active "$ROLE")"
[ $rc -eq 0 ] && [ "$(active "$ROLE")" = "$REL" ] || { say "stop: deploy did not take"; tail -5 "$D/$REL-deploy.log"; exit 1; }

sleep 60
for path in ${RUNNER_CHECKS:-}; do
  say "check $(curl -s -o /dev/null -w '%{http_code} %{time_total}s' -H 'Accept: text/html,application/json' "https://agentconcierge.biz$path") $path"
done
say "runner done: $ROLE $REL"
