# MCP 도구 설명 첫 문장 초안 (검색과 RAG, 2026-11-17 밤, PM 지시)

- **배경**: 외부 MCP 클라이언트는 tools/list만 보고 떠나고, tools/call은 거의 없다(성장·유통 22:00 실측).
- **목표**: 도구 설명의 첫 문장을 "무엇을 해 주는지"가 앞에 오는 한 문장으로 줄인다.
  - 공개 문구라 영어로 쓴다.
  - 둘째 문장부터 지금 설명(제약, 필드 설명)을 그대로 둔다.
  - 도구 수는 줄이지 않는다.
- **대상 파일**: `agent_market/concierge/mcp_contract.py`(tools 목록 26~101행)
  - 정책 해시 파일이 아니다. `explore_documents.policy_hash`가 읽는 파일은 selection, task_requirements, explore_search, execution_policy, capability_registry, collector/usage, postgres_capability_text다.
  - 목걸이 동결 경로(necklaces/, fallback_agents, owned_data_agents)도 아니다.
  - 그래서 11-18 낮 frontend 묶음으로 낼 수 있다.
  - 목걸이 도구(necklace_surface)는 성장·유통 몫이라 여기서 다루지 않는다.

| 도구 | 지금 첫 문장 | 새 첫 문장 초안 |
|---|---|---|
| find_agents | Recommend and connect: pick up to three active agents for a task and get what you need to connect to each (endpoint, verification evidence, calling details). | Get up to three recently verified agents for your task, with what you need to call each one. (PM 수정) |
| call | Run one tool of a listing you chose, through our gateway, after checking its current schema. | Run a read-only tool of a recommended agent through our gateway and get its answer in this session. |
| search | Browse: list up to three catalog matches for a task so you can compare names, grades and latest successful verification. | Compare up to three catalog agents for a task by name, grade and last successful check. |
| check_agent | Read-only check before you call an agent: our recorded status, recent check success rate and latency, grade, evidence sources and up to three alternatives for an endpoint or agent-card URL. | See an agent's recorded status, success rate and latency before you call it, with up to three alternatives. |
| report | Record caller feedback. | Tell us whether a call worked; on a failure, get up to three verified alternatives. |
| chat | Converse: describe a task in plain English and refine it over several turns (…). | Find an agent by describing your task in plain English and narrowing it over several turns. |
| search_workflows | Find up to three relevant published workflows by purpose, node capability, or English and common non-English aliases. | Find up to three ready-made multi-agent workflows (necklaces) for a purpose. |
| workflow_details | Read a currently public workflow definition and its recorded execution readiness. | See a published workflow's steps and whether it is ready to run. |
| whats_new | Read the last task saved by chat and re-evaluate its evidence without changing it. | Re-check the evidence for the last task you saved with chat. |
| hello | Optional greeting. | Get a visitor token so later calls remember you (optional). |
| adapt_rest | Turn a public OpenAPI/Swagger document into tools (…) or call one of its endpoints (action call). | Turn a public OpenAPI document into tools you can call, or call one of its endpoints. |
| credit | Check your own virtual credit balance using a valid visitor token. | Read your virtual credit balance (visitor token required). |
| verify_contact | Confirm your contact with the 6-digit code I sent there. | PM 결정 대기 (아래 '연락처 도구' 참고) |
| subscribe | Legacy contact command. | PM 결정 대기 (아래 '연락처 도구' 참고) |

## 지켜야 할 것

- **adapt_rest**: 둘째 문장의 경고("can change data there")는 반드시 남긴다. 첫 문장만 짧게 한다.
- **call**: "read-only만 중계, 키·결제가 필요한 도구는 거절, 불확실한 결과는 자동 재시도하지 말 것"은 둘째 문장부터 그대로 둔다.
- **find_agents의 price_status 설명**: 둘째 문장 뒤로 옮긴다. 지우지 않는다(유료 표시 규칙).
- **정확성**
  - "working agents"는 우리 최근 확인(검증·헬스)을 통과한 목록만 추천한다는 뜻이다. 그 근거가 둘째 문장(verification evidence)에 남아 있어야 한다.
  - "right now"는 run_here와 연결 정보가 바로 쓸 수 있다는 뜻이다. 연결이 안 되는 목록(중계 안 하는 도구)은 카드가 그렇다고 밝힌다(50d696e5).
- **시험**: 설명 문자열을 고정한 시험이 있으면 함께 고친다. 바꾼 뒤 `tests/`에서 옛 첫 문장을 grep해 확인한다.

## PM 검토 뒤 확인 (11-17 밤)

- **find_agents**: PM 문구로 바꿨다. 확인 기록으로 뒷받침되는 "recently verified"다.
- **report**: 코드상 실패 보고에 대안이 실제로 돌아온다(front.py 4097~ → recovery.report_outcome → alternatives()). 그래서 "on a failure, get up to three verified alternatives"를 유지한다.
- **연락처 도구 (subscribe, verify_contact)**: 지금도 연락처를 받는다.
  - front.py가 ContactDesk를 항상 만든다(193행).
  - subscribe는 웹훅이나 A2A 주소를 등록하고 확인 코드를 보낸다(engine._contact → contacts.register).
  - verify_contact는 알림을 켠다.
  - subscribe는 tools/list에서는 숨겨져 있지만(HIDDEN), 부르면 아직 답한다.
  - 그래서 첫 문장을 "contact sign-up is closed"라고 쓰면 실제 동작과 다르다.
  - 제안: 같은 묶음에서 두 도구를 막고 그 문구를 쓰거나, 막기 전까지는 "Legacy: registers a webhook or A2A address for task updates; not offered to new callers."처럼 실제 동작대로 쓴다. PM 결정을 기다린다.
