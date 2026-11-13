# 경쟁·유사 서비스 조사 (원자료)

- 조사 시각: 2026-11-14 04:54 KST, 웹 검색과 공식 페이지 읽기만 했다(가입·로그인·폼 제출·연락 없음).
- 표기: 날짜는 "출처 페이지의 날짜(없으면 '날짜 없음, 11-14 열람')"다. 공식 문서·가격 페이지 > 회사 블로그 > 언론 > 제3자 블로그 순으로 믿었다.
- **미확인** = 공식 출처로 확인하지 못함(제3자 단독, 수치 불일치, 페이지에 없음).
- 기호: ● 있음 / ◐ 부분 / ○ 없음(공개 자료 기준) / ? 미확인
- 우리 비교 기준: (a) 발견·레지스트리 (b) 독립 검증·시험·점수 (c) 여러 제3자 에이전트·도구를 묶어 새 에이전트·워크플로우 하나로 공급 (d) 실패 시 대체·라우팅·자동 교체 (e) 상시 감시·재시험

---

## 1. 비교표

### 1-A. 가장 가까운 후보 (a·b·d·e 중 2개 이상)

| 서비스 | (a) 발견 범위 | (b) 독립 검증·시험·점수 | (c) 묶어서 새 에이전트 하나로 공급 | (d) 대체·교체 | (e) 상시 감시 | 프로토콜 | 사업 모델·가격 | 규모·자금(날짜) | 출처 |
|---|---|---|---|---|---|---|---|---|---|
| **SealKeeper** (sealkeeper.run) | ● 공개 에이전트·서비스를 스스로 찾고 URL로 추가. 홈 "Today": 에이전트 4,798, 서비스 21,661 검사(날짜 없음, 11-14 열람) | ● Agent SEAL(다른 운영자가 낸 과제를 풀고 검증된 결과로 Trust Score), Service SEAL(동작·운영자·약관 검사). Bronze/Silver/Gold, 서명된 SEAL을 누구나 확인. 자기 운영자 에이전트 간 점수 불인정. 점수 공식 비공개 | ○ 없음 | ◐ LangChain·n8n 게이트(SEAL로 Pass/Block). 대체 공급은 없음 | ● "checks today 112,482", Silver 서비스는 30일 안정 유지 조건 | A2A(0.3·1.0 자체 에이전트), MCP(hosted `api.sealkeeper.run/mcp`), x402·MCP 서비스 검사 | 오픈 베타 무료, CLI 오픈소스 | 자금 미확인. Product Hunt 출시 2026(약 10월, 미확인). 약관 11-10 갱신 | https://sealkeeper.run , https://www.producthunt.com/posts/1271709 |
| **HOL Registry Broker** (Hashgraph Online, hol.org) | ● 15개 레지스트리 집계 104,504 에이전트(2026-03-04): Agentverse 36,338, ERC-8004 18,344, PulseMCP 16,510, Moltbook 14,436, x402 Bazaar 7,606, Virtuals 6,983, NANDA 2,702, OpenRouter 535 등 | ● HCS-25 AI Trust Score(공개 방법론): 16개 신호군·17개 어댑터, 가용성·연결성 실측 프로브 + SimpleMath/SimpleScience 정답 시험 + Arena 쌍대 비교 + 출력 검증 + 결제·분쟁 기록. 0~100, 오래된 값은 감쇠 | ○ 묶음 없음. "Universal Comms"로 UAID 하나로 아무 에이전트에 메시지 중계 | ○ 대체 설명 없음 | ◐ 가용성 프로브·`trustScoreUpdatedAt` 기록. 주기 미확인 | MCP, A2A, ERC-8004, Virtuals, NANDA, x402 Bazaar, OpenRouter, Hedera HCS | 미확인(가격 필터만 있음) | 일 30만+ 요청, HCS 일 3,300만+ 연산(자사 주장, 날짜 없음) | https://hol.org/blog/state-of-ai-agents-march-2026 , https://hol.org/standards/ai-trust-score , https://hol.org/registry |
| **Agoragentic** | ◐ 마켓플레이스·라우터(제공자 수 미공개) | ◐ 자동 샌드박스 검증 → verified / reachable / failed 상태, 라우팅 점수에 반영(시험 내용 미공개) | ◐ 과제 단위 `execute()`가 제공자 1개로 라우팅. "Browse workflows"·Triptych OS(swarm) 언급만, 여러 제공자 체인을 한 상품으로 파는지 미확인 | ● `execute()`: 최적 제공자 선택, 일시 오류면 다음 제공자로 자동 대체, 스키마 오류는 차단. 신뢰·가격·지연·성공률로 점수 | ◐ 성공률·지연을 라우팅 점수에 되먹임. 별도 감시 없음 | MCP, A2A, x402(`x402.agoragentic.com/v1/{slug}`), REST, USDC on Base | 판매자 97% 수령(수수료 3%), 기타 미공개 | 2025 Q4 출시, 2026 Q1 Execute Router. 창업자 1명, 자금 미확인 | https://agoragentic.com/about.html , https://agoragentic.com/agent-to-agent-commerce/ , https://agoragentic.com/guides/ai-agent-marketplace-buyers-guide-2026/ (2026-03-25) |
| **Glama** | ● 오픈소스 서버 120,659(2026-11-13 표시), 원격 커넥터 40,151(Apideck 2026-10-31) | ● 라이선스·품질·유지보수 등급, TDQS(도구 정의 6개 차원 1~5), 서버 응집도, Firecracker 샌드박스 행동 관찰(악성·위험 표시). 헬스체크는 세션 열고 목록만, **도구 호출은 안 함** | ○ 없음(Gateway는 접근 제어·로그용) | ○ | ● 커밋마다 재스캔, 커넥터는 상시 스윕(건강 22,362 / 불건강 15,392, 10-31). 스키마 변화 이력 공개 | MCP | 등재 무료, Boost $49/월, Gateway(가격 미확인) | 지난 12개월 100만+ 스캔(자사). 자금 미확인 | https://glama.ai/mcp/servers , https://glama.ai/mcp/methodology , https://www.apideck.com/blog/mcp-server-directories |
| **Arcade.dev (+Smithery, ToolBench)** | ● Smithery 디렉터리 27,365(10-31). ToolBench 9만+ 오픈소스 서버·63만+ 도구 재스캔(2026-09-30) | ● ToolBench: 정의 품질·프로토콜 준수·보안·지원성 등급(정적 분석 중심, 실호출 여부 미확인). A 이상 0.5%(2026-03) | ◐ 자사 도구 실행 런타임(인증·권한). 제3자 도구를 묶어 새 에이전트로 파는 기능은 없음 | ○ | ◐ 재스캔은 3월 출시 뒤 9월 1회 확인, 주기 미확인 | MCP | 기업용 유료(가격 미확인). Smithery 프록시·유료 구독 10-31 종료 | Series A $60M(2026-06-12, SYN Ventures 주도). Smithery 인수 2026-08-05 | https://arcade.dev/blog/smithery-joins-arcade , https://www.arcade.dev/blog/toolbench-rescan-90000-mcp-servers , https://toolbench.arcade.dev/methodology , https://smithery.ai/future |
| **Fetch.ai Agentverse + ASI:One** | ● 등록 에이전트 200만~300만(자사·언론 수치 불일치, 2025-11~2026) | ◐ 핸들·검증 메타데이터·공개 활동 로그, AI가 자연어 질의로 에이전트를 시험(docs, 날짜 없음). 점수 공개 없음 | ◐ ASI:One이 질의를 가장 맞는 에이전트로 라우팅, "여러 검증된 브랜드 에이전트 조율"(2025-11 보도자료). 묶음을 새 에이전트로 공개하는 기능은 미확인 | ? 미확인 | ? 미확인 | 자체 Chat Protocol, uAgents. A2A·MCP 지원 여부 docs에 없음(미확인) | 기업 등급(Fetch Business), 수익화 "coming soon" | 2.7M 에이전트(자사, 미확인) | https://docs.agentverse.ai/docs , https://www.businesswire.com/news/home/20251119088395/en , https://venturebeat.com/ai/the-google-search-of-ai-agents-fetch-launches-asi-one-and-business-tier-for |
| **Virtuals ACP + Butler** | ● ACP 등록 에이전트 1,300+(Butler 검색 대상, Google Cloud 사례 인용·미확인) | ● 거래마다 평가 에이전트(Gemini 3.0 Flash 등)가 요청·조건·결과를 비교해 완료/거절. 졸업(graduation) 평가 통과해야 실사용 노출 | ◐ Butler가 과제를 맞는 에이전트로 보내고 "여러 에이전트 조율"(제3자 리뷰). 공식 분해 방식 미확인 | ◐ 평가 실패 시 거절·환불 구조(escrow). 자동 대체 미확인 | ◐ 거래별 평가(상시 재시험은 아님) | ACP(자체), x402, Base | 에이전트 토큰·거래 수수료 | aGDP $470M·완료 작업 177만(2026-02, 자사 수치·미확인) | https://forkast.news/the-machine-as-buyer-virtuals-acp-and-the-evaluator-problem/ , https://cloud.google.com/customers/virtualsprotocol , https://www.printmoneylab.com/2026/04/acp-agent-episode-7-graduated-revenue-honest-numbers.html |
| **x402station** | ● agentic.market 카탈로그 86,599 x402 엔드포인트(2026-05-15) | ● 10분마다 프로브. zombie(30일+ 결제 0), decoy(300초+ 함정), wildcard_402, spa_fallback, 집중 위험 표시. 유료 verified 배지 | ○ | ◐ 결제 전 `/api/v1/preflight` 위험 확인(대체 공급은 아님) | ● 10분 주기 | x402 | 무료 시험 10회/IP/일, 나머지 미확인 | 미확인 | https://x402station.io/blog/signal-layer-after-86k-probes |
| **Decixa** | ● x402 30,000+ 추적, 5,500+ 실작동 확인(2026-04) | ● 실제 프로브로 유효한 402 응답 확인, 신뢰도 순 정렬, 업타임·지연·비용·trust score | ○ | ◐ `resolve`가 의도에 맞는 후보를 순위 목록으로 반환(자동 대체는 미확인) | ◐ 업타임 추적(주기 미확인) | x402, MCP(`npx decixa-mcp`) | 미확인 | 미확인 | https://dev.to/ucchy/were-building-google-for-ai-agents-2728 , https://dev.to/ucchy/x402-has-5500-working-apis-only-32-are-for-storing-data-or-sending-messages-51b9 |
| **agentstatus.dev** (Carmel Labs) | ◐ 공개 MCP 서버(수 미공개) | ● 접속·도구 목록·**안전한 읽기 도구 실제 호출**, "결과가 일처럼 보이나" 판정. 0~100(도달 35·도구 성공 30·속도 20·사양 15) 공개 | ○ | ○ | ● 약 6시간마다, 최근 7일 프로브 | MCP, WebMCP | 공개 서버 무료, 유료 요금 미확인 | 미확인 | https://agentstatus.dev/mcp-methodology (날짜 없음, © 2026) |
| **MCP Verified** | ◐ 공식 MCP Registry 표본 750개 | ● 샌드박스 설치·실행·핸드셰이크·무인자 도구 1회 호출. 750개 중 427개 작동(2026-10-19) | ○ | ○ | ● 주 1회 | MCP | Pro $9/월, Team $29/월(피드·변경 알림) | 미확인 | https://buttondown.com/mcpverified/archive/mcp-verified-1-427-of-750-mcp-servers-actually/ |

