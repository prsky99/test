# 구현·계약·운영 상세 설계

> 2026-10-25 구현 기록: [Adoption v1.1 개발·검증 보고서](../agent-adoption-development-2026-10-25/README.md). 이번에 구현한 작은 프로필과 아래의 더 넓은 초기 제안을 구분한다. 운영 반영은 별도다.

> 효율화 후속 계약: [Adoption Design v1.1](../../docs/AUTONOMOUS_AGENT_ADOPTION_DESIGN.md)의 `adoption-compact-v1`은 다섯 도구의 작은 입구다. 아래 `/mcp/agent` 8개 도구는 더 넓은 Task/구독 프로필 제안으로 구분하며 기존 예제/Schema를 조용히 대체하지 않는다. 개발 시 공통 내부 검색·준비·실행·상태/취소 서비스를 재사용한다.

**이 문서의 신규 모듈·경로·필드·flag·저장소는 제안이다. 현재 운영에 존재하는 항목과 명시적으로 구분한다.** 설계 단계에서 서버 교체·Provider 호출·게시·DB migration을 수행하지 않는다.

## 공통 서비스 경계

현재 파일을 덮어쓰거나 사람용 UI와 Agent용 서비스를 따로 복제하지 않는다. 새 공통 계층을 얇게 추가하고 기존 입구에서 호출한다.

- 현재 `concierge/front.py`: Entry·Chat·Explore·템플릿·A2A·MCP HTTP 연결부. 목적 분류 이후 shared service를 호출한다. embedded HTML은 기존 동기화·CSP 규칙을 유지한다.
- 현재 `concierge/mcp_contract.py`: 기존 11개 도구와 별칭 계약 유지. 신규 compact profile은 별도 factory와 version을 둔다.
- 현재 `concierge/discovery.py`, `hybrid_explore.py`, `selection.py`: Agent 정규화·후보·relevance·최종 검증 순서를 재사용한다.
- 현재 `gateway/store.py`의 `list_workflows`, `workflows.py`: 목록·정의·Runtime을 재사용한다. 자연어 검색을 위한 정규화 projection을 별도로 추가한다.
- 현재 `capability_registry.py`: Agent 참조·Schema 버전·scope별 증거·현재 적격성을 재사용한다.
- 현재 `edge_gateway/machine.py`, `native.py`, `service.py`: Ticket 소유권과 실행 전/후 fallback 경계를 유지한다.
- 현재 `concierge/task_updates.py`, `workspace_machine_automation.py`, `workspace_remote_a2a.py`, `workspace_release.py`: 알림·목적별 grant·원격 Task·웹앱 계약에 adapter를 추가한다.

제안하는 신규 모듈은 `agent_access/contracts.py`, `entry.py`, `router.py`, `catalog.py`, `workflow_search.py`, `passports.py`, `tasks.py`, `protocol_adapters.py`, `metrics.py`다. 최종 경로는 개발 시 저장소 구조와 충돌을 확인해 정한다. 처음에는 같은 프로세스 안의 서비스 경계로 구현하고 별도 microservice를 먼저 만들지 않는다.

## 제안 API와 기존 API의 연결

### 기존 API

`GET /`, `POST /chat`, `POST /mcp`, `POST /a2a`, `GET /api/explore`, `GET /api/workflows/templates`, Workflow 실행·상태·취소, task update 경로를 유지한다. 기존 client의 `query/protocol`, `task/kind`, Visitor 전송·기존 응답 필드도 호환한다.

### 신규 versioned REST — 모두 제안

