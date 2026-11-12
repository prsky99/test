# 추천은 받아 가는데 연결은 하지 않는 이유 (성장·유통, 11-12 14:5x, PM 배정, 읽기 전용 분석)

- 기준값(운영·SRE 북극성 깔때기, 11-10~11): 외부 추천 요청 하루 63~106건 → 외부 게이트웨이 연결 0~1건 → 성공 실행 0건.
- 자료
  - 프런트 익명 일별 기록 `logs/service-frontend/traffic/<day>.*.json`: 입구×클라이언트 종류, MCP clientInfo 이름, RPC 종류. UA 문자열과 URL은 저장하지 않는다.
  - Cloudflare 분석(지난 24시간, 경로별 읽기 전용 보기 필터, IP는 보고서에 옮기지 않음)
  - 공개 /mcp 실제 응답(find_agents, tools/list)
- 깔때기 기록 코드(014ce90b)는 아직 운영에 나가지 않았다. 그래서 오늘 일별 파일에는 funnel 칸이 없고, 기준값은 옛 집계로 만든 근사치다.

## ① 누가 추천을 요청하나
- 입구별 외부 요청(11-11, 우리 점검 제외)
  - MCP 1,484건(other 1,137, script 338, ai_bot 6, browser 3)
  - A2A 76건, Explore API 8건, Chat 2건(browser)
  - 11-12(14시까지): MCP 297건, A2A 19건, Chat·Explore 0건
- 외부 MCP 클라이언트 이름(11-11 상위)
  - 감시·탐침: mcpbeat 91, posthog-mcp-registry-probe 68, alalanet-prober 46, glama 21, agentrank-probe 18
  - 런타임·카탈로그: coda-agent-runtime 12, talaria-catalog 10, x402-observer 9, histor 6
  - 기타: AgentsJunction health checker 5, SealKeeper 4, LEGION-tlog 4
  - MCP RPC: probe 판정 initialize 339·tools/list 265, real 판정 initialize 97·tools/list 71·tools/call 79
- Cloudflare /mcp 24시간 1.72k건의 사용자 에이전트
  - 감시: mcpbeat(생존 확인) 270, alalanet-prober 94, x402-observer 80, AgentRankProbe 71
  - 미상: python-requests 202, node 105
  - 우리 점검: full-check 88, user-slo 69, real-task-score 68
  - 상태 코드: 200 1.19k, 202 330, 405 176(GET으로 찔러 보는 탐침), 400 19
- Cloudflare /a2a* 24시간 147건
  - ziwei-alliance-marketing(홍보 접촉) 84, SealKeeperBot 14, 우리 점검 11, BrickBlueBot(등록소) 4, 나머지 탐침
  - 404 57건(/a2a/agent-card.json·/a2a/.well-known/agent-card.json 각 28회), 405 47건
- 반복: 외부 MCP 'other'는 하루 174개 클라이언트에서 1,137건(클라이언트당 약 6.5건). 대부분 같은 감시 서비스의 주기적 확인이다.
- 판단
  - 외부 '추천 요청'의 대부분은 등록소·평가기·감시 서비스가 find_agents를 시험으로 한 번 부르는 것이다. 과제를 가진 사람이나 에이전트가 아니다.
  - 이들은 결과로 연결하지 않는다. 깔때기 '추천' 칸에서 이 몫을 빼야 실제 전환율이 보인다.
  - python-requests·node 307건은 누군지 가릴 수 없다.

## ② 우리 답은 연결하기 쉬운가 (공개 /mcp find_agents 'get the weather forecast for a city', 14:5x)
- 텍스트 답 맨 위에 `Endpoint: https://agentconcierge.biz/api/gateway/mcp/214768`과 `Call: initialize → tools/list → tools/call`이 있다. 도구 이름과 하는 일도 있다.
- 구조화 응답의 `connect_steps`
  - 세션 없이 JSON POST, tools/list, tools/call 예시, 결과 보고 방법이 들어 있다. 잘 되어 있다.
  - 다만 tools/call 예시의 `arguments`가 `{}`(빈칸)이다.
