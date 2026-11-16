# 가치 평가 뒤 발전 방향: 성장·유통 몫 (PM 11-16 21:13 배정)

위치: "목록이 아니라 실제 과제로 검증한 결과와 그 증거를 판다"(현황판 'PM 11-16 21:13' 블록). 성장·유통 몫은 다섯 가지다.

| 번호 | 할 일 | 기한 | 상태(11-16 21:3x) |
|---|---|---|---|
| ① | 화면·에이전트 응답 첫 줄을 등급 글자 대신 "역할 과제 N회 중 M회 정답, 서로 다른 날 2회 확인, 마지막 확인일"로 | 11-24 | 설계(아래 4절). 자료는 시험 보고서 v2와 role_groups |
| ② | 카탈로그 수·A~F 등급을 대표 홍보 문구에서 내림, "에이전트 마켓" 틀 금지 | 바로 | 홈 지표 띠 순서 변경(r11), 나머지 표면은 이미 해당 없음(1절) |
| ③ | 이름 정리: AgentValCon 먼저, agentconcierge.io와 무관 한 줄, 무료 디렉터리·Registry 설명 갱신 | 11-21 | llms.txt 한 줄(r11), 디렉터리·Registry 문안(2절) |
| ④ | x402 유료 엔드포인트 지도 공개 화면(결제 미시험 표시) | 11-30 | 설계(5절), 데이터는 검색과 RAG |
| ⑤ | 첫 목걸이 공개 뒤 커뮤니티 게시 초안(측정값·증거 주소만) | 첫 목걸이 공개 뒤 | `reports/launch-posts-2026-11-16` 5절을 공개 뒤 실제 값으로 채움 |

## 1. 대표 홍보 문구 점검 (②)

대표 홍보 문구는 사람과 에이전트가 처음 보는 문장이다. 공개 주소와 저장소 원문으로 확인했다(11-16 21:2x).

| 표면 | 카탈로그 수 | A~F 등급 | "마켓" 틀 | 조치 |
|---|---|---|---|---|
| 홈 제목·설명(`<title>`, meta·og description) | 없음 | 없음 | 없음 | 그대로 |
| 홈 첫 화면 문단 | 없음 | 없음 | 없음 | 그대로 |
| **홈 첫 화면 바로 아래 지표 띠** | **첫 칸이 "395,186 Cataloged agents & services"** | 없음 | 없음 | **순서 변경**: 실행 확인(24시간)을 첫 칸·강조로, 카탈로그 수를 마지막 칸으로. 띠 제목 "Catalog overview" → "Checks overview" |
| llms.txt 첫 문단 | 없음 | 없음 | 없음 | 무관 한 줄 추가(③) |
| A2A 카드 설명 | 없음 | "quality grade"가 순위 요소로 나옴 | 없음 | ①에서 바꿈(순위 설명은 사실이라 지금 지우면 설명이 틀려짐) |
| 공식 Registry `deploy/mcp-registry/server.json` | 없음 | 없음 | 없음 | 그대로(제목 이미 AgentValCon) |
| 디렉터리 긴 설명(`reports/growth-plan-2026-11-14/directory-submissions.md`) | "a catalog it checks continuously" | "a quality grade", "grades" | 없음 | 새 문안(2절) |
| 커뮤니티 게시 초안(`reports/launch-posts-2026-11-16`) | 없음 | 없음 | 없음 | 그대로 |
| 상태 화면(agent-status "See the scale") | 있음 | 없음 | 없음 | 그대로. 홍보가 아니라 현황 자료 |
| 목록·비교 페이지의 "quality grade" | 없음 | 에이전트별 등급 | 없음 | ①에서 첫 줄을 실측으로 바꿈 |

- 홈 지표 띠는 칸 네 개와 디자인을 그대로 두고 순서만 바꿨다. 칸을 지우지 않은 이유: 시안 요소를 지울 때는 시안 대조와 사용자 확인이 필요하다(11-13 규칙).
- 칸 내용을 목걸이·검증 진주 수로 바꾸는 것은 ①의 자료가 생긴 뒤(11-24) 같은 띠에서 한다.

