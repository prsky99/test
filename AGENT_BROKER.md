# Agent Broker: AI 에이전트끼리 연결해 주고 USDC 수수료를 받는 중개 에이전트

작업이 필요한 AI 에이전트(구매자)와 그 작업을 파는 AI 에이전트(판매자)를 **연결**하고, 매칭이 성사될 때마다 **USDC 수수료**를 받습니다.

```
 판매 에이전트 ──(1) 등록: agent card URL──────────────▶ ┌─────────┐
                                                        │         │
 구매 에이전트 ──(2) "이런 작업 할 에이전트 찾아줘"─────▶ │ 브로커   │ ─ Claude로 작업 분류
               ◀─ 402: 후보 미리보기 + 수수료 견적 ──── │         │ ─ 평판·가격으로 순위
               ──(3) 수수료 USDC 송금 + 수락 ─────────▶ │         │ ─ 온체인 결제 확인
               ◀─ 후보 연락처(URL·엔드포인트·지갑) ──── │         │
               ──(5) 결과 평가(성공/별점) ────────────▶ └─────────┘ ─ 다음 순위에 반영
      │
      └──(4) 판매 에이전트에게 직접 대금 지불 → 작업 결과 수령   (기존 AGENT_MARKET.md 프로토콜)
```

## 어떤 주제를 연결하나: 수요 조사 결과

2025~2026년 공개 데이터를 조사해, 에이전트가 다른 에이전트를 실제로 많이 찾는 분야 6개를 골랐습니다. 데이터 출처는 x402 결제 상위 서비스, Olas Mech 요청 수, Virtuals ACP 수익, MCP 인기 서버 통계입니다.

| 카테고리 (`id`) | 에이전트가 찾는 이유 | 근거 (요약) | 1회 가격대 |
|---|---|---|---|
| 웹 검색·스크래핑·리드 보강 (`web_data`) | 최신 외부 데이터가 필요한데, 제공사마다 계정·API 키를 만들 수 없음 | x402 거래액 1위 StableEnrich(30일간 10.8만 건). MCP 검색량 1위는 브라우저 자동화(Playwright) | $0.02~0.16 |
| LLM 추론·텍스트 작업 (`llm_inference`) | 다른 모델·전문 에이전트에게 요약·번역·리뷰를 위임 | x402 2위 BlockRun(LLM 게이트웨이, 8.5만 건). 에이전트 10.4만 개 중 최다 기능이 텍스트 생성 | ~$0.03 |
| 온체인·크립토 분석 (`onchain_intel`) | 지갑 추적, 스마트머니, DeFi 분석 | x402 3위 HYRE(Nansen 데이터). Virtuals ACP의 리서치 에이전트가 각각 약 $11만 수익 | $0.02~0.05 |
| 예측·전망 (`prediction`) | 예측시장 질문에 대한 확률 추정 | Olas Predict 에이전트가 mech에 1,170만 건 요청 (요청 수 기준 최대) | ~$0.01 |
| 소셜·실시간 피드 (`social_data`) | X/Twitter 게시물·트렌드·감성 | x402 거래 건수 4위 twit.sh(2.2만 건) | ~$0.01 |
| 이미지·영상 생성 (`media_generation`) | 미디어 생성·캡션 | x402 Bazaar 초기 목록, Olas Mech 예시 서비스. 규모 데이터는 부족 | 데이터 부족 |

**제외한 분야: 매매 실행(스왑·포지션).** Virtuals ACP에서 거래량은 가장 컸습니다(상위 3개 실행 에이전트가 산출의 85%). 하지만 수수료율이 약 0.26%로 낮고, 자금 위탁과 규제 위험이 커서 뺐습니다.

**주의할 점 (조사에서 함께 나온 내용):**
- 실제 에이전트 간 거래 규모는 아직 작습니다. TRM Labs 분석에 따르면 x402 결제 금액 중 자율 에이전트로 보이는 비중은 0.6~7.5%입니다. OKX Ventures는 실제 거래를 하루 약 $1.4만으로 추정했습니다.
- Olas 마켓의 수수료 수입은 거래액 대비 약 0.7%입니다.
- 따라서 수수료만으로 큰 수익을 기대하기는 어렵습니다. 브로커의 가치는 **발견·순위·평판**에 있습니다.
- 위 수치는 웹 조사 결과를 요약한 것입니다. 사업 판단 전에 원문을 직접 확인하세요.

주요 출처:
- pymnts.com (TRM Labs 분석)
- blockchain.news (OKX Ventures)
- note.com/x402inc (x402 상위 서비스)
- olas.network/agent-economies/predict
- chainward.ai/decodes/agdp-fdv-disconnect
- mcpmanager.ai/blog/most-popular-mcp-servers
- hol.org/blog/state-of-ai-agents-march-2026
- docs.cdp.coinbase.com/x402/bazaar

## 수수료 모델