- `GET /api/agent/v1/entry`: 공개 기능·목적별 다음 행동·지원 버전. 읽기 전용이며 세션을 매번 생성하지 않는다.
- `POST /api/agent/v1/discover`: Agent 또는 Workflow 하나를 목적에 따라 선택. 검색 body에는 token·Provider URL·권한 주장을 받지 않는다.
- `GET /api/agent/v1/resources/{resource_ref}`: 선택한 공개 대상의 Schema·버전·입출력·검증 범위. private 대상은 인증·권한 확인 후 반환한다.
- `POST /api/agent/v1/prepare`: 대상·버전·입력·기존 권한을 확인해 준비 상태 반환. Provider 업무 호출은 0건이다.
- `POST /api/agent/v1/runs`: 확인된 준비 결과·grant·idempotency key를 결합해 실행 시작. 준비 이후 입력·버전·권한이 달라지면 재검토한다.
- `GET /api/agent/v1/tasks/{task_id}`: 소유권 검사 후 상태·receipt·안전한 결과 요약. Task ID만으로 조회하지 못한다.
- `POST /api/agent/v1/tasks/{task_id}/cancel`: 취소 요청 기록과 가능한 취소 전달. 실제 취소 확인 여부를 분리한다.
- `POST /api/agent/v1/resume`: 소유자가 접근 가능한 Passport를 명시적으로 선택해 재개·차이 정보 반환.
- `GET /api/agent/v1/updates`: 목적별 opaque cursor 이후 이벤트 조회. 기존 grant·검증된 목적지 서비스와 연결한다.
- `GET /api/agent/v1/openapi.json`: 위 공개 계약만 담은 작은 문서. private Admin·개발자 설정을 포함하지 않는다.

`resource_ref`, `task_id`, Passport ID는 대상 식별자다. 실행권·인증 token을 뜻하지 않는다. 플랫폼 상대 경로만 다음 행동에 반환하며 원문 질의·Credential을 query string에 넣지 않는다.

### 신규 compact MCP — 제안

`/mcp/agent`는 discover/describe/prepare/run/status/resume/updates/cancel을 고정 도구로 노출한다. 서버가 사용자·Workspace scope를 확인하며, 지원되지 않는 권한에는 적절한 준비/승인 필요 상태를 반환한다. 검색 결과에 Provider 도구 수천 개를 tools/list로 등록하지 않는다.

동적 검색은 **업무 대상 발견**을 의미한다. MCP protocol의 기능 목록을 질의마다 임의로 바꾸는 것과 구분한다. 필요한 도구 Schema는 describe 결과로 전달하고, 여러 client에서 structuredContent·outputSchema·짧은 텍스트가 모두 일관되게 읽히는지 검사한다.

### A2A adapter

0.3·1.0 parser·serializer·Card·오류·header 협상 snapshot을 각각 둔다. 단순 발견 메시지는 즉시 메시지로 반환하고 긴 승인된 실행만 durable Task로 연결한다. Streaming·Push·취소·Task 메서드는 실제 adapter 검사를 통과한 기능만 advertise한다. 기존 private remote Task 권한을 public Visitor가 상속하지 않는다.

## Discover 계약의 의미

상세 syntax는 `discovery.schema.json`, 합성 예시는 `contract-examples.json`에 둔다. 이 Schema는 **신규 discover 제안 계약의 일부**이며 전체 runtime API의 구현·상호운용 검증을 대신하지 않는다.

요청의 `resource_type`은 agent/workflow/auto다. Protocol이 생략된 개별 Agent 선택은 기존 A2A 기본값을 적용한다. Workflow에서는 명시적 Protocol 제약을 노드 수준으로 검사하고, 생략 시 템플릿의 실제 Protocol을 설명한다. 기존 Chat의 명시적 selector는 항상 우선한다.

`data_policy=owner_authorized`는 client가 요구하는 검색 조건일 뿐 서버의 실행권이 아니다. `max_latency_ms`는 요청 budget이며 더 오래 작업하도록 허가한 뜻이 아니다. budget 초과는 정직한 unavailable 또는 허용된 좁은 결과로 반환한다.

`resources`는 최대 1개다. 여러 후보 목록은 기존 Explore의 browse 경로를 사용한다. 선택한 대상은 ID·타입·이름·이유·입력 요약·상대 상세 경로·노드 Protocol·준비 상태를 제공한다. 상세 Schema는 describe로 분리한다.

