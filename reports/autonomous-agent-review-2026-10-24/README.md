# Agent Concierge의 자율형 Agent 지원 검토

> 후속 수정 완료: 아래는 최초 발견 당시의 기록이다. 호환성 문제 2건·기존 fixture 실패 해결과 MCP Edge 연결, 운영 반영 결과는 [2026-10-25 수정 보고서](<저장소>/reports/autonomous-agent-fixes-2026-10-25/README.md)를 참고한다.

검토 완료: 2026-10-25, Asia/Seoul. 대상은 현재 작업 소스, 기록한 운영 Frontend 패키지, 실제 공개 서비스의 메타데이터다.

## 결론

**Agent를 위한 핵심 서비스는 유지돼 있으며, 외부 Agent가 실제 API로 필요한 Agent를 찾고 실행하는 여정이 동작한다.** 사람용 화면을 개발하면서 기존 Agent 인터페이스를 대체한 구조는 아니다. REST·A2A·MCP, 방문 기억, 도구 Schema, 실행 Gateway, 결과 피드백과 적격 대체 후보 제공 기능이 함께 존재한다.

현재 구조의 자율성은 주로 **외부 Agent가 계획과 다음 행동을 결정하고 Agent Concierge를 탐색·연결·실행 도구로 사용하는 형태**다. 사용자가 사전에 승인한 목적 안에서 움직이는 Workspace 자동화도 구현돼 있다. 범용 Agent가 처음 방문해 문서만 읽고 안정적으로 모든 기능을 이용하도록 만드는 부분에는 호환성 보완이 필요하다.

새 Agent 여정 검사 **12개 중 10개 성공, 2개 호환성 문제 재현**. 같은 검사를 기록한 운영 Frontend 패키지에서도 격리 환경으로 실행해 같은 결과를 확인했다. 실제 외부 Provider 호출과 결제를 포함한 성능·성공률 수치로 해석하지 않는다.

## 1. 자율형 Agent가 현재 이용하는 실행 경로

### 서비스 발견과 추천

1. `/.well-known/agent-card.json`, `/.well-known/mcp.json`, `/llms.txt`에서 서비스와 연결 방법을 발견한다. `GET /`에 JSON을 요청하면 기계용 안내를 받을 수 있다.
2. REST `POST /chat`, A2A `POST /a2a`, MCP `POST /mcp`로 필요한 작업을 전달한다. 사람용 화면을 거치지 않는다.
3. 기본 추천 Protocol은 A2A이며, MCP·x402를 명시하면 해당 범위에서 추천한다. 최근 성공 검증·활동·품질을 기준으로 하나의 관련 후보를 제공한다. 관련성·활성 상태·안전성 조건은 추천 범위를 제한한다.
4. 응답의 `tools_schema`에서 실제 도구명과 입력 구조를 읽는다. Visitor token을 후속 요청의 전송 정보로 보관하면 다른 대화 채널에서도 작업 문맥을 이어갈 수 있다.

실제 공개 서비스에서 Agent Card·manifest·llms.txt·MCP 도구 목록을 읽었다. MCP 도구는 `hello`, `chat`, `search`, `find_agents`, `whats_new`, `subscribe`, `verify_contact`, `call`, `report`, `credit`, `adapt_rest`의 11개다. 공개 메타데이터 확인 중 채팅·도구 실행·결제 요청은 보내지 않았다. 상세 기록: [live-public-metadata.json](<저장소>/reports/autonomous-agent-review-2026-10-24/live-public-metadata.json).

### 도구 실행과 결과에 따른 다음 행동

