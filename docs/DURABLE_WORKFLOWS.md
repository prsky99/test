# R-05 영속 실행·복구 계약

2026-10-18 · SQLite 실행 저장소 구현 및 PostgreSQL 실행 상태 이전 리허설

## 현재 적용 범위

기존 v1 게이트웨이 workflow의 공개/어드민/배포/예약/이벤트/내부 검증 실행에 적용한다. DB 대기열이 접수의 기준이며 로컬 future는 작업을 깨우는 수단이다. 기존 gateway scheduler가 5초마다 재개·전송 대기열을 확인한다. 별도 운영 워커는 `python -m agent_market.workflow_worker --db <explicit-path>`로 실행할 수 있고 `--once`는 한 번의 polling과 해당 프로세스 작업 완료를 기다린다. 개발 중 사용자 서버/워커는 시작·재시작하지 않았다.

현재 도구 admission·R-04 권한·공개 SDK 1.0/어드민 SDK 1.1·다운로드 형식은 유지한다. 장기 A2A task/session·분산 provider 상태 이전·자동 폴백·쓰기/결제 재실행은 제공하지 않는다. 기본 실행 예산 25초, 같은 DB에서 유효한 workflow lease는 최대 4개, 접수된 queued/running은 최대 12개다. 관리형 Testbench의 별도 실행 풀을 합친 전역 4개 제한은 아니다.

## 소유권과 체크포인트

`workflow_persistence.DurableRuns`를 실행 저장소 경계로 추출했다. SQLite writer lock 획득 후 용량을 확인하고 queued 실행을 CAS로 claim한다. 소유자마다 증가하는 fence와 2초 heartbeat를 사용한다. 파일 기반 SQLite는 정상 writer 대기(최대 10초)보다 짧았던 lease로 인한 조기 복구를 막기 위해 lease를 20초로 적용하며, 메모리 SQLite·PostgreSQL은 8초를 유지한다. 쓰기 경합 시 heartbeat는 200ms 간격으로 재시도하며, 성공하면 2초 간격으로 돌아간다. 전체 실행 deadline 25초와 만료·취소·fence 검사는 별도로 유지한다. heartbeat는 파일 DB에서 독립된 짧은 연결을 사용하고 일반 Store reader lock을 기다리지 않는다. lease/DB 장애에서 성공을 가정하지 않는다. 다른 워커가 fence를 올리면 과거 worker는 dispatch·체크포인트·완료 확정을 할 수 없다.

최초 claim에 `started/deadline`을 저장하고 재개 시 갱신하지 않는다. 각 프로세스의 외부 호출/monotonic 예산도 최대 25초로 제한한다. 영속 lease/deadline은 운영 시계에 의존하므로 시계 역행까지 포함한 전역 wall-time SLA는 주장하지 않는다. 최초 서명 주체는 1시간 만료를 유지하며 복구 때문에 권한을 새로 발급/연장하지 않는다.

제공자 호출 전에 입력 HMAC·node·run·fence와 `prepared`를 저장한다. 실제 제공자 dispatch 직전에 현재 권한/제어/소유권/취소/예산을 검사하고 `dispatched`를 먼저 확정한다. 이 기록 뒤 실제 bytes 전송 전 종료된 경우도 보수적으로 unknown이 될 수 있다. 재전송보다 안전을 우선하는 경계다.

각 단계 완료는 검사된 소유권 아래 node 상태·외부 시도의 확실성·서명 체크포인트를 한 트랜잭션에 저장한다. 체크포인트에는 redacted 결과/입력·downstream용 redacted 출력·라우터 판정·해당 단계의 전송 trace만 기록하며 raw credential을 복제하지 않는다. HMAC은 audience·run·snapshot digest·node·payload에 묶인다. 실행 snapshot 자체의 canonical digest도 다시 대조한다. 재개 시 현재 서명 주체·활성 배포/관리자/자동 설정·runtime policy를 다시 확인한다.