### 1-B. 디렉터리·레지스트리 (주로 a, 일부 b)

| 서비스 | (a) | (b) | (c) | (d) | (e) | 프로토콜 | 사업 모델 | 규모·자금 | 출처 |
|---|---|---|---|---|---|---|---|---|---|
| 공식 MCP Registry | ● 53,541(활성 52,702, 2026-10-31) | ○ 메타데이터만, 평가 안 함. 네임스페이스 소유만 검증 | ○ | ○ | ○ (디렉터리가 매시간 폴링하라는 권고) | MCP | 무료·오픈소스(프리뷰) | MCP 프로젝트 운영 | https://www.apideck.com/blog/mcp-server-directories |
| Smithery | ● 27,365(10-31) | ○ | ○ | ○ | ○ | MCP | 프록시·계정·CLI 2026-10-31 종료, Arcade가 운영하는 단순 디렉터리로 남음 | Arcade 인수(2026-08-05) | https://smithery.ai/future , https://arcade.dev/blog/smithery-joins-arcade |
| PulseMCP | ● 21,614(10-31) | ○ (주간 방문자 추정치만) | ○ | ○ | ○ 신규 등록·수정 동결 | MCP | 미확인 | 미확인 | https://www.apideck.com/blog/mcp-server-directories |
| mcp.so | ● 수 미확인 | ○ | ○ | ○ | ○ | MCP | 미확인 | 미확인 | (이번 조사에서 공식 수치 못 찾음, 미확인) |
| MCP Market | ● 50,999(10-31) | ○ ($29 유료 "Official" 배지) | ○ | ○ | ○ | MCP | 유료 빠른 등재 $29 | 미확인 | https://www.apideck.com/blog/mcp-server-directories |
| Docker MCP Catalog/Toolkit | ● 300+ 검증 서버(컨테이너 이미지) | ◐ 출처·버전·보안 업데이트 관리(카탈로그 절차, 동작 시험 아님) | ○ | ○ | ○ | MCP | 무료(Toolkit 베타) | Docker 사내 | https://docs.docker.com/ai/mcp-catalog-and-toolkit.md |
| Coinbase x402 Bazaar / Agentic.Market | ● Bazaar 23,000+ 자원(날짜 없음), Agentic.Market 365+ 서비스 7개 범주(2026-04-20 출시) | ○ 승인 절차 없음, x402 호환이면 등재 | ○ | ○ | ○ (실시간 가격·성능 표시 예정 언급) | x402, USDC on Base | 결제 레일 수수료(제3자 분석) | x402 누적 1.65억 거래·약 $50M(2026-04, 제3자) | https://docs.cdp.coinbase.com/x402/bazaar.md , https://blockeden.xyz/blog/2026/04/22/coinbase-agentic-market-launch-x402-165m-transactions-base-agent-commerce/ |
| Circle Agent Marketplace Discovery API | ● x402 서비스(15+ 체인, 6개 범주) | ◐ 큐레이션 + 판매자 제재 상시 대조. 품질 점수 없음 | ○ | ○ | ◐ `lastUpdated`만 | x402 v2, http·mcp | 무료 공개 API | 미확인 | https://developers.circle.com/agent-stack/agent-marketplace/discovery-api.md (샘플 2026-06-25) |
| MIT NANDA Index | ● 2,702(HOL 집계 2026-03), 15개 기관 호스팅 | ◐ 암호 서명된 AgentFacts(신원·능력 증명, 품질 시험 아님) | ○ | ○ | ○ | NANDA, A2A·MCP 연결 | 연구·오픈 | MIT 미디어랩 | https://www.media.mit.edu/publications/beyond-dns-unlocking-the-internet-of-ai-agents-via-the-nanda-index-and-verified-agentfacts/ |
| ERC-8004 탐색기 (8004scan, QuickNode) | ● 등록 519,333 에이전트·평판 589,322건 / 30개 망(2026-09, 제3자) | ◐ 평판 레지스트리(사용자 피드백). Validation Registry는 메인넷 미배포(2026-09 기준) | ○ | ○ | ○ | ERC-8004, A2A 카드 | 무료 탐색기 | QuickNode 탐색기 2026-05 출시 | https://erc-8004.quicknode.com/learn/registries/validation , https://www.datawallet.com/de/crypto/erc-8004-explained |
| agentconcierge.io | ● 22,309 에이전트·7개 마켓(날짜 없음, © 2026) | ○ 적합도·신뢰도 점수라고 하나 방법 공개 없음, 커뮤니티 평점 | ◐ "Team Stacks"(조직용 묶음 목록, 실행 묶음 아님) | ◐ "Swap Alerts": 더 나은 에이전트가 나오거나 성능이 떨어지면 알림 | ◐ ROI 대시보드 | 미확인(사람용 추천) | Free / Pro $11.11 / Business $99 / Enterprise | 사전 가입 2,400+(자사) | https://agentconcierge.io |
| Arcade ToolBench (단독 표기) | 위 Arcade 행 참조 | | | | | | | | |

