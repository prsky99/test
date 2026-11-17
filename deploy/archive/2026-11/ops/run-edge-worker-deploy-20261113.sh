#!/bin/bash
# Run by the user (the Claude session's permission check refuses production Worker deploys).
# Deploys the edge Worker with 5e44fd1e (gateway failures answer error.data.cause) and 533306aa (A2A card
# aliases go to Origin instead of a Worker 404). User approval 11-13 15:18 ("둘 다 진행", via PM).
# Production before this: 38857ee9-7c6b-4b96-841f-4a0ff5e08db3 (56f0d41e, 11-11 04:14 UTC).
# Rollback: deploy/cloudflare-edge-worker-20261113.md
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD
PREV=38857ee9-7c6b-4b96-841f-4a0ff5e08db3
LOG=logs/ops/edge-worker-deploy-20261113.log
NODE=gateway-data/toolchains/node-v26.12.1-darwin-arm64/bin/node
exec > >(tee -a "$LOG") 2>&1
date '+시작 %F %T'

echo "1/5 시각 확인(:55~:10 측정 시간, 20:45~21:59 relay 배포 시간이면 중지)"
m=$(date +%M); hm=$(date +%H%M)
if [ "${m#0}" -ge 55 ] || [ "${m#0}" -lt 10 ] || { [ "$hm" -ge 2045 ] && [ "$hm" -le 2159 ]; }; then
  echo "    중지: 지금은 피해야 하는 시간입니다($(date +%H:%M)). :10~:54 사이에 다시 실행해 주세요."; exit 1
fi
echo "    통과"

echo "2/5 코드 확인: Worker 폴더가 533306aa와 같고, 운영(56f0d41e) 이후 커밋이 5e44fd1e·533306aa 두 개뿐인지"
git diff --quiet 533306aa -- cloudflare/edge-gateway || { echo "    중지: Worker 폴더가 533306aa와 다릅니다"; exit 1; }
commits=$(git log --format=%h 56f0d41e..533306aa -- cloudflare/edge-gateway | tr '\n' ' ')
[ "$commits" = "533306aa 5e44fd1e " ] || { echo "    중지: 예상 밖 커밋: $commits"; exit 1; }
echo "    통과"

echo "3/5 Worker 시험(worker.test.mjs)"
summary=$(cd cloudflare/edge-gateway && "$ROOT/$NODE" --test --test-reporter=tap worker.test.mjs 2>&1 | grep -E '^# (pass|fail)')
echo "$summary" | sed 's/^/    /'
grep -q '^# fail 0$' <<<"$summary" || { echo "    중지: 시험 실패"; exit 1; }

echo "4/5 운영 Worker 버전이 ${PREV}인지 확인하고 배포 잠금을 잡은 뒤 배포"
current=$(cd cloudflare/edge-gateway && ./npmw exec -- wrangler deployments list 2>/dev/null | grep -oE '\(100%\) [0-9a-f-]{36}' | tail -1 | awk '{print $2}')
[ "$current" = "$PREV" ] || { echo "    중지: 운영 Worker가 예상과 다릅니다: $current"; exit 1; }
LINE="- 운영·SRE $(date '+%m-%d %H:%M') pid=$$ edge-worker cause-alias-worker-20261113-r1 (사용자 실행)"
lock() { .venv/bin/python - "$1" "$LINE" <<'EOF'
import sys
sys.path.insert(0, 'scripts')
from heavy_slot import board_lock
mode, line = sys.argv[1], sys.argv[2]
p = 'logs/ops/status-board.md'
with board_lock():
    t = open(p, encoding='utf-8').read()
    head = '## 배포 잠금\n'
    i = t.index(head) + len(head)
    j = t.index('\n## ', i)
    sec = t[i:j]
    if mode == 'take':
        if sec.strip() != '(비어 있음)':
            print('    중지: 배포 잠금이 잡혀 있습니다:', sec.strip()); sys.exit(3)
        sec = sec.replace('(비어 있음)', line, 1)
    elif line in sec:
        rest = sec.replace(line, '', 1)
        sec = rest if rest.strip() else sec.replace(line, '(비어 있음)', 1)
    open(p, 'w', encoding='utf-8').write(t[:i] + sec + t[j:])
EOF
}
lock take || exit 1
trap 'lock release' EXIT
(cd cloudflare/edge-gateway && ./npmw exec -- wrangler deploy --message "cause-alias-worker-20261113-r1 (5e44fd1e + 533306aa)") \
  || { echo "    중지: 배포 실패(운영 Worker는 그대로일 수 있음, deployments list로 확인)"; exit 4; }

echo "5/5 공개 주소 확인(새 연결): A2A 카드 별칭 2개가 200이어야 함"
sleep 20
for u in /a2a/agent-card.json /a2a/.well-known/agent-card.json; do
  curl -s -o /dev/null -w "    $u %{http_code} %{time_total}s\n" "https://agentconcierge.biz$u?deploy=$(date +%s)"
done
date '+끝 %F %T'
echo "되돌리기: (cd cloudflare/edge-gateway && ./npmw exec -- wrangler rollback $PREV --message 'rollback cause-alias-worker-20261113-r1')"
