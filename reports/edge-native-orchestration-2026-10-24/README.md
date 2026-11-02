# Native 실행 경로의 Edge 연결 · 운영 활성화 완료

## 완료한 개발과 현재 운영 상태

Workspace 비공개 실행, Workspace typed graph, Workflow MCP·A2A 노드, 이 Runtime을 사용하는 다운로드·게시 웹앱의 서버 실행 경로에 공통 Edge 연결 코드를 추가했다. Worker 확장 버전 `a37f7077-aeaa-4f19-bcdc-6a90c5c41200`는 100% 배포했고, 공식 API로 기존 5개 fail-open Route와 서명 health를 재확인했다.

**2026-10-24 13:13 KST, 사용자 승인에 따라 네 역할의 Native Edge 연결을 운영 활성화했다.** `native_node_delivery=true`, 선호 경로 `worker`, 정책 사유 `free_available`을 확인했다. Frontend·Admin은 A/B 전환했고 Jobs·Execution은 기존 프로세스 종료를 기다려 순차 교체했다. 네 역할 모두 준비 상태 또는 heartbeat를 통과했다. 무료 플랜과 자동 유료 전환 비활성화, 기존 5개 fail-open Route를 유지했다.

## 연결 방식과 보존한 보안 경계

1. 기존 Workspace 승인, 세션, Workflow lease/fence, 계약·입력 pin을 먼저 확인한다. 부모 dispatch fence가 없는 호출은 새 연결을 사용하지 않는다.
2. 같은 PostgreSQL/SQLite 상태의 기존 Edge run과 짧은 수명의 Ticket을 발급한다. 등록 버전과 입력을 다시 묶고, 원래 부모 실행권을 소비한 다음 플랫폼 도메인으로 HTTP 요청을 한 번 전송한다.
3. Worker가 원천 Provider를 호출한다. Native용 JSON 결과 형식은 기존 공개 SDK의 SSE 경로와 함께 지원한다. MCP 구조화 결과와 A2A parts를 원래 Runtime의 검증·저장 절차로 돌려준다.
4. 한도·health·프로필 조건이 맞지 않으면 요청 전 기존 Native 경로를 사용한다. Cloudflare가 Route를 fail-open하면 같은 Ticket을 Origin이 한 번 claim해 실행하고 `backend: origin`을 명시한다. HTTP 전송 후 결과가 불확실하면 Native Proxy로 작업을 다시 실행하지 않는다.
5. Cookie·방문자 Token·플랫폼 공용 Secret은 전송하지 않는다. 명시적인 Workflow credential_refs 바인딩과 credential key·Bearer/Basic 값·인증정보가 든 URL 입력은 기존 승인된 Native 경로를 유지한다. 중복 실행권 거부는 정책 거부로 처리해 정상 Provider를 Schema 오류로 오분류하지 않는다.

Native orchestration은 DAG의 중간 결과를 받아 계약을 검사하고 저장한다. 따라서 이번 연결은 Provider 호출을 Edge 경로로 옮기지만, 최종 결과를 Native 서버가 사용자에게 반환하는 전송 비용까지 제거하는 구조는 아니다. 큰 최종 산출물의 직접 전달은 별도 artifact/reference 전달 계약이 필요하다. 새 유료 Cloudflare 서비스·추가 Secret·DB 마이그레이션은 이번 변경에 포함되지 않는다.

## 신규 후보와 확대 대기 전수 검토

최근 스냅샷의 신규 후보 1,688건과 확대 대기 7,216건, 총 **8,904건**을 현재 등록 정책·등록된 Schema 거부 이력·DNS 기준으로 다시 검토했다. 운영 DB 쓰기와 이 전수 검토 중 Provider HTTP 호출은 각각 0건이다. 공개 DNS는 고유 140개 호스트 중 139개가 확인됐고 1개는 보류했다.

