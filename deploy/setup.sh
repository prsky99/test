#!/usr/bin/env bash
# Ubuntu VM(Oracle Always Free / GCP e2-micro)에서 한 번 실행: 도커 설치, 방화벽, DuckDNS 갱신, 게이트웨이 기동.
#   git clone -b claude/hopeful-darwin-i3qj6n https://github.com/prsky99/test.git && cd test/deploy
#   cp gateway.env.example gateway.env && nano gateway.env && sudo bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"
[ -f gateway.env ] || { echo "gateway.env 가 없습니다 (gateway.env.example 복사 후 작성)"; exit 1; }
chmod 600 gateway.env
set -a; . ./gateway.env; set +a
for v in DOMAIN GATEWAY_WALLET ADMIN_TOKEN DUCKDNS_SUBDOMAIN DUCKDNS_TOKEN; do
  [ -n "${!v:-}" ] || { echo "gateway.env 에 $v 값이 필요합니다"; exit 1; }
done

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

# Oracle Ubuntu 이미지는 iptables가 80/443을 막아 둔다 (클라우드 콘솔 보안 목록에서도 80/443 인바운드 허용 필요)
if command -v iptables >/dev/null; then
  for p in 80 443; do
    iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || iptables -I INPUT 6 -p tcp --dport $p -j ACCEPT
  done
  command -v netfilter-persistent >/dev/null && netfilter-persistent save || true
fi

# DuckDNS: 지금 한 번 + 5분마다 IP 갱신
cat > /etc/cron.d/duckdns <<CRON
*/5 * * * * root curl -fsS "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=" >/dev/null
CRON
chmod 600 /etc/cron.d/duckdns
curl -fsS "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=" && echo " <- DuckDNS"

docker compose up -d --build
echo "대기 중..."; sleep 20
curl -fsS "https://${DOMAIN}/health" && echo && echo "배포 완료: https://${DOMAIN}/.well-known/agent.json"