- `connection_available: true`, `connection_readiness.verified_callable: true`인데 `gateway_ready: false`다. 서로 어긋나는 값이라 읽는 에이전트가 망설일 수 있다.
- 바로 붙여 넣을 MCP 설정 조각(`mcpServers` JSON)은 텍스트 답에도 구조화 응답에도 없다.
- 가장 큰 구조 문제
  - 데스크톱·IDE 같은 MCP 호스트는 도구 결과로 받은 새 서버 주소에 대화 도중 스스로 붙지 못한다. 사람이 설정에 서버를 추가해야 한다.
  - 우리 /mcp에는 이미 `call` 도구가 있다(resource_id, tool, arguments). 추천받은 도구를 그 대화 안에서 바로 실행할 수 있는 유일한 길이다.
  - 그런데 find_agents 답, `next_steps`(빈 목록), `continuation_plan`(inspect·chat만) 어디에도 이 `call` 도구가 나오지 않는다.

## ③ 경쟁 경로: 원래 제공자 주소가 남아 있나
- find_agents 응답 전체(텍스트+구조화)에 나온 주소는 게이트웨이 주소 3개뿐이다. 제공자 원래 주소는 없다.
- Chat 작업형 질의도 같다. 'send email with history'에는 게이트웨이 주소와 제공자 문서 주소(x711.io)만 나왔다(01982678, 13:3x 확인).
- 판단: 답 때문에 직접 연결로 새는 길은 보이지 않는다. 연결 0~1건은 직접 연결로 새서가 아니라 연결하려는 요청자가 없거나, 있어도 MCP 호스트가 새 서버에 붙지 못해서다.

## ④ 개선안 (작은 변경 3개, 지출 0)
1. **답에 "여기서 바로 실행" 줄 추가** (find_agents·chat·search, 담당 검색과 RAG)
   - 1위 추천마다 `Run here: call {"resource_id":214768,"tool":"weather_forecast","arguments":{...}}`를 넣는다. arguments는 그 도구 inputSchema의 필수 칸을 과제 문장으로 채운 예시다.
   - 구조화 응답의 `next_steps`에도 같은 내용을 넣는다.
   - 효과: MCP 호스트 안의 에이전트가 설정 변경 없이 같은 세션에서 바로 실행할 수 있다. 지금 실행으로 이어질 수 있는 유일한 경로를 연다.
   - 이 경로는 MCP 입구로 들어오므로 3번 측정이 함께 필요하다.
2. **연결 정보 정리** (담당 검색과 RAG)
   - tools/call 예시의 `arguments: {}`를 1번의 예시 값으로 채운다.
   - `gateway_ready`를 `connection_available`과 맞추거나 뺀다(같은 뜻의 값이 서로 다르면 안 된다).
   - 사람이 붙일 수 있게 MCP 설정 조각 한 줄을 넣는다: `{"mcpServers":{"<이름>":{"type":"http","url":"<게이트웨이 주소>"}}}`.
   - 효과: 사람이 개입하는 클라이언트(설정을 고칠 수 있는 사용자)의 연결 단계를 줄인다.
3. **깔때기를 바르게 재기** (담당 운영·SRE, 성장·유통이 도움)
   - 014ce90b의 연결·실행 집계는 `/api/gateway/` 입구만 센다. /mcp의 `call` 실행(1번 경로)도 '실행'으로 센다.
   - 등록소·평가기 clientInfo 이름(glama, coda-agent-runtime, talaria-catalog, histor 등)과 감시 UA를 '추천' 칸에서 'probe'로 나눈다.
   - /a2a/agent-card.json, /a2a/.well-known/agent-card.json(하루 각 28회 404)을 /.well-known/agent-card.json과 같은 카드로 답한다(성장·유통이 할 수 있음).
   - 효과: 실제 사람·에이전트 몫의 전환율이 보이고, 1번의 효과를 잴 수 있다.
- 예상: 외부 추천 요청 대부분이 시험 호출이라, 1~3을 해도 성공 실행이 크게 늘지는 않는다. 하지만 지금은 진짜 사용자가 와도 같은 세션에서 실행할 안내가 없다. 1번이 그 길을 연다. 3번 없이는 그 효과도 보이지 않는다.