## 2. 이름 정리와 디렉터리 문안 (③)

- llms.txt 첫 문단 아래에 한 줄을 넣었다: "AgentValCon runs at agentconcierge.biz and is not affiliated with agentconcierge.io."
  - agentconcierge.io는 같은 일(에이전트 추천)을 하는 유료 서비스다(`reports/competitors-2026-11-14`, `reports/brand-strategy-2026-11-14`).
  - 남의 서비스에 대한 평가는 쓰지 않고, 우리가 무관하다는 사실만 쓴다.
- Registry 이름 `biz.agentconcierge/agent-concierge`는 바꿀 수 없는 식별자라 그대로 둔다. 제목과 설명은 이미 AgentValCon이다.

### 디렉터리 짧은 설명 (≤ 100자, 97자)

```
AI agents and MCP servers picked by recorded task checks, and necklaces joining them in one call.
```

### 디렉터리 긴 설명 (새 문안, 11-21까지 PM이 등록·갱신)

```
AgentValCon (agent value gateway) finds and tests other agents. Describe a task and it returns up to three A2A
agents or MCP servers chosen from recorded checks, with the evidence behind each: when it was last reached, what
our test calls returned and when, so you can choose before you connect.

Necklaces: when tested agents work better together than any one of them alone, we join them into a necklace, a
workflow that answers in one call instead of you finding, calling and merging several agents. Each necklace opens
only after its answers pass our gate, and its page shows what we measured, which agents it uses and how it falls
back when one fails. Need one we do not have? Request it at https://agentconcierge.biz/necklaces/request; the
answer appears on the request's own status page.

Tools (read-only unless noted):
- find_agents: up to three active agents for a task, with what you need to connect
- search: browse up to three matches to compare their latest checks
- check_agent / verify_agent: our recorded status and latest test results for one agent before you call it
- best_for_role: the verified pearls for a role and the necklaces that use them
- search_workflows / workflow_details: published workflows and their inputs
- run_workflow (runs): run one published workflow after reviewing it
- call (runs): run one tool of a listing you chose, through our gateway, after checking its schema
- chat: describe a task in plain English and refine it

No API key is needed. Endpoint: https://agentconcierge.biz/mcp (Streamable HTTP).
How we test: https://agentconcierge.biz/methodology
AgentValCon runs at agentconcierge.biz and is not affiliated with agentconcierge.io.
```

- 옛 문안에서 바꾼 것: "a catalog it checks continuously", "a quality grade", "grades"를 뺐다. 마지막 줄에 무관 한 줄을 넣었다.
- 넣지 않은 것: 카탈로그 수, 등급 글자, 목걸이 수, 재지 않은 숫자.
- 계정이 필요 없는 곳(공식 Registry, AgentPeering, a2a-registry.org, mcpservers.org)은 PM이 이 문안으로 갱신한다(PM 권한). 계정이 필요한 곳(mcp.so, cursor.directory, aiagentsdirectory.com)은 사용자 몫이다(`reports/necklace-demand-2026-11-16` 등록처 표).

## 3. 시험·배포

- 홈 지표 띠: `new/en/*.html` 9개(같은 띠가 각 화면 파일에 들어 있음). 칸의 `data-metric`과 선택자는 그대로라 화면 스크립트와 기존 시험은 바뀌지 않는다. 첫 화면 CSS를 다시 만든다.
- llms.txt: `agent_market/concierge/front.py` 한 줄(정책 해시 파일 아님).
- 둘 다 frontend r11 묶음에 넣는다.

## 4. ① 설계: 첫 줄을 실측으로 (11-24)

- 보일 문장(영어, 공개): "Correct on M of N role tasks · checked on 2 different days · last checked <date>".
  - 실측만 쓴다. N이 0이면 첫 줄을 쓰지 않고 지금처럼 최근 확인 기록을 보인다(등급 글자는 첫 줄에서 뺀다).
  - 서로 다른 날 2회가 아니면 "checked on 1 day"로 쓴다(검증 진주 기준을 넘었다고 쓰지 않음).