신규 후보 1,688건은 **1,684건이 정적·DNS 조건을 유지**, 3건은 인증 정책상 제외, 1건은 DNS 보류다. 조건 유지 구성은 A2A 15건·MCP 74건·x402 미결제 probe 1,595건이다. catalog 정책이 이미 전체 Protocol에 적용돼 있어 조건을 통과하는 신규 ID는 수동 allowlist 추가 없이 심사를 받는다. 이 수는 실제 호출 성공이나 유료 x402 작업 완료를 뜻하는 수치와 구분한다.

확대 대기 7,216건의 현재 상태는 Schema 확보 필요 3,132건·안전 입력 준비 3,225건·대용량/프로필 검토 856건·정책상 제외 3건이다. ID별 현재 상태와 다음 조치는 `candidate-review.csv`에 정리했다. Schema가 없거나 안전 입력을 만들지 못한 항목을 실행 가능으로 강제 전환하지 않았다.

추가로 서로 다른 MCP 호스트 3곳에 metadata-only 조사를 수행했다. `server/discover`와 `initialize` 요청 총 6회만 사용했고 도구 실행·결제·운영 DB 변경은 0건이다. 세 곳 모두 유효한 Schema를 확보하지 못해 편입을 보류했다. 오류 종류와 요청 수는 `metadata-survey.json`에 보존했다. 기존 결과 미확정 Provider를 재실행하거나 기존 장기 순회 큐를 변경하지 않았다.

## 5개 fail-open Route의 의미