### 1-C. 연결·통합·워크플로우 플랫폼 (주로 c, 일부 d)

| 서비스 | (a) | (b) | (c) | (d) | (e) | 프로토콜 | 사업 모델 | 규모·자금 | 출처 |
|---|---|---|---|---|---|---|---|---|---|
| Composio | ◐ 자사 툴킷 ~1,000(앱 500~1,500, 출처마다 다름) | ○ | ◐ Tool Router(2026-05 GA, 제3자): 세션 하나로 여러 툴킷 노출. 자사 통합만, 제3자 서버 검증 묶음 아님 | ○ | ○ | MCP, SDK | 사용량 요금(미확인) | 총 $29M, Series A $25M(2025-07) | https://composio.dev/blog/introducing-tool-router-(beta) , https://chatforest.com/reviews/composio-mcp-server/ |
| Zapier MCP / Agents | ◐ 9,000+ 앱, 3~4만 액션 | ○ | ● Zap·에이전트를 MCP로 노출(자사 통합 기반) | ◐ Zap 재시도(제3자 에이전트 대체 아님) | ○ | MCP | 구독 | 미확인 | https://docs.zapier.com/mcp/home.md |
| Pipedream MCP | ◐ 3,000+ 앱·1만+ 도구 | ○ | ◐ 워크플로우 | ○ | ○ | MCP | 구독 | Workday 인수(2025-11 발표) | https://rywalker.com/research/pipedream |
| n8n | ○ (템플릿 공유) | ○ | ● MCP Server Trigger로 **워크플로우 하나를 MCP 도구로 노출**, MCP Client로 외부 서버 호출. v2.14(2026-04) 자연어로 워크플로우 생성 | ◐ 오류 워크플로우(사용자가 직접 구성) | ○ | MCP | 오픈코어·구독 | Series C $180M, 가치 $2.5B(2025-10). SAP 투자 $5.2B(2026-05, 미확인) | https://sacra.com/research/n8n , https://www.highlandeurope.com/n8n-raises-180m-to-get-ai-closer-to-value-with-orchestration/ |
| Toolhouse | ◐ MCP 도구 스토어 1,000+(미확인) | ○ | ◐ 에이전트를 API로 배포(Agent BaaS) | ○ | ○ | MCP | 무료 50회/월(미확인) | 7,000+ 팀(미확인) | https://qveris.ai/guides/toolhouse-alternatives/ |
| QVeris | ◐ "capability routing network"(수 미공개) | ◐ 가격·지연·성공 신호 확인(측정 방법 미공개) | ○ | ◐ provider routing(자동 대체 미확인) | ◐ 실행 기록 | 미확인 | 크레딧 $19/1만, 발견·조회 무료 | 미확인 | https://qveris.ai/guides/toolhouse-vs-qveris/ (2026-03-12, 07-30 확인) |
| Agent.ai | ● 수천 에이전트(docs) | ○ (평점) | ◐ 노코드 에이전트 빌더 | ○ | ○ | 미확인 | 무료·크레딧 | 100만+ 사용자(미확인) | https://docs.agent.ai/ |
| Relevance AI / Gumloop | ○ | ○ | ◐ 노코드 에이전트·워크플로우 빌더 | ○ | ○ | MCP 일부 | 구독 | 이번 조사에서 2026 자금 미확인 | (미확인) |
| Olas (Pearl, Mech Marketplace) | ◐ 에이전트가 다른 에이전트를 고용하는 시장(2025-02-27 출시) | ○ (스테이킹·온체인 기록) | ◐ 에이전트가 Mech를 불러 하위 작업 위임 | ○ | ○ | 자체·온체인, Nevermined 결제 연동 | 토큰 경제 | $13.8M(2025 초). 구형 Mech 은퇴(2026 Q1) | https://olas.network/blog/olas-q1-2026-roundup , https://siliconangle.com/2025/02/27/olas-launches-decentralized-ai-marketplace-ai-agents-can-hire/ |
| Nevermined | ○ | ○ | ○ | ○ | ○ | x402, 카드 위임(Visa) | 에이전트 결제·과금 인프라 | 미확인 | https://nevermined.ai/blog/nevermined-unlocks-autonomous-agent-card-payments-with-x402-opening-a-new-market-for-publishers-digital-merchants |

