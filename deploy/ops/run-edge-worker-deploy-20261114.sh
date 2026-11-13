#!/bin/bash
# Run by the user (the Claude session's permission check refuses production Worker deploys).
# Deploys the edge Worker with b47872a5: a provider handshake failure from Origin is answered with the provider's
# code (PROVIDER_UNAVAILABLE / PROVIDER_RATE_LIMITED, 502, Retry-After) instead of our UNAVAILABLE 503 (PM 11-14 04:5x).
# Needs the user's approval (via PM) before it is run.
# Production before this: 09da7f12-5b08-4708-9439-009d8e89910e (533306aa, 11-14 02:19 KST).
# Rollback: deploy/cloudflare-edge-worker-20261114.md
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD
PREV=09da7f12-5b08-4708-9439-009d8e89910e
LOG=logs/ops/edge-worker-deploy-20261114.log
NODE=gateway-data/toolchains/node-v26.12.1-darwin-arm64/bin/node
exec > >(tee -a "$LOG") 2>&1
date '+시작 %F %T'

echo "1/5 시각 확인(:55~:10 측정 시간, 20:45~21:59 relay 배포 시간이면 중지)"
m=$(date +%M); hm=$(date +%H%M)
if [ "${m#0}" -ge 55 ] || [ "${m#0}" -lt 10 ] || { [ "$hm" -ge 2045 ] && [ "$hm" -le 2159 ]; }; then
  echo "    중지: 지금은 피해야 하는 시간입니다($(date +%H:%M)). :10~:54 사이에 다시 실행해 주세요."; exit 1
fi
echo "    통과"

echo "2/5 코드 확인: Worker 폴더가 b47872a5와 같고, 운영(533306aa) 이후 커밋이 b47872a5 하나뿐인지"
git diff --quiet b47872a5 -- cloudflare/edge-gateway || { echo "    중지: Worker 폴더가 b47872a5와 다릅니다"; exit 1; }
commits=$(git log --format=%h 533306aa..b47872a5 -- cloudflare/edge-gateway | tr '\n' ' ')
[ "$commits" = "b47872a5 " ] || { echo "    중지: 예상 밖 커밋: $commits"; exit 1; }
echo "    통과"

echo "3/5 Worker 시험(worker.test.mjs)"
summary=$(cd cloudflare/edge-gateway && "$ROOT/$NODE" --test --test-reporter=tap worker.test.mjs 2>&1 | grep -E '^# (pass|fail)')
echo "$summary" | sed 's/^/    /'
grep -q '^# fail 0$' <<<"$summary" || { echo "    중지: 시험 실패"; exit 1; }

echo "4/5 운영 Worker 버전이 ${PREV}인지 확인하고 배포 잠금을 잡은 뒤 배포"
current=$(cd cloudflare/edge-gateway && ./npmw exec -- wrangler deployments list 2>/dev/null | grep -oE '\(100%\) [0-9a-f-]{36}' | tail -1 | awk '{print $2}')
[ "$current" = "$PREV" ] || { echo "    중지: 운영 Worker가 예상과 다릅니다: $current"; exit 1; }
LINE="- 운영·SRE $(date '+%m-%d %H:%M') pid=$$ edge-worker provider-code-worker-20261114-r1 (사용자 실행)"
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
(cd cloudflare/edge-gateway && ./npmw exec -- wrangler deploy --message "provider-code-worker-20261114-r1 (b47872a5)") \
  || { echo "    중지: 배포 실패(운영 Worker는 그대로일 수 있음, deployments list로 확인)"; exit 4; }

echo "5/5 공개 주소 확인(새 연결): 공개 경로가 그대로인지(A2A 카드 별칭 2개가 200)"
sleep 20
for u in /a2a/agent-card.json /a2a/.well-known/agent-card.json; do
  curl -s -o /dev/null -w "    $u %{http_code} %{time_total}s\n" "https://agentconcierge.biz$u?deploy=$(date +%s)"
done
date '+끝 %F %T'
echo "되돌리기: (cd cloudflare/edge-gateway && ./npmw exec -- wrangler rollback $PREV --message 'rollback provider-code-worker-20261114-r1')"
