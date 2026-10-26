# 자율형 에이전트 접속 시나리오 테스트 안내

자율형 에이전트가 agentconcierge.biz에 접속하는 상황을 종류별로 흉내 내 확인합니다.
- **에이전트 종류 조사(12종, 출처 포함):** `reports/자율형 에이전트 종류 조사.md`
- **최근 결과:** `reports/자율형 에이전트 접속 테스트.md`

## 실행
```bash
.venv/bin/python -m scripts.agent_scenarios https://agentconcierge.biz
.venv/bin/python -m scripts.agent_scenarios https://agentconcierge.biz --only mcp,a2a --json out.json
```
- **결과:** 줄마다 `PASS`, `WARN`(동작하지만 고칠 점), `FAIL` 중 하나가 찍히고, 마지막 줄에 개수가 나옵니다. FAIL이 하나라도 있으면 종료 코드가 1입니다.
- **소요:** 한 번 실행에 3~5분, 요청은 약 150건입니다.
- **방문 기록:** User-Agent `AgentScenarioQA/1.0`으로 남습니다. 관리 화면에서 걸러 볼 수 있습니다.
- **프록시 환경:** `SSL_CERT_FILE`에 CA 묶음 경로를 지정합니다.

## 지키는 것
- 결제하지 않습니다. 402 응답의 요구 조건만 읽습니다.
- 자격 증명을 보내지 않습니다. 가짜 서명 헤더는 "특별 대우가 없는지"만 봅니다.
- `call`(실행) 도구는 호출하지 않습니다. 추천된 게이트웨이 MCP에는 `initialize`와 `tools/list`만 보냅니다.
- 연속 요청은 10건까지만 보냅니다. 부하 시험은 하지 않습니다.
- 사설 주소(SSRF) 시험은 운영자 본인의 사이트에서만, 차단되는지만 확인합니다.

## 종류별 시나리오 (스크립트 `--only` 이름)

| 종류 | 대표 예 | `--only` | 확인하는 것 |
|---|---|---|---|
| A·B. 학습·검색 크롤러 | GPTBot, ClaudeBot, OAI-SearchBot, Claude-SearchBot, PerplexityBot | `crawler` | robots·sitemap, UA별 같은 응답, sitemap 주소가 모두 200, JS 없이 보이는 본문, soft-404, 캐시 헤더 |
| C. 사용자 요청형 fetcher | ChatGPT-User, Claude-User, Perplexity-User | `llm_fetcher` | llms.txt 형식과 링크, 5초 안 응답, Link 헤더, 마크다운 협상, 문서 간 숫자 일치 |
| E. 코딩 에이전트 | Claude Code, Codex, Cursor | `coding_agent` | skill.md 안내 방식, llms.txt와 OpenAPI 일치, servers 절대 주소, 기계 판독 오류 |
| F. MCP 클라이언트 | Claude, ChatGPT 커넥터, Cursor | `mcp` | initialize·tools/list·tools/call, 도구 주석(readOnly·openWorld), outputSchema, 버전·Origin 헤더, 배치, CORS, server/discover |
| G. A2A 클라이언트 | ADK, a2a-sdk, LangGraph | `a2a` | 카드, 0.3 `message/send`·1.0 `SendMessage`, contextId 이어 받기, 오류 코드(-32601·-32700·-32009·-32602) |
| H. OpenAPI·REST 도구 에이전트 | GPT Actions, LangChain, CrewAI | `rest` | 방문 토큰, `details 1`, resume ETag/304, 잘못된 입력, CORS, 응답 시간, 요청 한도 헤더 |
| J. 멀티에이전트·레지스트리 수집기 | 오케스트레이터, 다른 게이트웨이 | `registry` | 같은 질의의 결과가 같은지, 다음 페이지 커서, 캐시 헤더, 변경 피드 |
| K. 준비도 점검 봇 | agentic readiness 스캐너 | `readiness` | HEAD가 GET과 같은지, 발견 파일의 Content-Type |
| I. 결제 에이전트 | x402 클라이언트, AP2 | `x402` | x402 후보 추천, 402와 `PAYMENT-REQUIRED`(v2) 해석, 잘못된 결제 헤더 |
| L. 적대적 에이전트 | 주입·SSRF·스크래핑 | `adversarial` | 프롬프트 주입, adapt_rest 사설 주소, SQL 주입, 1MB 본문, 깊은 중첩 JSON, 가짜 Web Bot Auth, 연속 ID 스크래핑 |
| D. 브라우저·컴퓨터 사용 에이전트 | ChatGPT agent, Claude in Chrome, browser-use | (수동) | 아래 절차 |

### D. 브라우저 에이전트(수동, Playwright)
1. 빈 프로필로 `/new/en/chat.html`을 엽니다. `page.locator('body').ariaSnapshot()`로 접근성 트리를 저장합니다.
2. 역할(role)과 이름만으로 입력창과 "Find matches" 버튼을 찾습니다.
3. 과업 "Find an MCP server that returns the current weather for Seoul"을 넣고 결과를 기다립니다.
4. 기록할 것:
   - 걸린 시간
   - 결과가 접근성 트리에 나오는지
   - 쿠키 배너가 흐름을 막는지
   - 이름 없는 버튼 수
5. `#register` → `#contact`처럼 해시만 바꿔 이동했을 때 화면이 바뀌는지 봅니다. 사이트 전반 보고서의 1번 문제와 같습니다.

조사 보고서 5장의 시나리오 중 스크립트에 넣지 않은 것은 다음과 같습니다. 필요할 때 손으로 확인합니다.
- **추천 엔드포인트 생존:** 추천된 상위 5개 항목의 엔드포인트가 실제로 응답하는지. 제3자 서버이므로 각 1회만 보냅니다.
- **x402 Bazaar 노출:** 공개 목록에 이 사이트의 유료 API가 올라가 있는지.
- **MCP Registry 검색:** 공식 레지스트리에서 이 사이트가 검색되는지.