이 5개는 실패 테스트 수가 아니라 A2A·MCP·x402·Testbench·Edge run API에 적용한 정상 Route의 수다. Cloudflare의 무료 일일 요청 한도 초과 시 Worker를 우회해 기존 Origin으로 보내는 설정이다. CPU 오류나 실행 후 연결 단절에 대해 작업을 자동 반복하는 설정으로 해석하지 않는다. 공식 문서: [Cloudflare Workers 한도와 Route 동작](https://developers.cloudflare.com/workers/platform/limits/#daily-requests).

## 검증 결과와 범위

- 기존 Runtime·Workspace·웹앱·Jobs 구성 회귀: 206개 통과.
- Gateway·Native 전송·실제 실행 분기·권한 회귀: 고유 81개 통과. credential URL 차단과 중복 권한의 정책 오류 분류도 재확인했다.
- 실제 Worker 소스의 격리 workerd: 39개 통과.
- Edge·Workspace·typed graph·다운로드 웹앱 브라우저 보안: 51개 통과.
- 합계 고유 **377개 통과**. 반복한 테스트는 합계에 다시 더하지 않았다.

네 역할의 실제 검토용 릴리스에서도 별도로 Frontend 33개, Admin 33개, Jobs 33개, Execution 32개를 통과했다. Execution은 HTTP Origin 서버를 제공하지 않는 역할이므로 해당 HTTP endpoint 1개는 이 역할에서 제외하고 Frontend·Admin 패키지에서 검증했다. 초기 진단 로그도 보존했다. 네 역할 모두 기존 운영 PostgreSQL 상태와 Edge 전용 설정을 읽기 전용으로 불러오는 데 성공했다. 오래된 Execution 릴리스에는 Edge 설정 파일 로딩 경로 2곳을 최소 수정으로 포함했다.

테스트는 합성 데이터와 모의 Provider를 사용했다. 새 Native 연결의 운영 Provider 결과까지 실측한 것으로 확대 해석하지 않는다. 기존 24시간 부하는 이전 Worker 소스 스냅샷의 baseline이며 새 Native Ticket 경로의 24시간 안정성 증거와 구분한다. 이전 메모리 안전 기준 중단과 확대 운영 표본 CPU 23.6ms는 남은 검증 과제다.

## 논문·SNS·공식 자료를 반영한 판단

[ExoFlow, OSDI 2023](https://www.usenix.org/conference/osdi23/presentation/zhuang)와 [Beldi, OSDI 2020](https://www.usenix.org/conference/osdi20/presentation/zhang-haoran)는 실행과 복구, 로그·상태의 소유권을 분리하는 설계 근거로 검토했다. 이 연구만으로 임의의 외부 Provider가 정확히 한 번 실행된다고 보장할 수는 없다. 이번 구현에서는 기존 durable fence와 단일 claim을 유지하고, 결과 미확정 시 자동 재실행을 막는 보수적인 방식을 택했다.

[MCP 공식 전송 규격](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)은 JSON과 SSE 응답 지원, 세션 헤더와 연결 단절·취소의 구분을 확인하는 기준으로 사용했다. Native JSON 응답 확장은 Provider 프로토콜 협상을 바꾸지 않고 플랫폼의 승인된 결과 전달 형식만 확장한다.

SNS에서는 [Worker 메모리 문제 경험담](https://www.reddit.com/r/CloudFlare/comments/1x89v7d/slow_workers_max_memory_reached/)과 [로컬 테스트·플랫폼 제한 차이 경험담](https://www.reddit.com/r/CloudFlare/comments/1wr08ql/psa_workers_caps_pbkdf2_at_100000_iterations_node/)을 교차 검토했다. 해당 글은 증상 조사 자료로 사용하고, 구현 판정은 공식 한도·실제 회귀·운영 서명 검증으로 확인했다. 로컬 성공을 전체 Provider의 CPU·메모리 안정성 보장으로 바꾸어 설명하지 않는다.

## 승인 후 운영 반영과 검증

승인 대기 중 갱신된 운영 릴리스를 다시 확인하고 최신 기준본을 복제했다. Frontend·Admin·Execution에는 이번 Native 코드가 이미 포함돼 있어 해당 코드의 추가 차이는 0개였으며, 새 설정을 읽도록 프로세스를 교체했다. Jobs에는 검토한 Edge 변경 11개 파일만 추가됐다. Execution의 최신 fallback 관련 코드와 Admin 리뉴얼을 보존했다.

- frontend: `web-20261024-130523-557e` → `native-edge-frontend-20261024-130810`.
- admin: `web-20261024-130523-557e` → `native-edge-admin-20261024-130810`.
- jobs: `admin-renewal-ui-20261023-v1` → `native-edge-jobs-20261024-130810`.
- execution: `fallback-independence-20261024-v1` → `native-edge-execution-20261024-130810`.

`activation-result.json`과 `activation-verification.json`에 운영 반영 결과를 기록했다. 네 역할의 릴리스 manifest·활성 PID·웹 준비 상태 또는 background heartbeat를 확인했고, Frontend·Admin의 페이지·정적 파일·권한 경계를 재검증했다. `approved-remote-preflight.json`은 배포 후 Worker 버전 100%, 5개 fail-open Route, 유효한 HMAC health 응답을 확인한 기록이다. `approved-remote-before-activation.json`은 활성화 전 상태를 보존한다. 새 Secret과 DB 마이그레이션은 각각 0건이다.

최신 패키지 회귀는 Frontend 34개·Admin 34개·Jobs 34개·Execution 33개 통과다. Execution의 HTTP 전용 1개는 역할 특성에 따라 제외하고 Frontend·Admin에서 검증했다. 최초 sandbox 검증과 임시 PostgreSQL 동시 생성에서 initdb/pg_ctl 실패가 발생했으며, 전체 권한의 단독 실행에서 세 패키지를 다시 확인해 모두 통과했다. 초기 실패 로그도 보존했다. 검증용 임시 클러스터는 정리됐고 운영 DB에 검증 데이터는 쓰지 않았다.

활성화 후 확인에서 `native_node_delivery=true`, `preferred_backend=worker`, `reason=free_available`, `worker_plan=free`, `automatic_paid_upgrade=false`였다. 이 상태는 승인된 조건을 충족하는 Native 노드에 적용된다. Credential 바인딩·인증 입력, 미지원 Schema/프로필, 무료 한도·health 조건은 기존 Native/Origin 경로를 유지한다. 결과가 불확실한 실행의 자동 반복도 계속 막는다.

이번 운영 확인은 추가 Provider 실행 없이 수행했다. 전체 Provider 성공과 새 Native 경로의 24시간 안정성 검증은 후속 검증 항목이다. 기존 격리 부하는 이전 Worker 소스 기준으로 계속 진행하며 기존 운영 순회 보호 대기는 변경하지 않았다.
