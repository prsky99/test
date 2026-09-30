# 무료 서버 + 무료 도메인에 게이트웨이 올리기

**권장 구성:** Oracle Cloud Always Free VM + DuckDNS 무료 도메인 + Caddy 자동 HTTPS. 비용은 0원입니다.
(2026-09 조사 기준: Render·Koyeb 무료 플랜은 유휴 시 잠들고 디스크가 없어 이 서비스에 맞지 않습니다. Fly.io·AWS·Hugging Face Docker는 더 이상 영구 무료가 아닙니다.)

가입은 본인 인증과 카드 확인이 필요해 직접 하셔야 합니다. 가입만 끝나면 나머지는 명령 한 줄입니다.

## 1. 수익 지갑 만들기 (본인 PC)
```bash
git clone -b claude/hopeful-darwin-i3qj6n https://github.com/prsky99/test.git && cd test
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m agent_market.wallet create ~/gateway-wallet.json   # 출력되는 0x... 주소를 적어 두기
```
keystore 파일과 비밀번호는 따로 백업하세요. 서버에는 **주소만** 넣습니다.

## 2. 무료 서버 (Oracle Cloud Always Free)
1. https://signup.cloud.oracle.com 가입 (카드 확인 필요, 과금 없음. 선불·가상 카드는 거절됨)
2. Compute → Instances → Create: 이미지 **Ubuntu 24.04**, Shape **VM.Standard.E2.1.Micro** (Always Free), SSH 키 등록
3. 인스턴스의 서브넷 → Security List → Ingress Rule 추가: TCP **80**, **443** (소스 0.0.0.0/0)
4. 공인 IP 확인

> 주의: Oracle은 7일간 CPU·네트워크 사용률이 매우 낮은 무료 인스턴스를 회수할 수 있습니다. 계정을 Pay-As-You-Go로 전환하면(Always Free 자원은 계속 무료) 회수 대상에서 빠집니다. 예산 알림을 $1로 설정해 두세요.
> Oracle 가입이 안 되면 Google Cloud e2-micro(us-central1 등 미국 3개 리전)에서 같은 절차로 하면 됩니다.

## 3. 무료 도메인 (DuckDNS)
1. https://www.duckdns.org 에서 GitHub/Google로 로그인
2. 서브도메인 생성 (예: `myagentgw` → `myagentgw.duckdns.org`), 화면의 **token** 복사

## 4. 서버에 올리기
```bash
ssh ubuntu@<공인 IP>
git clone -b claude/hopeful-darwin-i3qj6n https://github.com/prsky99/test.git && cd test/deploy
cp gateway.env.example gateway.env && nano gateway.env   # DOMAIN, GATEWAY_WALLET, ADMIN_TOKEN, DUCKDNS_* 입력
sudo bash setup.sh
```
끝나면 `https://<서브도메인>.duckdns.org/.well-known/agent.json` 이 열립니다. 첫 전체 수집은 몇 분 걸립니다.

## 운영
```bash
cd ~/test/deploy
sudo docker compose logs -f gateway                      # 로그
curl -s localhost:8200/health                            # 상태
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8200/admin/report   # 수익·수락률·수수료 (서버 안에서만)
git pull && sudo docker compose up -d --build            # 업데이트
sudo docker compose cp gateway:/data/gateway.sqlite3 ./backup.sqlite3          # 백업
```
- 관리자 API(`/admin/*`)는 외부에서 막혀 있고 서버 안(localhost)에서만 됩니다.
- 시험 운영은 `NETWORK=base-sepolia`, 실제 수수료를 받을 때 `NETWORK=base`로 바꾸고 `docker compose up -d`.
- 에이전트들이 찾아오게 하려면 게이트웨이 주소를 알려야 합니다 (예: 자체 agent card를 x402/MCP/A2A 디렉터리에 등록).