검색 응답 상태는 `matched`, `no_match`, `clarification_required`, `authorization_required`, `unavailable`, `error`다. 실행 Task의 상태와 혼용하지 않는다. `authorization_required`는 기존 사용자 권한 확인을 위한 다음 행동이며 실행이 시작됐다는 뜻이 아니다.

HTTP 인증 실패와 malformed request는 전송·프로토콜 오류다. 정상적인 no_match·확인 질문·준비 단계의 권한 필요는 성공적으로 완료된 도구 결과다. 실제 run 실패·unknown·실행 거절은 MCP isError와 domain 상태를 맞춘다. 기존 call 실패의 isError 보호는 유지한다.

## 검색 자료와 안전한 캐시

신규 projection은 원본 식별자, 버전, 문서 hash, field 출처, 언어 alias, 목적·입력·출력, 노드 Protocol, private scope, evidence reference를 가진다. 추정된 목적은 `inferred`로 표시하고 원본 계약과 구분한다.

검색 단계는 입력 종류 정규화 → lexical fast path → 필요한 semantic 후보 보충 → relevance/입출력 제약 → 현재 적격성 → 기존 우선순위 → 공개 projection이다. 캐시·embedding·LLM이 마지막 적격성 검사를 생략하지 못한다.

3개 템플릿의 첫 구현은 메모리 projection+동의어로 충분한지 측정한다. 후보가 커졌을 때도 같은 service 계약을 유지하며 PostgreSQL 색인으로 교체한다. threshold·후보 수·reranker는 고정 정답셋과 별도 holdout에서 결정한다.

공개 계약/Schema 문서는 ETag를 제공하고 개인 응답은 `Cache-Control: private, no-store`를 기본으로 둔다. 검색어를 포함하는 결과의 공유 캐시는 익명·비민감·동일 공개 범위를 증명한 경우에만 허용한다. 모델·색인·권한·Protocol·Schema 변화는 관련 cache를 무효화한다. Secret·실행권·원문 개인 질의는 cache key·trace에 남기지 않는다.

## Task·실행권·요금 권한

서버 grant는 목적, 대상·버전, 입력 digest, 실행/전송 범위, 허용 attempt·시간·기간, 조직·owner, 필요 시 비용 상한을 가진다. 사용자 세션이 만료되더라도 명시적으로 발급한 독립 grant가 살아 있는지 현재 소유권·철회를 확인한다. Visitor identity는 Workspace grant를 대체하지 않는다.

공개 저위험 도구는 별도의 public execution policy가 허용한 계약·공개 입력·한도에서 anonymous 세션에도 목적별 실행권을 발급할 수 있다. 이 공개 정책은 운영자 검토를 거쳐 등록하며 Provider의 readOnlyHint만으로 결정하지 않는다. 기존 공개 MCP 실행을 일괄 로그인 필수로 바꾸지 않고, 새 Task 계층에서도 같은 승인 경계를 명시적으로 이어간다.

`prepare`와 `run`은 TOCTOU를 막도록 실행 직전에 현재 Schema·증거·권한·한도를 재검사한다. prepare 만료 뒤의 run은 시작되지 않는다. 동시 run은 같은 Task·idempotency 소유권을 원자적으로 점유한다. cache나 client 기억만으로 중복을 막지 않는다.

자동 Fallback의 구독 자격은 실행 정책의 필요조건이다. 구독만으로 다른 Provider에 데이터를 보내는 권한이 생기지 않으며, grant가 허용한 후보·데이터·예산 안에서만 실행한다. 비용·구독 정보는 필요한 machine 계약과 인증된 Workspace에서 다루고 공개 Chat의 답변·상세 화면에는 표시하지 않는다.

작성 Credit은 creation_session별 reserve/commit/release 원장을 사용한다. 중단·취소·기술 실패와 최종 확정의 과금 정책을 사전에 명시한다. 같은 작성 주기 재생성·수정은 중복 차감하지 않는다. 실제 외부 실행은 별도 권한과 사용량 원장을 적용한다. 플랜 요금·지급량은 아직 확정하지 않는다.