### 1-D. 게이트웨이·기업 마켓플레이스

| 서비스 | (a) | (b) | (c) | (d) | (e) | 프로토콜 | 사업 모델 | 규모·자금 | 출처 |
|---|---|---|---|---|---|---|---|---|---|
| MetaMCP | ○ (자체 호스팅) | ○ | ◐ 여러 MCP 서버를 네임스페이스 하나의 엔드포인트로 집계(도구 이름 접두어). 단계 실행 워크플로우는 아님 | ○ | ○ | MCP | 오픈소스 | — | https://docs.metamcp.com/en/concepts/namespaces |
| MCPJungle | ◐ 사내 레지스트리 | ○ | ◐ `/mcp` 단일 게이트웨이 | ○ | ○ | MCP | 오픈소스(MPL-2.0) | — | https://dev.co/ai/mcp/mcpjungle |
| Portkey MCP Gateway | ◐ 사내 MCP 레지스트리(2026-01 GA) | ○ | ◐ 단일 게이트웨이 | ● LLM 쪽 대체·재시도는 강함. MCP 서버 간 대체는 미확인 | ◐ 관측 | MCP, LLM | 2026-03-24 전면 오픈소스, Palo Alto Networks 인수(2026-05-29, 미확인) | 일 1~2조 토큰 | https://portkey.ai/docs/changelog/2026/january , https://www.globenewswire.com/news-release/2026/03/24/3261574/0/en/Portkey-s-Gateway-is-Now-Fully-Open-Source-Processing-over-1-Trillion-Tokens-Every-Day.html |
| AWS Marketplace AI Agents & Tools + AgentCore Gateway / Agent Registry | ● 파트너 에이전트·도구 카탈로그(2025-07), 사내 Agent Registry(2026-08-31 GA) | ◐ 판매자 심사(동작 시험 공개 없음) | ◐ 구매한 원격 MCP를 AgentCore Gateway 대상으로 추가 | ○ | ○ | MCP, A2A | 계약·사용량 요금 | AWS | https://aws.amazon.com/about-aws/whats-new/2026/08/aws-agent-registry-generally-available |
| Google Cloud AI Agent Marketplace / Gemini Enterprise | ● 파트너 에이전트(수천 vs 50+ 인증, 불일치) | ◐ A2A·Gemini Enterprise 통합 검증(파트너 검증 양식) | ○ | ○ | ○ | A2A(Agent Card 필수) | 마켓 수수료 | Google | https://docs.cloud.google.com/marketplace/docs/partners/ai-agents |
| Microsoft Agent Store / Copilot Studio | ● 출시 70+ 에이전트(2025-05) | ◐ 스토어 심사 | ◐ Copilot Studio에서 다중 에이전트 | ○ | ○ | MCP, A2A | M365 라이선스 | 400k+ 에이전트·160k 조직(2026-07, 미확인) | https://www.pymnts.com/artificial-intelligence-2/2025/ai-models-and-tools-microsoft-launches-agent-store-marketplace/ |
| Salesforce AgentExchange | ● 200+ 파트너(출시 시) | ◐ AppExchange 보안 심사 | ◐ Agentforce 템플릿 | ○ | ○ | 자체·MCP | 마켓 수수료 | Agentforce ARR 약 $800M(2026 Q1, 제3자) | https://agentmarketcap.ai/blog/2026/04/12/enterprise-agent-marketplace-war-q2-2026 |
| OpenAI AgentKit / Apps in ChatGPT | ◐ Connector Registry(사내 관리), 앱 디렉터리(출시 여부 미확인) | ○ (Evals는 자사 에이전트용) | ◐ Agent Builder 다중 에이전트 캔버스 | ○ | ○ | MCP, Apps SDK | API 사용량 | **Agent Builder·Evals 2026-06-03 종료 공지**(OpenAI 페이지 표기, 세부 미확인) | https://openai.com/index/introducing-agentkit/ |

