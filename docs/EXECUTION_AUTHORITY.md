# R-04 실행·결과 전달 권한과 운영 제어

2026-10-18 · 현재 제한 profile의 구현 계약 · 조직/v2 인증은 R-08

## 실행 주체와 목적

HTTP body의 actor/source/authority를 권한으로 사용하지 않는다. 어드민 실행은 인증된 관리자 ID·현재 역할, 공개 실행은 public, 어드민 다운로드 앱은 실제 활성 배포 ID, 예약/이벤트는 활성 설정과 서명 확인 경로에서 서버가 주체를 만든다. HMAC 서명 envelope는 `workflow-runtime-v1` audience, 워크플로우 ID, 주체 종류, 만료(1시간)를 고정한다. 실행 생성 트랜잭션에서 definition digest·source·run ID·선택된 전달 grant와 함께 다시 서명하여 저장한다. 각 단계에서 확인하고 배포 철회·계정 비활성화/역할 변경·예약 중단/이벤트 키 변경을 반영한다.

기존 내부 템플릿 검증의 `verification` 출처는 별도 서명 주체로 유지한다. 관리자 주체로 바꾸지 않으며 결과 전달 grant 및 플랫폼 credential을 상속하지 않는다. 공개/어드민 HTTP body로 이 출처를 지정할 수 없다.

공개 배포 키·Origin은 여전히 배포 통제다. 사용자 계정·조직·결제 권한으로 승격하지 않는다. 기존 내부 Python 호출의 `internal` 주체는 서버 내부 호환용이며 HTTP 입력으로 발급할 수 없다. 로그아웃만으로 이미 접수된 실행을 취소하지 않으며 취소·배포 철회·실행 중단을 사용한다. 레거시 실행에는 새 권한을 소급 발급하지 않는다. 권한 없는 기존 대기 실행은 제한된 읽기 실행만 가능하고 플랫폼 credential 및 관리자 inbox 전송은 허용하지 않는다.

## 결과 전달 grant

수신처 challenge 성공과 결과 전달 grant 발급은 별개다. **기존 인증된 수신처도 새 grant 없이는 결과를 보내지 않는다.** 최고관리자는 워크플로우의 예약·수신처 모달에서 현재 버전·수신처·출처를 검토하고 기본 미선택 체크박스로 명시적으로 발급한다. notice는 `workflow-result-grant-v1`이며 30일 만료, 별도 철회와 관리자 조회를 지원한다.

- 수동 실행은 발급한 관리자에게만, 자동 실행은 명시적으로 선택한 예약/서명 이벤트 출처에만 적용한다.
- grant는 워크플로우 ID·불변 definition digest·인증된 수신처 ID/봉인 데이터 해시·출처·비가역 주체 키에 묶인다. 주체 키는 단순 공개 ID 해시가 아닌 서버 HMAC이다.
- 일반 공개 실행과 SDK 1.0, 어드민 SDK 1.1 배포 앱은 관리자 수신처를 상속하지 않는다. 이번 릴리스에서 고객 배포용 결과 수신처 권한을 새로 제공하지 않는다.
- 새 버전·수신처 변경·철회·만료는 전송을 허용하지 않는다. 전송 claim 전과 실제 dispatch 직전에 현재 인증·grant·제어를 다시 확인한다. 중단/철회로 전송하지 못했어도 이미 성공한 workflow 산출물은 성공으로 유지하며 배포 상태를 `NOT_AUTHORIZED`로 표시한다.
- 광고 동의·작업 알림·워크플로우 결과 전달은 상호 대체하지 않는다. 광고 발송은 계속 비활성이다.

`workflow_run_authority`에는 서명 주체·scope만 저장하며 입력/출력·주소·방문자 토큰을 복제하지 않는다. grant에는 주소 대신 기존 암호화 수신처의 해시를 저장한다. 관리자 authority 조회는 유효 여부·종류·audience·출처·grant ID·만료만 반환하고 서명/키/subject는 반환하지 않는다. 새 authority/grant/audit 이력의 장기 보존·삭제·archive 용량 정책은 아직 확정하지 않았다.

## 실제 운영 제어

최고관리자 **오류 → 실행·결과 전달 제어**에서 다음 3개를 독립 변경한다. `GET/PUT /admin/api/execution-controls`는 최고관리자 인증·현재 revision CAS·정확한 boolean 3개를 요구한다. 변경과 고정 flags/관리자 ID 감사 이벤트는 같은 트랜잭션에 기록한다. 자동 새로고침은 미저장 편집을 덮지 않는다. 기본값은 현재 운영 기능과 호환되게 모두 허용이다. 새 고도화·광고·결제 flag를 활성화하는 기능은 아니다.