- 완료한 체크포인트는 도구를 다시 호출하지 않고 재사용한다.
- 아직 `prepared`이거나 시작 전인 단계만 원래 deadline 안에서 계속할 수 있다.
- `dispatched` 뒤 완료 증거가 없으면 실행은 종료하고 `execution_outcome=unknown`을 보존한다. 자동 재실행/폴백하지 않는다.
- 만료된 deadline, 취소, 변조된 snapshot/체크포인트, 만료/철회된 권한은 재개 권한이 아니다.
- 레거시 interrupted 실행에는 dispatch 증거를 만들어 넣지 않는다. 외부 결과를 unknown으로 보존하고 검토를 요구한다.

최상위 API 상태는 기존 SDK가 지원하는 queued/running/succeeded/failed/cancelled를 유지한다. 실패한 orchestration과 외부 업무의 확실성은 `execution_outcome`으로 구분한다. 이 필드가 unknown이면 외부 작업이 실패했다고 확정한 것이 아니다. 관리자 복구 조회는 node attempt의 prepared/dispatched/succeeded/failed/unknown과 고정 이벤트 이력을 별도로 보여준다.

## Transactional result outbox

최종 결과·실행 상태·정확히 한 번의 로컬 runs_count 증가·명시적으로 권한이 있는 결과 전송 outbox 삽입을 같은 트랜잭션에 확정한다. outbox에는 대상/run/event 참조만 저장하고 결과 본문·수신 주소·토큰을 다시 복제하지 않는다. 실행 결과는 전송 네트워크 오류 때문에 실패로 바뀌지 않는다.

전송 worker는 pending → claimed → dispatched를 CAS로 관리한다. 원래 R-04 grant와 인증된 수신처·digest·주체·현재 계정/배포/일정·만료/철회·delivery 제어를 dispatch 직전에 재확인한다. event ID는 재개 후에도 같다. 전송 claim lease는 60초다.

- 결과 commit 직후 worker가 종료되어도 pending event는 다음 polling에서 처리한다.
- claimed 상태에서 dispatch 전 종료되면 lease 만료 후 pending으로 돌아간다.
- dispatched 후 수신/응답이 불명확하면 unknown으로 종료하며 자동 재전송하지 않는다. Courier의 False/예외도 외부 수락 부재를 증명하지 못하므로 unknown이다.
- pause 이전의 미접수 pending event는 보존하고 재개 시 권한을 다시 검사한다. claim 후 마지막 경계에서 차단/철회된 건은 denied로 종료한다.
- 기존 `_deliver` 내부 호환 경로도 이미 commit된 event만 drain하며 새 전송 권한/event를 만들어내지 않는다.

공급자/수신자가 이미 수락한 업무를 취소할 수 없으며 local unique key·CAS·fencing은 외부 exactly-once 보장이 아니다. 명시적인 provider idempotency/status 계약 없는 불확실 업무의 재시도는 지원하지 않는다.

## 백업·복원

`python -m agent_market.workflow_backup backup --db <source> --directory <new-private-directory>`는 SQLite online backup API·integrity_check·SHA-256 manifest를 사용한다. 디렉터리 700, 파일 600이며 원본 DB raw copy/복구/교체를 하지 않는다. 로컬 updates-key는 private backup에 함께 보존한다. `AGENT_UPDATES_KEY` 같은 환경 관리 키는 내보내지 않으므로 같은 키의 별도 복구가 필요하다. 서명·암호화 자료가 없으면 과거 authority/inbox를 복호화할 수 없다.

`restore --directory <backup> --target <new-path>`는 기존 DB/키를 덮지 않고 새 경로에만 복원한다. checksum과 SQLite 무결성을 검사한다. 과거 snapshot이 실제 전송 이후의 상태를 알 수 없으므로 복원된 pending/claimed/dispatched event는 전부 unknown으로 격리한다. 미완료 실행도 자동 재개하지 않는다.

