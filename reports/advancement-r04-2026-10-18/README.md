# R-04 실행 권한·명시적 결과 전달·운영 중단 제어

2026-10-18 · 소스 구현과 격리 검증 완료 · 새 코드 운영 반영 대기

사용자 재시작 후 R-02 완료 trace와 R-03 실행 증거 생산자를 확인하고 R-04를 개발했다. [현재 구현 계약](../../docs/EXECUTION_AUTHORITY.md), [설계서 v1.7](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md), [검증 JSON](verification.json).

## 적용 결과

- 공개/어드민/활성 배포/예약/서명 이벤트/내부 템플릿 검증에 서버 발급 주체와 `workflow-runtime-v1` audience를 고정한다. 서명된 실행 권한은 워크플로우 ID·digest·source·run ID·grant에 묶여 생성 트랜잭션에서 저장되고 단계/전송에서 재검사된다. 관리자 역할·활성 상태 변경, 배포 철회와 자동 실행 설정 변경을 반영한다. HTTP body로 주체를 덮을 수 없다.
- 수신처 인증과 결과 전송 grant를 분리했다. 최고관리자가 현재 버전·검증된 수신처·관리자 본인/예약/서명 이벤트 출처를 선택하고 미선택 동의란을 체크해야 새 30일 grant가 발급된다. 별도 만료·철회·조회가 있다. **기존 수신처 인증만으로는 전송하지 않는다.**
- 공개 SDK 1.0 및 어드민 SDK 1.1 다운로드 앱은 관리자 inbox를 상속하지 않는다. 다른 관리자와 내부 템플릿 검증도 수동 grant를 상속하지 않는다. 조직/고객 배포용 별도 결과 수신 권한은 R-08 범위다.
- 최고관리자 **오류 → 실행·결과 전달 제어**에서 호출·워크플로우·결과 전송을 각각 중단/재개한다. SQLite 공통 설정·revision CAS·감사 이력을 유지하며 새 접수·단계·dispatch에 적용한다. 제어 읽기 실패는 거절하고, 관측 저장 no-op이 우회 경로가 되지 않는다. 타임아웃 worker의 새 dispatch도 거절한다.
- 전송 직전 철회/중단은 이미 성공한 workflow 산출물을 보존하고 `NOT_AUTHORIZED`로 남긴다. 작업 알림은 중단 중 대기 건을 소모하지 않고 재개 시 동의와 최신 증거를 다시 검사한다. 주소 challenge는 결과 전송과 별개다. 광고 발송은 계속 비활성이다.
- Home·메타데이터에 실행 시 최신 이용 가능 상태 확인 안내를 영어로 반영했다. public HTML 두 파일을 동기화했고 CSP/escaping/연결 URL 비노출을 유지한다. 공개 SDK 앱 JS·공개/어드민 다운로드 builder는 R-03 해시와 동일하다.

## 검증

최종 소스로 [전체 통합 1,116개 통과](final-v2.log), [권한/워크플로우/어드민/브라우저 관련 122개 통과](final-authority.log)를 확인했다. XML classname/name 중복 제외 **고유 1,116개 통과, 실패·오류·skip 0건**이다. 별도 46개 템플릿/권한 재검증, 초기 91개 연동과 중간 실행은 합산하지 않는다. [최종 통합 XML](final-v2/regression.xml), [관련 XML](final-authority.xml).

최종 통합은 내부 verification 출처 복원과 마지막 입력/역할 방어를 모두 포함한다. 격리된 SQLite·FastAPI/TestClient, 실제 Chromium, 제어된 HTTP·인증서 검증 TLS 서버를 사용했다. 범위는 정상 기능/실제 fixture 도구 호출·관리자 권한·객체/배포/실행 key 격리·HMAC 변조/audience·만료·철회/역할 변경·출처/digest/수신처 변경·대기/dispatch 중단·no-op 관측·알림 동의 분리·SSRF/XSS/SQL/출력 노출·CSP/영어 콘텐츠·기존 공개 SDK/어드민/ZIP 호환이다. 임의 운영 대상 공격은 하지 않았다.