(참고·유비) OpenRouter는 LLM 모델에 대해 "여러 제공자 + 실패 시 자동 대체"를 이미 상용화했다. 에이전트·도구 층에서 같은 일을 하는 것이 우리 목걸이 슬롯 대체 사슬이다. OpenRouter 세부는 이번에 재확인하지 않았다(미확인).

---

## 2. 가장 가까운 10곳: 겹치는 점과 다른 점

### 2-1. SealKeeper (sealkeeper.run) — 가장 직접적인 경쟁자
- **겹침**: 키 없이 공개 에이전트(A2A 카드)와 서비스(x402·MCP)를 스스로 찾아 검사하고, 결과를 공개한다. 하루 112,482회 검사로 상시 감시도 한다. MCP 서버·A2A 에이전트·LangChain 게이트·n8n 노드로 "쓰기 전에 신뢰 확인"을 에이전트에게 공급한다. 우리 (a)(b)(e)와 범위가 거의 같다(에이전트 4,798, 서비스 21,661, 날짜 없음, 11-14 열람).
- **다름**: 검증 방식이 "다른 운영자가 낸 과제를 풀어 쌓는 평판(Strava형)"이다. 우리는 정답을 아는 역할 과제로 직접 시험하고 보고서를 공개한다. 그쪽은 에이전트 소유자가 CLI로 참여해야 Silver 이상이 되고, 우리는 소유자 참여 없이 시험한다. 묶음(c)·대체 공급(d)·"단일 최고보다 나은지(Δ)" 비교는 없다. SealKeeper는 **신뢰 신호를 파는 층**이고 우리는 **검증된 결과물(목걸이)을 파는 층**이다.
- 출처: https://sealkeeper.run (약관 2026-11-10 갱신), https://www.producthunt.com/posts/1271709

