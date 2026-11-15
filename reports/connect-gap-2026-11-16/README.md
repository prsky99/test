# 외부 추천 뒤 게이트웨이 연결 0건 원인 (성장·유통, PM 11-16 08:2x)

- 측정: 11-16 08:24~08:26
- 자료
  - 공개 주소에서 MCP find_agents와 A2A message/send를 직접 호출
  - traffic 기록(logs/service-frontend/traffic/2026-11-15*.json)
  - 운영 DB 읽기 전용 조회(scripts.prod_ro_sql, agent_messages·agent_visitors, 집계만)

## 결론
- 연결이 0건인 주된 이유는 주소가 아니다. 추천을 받은 "외부" 상대 대부분이 과제를 가진 사용자가 아니다. 생존 확인 도구, 디렉터리 감시 도구, 홍보·제휴 권유, 보안 점검이고, 이들은 원래 연결하지 않는다.
- 추천 응답은 이미 우리 게이트웨이 주소만 준다. 제공자 원래 주소는 응답에 없다.
- 과제를 가진 외부 질의는 하루 한 자릿수다. 그 몇 건도 바로 실행되는 결과를 받지 못해 다음 단계로 오지 않았다. 늘릴 곳은 이 몇 건을 한 번에 결과까지 가게 하는 것이다.

## (1) 추천 응답이 주는 연결 주소
| 경로 | 첫 항목에서 보이는 것 | 제공자 원래 주소 |
|---|---|---|
| MCP find_agents | 첫 줄 바로 아래 `Run here: call {"resource_id":…,"tool":…,"arguments":…}`, 다음 줄 `Endpoint: https://agentconcierge.biz/api/gateway/mcp/<id>`, MCP 설정 조각 | 없음 |
| A2A message/send | `Run here: run 1 {"location":"<location>"}`, 같은 게이트웨이 Endpoint와 MCP 설정 | 없음 |
| 구조화 데이터 | recommendations[i].url·usage_endpoint = 게이트웨이 주소, connect_steps, connection_available | 없음 |

연결 주소는 충분히 눈에 띈다. 다만 두 경로 모두 인자 자리가 `<location>`처럼 비어 있다. 그래서 상대가 한 번 더 채워서 불러야 결과가 나온다.

## (2) 11-15 외부 요청의 출처와 그 뒤의 행동
traffic funnel 합계(11-15, 프로세스별 파일 합, 요청 수):
- 외부 추천: A2A 129, Explore 7, search 5, find_agents 4, Chat 2. 외부 connect 0, 외부 execute attempt 1
- 내부: find_agents 414, Explore 608. connect는 내부만 144

A2A 외부: 요청 238, 서로 다른 지문 40. MCP 외부 클라이언트 상위는 모두 감시·조사 도구다.
- mcpbeat 90, glimind-probe 81, histor 49, alalanet-prober 45, glama 22, ainet-probe 19, agentrank-probe 17
- posthog-mcp-registry-probe 14, talaria-catalog 14, nuclei 12, glama-mcp-inspector 11 등

운영 DB의 질의 문장(11-15 KST, 내부 표시 제외, 집계):
- A2A 36건이 방문자 36명이다. 모두 한 번만 묻고 떠났다(상태를 남기지 않는 스캐너의 특징).
- 분류
  - 생존·연결 확인: "ping" 3, agentprobe "Reply with the single word OK" 2, "hi" 1, "Hello, what can you do?" 1
  - 홍보·제휴 권유: Scion "local digital-services desk" 5, 紫薇联盟 권유·握手 8, "Public research only…" 3
  - 보안 점검: llmrt red-team 1
  - 과제가 있는 질의: 파일 변환 3(번호만 다른 같은 문장으로, 자동 평가로 보임), 워크플로우 찾기 2, "Is Find a published workflow … available" 1, "details 1" 1, "what's new" 2, "Get updates for this task" 1, 날씨 1
  - 날씨 1건(17:05)은 성장·유통이 이 맥에서 보낸 시험이다. 우리 측정이 "외부"로 들어가 있다(아래 안 A).
- MCP 외부 5건: "Structured discovery request" 3, audit-fixture 1, task update 1. 모두 감시 도구의 정형 질의다.
- 그 뒤의 행동: traffic의 외부 connect가 0이고, 외부 execute 시도는 1건이다. 과제가 있던 상대도 relay나 목걸이를 부르지 않았다. 목걸이는 공개된 것이 0개라 부를 수도 없었다.

## (3) 연결을 늘릴 안
| 안 | 내용 | 효과 예상 | 비용·위험 |
|---|---|---|---|
| A. 분모를 바로잡기 | 북극성·자동 점검의 "외부 추천"에서 생존 확인·권유·감시·보안 점검을 빼고 "과제가 있는 외부 질의"만 센다. 우리 측정(성장·유통 curl 등)이 외부로 섞이지 않게 내부 표시를 고친다 | 연결 수는 그대로다. 대신 "74건 중 0"이 "과제 약 5~8건 중 0"으로 바로 보여, 무엇을 고칠지가 분명해진다 | 작음(traffic 분류) |
| B. 추천과 함께 바로 결과 주기 | 과제에서 인자를 확실히 뽑을 수 있고(도시·회사명·도메인 등), 1순위가 읽기 전용이며 시험 통과한 도구면, 추천 답에 그 도구를 게이트웨이로 한 번 불러 결과를 함께 준다. 인자를 못 뽑으면 지금처럼 `Run here` 한 줄을 준다. 실제로 부른 사실과 원래 제공자를 밝힌다 | 과제가 있는 질의 가운데 인자가 분명한 것(날씨·환율·회사·도메인류)은 바로 게이트웨이 연결 1건이 된다. 하루 과제 질의 5~8건 중 2~4건으로 추정 | 응답 시간(복잡한 답 5초 목표 안). 남의 서버 호출이 늘어나니 기존 시험 호출 예산·도메인 한도 안에서만 |
| C. 목걸이 실행을 앞에 | 첫 목걸이가 공개되면, 질의가 그 목걸이 범위에 맞을 때 추천 맨 앞에 "Free to run now: <목걸이> — run necklace <slug> {…}" 한 줄을 넣는다(지금도 llms·도구에는 들어감) | 목걸이 범위 질의에서만 효과가 있다. 공개 전에는 0 | 작음. 공개 목걸이가 생긴 뒤에만 보임 |

권장 순서:
1. A를 먼저 해서 진짜 분모를 잰다.
2. B는 효과가 가장 크다. 응답 시간과 호출 예산 확인이 필요하니 담당(검색과 RAG·에이전트 팀)과 범위를 정한다.
3. C는 첫 목걸이 공개와 함께 한다.

속이는 문구는 쓰지 않는다. B는 "we called <tool> for you through our gateway"처럼 실제로 한 일만 적는다.