- 자료(11-16 21:3x 코드 확인): 공개 화면·응답이 읽는 검증 스냅샷(`scripts/verify_snapshot.py` → `check_route.load`)에는 에이전트·역할마다 점수, 검증 진주 여부, 마지막 시험 시각만 있다. N·M·날짜 수는 없다.
  - 원자료는 시험 보고서 v2 기록(`scripts/report_v2.py` `versions_of`)에 있다. 같은 계약의 시험 횟수 = N, 그중 정확도 점수가 있는 횟수 = M, `success_days()` = 서로 다른 날 수, 가장 늦은 `tested` = 마지막 확인일.
  - 스냅샷의 `agents[].roles[]`에 `tasks_run`·`tasks_correct`·`success_days`·`last_checked` 네 칸을 더해 달라고 에이전트 팀에 요청한다(11-18까지). 칸은 "기계 판독 시험 증거 v1"(11-28, 에이전트 팀·검색과 RAG)과 이름을 맞춘다.
  - 성장·유통은 그 칸만 읽는 첫 줄 함수 하나를 만들고 화면·응답에 붙인다. 계산을 화면 쪽에 따로 두지 않는다(두 벌이 되면 숫자가 어긋난다).
- 적용할 곳: 에이전트 페이지, 카테고리 목록·비교 페이지, find_agents·A2A·Chat 응답의 첫 줄, 목걸이 멤버 줄.
- 순서: 자료 칸 확인(11-18) → 첫 줄 함수 하나(공용) → 화면·응답 적용 → 시험 → r12 이후 frontend 묶음.

## 5. ④ 설계: x402 유료 엔드포인트 지도 (11-30)

- 규칙(CLAUDE.md fd879f9f ②): 402 응답만, 결제 없음, 카탈로그·추천과 분리, "결제 미시험" 표시, 등급 B 상한, COLLECT_X402=0 유지.
- 화면: `/x402/map` 한 페이지. 호스트별 유료 엔드포인트 수, 402 응답에 적힌 가격·네트워크·자산, 마지막 402 확인일. 맨 위에 "Payment not tested: we record the 402 answer only" 표시.
- 데이터: 검색과 RAG(기존 Bazaar 기록 + 장부 몫 안 402 표본). 성장·유통은 화면과 시험을 맡는다.
- 추천·탐색 결과에는 섞지 않는다. 사이트맵에는 넣되, 내용이 적으면 noindex로 둔다(색인 규칙과 같음).

## 6. (PM 22:3x 추가) 공개 페이지 조립 캐시 확인

- 운영 r10 원서버(활성 슬롯 8401)에서 3회씩, 쿠키 있음·없음으로 쟀다(22:34, 부하 12).
  - test.html·/connect·chat.html: 4~15ms. 조립 결과 메모가 쿠키와 상관없이 맞는다.
  - 홈 `/`: 매번 210~260ms. 요청마다 탐색 미리보기를 새로 시작하고 0.15초까지 기다려, 미리보기가 들어갈 때와 빠질 때가 섞였다. 그래서 바이트가 달라 메모가 맞지 않았고 엣지 사본도 서로 달랐다.
  - test.html 첫 요청: 3.1초(새 프로세스의 첫 조립).
- 20:29 회차의 test.html 5.36초·/connect 4.45초는 원서버가 아니라 경로였다. TLS 1.25초 + 본문 3.6초, TLS 4.0초였다(phases).
- 고친 것(`growth/home-bootstrap-1116` 7fda77bd, r11 후보)
  - 공개 홈은 늘 빈 초기 데이터를 내 같은 바이트가 된다. 탐색·개요는 열 때 각자의 API로 불러온다. 미리보기가 늦을 때 이미 그렇게 동작했다.
  - 새 프로세스는 시작 5초 뒤 공개 페이지를 미리 조립한다.
  - 시험: 새로 2개, 기대값 2개를 고쳤고 세 파일 52개가 통과했다.