### 2-2. HOL Registry Broker (Hashgraph Online)
- **겹침**: 여러 프로토콜(MCP·A2A·ERC-8004·x402 Bazaar·Virtuals·NANDA·Agentverse)을 하나로 모으는 집계형 레지스트리다(104,504, 2026-03-04). 공개 신뢰 점수 HCS-25에 **정답이 있는 시험(SimpleMath·SimpleScience)**, 쌍대 비교(Arena), 가용성 프로브까지 들어 있어 우리 (b)와 개념이 가장 비슷하다. UAID 하나로 어떤 에이전트에게나 메시지를 보내는 중계도 있다.
- **다름**: 시험이 범용 기초 문제다. 우리처럼 역할별 정답 세트로 시험하고 역할마다 "최종 진주"를 뽑지 않는다. 묶음·대체·Δ 공급은 없다. 중계는 단일 에이전트 호출이다.
- 출처: https://hol.org/blog/state-of-ai-agents-march-2026 , https://hol.org/standards/ai-trust-score (샘플 2026-09-02), https://hol.org/registry

### 2-3. Agoragentic
- **겹침**: 우리 (d)에 가장 가깝다. `execute()`가 과제를 받아 신뢰·가격·지연·성공률로 제공자를 고르고, 일시 오류면 **다음 제공자로 자동 대체**한다. 샌드박스 검증 상태(verified/reachable/failed)가 라우팅에 반영된다. MCP·A2A·x402·USDC on Base로 우리와 같은 결제 레일이다.
- **다름**: 단위가 "능력(capability) 하나 → 제공자 하나"다. 진주 2개 이상을 엮어 새 에이전트로 공개하는지(c)는 확인되지 않았다("Browse workflows" 링크만). 제공자는 등록·판매자 모델이고, 우리는 공개 에이전트를 키 없이 수집한다. 시험 보고서·정답 세트·Δ 기준은 공개하지 않는다. 규모·자금은 미확인(창업자 1인 표시).
- 출처: https://agoragentic.com/about.html , https://agoragentic.com/agent-to-agent-commerce/ (© 2026), https://agoragentic.com/guides/ai-agent-marketplace-buyers-guide-2026/ (2026-03-25)

### 2-4. Glama
- **겹침**: 가장 큰 MCP 목록(오픈소스 120,659, 원격 40,151)과 품질 등급(TDQS·라이선스·유지보수), 커넥터 상시 헬스체크, 커밋마다 재스캔, 스키마 변화 이력 공개. 우리가 "뒤처지지 않아야 할" 기준선이다.
- **다름**: 헬스체크가 도구 목록까지만 하고 **도구를 호출하지 않는다**(방법론에 명시). 과제 성공 여부를 재지 않는다. MCP만 다루고 A2A·x402는 없다. 묶음·대체 없음.
- 출처: https://glama.ai/mcp/methodology , https://glama.ai/mcp/servers (2026-11-13 표시), https://www.apideck.com/blog/mcp-server-directories (2026-10-31)

### 2-5. Arcade.dev (+ Smithery, ToolBench)
- **겹침**: 발견(Smithery 27,365) + 품질 등급(ToolBench 9만+ 서버, 2026-09-30) + 실행 런타임을 한 회사가 갖췄다. "도구 공급망(supply chain)"을 쥐겠다는 전략이 우리와 같은 방향이다. $60M Series A(2026-06-12).
- **다름**: ToolBench는 정의·프로토콜·보안 중심 정적 등급이다(실호출 시험 여부 미확인). 실행은 Arcade 자체 도구와 기업 권한 관리 중심이다. 제3자 도구를 묶어 새 에이전트로 공급하거나 대체 사슬을 두지 않는다. Smithery는 10-31에 프록시·계정을 닫고 디렉터리로만 남았다. MCP 전용.
- 출처: https://arcade.dev/blog/smithery-joins-arcade (2026-08-05), https://www.arcade.dev/blog/toolbench-rescan-90000-mcp-servers , https://smithery.ai/future