## 결과 전달과 실패 처리

내부 Task·노드 attempt·receipt·artifact를 분리한다. Provider 접속 성공과 특정 업무의 완료 검증은 다른 필드다. 결과가 일부만 유효하면 partial과 누락 범위를 제공한다. 사실을 생성해 성공으로 채우지 않는다.

실행권 발급 전의 미지원 Profile은 기존 승인된 runtime을 사용할 수 있다. 실행권을 준비한 뒤에는 결과 불확정을 다른 runtime 실행으로 우회하지 않는다. Worker 무료 한도 도달은 실행 전 같은 소유권으로 Origin 경로를 선택한다. 실행 점유 이후의 모호한 오류는 unknown이다.

모든 실행 결과의 우선 경로는 직접 Edge 실행 SDK 또는 Worker compact MCP ingress다. 정상 결과는 크기와 관계없이 Edge로 전달하고 Edge를 사용할 수 없을 때만 Origin으로 폴백한다. 발견·grant·receipt만 Origin에 보내는지 네트워크 byte로 확인한다. Provider 실행 점유 이후에는 중복 호출 없이 기존 receipt·상태를 확인하고, 같은 실행의 결과를 안전하게 회수할 수 있는 경우에만 전달 경로를 복구한다. 현재 Origin MCP wrapper의 결과 반환 bytes는 전후 baseline에 포함한다. 단순히 worker backend가 기록됐다는 이유로 egress 감소를 인정하지 않는다.

큰 결과의 자동 의미 분석은 기본 streaming에 넣지 않는다. 필요 시 명시적 비동기 요약 작업으로 분리한다. upstream body를 제한 없이 메모리에 쌓지 않고 backpressure·byte/time 한도·client disconnect를 검사한다. 실패 후 받은 일부 결과는 partial artifact로 남길 수 있지만 완료로 표시하지 않는다.

## 제안 저장 모델

현재 Registry·Workflow·Task·권한 원장을 먼저 재사용한다. 다음은 기존 테이블로 수용 가능한지 검토할 **논리 모델**이며 확정 DDL이 아니다.

- Capability projection: 대상·Schema 버전·목적·입출력·출처·공개 범위.
- Task Passport: owner·목적 요약·대상/Protocol·최근 상태·보존/삭제 정책.
- Task decision: 선택 이유·적격성 snapshot·준비 입력 digest·승인 범위.
- Task attempt: dispatch 소유권·Provider·시도·deadline·결과/unknown.
- Receipt/artifact reference: 검증 scope·상태·출력 hash·허용된 결과 경로·만료.
- Change event/cursor: 목적·의미 digest·순번·수신/전달 상태·멱등 event ID.
- Attribution: 게시된 공개 채널·설치 예시·검증된 client 연결과 업무 완료 수. UA 추정과 실제 인증 client는 분리한다.

private 데이터는 owner/조직별로 격리한다. raw 질의·실행 입력·결과 전문의 보관은 최소화하고 별도 목적·기간을 적용한다. 예외 상태의 실행 소유권·회계·보안 감사는 일반 캐시 정리와 분리한다.

## Admin 리뉴얼과의 연결

Visiting Agents에는 원문·token 대신 첫 연결 경로, 실제 인터페이스, 익명/인증 client 구분, 선택한 목적, 추천/준비/완료·재방문 상태를 집계한다. Machine grant에는 목적·owner·만료·건수·철회·목적지 검증·남은 권한을 표시한다.

Provider/Workflow에는 발견 가능성, 현재 적격성, Schema 버전, 실제 업무 검사 scope, 마지막 실패·unknown, 전달 backend·Origin bytes를 구분한다. 운영자에게 필요한 상세는 Admin에 두고 public에는 안전한 요약만 보낸다.