- MCP Agent는 `tools/list`의 실제 Schema를 읽고 `search(task, kind)` → `call(resource_id, tool, arguments)` 순서로 실행할 수 있다. 이번 검사에서는 날씨 도구의 `city` 입력을 읽고 호출해 결과를 받았다.
- A2A Agent는 Concierge의 `message/send`로 추천을 받은 뒤 응답의 플랫폼 Gateway 주소를 읽고, 그 주소의 Agent Card와 `message/send`를 사용해 결과를 받을 수 있다.
- 실행 결과에는 서비스 고유의 구조화된 상태가 있다. 이번 클라이언트는 `structuredContent.ok`를 확인하고, 실패 시 제공된 다른 적격 Agent를 선택해 새 호출을 수행했다. 호출 결과가 불확정인 경우 자동 반복을 허용하는 검증은 수행하지 않았다.
- 실패를 기록하는 `report`와 마지막 작업을 다시 평가하는 `whats_new`도 존재한다. 적격 대체 후보가 없으면 빈 결과를 받아 클라이언트가 중단하거나 요구를 수정해야 한다.
- 도구 전이 이력과 규칙을 이용한 다음 도구 힌트·Code Mode 코드 템플릿이 있다. 코드 템플릿 제공과 서버의 자동 실행 권한은 구분해야 하며, 이번 검사에서 지연시간 0ms나 무인 장기 실행 성능을 측정하지 않았다.

핵심 소스: [front.py](<저장소>/agent_market/concierge/front.py:2852), [proxy.py](<저장소>/agent_market/concierge/proxy.py:41), [inertia.py](<저장소>/agent_market/concierge/inertia.py:42).

### Origin과 Edge의 경로 차이

현재 `/mcp`의 `call`은 `front.proxy.execute`를 직접 호출하는 Origin 경로다. 반면 추천 결과에 있는 `/api/gateway/a2a|mcp|x402/{id}` 주소와 Native Ticket stream은 Worker 소스의 Edge 처리 대상이다. Agent가 추천 주소를 직접 따르는 방식과 Concierge의 MCP `call`을 사용하는 방식이 동일한 실행 입구로 통합돼 있지 않다.

따라서 자율형 Agent 경로의 비용·관측·폴백 정책까지 일관되게 운영하려면 MCP `call`도 공통 승인·Ticket 실행 경로와 연결하는 작업이 필요하다. 이번에는 경로를 검토했으며, 운영 Provider 호출로 Edge 전달 비율을 측정하지 않았다.

근거: [MCP call 분기](<저장소>/agent_market/concierge/front.py:3082), [Worker 입구 분기](<저장소>/cloudflare/edge-gateway/worker.mjs:711).

## 2. 사람용으로 보이는 기능 중 Agent도 쓸 수 있는 부분

### 게시된 Workflow의 실행

Agent는 `GET /api/workflows/templates`로 공개된 템플릿과 입력을 읽고, `POST /api/workflows/run`으로 실행한 뒤 실행 키로 결과를 조회할 수 있다. 검사에서 임의 `nodes` 주입과 공유 동의 없는 보호된 제품 실행은 거부됐다. 테스트 소유자가 정확한 읽기 전용 폴백 공유 목적을 승인한 뒤에는 실행과 결과 조회가 성공했다. 실행 키가 없는 결과 조회는 404로 차단됐다.

이는 **이미 게시된 Workflow를 승인된 입력으로 소비하는 자율성**이다. 익명의 Agent가 새로운 임의 그래프를 만들고 게시할 권한까지 받는 방식과 구분한다. AI 생성·편집·검토·저장은 Workspace/customer 권한 체계 안에 구현돼 있으며, 공개 MCP에는 현재 해당 생성 여정을 위한 전용 도구가 없다.

근거: [공개 Workflow API](<저장소>/agent_market/concierge/front.py:2800), [검토용 생성 연결 설정](<저장소>/agent_market/workspace_integrations.py:9).

### 장기 Task·SDK·고객 세션

Workspace에는 원격 A2A Task, 세션, SDK/BFF, 서명·계약·실행권을 다루는 기능과 검사가 존재한다. 공개 Concierge의 `/a2a`는 즉시 message 응답형이며, 해당 입구의 `tasks/get`·`tasks/cancel`은 Task 없음으로 응답한다. Agent Card도 streaming·push notifications를 false로 표시한다. 공개 Concierge의 발견 대화와 Workspace의 권한 있는 장기 실행을 별도의 기능 범위로 이해해야 한다.

## 3. 사전 승인 후 사람의 세션 없이 움직이는 자동화

`MachineUpdateAutomation`은 목적별 grant를 받아 변경된 증거를 검증된 inbox로 전송할 수 있다. 기존 개인 세션이 만료된 뒤에도 승인된 목적·소유권·유효기간·건수를 다시 확인해 동작한다. 이번 관련 검사에서는 권한 철회·변조·기간·목적지·중복 전송 경계를 확인했다.