복원본은 invoke/workflow/delivery 제어와 자동 일정을 중단하고, 기존 배포 키를 비활성화하며, workflow grant/수신처 인증·이벤트 키·관리자 세션과 활성 task callback을 무효화한다. 이전에 철회된 권한을 오래된 백업에서 되살리지 않기 위한 조치다. 재인증/재발급·검토 없이 실행/전송을 활성화하지 않는다. 이 도구는 전체 플랫폼의 공급자/결제/조직 DR 인증이나 운영 DB 교체를 대신하지 않는다.

스키마 변경은 시작 시 additive/idempotent하게 적용한다. 운영 DB 직접 migration은 실행하지 않았다. R-05 체크포인트가 있는 대기 작업을 구버전 실행기로 롤백해 재생하지 않는다. downgrade가 필요하면 R-04 제어로 접수/호출/전달을 먼저 중단하고 실행 상태를 검토한다. 원본 upstream URL을 공개하는 롤백은 없다.

## PostgreSQL 리허설과 남은 경계

`scripts/rehearse_workflow_postgres.py`는 명시적으로 지정한 격리 SQLite의 실행 상태 15개 테이블을 private Unix socket 전용 임시 PostgreSQL로 옮긴다. 전체 row round-trip(서명 payload·따옴표·역슬래시·실제 fixture attempt/grant/outbox 포함), 8개 contender의 단일 claim, stale-owner 거절, run별 outbox unique를 검사한 뒤 임시 클러스터를 종료한다. REAL을 DOUBLE PRECISION으로 옮겨 timestamp 정밀도를 보존하고 PostgreSQL claim은 transaction advisory lock으로 전역 용량 판단을 직렬화한다.

현재 운영 adapter는 SQLite다. 전체 Store의 카탈로그/FTS·인증·collector·조직·거래를 PostgreSQL로 전환한 것은 아니며 운영 cutover나 전체 DB 호환 완료로 표현하지 않는다. 저장소 인터페이스/실행 상태 이전 근거를 후속 다중 조직 전환에 사용한다.

lease/fence는 현재 DB의 현재 상태에만 유효하다. 원본과 복원 clone을 동시에 자동 실행하지 않는다. 백업 restore는 의도적으로 fail closed하며 source snapshot의 성공만으로 운영 복구를 승인하지 않는다. 체크포인트·attempt·outbox·run event의 장기 정리/보존과 확대 용량, 고가용성 coordinator, provider 사실 검증·조직 ACL은 별도다. 자동 fallback/canary는 R-06이며 이번 코드에 활성화하지 않았다.

근거: [R-05 보고서](../reports/advancement-r05-2026-10-18/README.md), `tests/test_workflow_durability.py`, `tests/test_workflow_recovery_api.py`, `tests/test_workflow_durability_browser.py`, [SQLite 운영 지침](../deploy/DATABASE_OPERATIONS.md).


## R-06 integration

[Informational routing](WORKFLOW_FALLBACK.md) adds signed opt-in admission and separate ordinal routing attempts. The R-05 logical attempt remains the recovery barrier: uncertainty or a reserved alternative interrupted by process death requires review, never replay. Committed signed checkpoints still resume without another provider call. Restore also pauses routing and removes its policies/shadow receipts. R-05 PostgreSQL rehearsal covers the original 15 tables; new routing tables and full application adaptation remain outside that rehearsal.


## v1.10 operations hardening

See [implementation and rollout order](WORKFLOW_OPERATIONS_HARDENING.md). Standard/public execution remains 25 seconds. Explicit highest-admin run budgets are signed and bounded to 60 seconds total/15 seconds per baseline node; original deadlines survive resume. Heartbeats reuse a worker-owned connection without reducing synchronous durability. Explicit retention preserves replay tombstones and unresolved evidence. Reconciliation never overwrites unknown; a separately authorized, duplicate-risk-acknowledged result resend is one new event per original source event. Restore inventories prior IDs/states privately and keeps all controls/replays paused. The latest isolated migration rehearsal covers 27 state tables, not a full application cutover.
