# 목걸이 수요 조사 1차: 밖의 자료 (2026-11-15, PM)

사용자 지시(11-15): 목걸이는 지금 많이 찾는 주제를 조사해 만든다. 찾지 않는 목걸이를 만드는 데 시간을 쓰지 않는다.

## 1. 이 조사의 한계 (먼저 읽을 것)
- 수요 근거의 대부분은 PulseMCP의 "주간 추정 방문자"다. 실제 호출 수가 아니라 디렉터리 사이트의 추정치다. 같은 제공자 묶음에는 같은 숫자가 붙는다.
- Reddit·X·HN의 개발자 토론 원문은 열지 못했다. "개발자가 직접 말한 수요"의 원문 근거는 없다.
- Smithery·Glama의 사용량 순위, 공식 MCP Registry, mcp.so는 얻지 못했다.
- 원천 예시의 "키 없이 쓸 수 있음"은 이번에 확인하지 않았다. 약관 판정은 에이전트 팀이 따로 한다.
- 우리 자신의 질의 기록(검색·Chat·find_agents)은 이 문서에 없다. 검색과 RAG가 따로 낸다. 두 자료가 맞는 주제를 우선한다.

## 2. 수요 순 후보와 우리 정의의 대응

| 순 | 후보 | 수요 근거 (PulseMCP 주간 추정 방문, 11-15 열람) | 세기 | 우리 정의 |
|---|---|---|---|---|
| 1 | 라이브러리 최신 사용법 확인 | Context7 1.1m, GitMCP 130k, AWS Documentation 87.6k | 강함 | 없음 |
| 2 | 회사·거래처 실사 요약 | Edgar Tools 269k, Companies House UK 33.4k, OpenRegistry 19.2k | 강함 | company-due-diligence (후보) |
| 3 | 주제 조사 브리프 | Fetch 203k, Firecrawl 170k, Perplexity 54.1k, Tavily 52.6k. LangChain 조사 1,340명: 주 용도 "조사·데이터 분석" 24.4%로 2위 | 강함 | topic-evidence-brief (후보) |
| 4 | CVE 긴급 판단 | DataNexus 38.1k. 11-02~06 한 주에 주요 CVE 다수 | 보통~강함 | cve-incident-brief (후보) |
| 5 | 패키지·의존성 위험 점검 | TrendsMCP npm 26.1k, MCP Hub Security 34.8k | 보통 | package-risk-audit (후보) |
| 6 | MCP 서버·에이전트 도구 신뢰 점검 | Agentage Catalog 38.8k, AgentBazaar 38.8k, MCPFinder 33.7k | 보통 | 없음 (우리 카탈로그·시험 기록이 원천) |
| 7 | 상장사 실적·시장 스냅샷 | WeRead Finance 278k, Alpha Vantage 40.2k | 보통 | 없음 (sec-filings 자체 대체가 원천) |
| 8 | 법령·규제 조회 | KorDoc 69.2k, Legal Data Hunter 33.4k | 보통 | 없음 |
| 9 | 논문 근거 확인 | scite 29.7k, ToolUniverse 17.2k | 보통 | topic-evidence-brief의 papers 자리 |
| 10 | 암호화폐 토큰 점검 | CoinGecko 21.6k, TrendsMCP Crypto 26.1k | 보통 | 없음 (자체 대체를 만들 수 없는 역할) |
| 11 | 뉴스와 배경 브리프 | TrendsMCP News 26.1k | 보통 | 없음 (E9 보류, GDELT 자체 대체 준비 중) |
| 12 | 제재·컴플라이언스 선별 | DataNexus 38.1k | 약함~보통 | 없음 |
| 13 | 장소·여행 사실 | Google Maps 20.3k(키 필요) | 약함~보통 | 없음 |
| 14 | 도메인·웹사이트 신뢰 | 전용 서버의 상위 근거 없음 | 약함 | website-trust-brief (후보) |
| 15 | 날씨·재난 경보 | 큰 근거 없음 | 약함 | quakes-near-address, quakes-near-airport (후보) |
| - | 책·저자, 공휴일 | 근거를 찾지 못함 | 없음 | book-author-brief, holidays-at-address (후보) |

배경: PulseMCP 상위는 브라우저 조작과 개발 도구다(Playwright 5.5m 등). 읽기 전용 공개 데이터 서버 중에는 Context7(문서)과 Edgar Tools(공시)가 가장 높다.

## 3. 읽은 결과
- 우리가 관문 직전까지 만든 것(지진 두 개, 책·저자, 공휴일)은 수요 근거가 약하거나 없다.
- 수요가 강한 네 개(회사 실사, 주제 조사, CVE, 패키지 위험)는 이미 정의가 있는데 진주·대체 승인에서 막혀 있었다. 임시 멤버 규칙(11-15 사용자 지시)으로 이 네 개를 먼저 연다.
- 정의가 없는 것 가운데 먼저 만들 것: 1번(라이브러리 최신 사용법), 6번(MCP 서버 신뢰 점검), 7번(상장사 스냅샷). 6번은 우리 카탈로그와 시험 기록이 원천이라 남이 따라 하기 어렵다.

## 4. 만들지 않는 유형
- 쓰기·조작형(브라우저 자동화, 파일, 결제, 메시지 전송): 수요는 가장 크지만 읽기 전용 원칙 밖이다.
- 사내·개인 SaaS 데이터 결합(Notion, Slack 등): 로그인이 필요하다.
- 가격·상품 비교: 키 없는 공개 가격 원천이 거의 없다.
- 인물·구직·SNS 조회: 로그인·키가 필요하고 개인정보 위험이 있다.
- 단순 헤드라인 나열, 단일 원천 날씨·시간: 호출 1번으로 끝나 묶는 가치가 없다.

## 5. 홍보에 쓸 수 있는 밖의 숫자 (출처 확인된 것만)
- Anthropic "Advanced tool use"(2025-11-24): 5개 서버 58개 도구의 정의가 대화 전에 약 55K 토큰을 쓴다.
- MCPMark(arXiv 2509.24002): 과제당 평균 16.2턴, 도구 호출 17.4회. 최고 모델의 첫 시도 통과율 52.56%.
- RAG-MCP(arXiv 2505.03275): 도구가 많을 때 도구 선택 정확도 기준 13.62%.
- "여러 원천 답 하나를 모으는 데 드는 탐색 호출 수"를 직접 잰 2026년 자료는 찾지 못했다. 우리 값 증명 측정(reports/necklace-value-method-2026-11-15)이 그 숫자를 낸다.
- 이 숫자들은 2025년 자료다. 홍보에 쓸 때는 출처와 연도를 함께 적는다.

## 6. 출처
- pulsemcp.com/servers (11-15 열람, 5쪽까지), glama.ai/mcp/servers (11-15), zplatform.ai/mcp-servers (11-09 갱신)
- langchain.com/state-of-agent-engineering (조사 2025-11~12, 발행 2026-06-12)
- claude.com/resources/articles/how-enterprises-are-building-ai-agents-in-2026 (2025-12-09)
- anthropic.com/engineering/advanced-tool-use (2025-11-24), arXiv 2505.03275, 2509.24002, 2508.01780, 2506.01056
- cyberpress.org/weekly-cybersecurity-roundup-november-2-6-2026
