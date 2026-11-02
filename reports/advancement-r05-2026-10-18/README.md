# R-05 영속 실행·체크포인트·결과 outbox·복원 검증

2026-10-18 · 제한된 SQLite 실행기 소스 구현·격리 검증 완료 · 운영 반영 대기

R-04 재시작 후 정상 공개 workflow와 권한 기록을 확인하고 R-05를 구현했다. [구현 계약](../../docs/DURABLE_WORKFLOWS.md), [설계서 v1.8](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md), [검증 JSON](verification.json).

## 적용 결과

- DB 대기열·현재 소유자/fence/8초 lease·2초 heartbeat와 같은 DB의 4개 활성 workflow 제한을 추가했다. 최초 deadline을 유지하고 프로세스별 외부 호출 예산도 최대 25초로 제한한다. 로컬 future가 완료·소유권의 근거가 아니다.
- 제공자 호출 전에 prepared/입력 HMAC, dispatch 직전에 현재 권한·정책·소유권/취소·dispatched를 확정한다. 서명 체크포인트와 snapshot digest를 검사하여 완료된 단계만 재사용한다. 자격증명은 masked 결과/입력/downstream 기록에도 복제하지 않는다.
- 제공자가 수락했을 수 있는 외부 요청에 완료 증거가 없으면 orchestration은 종료하고 execution_outcome=unknown을 보존한다. 외부 업무가 실패했다고 단정하거나 자동 재실행하지 않는다. 기존 SDK의 최상위 status 계약은 유지한다.
- 완료 결과·카운트·명시적 grant에 묶인 전송 outbox를 한 트랜잭션으로 기록한다. 완료 후 프로세스 종료는 pending event를 복구하고, 전송 후 응답 유실은 unknown으로 종료해 자동 재전송을 막는다. 이미 성공한 workflow 결과는 전달 오류 때문에 실패로 바뀌지 않는다.
- private recovery API와 관리자 **오류 → 실행 복구·전달 조회**, workflow 이력의 **복구·전달 상태**를 추가했다. 중앙 native dialog에서 고정 이벤트와 외부 시도/전송 확실성을 확인하며 raw checkpoint/서명/입력/수신처/토큰은 반환하지 않는다.
- HTTP server/collector를 시작하지 않는 명시적 workflow worker CLI, private online backup/integrity/hash/key 보존과 새 경로 복원 CLI를 추가했다. 복원본은 pending/unfinished를 unknown으로 격리하고 실행·예약·전송을 중단하며, 과거 배포/동의/수신처/이벤트 키/관리자 세션/활성 task callback을 무효화한다. 오래된 pending snapshot이 실제 전송 뒤에 복원돼도 자동 재전송하지 않는다.
- Home·메타데이터에 interrupted run 검토 안내를 영어로 추가했고 HTML 두 소스를 동기화했다. 공개 SDK/app JS와 공개/어드민 다운로드 builder는 R-04 해시와 같다.

## 검증 결과와 실제 범위

[전체 통합 1,130개 통과](final.log) 뒤 마지막 snapshot digest/예산 상한/복원 권한 보강에 대해 [영향 경로 274개 통과](final-boundaries.log)를 확인했다. 중복 제외 **고유 1,131개 통과, 실패·오류·skip 0건**이다. 중간 54개 core·74개 integration·68개 security는 합산하지 않는다. [통합 XML](final/regression.xml), [최종 경계 XML](final-boundaries.xml).

전체 통합은 마지막 방어 보강 전 시작했다. 마지막 소스에 대해 workflow/runtime/template/SDK·ZIP, actor/grant, admin recovery/workflow, observation, managed gateway, 실제 Chromium 및 제어된 HTTP/TLS의 모든 영향 경로를 다시 실행한 것이며 최종 소스로 전체 suite를 재실행했다고 주장하지 않는다.

격리된 별도 Python 워커를 실제 SIGKILL로 종료하는 경계는 prepared 전송 전, node checkpoint commit 후, 제공자 수락 후, 최종 결과/outbox commit 후, 수신처 수락 후다. 원래 workflow deadline·오래된 worker fencing·체크포인트/snapshot 변조·취소·heartbeat·입력 마스킹·복원된 pending 데이터와 stale authorization을 함께 검증했다. 이는 fixture/프로세스/DB 상태 전이 시험이며 모든 실제 공급자의 멱등성·복구 계약 검증은 아니다.

콘텐츠 **53개 파일 위반 0건**과 HTML 동기화·다운로드 해시 보존을 확인했다. 관리자 화면은 실제 Chromium에서 중앙 배치, Escape, 새로고침 유지, 악성 node ID의 DOM 비생성, 사적 API 역할 경계를 검증하고 화면을 확인했다. [관리자 복구 상세](admin-workflow-recovery.png).