- 한 grant의 기간은 최대 24시간, 이벤트 한도는 최대 20건이다.
- 검증된 목적지와 서명된 전달·수신 계약을 사용한다.
- 일반 Workspace 업무 실행권과 분리된 메타데이터 알림 목적이다.
- 결과 불확정 이벤트를 무조건 재전송하지 않는다.
- `PrivateIntegrations` 기본값은 machine worker·receiver·single admission·circuit automation을 꺼 둔다. 표준 서버 연결 코드에서 확인한 설정은 모델 제안자 연결이며, 이 자동화 전체를 기본으로 켜는 설정은 확인되지 않는다. 운영 DB의 개별 grant 발급 현황을 조회한 결과와는 구분한다.

따라서 이 부분은 **구현과 격리 검증이 존재하는 승인 기반 자동화**로 평가한다. 공개 Agent 전체에 이미 무인 업무 실행이 활성화돼 있다는 설명은 범위를 넘어선다.

근거: [목적별 grant와 자동화](<저장소>/agent_market/workspace_machine_automation.py:118), [기본 설정](<저장소>/agent_market/workspace_integrations.py:15), [실제 worker 연결](<저장소>/agent_market/workspace_platform.py:171).

## 4. 재현된 호환성 문제와 영향

### 먼저 보완할 문제: manifest와 실제 입력 필드 불일치

공개 manifest의 `search`는 `query`, `protocol`을 안내하지만, 실제 `tools/list`와 실행 분기는 `task`, `kind`를 사용한다. manifest만 읽고 요청을 만든 Agent는 검색 대신 `greet` 응답을 받았다. 실제 운영 메타데이터에서도 같은 차이를 확인했다.

`tools/list`를 먼저 읽는 Agent의 여정은 성공했다. 그러나 새로운 Agent가 어느 안내를 먼저 읽느냐에 따라 결과가 달라진다. 도구 정의를 단일 원천에서 생성해 manifest·실제 도구·문서를 일치시키고, 필요한 기존 필드 별칭은 명시적으로 검증하는 것이 우선이다.

manifest에는 transport가 `sse`로 표시돼 있으나 실제 입구는 Streamable HTTP의 JSON 응답형이며 `GET /mcp`는 405다. **405 자체는 Streamable HTTP에서 허용되는 동작**이다. 메타데이터가 클라이언트를 다른 연결 방식으로 유도하는 점을 정리해야 한다. 근거: [MCP 공식 전송 규격](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).

### 먼저 보완할 문제: 실행 실패의 표준 MCP 신호

Provider 도구 실패 시 `structuredContent.ok=false`이면서 MCP 결과의 `isError=false`가 반환됐다. 서비스 고유의 `ok`를 확인하는 이번 Agent는 실패를 인식하고 복구했다. 일반 MCP 클라이언트가 표준 신호를 사용하면 성공으로 오해할 위험이 있다.