### 2-6. Fetch.ai Agentverse + ASI:One
- **겹침**: 대형 에이전트 레지스트리(자사 270만, 미확인)와 "질의를 가장 맞는 에이전트로 보내는" LLM 라우터 ASI:One. "여러 검증된 브랜드 에이전트 조율"을 내세운다(2025-11-19). AI가 자연어 질의로 에이전트를 시험한다는 문구도 있다.
- **다름**: 자기 생태계(uAgents·Chat Protocol) 안에서만 돈다. 외부 A2A·MCP·x402 수집은 확인되지 않았다. 시험 결과나 점수는 공개하지 않는다. 대체·재시험·Δ 공급 기준도 확인되지 않았다.
- 출처: https://docs.agentverse.ai/docs , https://www.businesswire.com/news/home/20251119088395/en

### 2-7. Virtuals ACP + Butler
- **겹침**: 거래마다 평가 에이전트가 결과를 검사하고(b), 졸업 평가를 통과해야 실제 사용자에게 노출된다(우리 "진주 선발"과 유사). Butler는 사용자 과제를 에이전트에게 보내고 여러 에이전트를 조율한다고 소개된다(c 일부). x402·Base.
- **다름**: 평가는 거래 사후 판정이고, 정답 세트로 매일 재시험하지 않는다. 생태계는 Virtuals 등록 에이전트(약 1,300)로 닫혀 있다. 묶음을 새 에이전트로 공개하는지, 대체 사슬이 있는지는 공식 문서로 확인되지 않았다. 수치는 대부분 자사 발표다.
- 출처: https://cloud.google.com/customers/virtualsprotocol , https://forkast.news/the-machine-as-buyer-virtuals-acp-and-the-evaluator-problem/ , https://www.printmoneylab.com/2026/04/acp-agent-episode-7-graduated-revenue-honest-numbers.html

### 2-8. x402station / Decixa (x402 검증 계층)
- **겹침**: x402 엔드포인트를 실제로 찔러 보고(10분 주기 86,599개 / 30,000개 중 5,500개 실작동), 죽은 곳·함정·와일드카드 402를 걸러낸다. 우리 x402 연결 확인(결제 없는 402 = 전송 증거)과 같은 층이다. Decixa는 의도로 후보 순위를 돌려준다.
- **다름**: x402만 다룬다. 과제 정답 시험은 없다. 묶음·대체 공급이 없다(preflight 경고와 순위 목록까지만).
- 출처: https://x402station.io/blog/signal-layer-after-86k-probes (2026-05-15, 05-31 정정), https://dev.to/ucchy/were-building-google-for-ai-agents-2728

### 2-9. agentstatus.dev / MCP Verified (MCP 실호출 감시)
- **겹침**: 우리 MCP 헬스체크·안전한 읽기 전용 시험 호출과 방법이 거의 같다. agentstatus는 약 6시간마다 안전한 읽기 도구를 실제로 호출하고 "결과가 일처럼 보이는지"까지 점수에 넣는다(0~100 공개). MCP Verified는 매주 750개를 설치·실행·호출한다(427/750 작동, 2026-10-19).
- **다름**: 정답이 있는 역할 과제가 아니다. 단일 서버 상태만 본다. 묶음·대체 없음. MCP만.
- 출처: https://agentstatus.dev/mcp-methodology , https://buttondown.com/mcpverified/archive/mcp-verified-1-427-of-750-mcp-servers-actually/

### 2-10. n8n / MetaMCP (묶어서 엔드포인트 하나로)
- **겹침**: n8n은 워크플로우 하나를 MCP 도구 하나로 노출한다(MCP Server Trigger). 우리 "목걸이 = 새 MCP 도구"와 공급 형태가 같다. MetaMCP는 여러 MCP 서버를 네임스페이스 하나로 묶는다.
- **다름**: 사용자가 직접 만드는 도구다. 어떤 구성 요소가 좋은지 고르는 발견·검증이 없다. 대체는 사용자가 오류 흐름을 직접 짜야 한다. 매일 재시험이나 Δ 기준도 없다. 자금은 n8n $180M Series C, $2.5B(2025-10).
- 출처: https://sacra.com/research/n8n , https://docs.metamcp.com/en/concepts/namespaces

---

## 3. 기능 비교

### 3-A. 공개 자료로 볼 때 아무도 제공하지 않고 우리만 하는 것
1. **역할별 정답 세트로 시험하고, 시험 보고서를 공개해 역할마다 "최종 진주"를 뽑는 것.** HOL은 범용 기초 시험, SealKeeper는 다른 운영자 과제 기반 평판, Virtuals는 거래별 사후 평가다. 역할별 정답 세트·보고서·1위 선정을 함께 하는 곳은 없다.
2. **검증된 제3자 에이전트 2개 이상을 엮어 새 에이전트(MCP·A2A·웹) 하나로 공개하는 것.** n8n·MetaMCP는 사용자가 직접 엮는 도구이고, 운영자가 검증 뒤 묶어 공급하지 않는다.
3. **"같은 정답 세트에서 단일 최고 에이전트보다 나을 때(Δ>0) + 95% 관문 통과"일 때만 공급하는 규칙.** 이런 공개 공급 기준은 어디에도 없다.
4. **슬롯마다 대체 사슬(주 진주 → 외부 대체 여럿 → 자체 대체 에이전트 최대 2개), 전부 실패하면 묶음 중지·새 묶음으로 교체·이용자 통지.** Agoragentic의 자동 대체는 단일 능력 수준이고, 자체 대체 에이전트나 교체 통지는 없다.
5. **A2A·MCP·x402 세 가지를 키 없이 한곳에서 수집(약 39만)하고 자체 프로브로 등급까지 매기는 것.** HOL은 다른 레지스트리를 모으기만 한다(10만). SealKeeper는 세 가지를 다 보지만 규모가 작다(약 2.6만). Glama·agentstatus는 MCP만, x402station·Decixa는 x402만 다룬다.
6. **홍보 단위가 개별 에이전트가 아니라 묶음(목걸이)이다.** 모든 경쟁자는 개별 에이전트·서버를 노출한다.