정적 Bandit은 8개 변경 Python 모듈에서 **High 0·Medium 35·Low 29** 경고를 남겼다. 새 persistence/backup/worker/observability 모듈 경고는 0이다. 기존 SQL/예외 처리와 격리 PostgreSQL tool의 고정 schema/식별자·SQL literal/임시 디렉터리 경고를 개별 검토했다. PG DDL은 입력 DB의 sqlite_master가 아닌 신뢰된 소스 schema에서 만들고 NUL/비유한 값을 거부하며 quote/backslash round-trip을 실제 DB에서 검사한다. [원본](bandit.json), [개별 검토](static-triage.json). 이전 14-module 범위와 단순 수치 비교하거나 전체 무결함 인증으로 해석하지 않는다.

## PostgreSQL 이전 리허설

[실행 상태 15개 테이블](postgres-rehearsal.json)을 private Unix socket-only 임시 PostgreSQL에 옮겨 모든 행/서명 payload·quote/backslash·실제 fixture tool attempt·인증된 수신처/grant·accepted/pending outbox를 대조했다. REAL→DOUBLE PRECISION으로 시간 정밀도를 보존했다. 8개 contender 중 claim 승자 1개, stale-owner update와 중복 run outbox 거절을 확인하고 임시 cluster를 종료/삭제했다. 제공자 실호출/운영 DB 쓰기는 없었다.

**운영 adapter는 SQLite다.** 전체 Store/FTS·인증·collector·거래/조직을 PostgreSQL로 옮기거나 운영 cutover를 완료한 것이 아니다. 이 리허설은 실행 저장소 경계의 이전 근거다. 확장 시 실제 application adapter/lock·backup·키/ACL·부하를 별도로 검증해야 한다.

## 재시작 확인

[운영 정상 smoke](restart-verification.json): Home 200·R-04 안내/CSP, 실제 공개 workflow 1건 succeeded, 독립 read-only DB의 HMAC 서명 길이/public 주체/workflow-runtime-v1 audience/admin grant 없음, 관리자 controls API의 익명 403을 확인했다. 라이브 관리자 자격증명이 없어 인증 조회를 우회하지 않았다.

사용자 서버 중지/시작/재시작/교체 **0회**, 직접 운영 DB 쓰기/수동 migration **0회**, 외부 알림 발송/광고/결제 신규 활성화 **0회**다. 일반 공개 workflow smoke는 서비스 이력을 만들 수 있다. SIGKILL·악성 입력·복원·PostgreSQL cluster는 모두 임시 DB/프로세스만 대상으로 했다.

## 중간 실패와 수정

초기 회귀에서 기존 _deliver 호환 메서드를 복원했고 이미 commit된 event만 drain하도록 제한했다. 기존 restart fixture가 완료된 R-05 실행을 running으로 바꾸면서 복구 가능한 새 작업으로 만들어 다른 Runtime worker를 시작했다. fixture DB가 그 worker보다 먼저 닫혀 격리 Python이 crash한 기록은 initial.log에 보존한다. fixture는 legacy no-deadline 중단을 정확히 모델링하도록 수정했고, bounded 독립 heartbeat와 최종 강제 종료/늦은 worker/fixture 종료 회귀가 통과했다. 사용자 서버는 대상이 아니었다.

PostgreSQL 초기 CAS 검증은 psql 다중 명령의 중간 RETURNING 출력 수집이 누락돼 집계가 실패했다. stdin SQL script로 결과 수집을 바꾼 후 풍부한 최종 fixture 리허설을 통과했다. 실패 기록을 최종 성공 수에 포함하지 않는다.

## 운영 반영과 다음 작업

**새 R-05 코드를 반영하려면 사용자가 프론트엔드·어드민을 재시작해야 한다.** 관리자 HTML은 먼저 바뀔 수 있으므로 화면 존재만으로 새 recovery API 반영을 판정하지 않는다. 다음 정상 실행의 체크포인트/outbox 및 인증된 관리자 recovery·R-04 controls/grants 조회를 확인해야 한다. 운영 중 실제 중단 flag를 시험 목적으로 변경하지 않았다.

다음 개발은 **R-06 제한된 read-only 계약의 호환 fallback → shadow → 명시적 opt-in canary**다. 전체 G0의 운영 인증/과거 artifact/외부 재배포·확대 용량과 hosted CI는 남아 있다. 장기 A2A task/session, full PostgreSQL cutover, HA/global wall-time SLA, 전체 checkpoint/outbox 보존 정책, 전문가 provider benchmark, 조직 ACL·AI 합성·상용 결제는 완료 범위가 아니다. 외부 exactly-once나 이미 수락된 전송의 소급 취소를 보장하지 않는다.

설계서·구조화 backlog·기존 Canvas를 v1.8로 동기화했다. TSX 문법과 inline plan 일치, AC 14개·권장 순서 10개·Gate 4개 보존을 확인했다. [Canvas 검증](canvas-validation.json), [최종 소스 해시](final-source-snapshot.json).