실행 실패의 `isError=true`와 구조화 상태를 일치시키고, 안전한 오류 코드·다음 행동을 함께 제공하는 것이 필요하다. MCP 공식 SDK도 도구가 복구할 수 있는 실행 오류를 `isError: true`로 전달하도록 설명한다. 근거: [공식 MCP SDK 오류 처리](https://ts.sdk.modelcontextprotocol.io/v2/servers/errors).

Provider 주소 노출을 의심해 대체 후보도 검사했으며, 이번 재현에서는 대체 후보가 플랫폼 Gateway 주소를 유지하는 검사가 통과했다.

## 5. 테스트 결과와 객관적인 한계

새 검사는 실제 API handler를 사용하는 deterministic headless Agent 클라이언트다. 임시 DB와 합성 카탈로그를 사용하고, Provider 전송은 모의 처리했다. 실제 HTTP 전송을 시도하는 기본 transport를 차단하는 보호 검사도 포함했다. LLM 자체의 계획 능력을 평가하는 벤치마크는 아니다.

- 새 Agent 여정: 10개 통과, 위 호환성 재현 2개 실패.
- 기록한 운영 Frontend 패키지 `web-20261024-232757-c0d8`를 격리해 동일 검사: 10개 통과, 같은 2개 실패. 반복 검사를 합계에 다시 더하지 않았다.
- 기존 관련 회귀: 201개 통과, 1개 기대 불일치.
- 추가 Machine 수신·증거·자동화 경계: 35개 통과.
- REST 어댑터·내부 escrow 관련: 4개 통과.
- 중복 재실행 제외 합계: **250개 통과, 3개 실패**. 실패는 신규 호환성 문제 2개와 아래 기존 테스트 기대 불일치 1개다.

기존 실패는 `test_mcp_initialize_tools_and_calls`가 항상 대체 검색 Agent를 기대하는 부분이다. 해당 fixture의 x402 목록은 검색·잔액·이미지 API 각 하나이며, 유일한 적격 검색 API를 제외하면 대체 후보가 없다. 이 경우 `None`을 반환해 관련 없는 대상을 추천하지 않는 동작이 확인됐다. 적격 대체 Agent를 두 개 준비한 새 여정에서는 실패 인식→대체 선택→재실행이 성공했다. 이 기존 기대 불일치를 운영 Provider 복구 실패로 확대 해석하지 않는다.

작업 소스와 운영 패키지는 일부 파일이 다르다. 특히 기록한 Frontend의 `fast_chat.py`는 작업 소스와 달랐다. 전체 소스가 운영에 동일하게 반영됐다고 가정하지 않고, 두 버전으로 재현 검사를 수행했다. 제품 코드·운영 설정·프로세스는 변경하지 않았다.

이번 작업에서는 실제 Provider 업무·실제 결제·운영 채팅을 실행하지 않았고, 운영 DB를 직접 변경하지 않았다. 기존 24시간 Edge 부하 검증을 연장하거나 재개하지도 않았다. 실제 고객 Agent의 장기 성공률, 지갑·정산 실거래, 새 Agent의 LLM 판단 성능은 후속 검증 항목이다.

## 6. 권장 보완 순서

1. **처음 온 Agent의 연결 계약 정리:** manifest와 runtime Schema·transport 안내를 일치시키고, 일반 MCP 클라이언트로 무설정 탐색 여정을 CI에 넣는다.
2. **실패를 학습·복구할 수 있는 응답 정리:** 표준 오류 신호, 구조화 상태, 재시도 가능 여부와 결과 불확정 상태를 일치시킨다.
3. **Agent 실행 입구 통합:** MCP `call`도 기존 Gateway/Ticket의 승인·무료 한도·관측·불확정 결과 보호를 재사용하도록 연결한다.
4. **승인된 Workflow를 Agent에게 명확히 노출:** 목록·입력·실행·상태·취소 도구와 목적·기간·건수·대상 제한 grant를 제공한다. 현재 권한·검토·계약 경계를 유지한다.
5. **Agent용 Workspace 진입 계약 보완:** Visitor 기억과 업무 실행권을 분리한 서비스 계정·범위 제한 위임을 설계하고, 사전 승인 이후의 반복 업무를 headless Agent로 검증한다.

핵심적으로, 현재의 탐색·실행 엔진을 활용하면서 **Agent가 읽는 계약과 승인된 반복 실행 경로를 완성하는 방향**이 적합하다.

## 검증 자료

- [재현 테스트 소스](<저장소>/tests/test_autonomous_agent_journey.py)
- [구조화된 검토 결과](<저장소>/reports/autonomous-agent-review-2026-10-24/review-summary.json)
- [새 Agent 여정 로그](<저장소>/reports/autonomous-agent-review-2026-10-24/agent-journey-final.log)
- [운영 패키지의 격리 재현 로그](<저장소>/reports/autonomous-agent-review-2026-10-24/operating-package-journey.log)
- [소스와 운영 패키지 비교](<저장소>/reports/autonomous-agent-review-2026-10-24/source-package-comparison.json)

재현 명령: `.venv/bin/python -m pytest -q tests/test_autonomous_agent_journey.py`. 현재 호환성 문제 2개를 실패 assertion으로 보존했으므로, 해당 문제가 수정되기 전에는 이 명령의 종료 코드는 1이다.