검색 0건·wrong_type·입력 누락·승인 필요·Schema 변경·전달 실패·결과 불확정을 별도 사유로 집계한다. 이를 통해 “방문은 있는데 왜 못 쓰는가”를 업무 단계별로 진단한다.

## API·실행·성능 시험

예정 시험 목록은 acceptance-cases.jsonl이다. 이는 실행 결과 파일이 아니다. 첫 단계의 평가 데이터는 수동 검토한 한글·영문 질의 300개를 제안한다: Agent 탐색 100개, Workflow 100개, 없는 업무·모호성·제약 충돌 100개. 개발 조정용과 고정 holdout을 나누고, 공급자·표현 변형이 holdout으로 누출되지 않게 한다.

작업 성공은 출력 계약과 source·필수 필드·범위·목적을 독립 validator로 판정한다. 모호한 예시는 사람 검토와 LLM 판단을 보조로 쓰되 스스로 생성한 답이 스스로 통과시키는 단일 평가를 피한다.

세 대표 업무의 semantic validator도 별도로 정의한다. 뉴스→논문은 주제 관련성·요청 기간·실제 source link·두 단계 연결을 확인한다. 국가→지표는 국가 식별·지표 코드·실제 source year·단위·없는 관측값 처리를 확인한다. 패키지→권고는 ecosystem·패키지 이름·버전 범위·출처·빈 검색 결과의 의미를 확인한다. 관련 Schema가 있다는 사실만으로 목적 달성으로 집계하지 않는다.

pass^5는 같은 업무를 독립적인 깨끗한 시험 세션에서 5회 수행해 모두 성공한 업무 비율이다. 동일 운영 작업을 부작용과 함께 5번 실행한다는 뜻이 아니다. 외부 Provider 검증은 별도 승인한 환경·데이터·건수로 제한한다.

모든 릴리스는 alias·Protocol·기존 MCP·A2A 버전·프론트 콘텐츠/보안·권한 철회·공개/개인 cache·Origin/Worker 중복 보호를 검사한다. 성능은 검색 warm/cold, client/server, payload 크기, Provider 포함/제외를 나눠 기록한다. 새로운 Edge 경로는 기존 heap/CPU 문제의 후속 24시간 격리 검증을 통과한 뒤 활성화한다.

## 적용과 복구 순서

제안 flag는 machine_entry, workflow_discovery, compact_mcp, task_passport, machine_task_bridge, edge_machine_ingress다. 처음에는 각각 비활성으로 추가하고 기존 동작을 기준으로 shadow 판정부터 비교한다. shadow는 Provider 실행을 추가하지 않는다.

발견 기능 canary → 공개 안내 일치 확인 → 준비 전용 canary → 권한 있는 실행 canary → Edge 결과 최적화 순서다. 각 단계마다 배포 artifact·변경 파일·active 역할·전후 지표·복구 버튼을 준비한다.

복구는 신규 요청의 기능 노출을 줄이고 이전 검증된 handler로 전환하되, 이미 실행된 Ticket/Task를 새로운 작업으로 다시 보내지 않는다. DB 추가는 기존 데이터 파괴 없이 진행하고, 이전 코드가 추가 테이블을 무시해도 정상 동작하게 한다. 기존 Jobs·Execution·Admin 서비스는 이번 문서 작성으로 시작·중지·교체하지 않는다.


## 사용자 확정 전달 정책 — 2026-10-25

모든 실행 결과는 크기·형식과 관계없이 Edge가 우선이다. Origin은 Edge 사용 불가·실패의 폴백 경로다. 실행 전 라우팅 실패는 안전한 Origin 전환을 허용하며, Provider가 이미 실행된 뒤에는 중복 실행 대신 기존 상태·결과 회수 가능 여부를 먼저 확인한다. 이 기준은 신규 MCP 입구와 Workspace·Workflow·다운로드 앱에도 동일하게 적용한다. 공개 검색·권한·작업 상태 같은 제어 처리는 Origin을 사용할 수 있으며, 정상 Provider 결과를 크기가 작다는 이유로 Origin에 우선 전달하지 않는다.