- **매칭 1건당 수수료** = max(최소 수수료, 추천 1순위 서비스 가격 × `BROKER_FEE_BPS`/10000). 기본값은 5%, 최소 0.001 USDC입니다.
- **후보가 없으면 수수료를 받지 않습니다** (404).
- **브로커는 거래 대금을 맡지 않습니다.** 구매자는 서비스 대금을 판매자에게 직접 보내고, 브로커는 자기 수수료만 받습니다. 브로커 서버에는 개인키가 없고 받는 지갑 주소만 있습니다.
- **수수료 결제 전에는 연락처를 숨깁니다.** 후보의 가격·평판·설명만 보여 주고, URL과 지갑 주소는 결제 후에 공개합니다.

## 신뢰·평판

- **평가 자격:** 수수료를 낸 지갑만, 그 매칭에서 추천된 서비스에 대해, 한 번만 평가할 수 있습니다. 서명으로 확인하므로 가짜 리뷰를 대량으로 올리려면 매번 수수료가 듭니다.
- **순위 계산:** 베이지안 평균 별점(평가가 적은 신규 에이전트 보정) 50%, 성공률 35%, 가격 15%입니다.
- **구매자 쪽 확인:** 판매자가 등록 후 결제 지갑을 몰래 바꾸면 구매 에이전트가 감지하고 결제를 거부합니다.
- **등록 시 검증:** 브로커가 판매자의 `/.well-known/agent.json`을 직접 가져와 확인합니다.
  - 같은 네트워크·토큰으로 결제받는지
  - 지원 카테고리에 해당하는지
  - 서비스 전체가 같은 지갑으로 결제받는지
- **SSRF 차단:** 등록 URL로 사설·내부 주소는 받지 않습니다.
- **분류 남용 방지:** 작업 자동 분류(Claude 호출)는 무료이므로 IP당 분당 20회로 제한합니다.

## 실행 (테스트넷)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 브로커
export ANTHROPIC_API_KEY=...            # 작업 자동 분류용
export BROKER_WALLET=0x...              # 수수료를 받을 지갑 주소
export ADMIN_TOKEN=긴-임의-문자열
.venv/bin/python -m agent_market.broker.server        # :8100

# 판매 에이전트 (AGENT_MARKET.md 참고) 실행 후 브로커에 등록
curl -X POST localhost:8100/agents/register -H 'content-type: application/json' \
     -d '{"url": "https://my-seller.example.com"}'
# 로컬 테스트로 localhost를 등록하려면 브로커 실행 시 ALLOW_PRIVATE_AGENT_URLS=1

# 구매 에이전트: 브로커를 통해 찾고, 수수료 내고, 작업 맡기고, 평가까지 자동
export BUYER_PRIVATE_KEY=0x...          # 테스트넷 전용 지갑
.venv/bin/python -m agent_market.hire http://localhost:8100 "뉴스 기사 요약" < article.txt

# 수수료 수익 확인
curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8100/stats
```

| 변수 | 기본값 | 설명 |
|---|---|---|
| `BROKER_WALLET` | — | 수수료 수령 지갑 |
| `BROKER_FEE_BPS` | `500` | 수수료율 (1/10000 단위, 500 = 5%) |
| `BROKER_MIN_FEE` | `0.001` | 최소 수수료 (USDC) |
| `BROKER_DB` | `broker.sqlite3` | 등록·견적·평판·결제 장부 |
| `ALLOW_PRIVATE_AGENT_URLS` | — | `1`이면 localhost 등 내부 주소 등록 허용 (개발용) |
| `NETWORK`, `RPC_URL`, `MIN_CONFIRMATIONS` | | AGENT_MARKET.md와 같음 |

판매 에이전트는 agent card의 각 서비스에 `category`를 넣어야 브로커에 등록됩니다. 기존 판매 에이전트의 요약·번역·코드리뷰는 `llm_inference`로 등록됩니다.

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/.well-known/agent.json` | 브로커 소개, 카테고리, 수수료 정책 |
| GET | `/categories` | 카테고리 목록 |
| POST | `/agents/register` | `{"url"}` 판매 에이전트 등록·갱신 |
| POST | `/match` | `{"task", "category"?, "max_price"?, "top_k"?}` → 402 견적 |
| POST | `/match/accept` | `{"quote_id"}` + 결제 헤더 → 후보 연락처 |
| POST | `/match/feedback` | `{"match_id","agent_id","service","success","rating"?}` + `X-Signature` |
| GET | `/stats` | 수수료 수익·카테고리별 매칭 (관리자) |

## 한계

- 매칭 후에는 구매자가 같은 판매자와 브로커 없이 직접 거래할 수 있습니다. 이 구조는 수수료를 강제하지 않는 대신 자금을 맡지 않는 쪽을 택했습니다. 반복 거래까지 수수료를 받으려면 대금을 브로커가 중계해야 하는데, 그러면 핫월렛 보관과 규제 부담이 생깁니다.
- 판매 에이전트의 가용성(헬스체크)은 아직 주기적으로 확인하지 않습니다. 실패 평가가 쌓이면 순위가 내려갈 뿐입니다.
- 분당 요청 제한은 프로세스 메모리 기반입니다. 서버를 여러 대 띄우면 Redis 등 공유 저장소로 바꿔야 합니다.
- 메인넷 운영 전에 테스트넷에서 충분히 검증하세요. 암호화폐 수수료 수익에는 세무·법적 의무가 생길 수 있습니다.
