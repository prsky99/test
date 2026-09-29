# Agent Market: 에이전트끼리 거래해 코인(USDC)을 버는 AI 에이전트

AI 에이전트가 다른 AI 에이전트에게 작업을 팔고 **USDC(스테이블코인)** 로 대가를 받는 예제입니다.

- **판매 에이전트** (`agent_market/server.py`): Claude로 요약·번역·코드리뷰를 수행하는 HTTP 서비스. 결제가 없으면 `402 Payment Required`와 결제 조건을 돌려주고, 온체인 결제를 확인한 뒤 작업 결과를 줍니다.
- **구매 에이전트** (`agent_market/buyer.py`): 판매자를 찾아 가격을 확인하고, 예산 안에서 USDC를 보낸 뒤 결과를 받습니다.

```
구매 에이전트                                판매 에이전트                    Base 체인
    │  GET /.well-known/agent.json  ─────────▶ │  서비스·가격·지갑 주소
    │  POST /services/summarize     ─────────▶ │  402 + 결제 조건
    │  USDC transfer ──────────────────────────────────────────────────────▶ │
    │  POST + X-Payment-Tx/Signature ────────▶ │  영수증 조회·검증 ──────────▶ │
    │  ◀──────────────────────────  결과 + 영수증 (Claude가 작업)
```

## 빠른 시작 (테스트넷)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1) 판매 에이전트 실행 — 받는 지갑 주소만 필요 (개인키 불필요)
export ANTHROPIC_API_KEY=...          # Claude API 키
export SELLER_WALLET=0x...            # 수익을 받을 지갑 주소
export ADMIN_TOKEN=아무-긴-문자열       # /stats 조회용
.venv/bin/python -m agent_market.server   # http://127.0.0.1:8000

# 2) 구매 에이전트 (다른 터미널)
export BUYER_PRIVATE_KEY=0x...        # 테스트넷 전용 지갑! (Base Sepolia ETH + 테스트 USDC 필요)
.venv/bin/python -m agent_market.buyer http://127.0.0.1:8000              # 서비스 목록
.venv/bin/python -m agent_market.buyer http://127.0.0.1:8000 summarize "요약할 긴 글..."

# 3) 수익 확인
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/stats
```

테스트넷 자산: Base Sepolia ETH(가스비)는 Base 공식 faucet, 테스트 USDC는 Circle faucet(faucet.circle.com)에서 받을 수 있습니다.

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `NETWORK` | `base-sepolia` | `base-sepolia`(테스트넷) 또는 `base`(메인넷) |
| `RPC_URL` | 네트워크 공개 RPC | 사용할 JSON-RPC 주소 |
| `SELLER_WALLET` | — | 판매자 수익 지갑 주소 |
| `MIN_CONFIRMATIONS` | `1` | 결제 인정에 필요한 컨펌 수 |
| `LEDGER_DB` | `ledger.sqlite3` | 결제 장부 파일 |
| `BUYER_MAX_PER_CALL` | `0.10` | 구매자 1회 결제 상한 (USDC) |
| `BUYER_BUDGET` | `1.00` | 구매자 실행당 총 예산 (USDC) |
| `ALLOW_MAINNET` | — | `1`일 때만 구매자가 메인넷에서 결제 |

서비스 종류와 가격은 `agent_market/services.py`의 `SERVICES`에서 바꿀 수 있습니다.

## 보안 설계

- **판매자는 개인키를 갖지 않습니다.** 받는 주소만 알면 되므로 서버가 털려도 자금이 빠져나가지 않습니다.
- **결제 재사용 방지:** 결제 트랜잭션 하나는 한 번만 쓸 수 있습니다 (SQLite 장부).
- **결제 도용 방지:** 체인에 공개된 남의 tx 해시로는 서비스를 받을 수 없습니다. 요청마다 송금 지갑이 `tx 해시 + 요청 본문 해시`에 서명해야 합니다.
- **작업 실패 시 재시도:** Claude 호출이 실패하면 결제 선점을 풀어, 같은 결제로 다시 요청할 수 있습니다.
- **구매자 지출 제한:** 1회 상한과 총 예산을 넘는 결제는 하지 않고, 메인넷 결제는 명시적으로 켜야 합니다.

## 한계와 주의사항

- 이 코드는 **수익을 보장하지 않습니다.** 돈이 되려면 서비스를 사 줄 다른 에이전트(구매자)가 있어야 하고, Claude API 비용보다 비싸게 팔아야 합니다.
- 메인넷에서 실제 코인을 주고받기 전에 테스트넷에서 충분히 검증하세요. 개인키는 절대 커밋하지 마세요.
- 암호화폐로 서비스를 판매하면 거주 국가에 따라 세금 신고, 사업자 등록 등 법적 의무가 생길 수 있습니다.
- 외부에 공개할 때는 HTTPS 리버스 프록시와 요청 제한(rate limit)을 앞단에 두세요.

## 테스트

```bash
.venv/bin/python -m pytest tests
```

가짜 체인과 가짜 Claude로 결제 흐름 전체(402 응답, 정상 결제, 재사용·도용·금액 부족·잘못된 토큰 거부, 예산 제한, 메인넷 차단)를 검증합니다.