콘텐츠 **53개 파일 위반 0건**, embedded HTML 동기화 및 보존 대상 패키지 해시 일치를 확인했다. 정적 Bandit은 14개 Python runtime/registry/gateway/collector/Store/admin 모듈에서 **High 0·Medium 46·Low 40** 경고를 남겼다. 고정 서버 SQL/주소 비교/기존 예외 처리 등 개별 근거로 검토했으며 새 authority/registry/contracts/observability는 경고 0건이다. [원본](bandit.json), [개별 검토](static-triage.json). 점검 범위가 다른 이전 수치와 단순 비교하거나 전체 무결함 인증으로 해석하지 않는다.

관리자 화면에서 제어 적용/재개와 목록 새로고침 중 미저장 편집 보존, 기본 미선택 목적별 grant 발급/철회를 실제 브라우저로 검증했고 화면을 확인했다. [실행 제어](admin-runtime-controls.png), [전달 권한 모달](admin-delivery-grant.png).

## 재시작된 운영 서버 확인

[읽기 전용 확인](restart-verification.json): 정상 뉴스 예제 1건이 실제 성공(simulated=false)했고 동일 참조가 공통 DB에서 R-02 succeeded/finished와 R-03 execution/succeeded 증거로 연결됐다. 로컬·공개 홈에 Accept:text/html을 지정한 정상 GET은 200/HTML·현재 검증 표시·CSP를 확인했다. 최초 Accept 없는 응답의 marker=false는 배포 판정에 사용하지 않는다. 관리자 trace API 익명 요청은 403이었다.

도구 환경에 관리자 자격증명이 없어 인증된 운영 조회를 우회하지 않았다. 정상 뉴스 요청은 일반 서비스 이력을 만들 수 있으나 직접 운영 DB 쓰기/수동 migration/복구는 하지 않았다. 사용자 서버 중지·시작·재시작·교체는 **0회**, 실제 외부 알림/광고/결제 발송 및 신규 활성화도 **0회**다. 악성/용량/정책 거절 입력은 모두 격리 환경에만 보냈다.

## 중간 실패와 수정

초기 연동 2개는 인증된 inbox만으로 전송을 기대하던 fixture여서 새 명시적 grant 동의를 추가했다. 배포 철회 테스트는 기존 취소 동작의 cancelled를 failed로 기대해 정확한 상태로 수정했다. 늦은 worker 테스트는 새 dispatch 거절을 확인하도록 바꿨다. 첫 전체 통합의 6개 오류는 내부 템플릿 verification 출처가 새 허용 목록에서 빠져 setup이 중단된 원인이었다. 별도 서명 주체로 복원하고 관리자 grant/credential을 상속하지 않는 테스트와 관련 46개를 통과한 뒤 전체 통합을 다시 실행했다. 중간 로그/XML은 그대로 보존하며 성공 근거에 포함하지 않는다.

## 운영 반영과 다음 작업

**새 R-04 Python 코드는 사용자가 프론트엔드·어드민 서버를 재시작해야 한다.** 어드민 HTML은 파일에서 먼저 읽히므로 새 화면 표시만으로 API 반영을 판정하지 않는다. 인증된 최고관리자로 제어 revision/flags·전달 grant·실행 권한과 기존 trace/evidence 조회를 확인해야 한다. 운영 제어를 시험하기 위해 실제 서비스 중단 flag를 임의로 변경하지 않았다.

전체 G0는 open이다. 인증된 운영 smoke, 과거 공개 artifact 전체 inventory, 외부 서버에 다시 배포한 앱, 확대 용량/복구 검증과 최초 hosted CI를 별도 남긴다. R-04는 AC-07의 기초 제어이며 R-06 fallback shadow/opt-in canary를 완료한 것이 아니다.

다음 개발은 **R-05 영속 worker·lease/fencing·checkpoint·transactional outbox·백업/복원 및 PostgreSQL 이전 리허설**이다. 현재 로컬 풀/25초 예산/12개 대기열과 기존 claim은 영속 복구·exactly-once·SLA가 아니다. 이미 외부에서 수락한 작업을 철회하지 못하며 마지막 검사/실제 전송 사이의 경합을 소급 제거하지 않는다. 주체/grant/control 이력의 장기 보존·archive 정책, 조직 ACL(R-08), 전문가 provider benchmark·전수 실호출·AI 합성·상용 결제도 별도다.

설계서·구조화 백로그·기존 Canvas를 v1.7로 갱신했다. Canvas TSX 문법과 inline plan 일치, AC 14개·권장 순서 10개·Gate 4개 보존을 확인했다. [Canvas 검증](canvas-validation.json), [최종 소스 해시](final-source-snapshot.json).