- `invoke_enabled`: 관리형 Testbench/MCP/A2A/x402·기존 proxy의 새 호출 및 실제 제공자 dispatch를 차단한다. workflow 도구 호출에도 적용한다. 탐색/목록/initialize와 실행은 구분하며 공개 준비 상태에는 내부 설정 대신 이용 가능 여부만 반영한다.
- `workflow_enabled`: workflow 새 접수·대기 실행의 단계·제공자 dispatch를 차단한다. 공개·어드민·예약·이벤트·다운로드 앱이 같은 저장 설정을 확인한다.
- `delivery_enabled`: 동의된 작업 알림과 workflow 결과 dispatch를 차단한다. 작업 알림 대기 건은 일시 중단만으로 소모하지 않고 재개 후 기존 동의/최신 증거를 다시 검사한다. 수신처 검증 challenge는 결과/광고 전송과 별개이며 계속 동작한다.

설정은 공통 SQLite에 영속 저장하며 프로세스별 환경 변수 캐시에 의존하지 않는다. 읽기 실패/누락은 실행 거절이다. 관측이 용량/저장 오류로 no-op이어도 메모리의 operation 종류로 제어하고, 타임아웃으로 분리된 worker의 dispatch 경계에서는 DB에 접근하지 않고 새 dispatch를 거절한다. 관측 저장 실패를 실행 허용 우회로 쓰지 않는다.

운영 순서는 현재 revision 조회 → 필요한 flag 해제 → 적용 확인 → 원인 조사/격리 시험 → 현재 revision 재조회 → 필요한 flag 복구다. 중단 중에도 status/cancel·기존 산출물·게이트웨이 projection은 유지하며 원본 주소를 재노출하지 않는다. 새 Python 코드 배포 전 HTML만 보이면 제어가 적용된 것으로 판단하지 않는다. 사용자가 프론트엔드·어드민을 재시작한 후 인증된 API로 확인해야 한다.

## 보장 범위와 다음 단계

중단은 새 접수·다음 단계·전송 직전 경계에 적용한다. 이미 외부에서 수락한 작업/전송을 취소하거나 마지막 검사 이후 전송 사이의 경합을 소급 제거하지 않는다. process-local 실행 풀(관리형 4개, workflow 4개/대기 12개)과 기존 예산은 유지한다. SLA·전역 분산 semaphore·전체 부하 시험·exactly-once 전송·자동 폴백·조직별 객체 ACL을 이번 완료로 주장하지 않는다.

R-04는 AC-07의 선행 중단/복구 통제만 구현한다. 전체 G0의 인증된 운영 검증·외부 배포·historical surface inventory·용량 검증, R-06 fallback shadow/canary는 남아 있다. 다음 R-05는 영속 worker·lease/fencing·checkpoint·outbox와 장애/복원 후 중복 확정 방지를 다룬다. 기존 전송 claim과 권한 envelope는 재시도 가능한 영속 outbox의 완성으로 해석하지 않는다.

근거: [R-04 검증 보고서](../reports/advancement-r04-2026-10-18/README.md), `execution_authority.py`, `workflows.py`, `workflow_apps.py`, `observability.py`, `tests/test_execution_authority*.py`.

## R-05 후속 반영

현재 SQLite 영속 실행·체크포인트·fencing·결과 outbox와 복원 격리는 [DURABLE_WORKFLOWS.md](DURABLE_WORKFLOWS.md)를 우선한다. 위 R-05 미구현 설명은 R-04 당시 범위다. 새 실행기에서도 원래 actor/audience/grant/만료를 연장하지 않으며 복원본은 과거 grant/배포/수신처 권한을 무효화한다. PostgreSQL은 실행 상태 이전 리허설만 했고 전체 Store 운영 전환·조직 ACL·외부 exactly-once는 완료하지 않았다.


## R-06 informational sharing

[Informational routing](WORKFLOW_FALLBACK.md) is a separate, default-off CAS control and signed policy. An explicit per-run sharing notice does not grant result delivery or advertising permission. Routing policy changes alter the runtime definition digest and revoke earlier delivery grants. Alternative dispatch revalidates the current signed run principal and live admin role; schedule/event/deployment/verification sources cannot opt in in this release.


## v1.10 operational permissions

[Operations hardening](WORKFLOW_OPERATIONS_HARDENING.md) adds explicit highest-admin-only extended run budgets, reconciliation, single-result manual resend and bounded retention apply. A new manual delivery uses signed current admin authorization tied to the exact result and verified inbox, one-hour expiry and a separate duplicate-risk acknowledgement. It never inherits the old unknown event permission, executes a provider again or grants advertising permission. Revocation/role/result/inbox changes block dispatch. The original unknown record remains immutable evidence.
