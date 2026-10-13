# A2A Discovery

AI 에이전트가 다른 AI 에이전트(A2A 에이전트, MCP 서버, x402 유료 API)를 **찾고, 확인하고, 소개받는** 서비스입니다.
공개 레지스트리와 온체인 등록부에서 에이전트를 모아 살아 있는지 점검하고, 품질을 평가한 뒤, 작업에 맞는 에이전트를 소개합니다.

## 구성: 세 단계로 발전

| 단계 | 모듈 | 하는 일 | 상태 |
|---|---|---|---|
| 1. 마켓 | `agent_market/server.py`, `buyer.py` | 에이전트끼리 작업을 사고팔고 USDC로 결제 (HTTP 402) | 예제. 결제·서명 모듈은 공용으로 씀 |
| 2. 브로커 | `agent_market/broker/` | 판매 에이전트 등록 → Claude로 작업 분류 → 매칭 | 게이트웨이로 대체 중. 카테고리·URL 검사는 공용 |
| 3. **게이트웨이 + 수집기** | `agent_market/gateway/`, `agent_market/collector/` | 에이전트 수집·헬스체크·평가, 요청에 맞는 에이전트 소개·재소개 | **현재 주력** |

```
 공개 출처                         수집기 (collector/)                      게이트웨이 (gateway/)
 x402 Bazaar ─┐                ┌ 연속 수집 (crawler)               ┌ POST /needs: 작업 → 최적 에이전트 소개
 MCP Registry ─┼──▶ SQLite ◀──┤ 헬스체크 (health)        ◀──────┤ 순위: 관련도·인기·가용성·가격·품질…
 ERC-8004     ─┤               │ 도구·인증 조사, 사용 검증         └ 재평가: 더 좋은 에이전트가 나오면 재소개
 well-known   ─┘               └ 규칙 기반 품질 평가 (A~F)
```

## 빠른 시작

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

게이트웨이를 실행하면 수집기가 함께 돕니다. 기본은 무료 정책이라 지갑 설정이 필요 없습니다. 주소는 http://127.0.0.1:8200 입니다.
```bash
GATEWAY_DB=gateway-data/collector.sqlite3 .venv/bin/python -m agent_market.gateway.server
```

수집기와 조회 API만 띄울 수도 있습니다(http://127.0.0.1:8300/stats). 게이트웨이와 같은 DB로 동시에 띄우지 마세요. 수집이 중복됩니다.
```bash
COLLECTOR_DB=gateway-data/collector.sqlite3 .venv/bin/python -m agent_market.collector.server
```

테스트:
```bash
.venv/bin/python -m pytest tests
```

## 문서

| 문서 | 내용 |
|---|---|
| [COLLECTOR.md](COLLECTOR.md) | 수집·헬스체크·인증 조사·사용 검증·품질 평가·A2A 수집, 실측 결과 |
| [AGENT_BROKER.md](AGENT_BROKER.md) | 14개 카테고리, 게이트웨이 요청 조건(언어·지역·인증·등급), 브로커 |
| [AGENT_MARKET.md](AGENT_MARKET.md) | 에이전트 간 USDC 결제 프로토콜과 보안 설계 |
| [deploy/DEPLOY.md](deploy/DEPLOY.md) | 무료 클라우드 VM에 게이트웨이 배포 |
| [reports/](reports/) | 시장 동향, MCP 서버 평가 방법, 에이전트 인프라 분류 보고서 |

## 안전 원칙

- 서버는 지갑 **주소**만 갖고 개인키는 갖지 않습니다.
- 외부 URL에는 리다이렉트를 따라가지 않습니다. 사설·내부 주소는 요청 전과 접속 순간에 두 번 확인해 막습니다.
- 남의 서버를 점검할 때는 호스트당 한 번에 하나씩, 간격을 두고 요청합니다. 파괴적인 도구는 호출하지 않습니다.
