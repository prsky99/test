# 1안 설계: 추천 답 안에서 첫 후보를 대신 실행 (2026-11-17)

PM 11-17 10:3x 승인(설계 먼저, 16:00까지). 성장·유통 작성. 검색과 RAG 10:5x 의견(다섯 가지)을 반영했다.

## 1. 하는 일

외부 에이전트가 과제를 담아 추천을 물을 때, 첫 후보가 아래 조건을 모두 만족하면 그 도구를 우리 게이트웨이로 한 번 실행한다. 추천과 함께 그 결과를 돌려준다.
- 바로 실행할 수 있는 MCP 도구이고, 인자를 과제에서 확실히 채울 수 있다.
- 2안(Run here 미리 채우기)과 같은 판정을 쓴다.

실행이 정해진 시간 안에 끝나지 않거나 조건이 하나라도 빠지면, 지금 답(추천 + 채운 Run here 줄)을 그대로 낸다.

## 2. 조건 (PM 다섯 가지 + 검색과 RAG 의견)

| 조건 | 구현 |
|---|---|
| (a) 응답 2.0초 | 첫 후보가 정해지는 즉시(ExposedFirstRecommender 결과의 첫 relayable 항목) 실행을 시작하고, 추천 본문 작성과 병렬로 돈다. 추천 요청이 들어온 때부터 1.9초가 지나면 실행을 기다리지 않는다. 끝나지 않은 실행은 결과를 버리고 답에 넣지 않는다(실행 자체는 끝까지 가서 장부에 기록). 1.5초를 더 기다리는 방식은 쓰지 않는다. |
| (b) 읽기 전용·약관·장부 | ① fast_chat.relayable(item)이 참 ② 도구가 usage.is_relay_safe_tool이고 execution_policy.safe_registered_tool을 통과(proxy.py와 같은 판정) ③ action_mismatch가 아님(21a8f3d8) ④ provider_budget의 TRUTH_SOURCE_TERMS·member_terms 판정이 prohibits가 아님 ⑤ provider_budget.reserve(url, 'auto_run')이 ok(새 SHARE 몫 'auto_run'). 하나라도 거짓이면 실행하지 않는다. |
| (c) 개인정보 | run_here_fill.personal(task)가 참이면 실행하지 않는다(메일·전화·주소·사람 이름 패턴, 2안과 같은 함수). |
| (d) 지표 | 실행 기록에 origin='auto_run'을 단다. north_star는 이를 execute와 따로 auto_run 칸(pairs·attempts·ok)으로 센다. 호출자가 직접 부른 실행(execute)과 섞지 않는다. 이 실행 뒤 같은 호출자가 직접 부르면 그때 execute로 센다. |
| (e) 밝히기 | 답 맨 앞에 "AgentValCon executed this read-only call on your behalf: <tool> on <listing> (provider <domain>), arguments {...}, at <UTC time>." 한 줄과 결과 요약을 둔다. data에는 auto_run 객체(listing id, tool, arguments, ok, ms, provider, result_excerpt)를 넣는다. |
| 기타 | 같은 호출자·같은 과제는 하루 1회(방문 토큰이나 지문 기준). tool_unlisted 카드에는 붙이지 않는다(50d696e5). Endpoint 줄 형식은 바꾸지 않는다(user_slo가 읽음). 결과는 2,000자로 줄이고 제공자 문구임을 표시한다. 결과 안의 명령형 문구는 지시로 다루지 않는다(기존 주입 방어 그대로). |

## 3. 흐름

```
추천 요청 (a2a message/send, MCP find_agents·search, REST find)
 ├─ 과제 해석·후보 검색 (지금 그대로)
 ├─ 첫 relayable 후보가 정해지는 순간 → gate(item, task)
 │     relayable? safe tool? not action_mismatch? terms != prohibits? not personal(task)?
 │     run_here(id, tool, task)의 인자에 '<...>' 빈칸이 하나도 없음? reserve(url,'auto_run') ok?
 │     하루 1회 아님?
 │   └─ 통과 → 실행 스레드 시작: proxy의 tools/call 경로(공용 풀, 제공자 시간 제한 1.7초)
 ├─ 추천 본문 작성 (병렬)
 └─ 마감 = 요청 시작 + 1.9초
       실행 끝·성공 → 답 맨 앞에 실행 사실·결과, data.auto_run
       실행 끝·실패 → 답은 지금과 같음, data.auto_run.ok=false(사유만)
       실행 미완   → 답은 지금과 같음(결과 없음), 실행은 끝까지 가서 장부·기록만
```

## 4. 바꿀 파일 (예상)

| 파일 | 담당 | 바꿀 것 |
|---|---|---|
| agent_market/concierge/auto_run.py (새 파일) | 성장·유통 | gate(), start(), collect(deadline), 밝히는 줄 만들기, 하루 1회 기억(메모리, 장기 저장 없음) |
| agent_market/concierge/fast_chat.py | 검색과 RAG(확인) | find 답을 만드는 곳에서 auto_run.start/collect를 부르고 맨 앞 줄·data.auto_run을 붙임 |
| agent_market/concierge/gateway_exposure.py | 검색과 RAG(확인) | 첫 relayable 후보가 정해지는 시점에 알림(callback) 한 곳 |
| agent_market/concierge/proxy.py | 운영·SRE(확인) | 내부 호출용 tools/call 함수를 꺼내 씀(HTTP 왕복 없이), origin='auto_run' 표시 |
| agent_market/provider_budget.py | 운영·SRE(확인) | SHARE에 'auto_run' 몫 추가(처음은 도메인별 하루 몫의 10%) |
| agent_market/concierge/traffic.py, scripts/north_star.py | 성장·유통 | funnel에 auto_run 칸, 북극성 줄에 auto_run 따로 |

정책 해시 파일(selection.py, task_requirements.py, explore_search.py, execution_policy.py 등)은 바꾸지 않는다. 그래서 낮 배포가 가능하다.

## 5. 시험 계획

- 단위(pytest_slot)
  - gate 조건마다 한 건씩: relayable 아님, unsafe tool, action_mismatch, prohibits, personal, 빈칸 남음, 장부 거절, 하루 1회
  - 마감: 가짜 제공자가 0.2초, 1.85초, 3초에 답할 때. 1.9초 안이면 결과가 들어가고, 넘으면 빠지며 응답 시간은 2.0초 이하인지 본다.
  - 밝히는 줄과 data.auto_run 형식
  - 결과 안의 명령형 문구가 답의 지시로 바뀌지 않는지
  - north_star에서 auto_run이 execute와 따로 세지는지
- 통합: TestClient로 a2a message/send·MCP find_agents에서 auto_run이 붙는 경우와 안 붙는 경우
- 운영 전 측정: user_slo 추천 표본에서 2.0초 넘는 비율이 바뀌지 않는지, 사본에서 한 회차 확인
- 검색과 RAG 10:5x 기준 07:52 공개 find_agents는 서버 1,428ms였다. 실행을 병렬로 돌려도 남는 시간이 0.4~0.5초뿐이라, 처음에는 실행이 붙는 비율이 낮을 수 있다. 붙은 비율과 실행 시간 분포를 Server-Timing(auto_run 구간)으로 기록해 판단한다.

## 6. 일정 제안

- 오늘: 설계 확정(PM), 2안 배포(낮 묶음)
- 11-18: auto_run.py·시험 → 검색과 RAG·운영·SRE 확인 → 사본 측정
- 11-19 낮 묶음: frontend 배포, 장부 몫 10%로 시작
- 3일 뒤: auto_run 붙은 비율·성공률·추천 시간으로 몫 조정