### 3-B. 남들은 하는데 우리에게 없거나 약한 것
1. **소유자 참여형 검증과 서명된 증명서**(SealKeeper SEAL, Bronze~Gold, 공개 키로 로컬 검증, DNS 도메인 인증). 우리는 등급을 서명된 이식 가능 증명으로 내보내지 않는다.
2. **다른 프레임워크에 바로 꽂는 게이트**: SealKeeper의 LangChain 게이트, n8n Pass/Block 노드, 배지 엔드포인트. x402station의 결제 전 `preflight`.
3. **공개 점수 방법론 문서**(HOL HCS-25, agentstatus 가중치 공개, Glama TDQS 방법론, ToolBench 방법론). 우리 점수 규칙의 외부 공개 수준과 비교해 볼 것.
4. **실행 중개와 결제 정산**: Agoragentic `execute()`(USDC on Base, 판매자 97%), Virtuals escrow·평가 뒤 정산. 우리는 결제 스위치가 꺼져 있다.
5. **고빈도 감시**: x402station 10분, agentstatus 약 6시간, Glama 커밋마다·상시 스윕. 우리 목걸이는 매시간 감시·매일 재시험이고, 개별 수집 대상의 재검사 주기는 별도 확인이 필요하다.
6. **행동 기반 보안 관찰**: Glama Firecracker 샌드박스(악성·위험 판정), Docker 서명·출처 관리.
7. **소유자 클레임·자기 정보 수정 경로**(Glama `glama.json`, SealKeeper claim, HOL UAID).
8. **규모와 유통**: Glama 16만, Agentverse 수백만(자사), 클라우드 마켓(AWS·Google·Microsoft·Salesforce)의 구매·과금 경로.
9. **집계 범위**: HOL은 Agentverse·Virtuals·NANDA·Moltbook·OpenRouter까지 모은다. 이 레지스트리들이 우리 수집 대상에 들어 있는지 확인이 필요하다.

---

## 4. 종합 판정

**"발견 → 시험 보고서로 검증 → 묶음 → 대체 → 새 에이전트로 공급 → 재시험" 전체 사슬을 하는 서비스는 공개 자료로 확인되지 않았다(2026-11-14 기준).**

근거(사슬 단계별 최고 근접자):

| 단계 | 가장 가까운 곳 | 빠진 것 |
|---|---|---|
| 발견(A2A·MCP·x402) | HOL(10만, 집계), SealKeeper(약 2.6만, 자체 탐색), Glama(MCP 16만) | — |
| 시험 보고서로 검증 | HOL HCS-25(정답 있는 범용 시험), SealKeeper(과제 기반 평판), agentstatus(실호출) | 역할별 정답 세트 + 공개 보고서 + 역할 1위 |
| 묶음 → 새 에이전트 하나 | n8n MCP Server Trigger, MetaMCP 네임스페이스(사용자가 직접 구성) | 검증된 제3자 구성 요소를 운영자가 묶어 공급 |
| 대체 | Agoragentic `execute()` 자동 대체(능력 단위) | 묶음 슬롯 단위 대체 사슬, 자체 대체 에이전트, 중지·교체·통지 |
| 공급 기준 | 없음 | Δ>0 + 95% 관문 |
| 재시험 | x402station 10분, agentstatus 6시간, Glama 상시(모두 단일 대상 상태 감시) | 묶음 결과 품질의 매일 재시험 |

- **두 단계 이상을 합친 곳**: SealKeeper(a+b+e), HOL(a+b, e 일부), Agoragentic(b 일부+d), Glama(a+b+e), Arcade(a+b+실행)뿐이다. 셋 이상의 사슬을 끝까지 잇는 곳은 없다.
- **위협 순위(추정)**: ① SealKeeper — 범위(A2A·MCP·x402)와 키 없는 자체 탐색이 우리와 같고, 에이전트 게이트로 유통 중이다. ② Agoragentic — 대체 라우팅과 USDC on Base 결제가 이미 있어, 워크플로우를 붙이면 목걸이와 가장 빨리 겹친다. ③ HOL — 집계 범위와 공개 점수 방법론이 있다. ④ Arcade+Smithery — 자금($60M)과 "도구 공급망" 전략.
- **주의**: 대부분의 수치는 자사 발표이고 날짜가 없는 경우가 많다. SealKeeper·Agoragentic·HOL의 규모와 자금은 미확인이다. 비공개 기업 기능(AWS·Google 내부 평가 등)은 공개 자료 밖이라 판단하지 않았다.
