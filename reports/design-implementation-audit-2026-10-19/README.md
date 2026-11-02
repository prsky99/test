# 설계 대비 구현 누락·부분 구현 감사

작성: 2026-10-19T13:24:35.514569+09:00 · 범위: R-01~R-10 / G0 / P2-01~P2-10 / R&D 하위 묶음.

**전체 설계가 모두 개발되었거나 누락이 없다고 판단할 수 없다.** 공개 Chat·실제 Testbench 예제·게시 워크플로우/게이트웨이 ZIP·주소 인증/알림·방문 에이전트/고객 요청의 기존 핵심 연결은 확인했다. 제한된 2차/R&D 구현도 존재한다. 그러나 구체적인 소스·화면 연결의 부분 누락과 아직 선택·구현하지 않은 확대 profile이 남아 있다. 외부 설정만으로 모두 완료되지 않는다.

## 범위와 증거의 의미

- 세 병렬 감사에서 소스·호출자·라우터·관리자 UI·worker·CI 선택을 읽고 설계와 대조했다. 모든 변경 요구가 보안 취약점이라는 뜻은 아니다.
- 이번 감사에서는 제품/테스트 코드를 수정하지 않았고, 서버/프로세스/운영 DB/외부 연동을 건드리지 않았다. 새 동적 재현·회귀 실행은 0건이다.
- 과거 동결 v1.40의 700입력·78모듈·1,313고유 회귀와 내부 native80계약, 재시작 후 읽기38건은 역사적 근거다. native80을 pytest 수에 합산하지 않는다. 인증된 관리자·실제 외부 품질/전달/DR 수용으로 대체할 수 없다.
- 현재 accepted 입력 중 12개가 과거 SHA와 다르고 과거 스냅샷 밖의 관련 제품/시험/복구 스크립트 9개를 관찰했다. 스냅샷 미포함은 최근 생성의 증거가 아니며 다른 batch 삽입 스크립트는 이번 검토 범위에서 제외했다. 다른 실행의 변경을 보존했다. 현재 변경분은 과거 1,313개로 검증되지 않았다. 정확한 SHA와 CI 목록은 [current-source-inventory.json](<저장소>/reports/design-implementation-audit-2026-10-19/current-source-inventory.json)에 있다.
- frontend embedded HTML/미러 일치와 literal Hangul 부재는 읽기 확인했다. 이는 공개 콘텐츠 전체 검사 재실행이나 전 소스 보안 보증이 아니다.

## 우선 보완할 부분 누락

### ER-01 · 운영 품질 증거의 자격 승인·승격 경로 누락

현재 실제 연결된 evidence producer는 운영 자격을 항상 false로 반환한다. 설정 가능한 환경에도 operating이 없어 평가자나 enable flag만 추가해도 운영 admission/circuit 요건을 충족할 수 없다. 보수적 차단은 올바르지만 완성된 운영 경로로 볼 수 없다.

완료할 차이: 기존 evidence plane에 provenance·독립 rubric/holdout·목적·현재 버전/권한·만료/철회를 묶은 서명 자격 승인·승격 계약을 추가한다. 단순 flag 완화로 우회하지 않는다.

근거: [workspace_reliability.py:166](<저장소>/agent_market/workspace_reliability.py:166), [workspace_reliability.py:612](<저장소>/agent_market/workspace_reliability.py:612), [reliability_admission.py:189](<저장소>/agent_market/reliability_admission.py:189), [reliability_circuit.py:147](<저장소>/agent_market/reliability_circuit.py:147), [workspace_platform.py:112](<저장소>/agent_market/workspace_platform.py:112). 담당 순서: `POST139R-03`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### ER-02 · 보관된 연구 manifest 재선택·재사용 UI 누락

연구 대화상자는 닫거나 다시 열면 선택을 잃으며 새 manifest 생성만 로컬 선택을 채운다. 저장된 정상 manifest를 목록에서 선택해 재사용할 수 없어 불필요한 재생성을 유도한다. 기존 corpus/plan API는 존재한다.

완료할 차이: 정확한 ID/hash/revision·유효기간·현재 권한을 확인하는 재선택 UI를 연결하고 새 계획 승인은 매번 미선택 상태로 검토한다. 기존 corpus와 worker를 재사용한다.

근거: [workspace-reliability-research-admin.js:16](<저장소>/agent_market/gateway/workspace-reliability-research-admin.js:16), [workspace-reliability-research-admin.js:53](<저장소>/agent_market/gateway/workspace-reliability-research-admin.js:53), [workspace-reliability-research-admin.js:59](<저장소>/agent_market/gateway/workspace-reliability-research-admin.js:59), [workspace-reliability-research-admin.js:70](<저장소>/agent_market/gateway/workspace-reliability-research-admin.js:70), [reliability_control_service.py:76](<저장소>/agent_market/reliability_control_service.py:76). 담당 순서: `POST139R-01`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### ER-03 · 연구 분석의 동일 corpus ID 확인 누락

연구 분석은 요청 manifest의 corpus와 현재 평가 계획을 hash로만 비교한다. 같은 내용이지만 ID가 다른 활성 manifest 두 개가 있으면 다른 계획의 작업 수/분모를 섞어 표시할 수 있다. 독립 품질을 허위 승격하는 경로는 확인하지 않았다.

완료할 차이: dispatch와 마찬가지로 정확한 corpus_id와 hash를 함께 검사한다. 외부 호출 없이 두 활성·동일 내용·상이 ID의 분석 거부 회귀를 추가한다.

근거: [reliability_research.py:328](<저장소>/agent_market/reliability_research.py:328), [reliability_research.py:332](<저장소>/agent_market/reliability_research.py:332), [reliability_research.py:353](<저장소>/agent_market/reliability_research.py:353), [reliability_research.py:404](<저장소>/agent_market/reliability_research.py:404), [reliability_research.py:248](<저장소>/agent_market/reliability_research.py:248). 담당 순서: `POST139R-01`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### ER-04 · 준비된 admission의 재검토·재개 연결 누락

서버에는 prepared admission과 단발 execute 경로가 있지만 관리자 이력은 텍스트다. 화면을 닫았다 열면 기존 준비 건을 선택해 정확한 입력을 재검토하고 실행할 수 없어 새 logical ID/ticket을 다시 만들게 된다.

완료할 차이: 현재 권한으로 보관 ticket/snapshot의 정확한 입력을 읽고 재검토하는 경로와 UI를 추가한다. 같은 ticket에 새 명시 동의를 받아 실행하며 unknown/denied/not-selected를 자동 재생하지 않는다.

근거: [workspace-research-controls-admin.js:65](<저장소>/agent_market/gateway/workspace-research-controls-admin.js:65), [workspace-research-controls-admin.js:75](<저장소>/agent_market/gateway/workspace-research-controls-admin.js:75), [workspace-research-controls-admin.js:80](<저장소>/agent_market/gateway/workspace-research-controls-admin.js:80), [reliability_admission.py:144](<저장소>/agent_market/reliability_admission.py:144), [reliability_admission.py:267](<저장소>/agent_market/reliability_admission.py:267). 담당 순서: `POST139R-01`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### ER-05 · 재계획 변경 비교·기준 revision 표시 누락

백엔드는 기준 flow/revision과 필드별 변경 목록을 계산한다. 화면에는 목적지와 전체 제안 그래프만 보이며 변경 비교와 기준 revision이 빠졌다. 명시적인 새 초안 검토 자체는 가능하다.

완료할 차이: 안전한 제한 텍스트 diff와 기준 revision을 먼저 표시한다. 편집·세션·workspace 변경 시 동의를 초기화하고 새 초안으로만 저장하는 경계를 유지한다.

근거: [workspace_app_factory.py:193](<저장소>/agent_market/workspace_app_factory.py:193), [workspace_app_factory.py:210](<저장소>/agent_market/workspace_app_factory.py:210), [workspace-research-controls-admin.js:55](<저장소>/agent_market/gateway/workspace-research-controls-admin.js:55), [test_workspace_plan_reviews.py:40](<저장소>/tests/test_workspace_plan_reviews.py:40). 담당 순서: `POST139R-01`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### PA-00 · 비공개 기능의 검증된 서버 조립·설정 진입점 누락

PrivateIntegrations 주입과 adapter/core wiring은 있으나 실제 서버의 검증된 비공개 조립 진입점은 없고 주입 예는 테스트에 있다. public 기본 off는 올바르지만 이것만으로 운영자가 비공개 파일럿을 구성할 수는 없다.

완료할 차이: cached platform 생성 전 정확한 typed adapter/목적지/수신기 binding을 설치하는 단일 private builder를 추가한다. 기존 worker/lifecycle을 재사용하고 설정 flag를 실행 권한으로 취급하지 않는다.

근거: [workspace_integrations.py:30](<저장소>/agent_market/workspace_integrations.py:30), [workspace_platform.py:99](<저장소>/agent_market/workspace_platform.py:99), [workspace_platform.py:126](<저장소>/agent_market/workspace_platform.py:126), [workspace_platform.py:134](<저장소>/agent_market/workspace_platform.py:134), [test_workspace_integration_wiring.py:60](<저장소>/tests/test_workspace_integration_wiring.py:60). 담당 순서: `POST139R-02`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### PA-01 · 고객 조직의 시험→릴리스→배포·내보내기 연결 미완성

고객 조직 owner는 초안/snapshot을 관리하고 관리자 발급 앱을 사용할 수 있다. 그러나 시험→immutable release→배포/다운로드는 관리자 중심이어서 고객 자체 개발·배포 전체 여정은 미완성이다. Google/GitHub 설정만으로 해결되지 않는다.

완료할 차이: 기존 executor/release/lifecycle에 고객 owner/editor/runner 권한·quota·현재 세션·목적 검증과 검토 UI를 연결한다. 고객을 staff로 변환하지 않는다.

근거: [customer_organizations.py:168](<저장소>/agent_market/customer_organizations.py:168), [customer_organization_service.py:155](<저장소>/agent_market/customer_organization_service.py:155), [workspace_release.py:65](<저장소>/agent_market/workspace_release.py:65), [workspace_release.py:99](<저장소>/agent_market/workspace_release.py:99), [workspace_release_service.py:76](<저장소>/agent_market/workspace_release_service.py:76). 담당 순서: `POST139R-05`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### PA-02 · 비공개 증거 변경→구독 알림 자동 소비 경로 미완성

비공개 machine subscription의 관리자 개별 prepare/dispatch는 있다. 증거 변경을 자동 소비해 전달하는 경로와 지속 목적별 권한은 없으며 원 관리자 세션에 묶여 있다. 공개 TaskUpdates는 별도 구현된 기능이다.

완료할 차이: 기존 event/dedupe/receipt 위에 제한된 변경 consumer와 지속 전달 권한을 추가하고 현재 소유권·철회·버전·목적지를 dispatch 직전에 재검증한다. 기존 사람 세션 메서드를 cron으로 호출하는 것으로 대신하지 않는다.

근거: [workspace_machine_update_service.py:77](<저장소>/agent_market/workspace_machine_update_service.py:77), [workspace_machine_updates.py:374](<저장소>/agent_market/workspace_machine_updates.py:374), [workspace_machine_updates.py:461](<저장소>/agent_market/workspace_machine_updates.py:461), [workspace_machine_updates.py:544](<저장소>/agent_market/workspace_machine_updates.py:544), [workspace_machine_updates.py:568](<저장소>/agent_market/workspace_machine_updates.py:568). 담당 순서: `POST139R-05`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### PA-03 · 비공개 수신기 앱·허용 호스트 ingress 조립 미완성

수신 transport/router와 허용 host 경계는 있다. 하지만 실제 별도 비공개 ingress에 이를 조립하는 앱/실행 진입점은 없어 합성 시험이 직접 router를 올린다. DNS/TLS는 자동 제공되지 않는다.

완료할 차이: private receiver app factory·허용 host/origin·키 관리·운영 지침을 추가한 뒤 지정 TLS 수신처에서 수용한다. public/admin origin에 임의로 열지 않는다.

근거: [workspace_machine_receiver_service.py:40](<저장소>/agent_market/workspace_machine_receiver_service.py:40), [workspace_machine_receiver_service.py:42](<저장소>/agent_market/workspace_machine_receiver_service.py:42), [workspace_platform.py:134](<저장소>/agent_market/workspace_platform.py:134), [workspace_platform.py:203](<저장소>/agent_market/workspace_platform.py:203), [rehearse_machine_updates_postgres.py:137](<저장소>/scripts/rehearse_machine_updates_postgres.py:137). 담당 순서: `POST139R-05`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### BP-02 · 핵심 회귀가 공통 CI 선택에서 제외됨

공통 CI는 파일명 pattern으로 모듈을 고른다. 운영 개선의 기존 핵심 9개가 선택 밖이며 새 개발 영향 시험 일부도 제외된다. 과거 로컬 통과와 별개로 앞으로 CI에서 퇴행을 놓칠 수 있다.

완료할 차이: 관련 필수 모듈을 명시 선택하고 소유 목록 대비 무누락·shard 무중복을 검증한다. hosted CI 실행 수용은 이 소스 선택 문제와 따로 기록한다.

근거: [run_frontend_regressions.py:15](<저장소>/scripts/run_frontend_regressions.py:15), [run_frontend_regressions.py:45](<저장소>/scripts/run_frontend_regressions.py:45), [frontend-regressions.yml:64](<저장소>/.github/workflows/frontend-regressions.yml:64). 담당 순서: `POST139R-01`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

### BP-03 · 개인정보 요청 입력·실제 완료 상태 계약 불일치

개인정보 endpoint는 JSON 파싱 실패를 삼키고 임의 request_type을 받으며 Store는 실제 권리 처리와 관계없이 completed와 완료 시각을 저장한다. 로컬 opt-out과 관리자 접수 조회는 연결되지만 데이터 접근/삭제 완료를 증명하지는 않는다.

완료할 차이: 허용 요청 유형·엄격한 JSON/입력 계약과 received/verification/processing/completed를 분리한다. 접수 문구를 사실에 맞추고 실제 완료 근거가 있을 때만 완료한다. 익명 opt-out은 로그인 없이 유지한다. 법적 적합성 판정이나 판매 증거로 해석하지 않는다.

근거: [front.py:2540](<저장소>/agent_market/concierge/front.py:2540), [front.py:2557](<저장소>/agent_market/concierge/front.py:2557), [front.py:2580](<저장소>/agent_market/concierge/front.py:2580), [store.py:2604](<저장소>/agent_market/gateway/store.py:2604), [store.py:2620](<저장소>/agent_market/gateway/store.py:2620). 담당 순서: `POST139R-01`. 정적 확인이며 이번 감사에서 새 동적 재현은 하지 않았다.

## 성능·문서 및 조건부 확대 잔여

- **홈 초기 HTML 지연:** 과거 첫 요청12초 제한 초과, 후속12.998초를 관찰했다. 전체 bootstrap을 기다리는 구조와 작은 fixture의 대표성 공백을 확인했다. 특정 SQL/lock 원인은 계측하지 않았다. 최신 성능·보고서 변경 완료본을 먼저 검증하고 격리 대표 규모에서 측정한다. 현재 코드가 여전히13초라는 새 측정은 아니다.
- **CI 선택:** 감사 시 기존 핵심 9모듈과 신규 개발 영향 모듈이 선택 밖에 있었다. hosted CI 미실행과 선택 소스 누락은 별개다. 전체 unrelated 테스트를 무조건 추가하기보다 필수 소유 목록과 무누락 검사를 둔다.
- **문서 상태:** 과거 R09/R10 pending, R07/R08와 N의 오래된 범위가 뒤의 구현과 충돌했다. 이번에 이력을 보존하고 현재 대조/단일 POST139R 순서와 분리했다. 이는 제품 구현 완료를 뜻하지 않는다.
- **저장소:** finite SQL/native/repository·copy/reconcile·복원 격리는 재사용한다. 전체 PG server/worker, 실제 writer 전환/rollback, 대표 부하/DR은 남았다. 명시적인 retention preview/apply 도구는 이미 있어 없는 것으로 재개발하지 않는다.
- **신뢰성 운영 확대:** circuit API/UI/자동 신뢰 관측과 승인 probe 생명주기, authority/threshold-bound 조기 종료 controller, 공개 trust projection/키·철회 정책은 조건부 추가 소스다. core/offline helper·반사실 replay를 운영 기능으로 과장하지 않는다.
- **용량/평가:** manifest20·routing decision100·admission100·circuit consumed claim500의 수명 cap은 제한 파일럿을 보호한다. 지속 운영에는 archive/회전과 replay tombstone 유지가 필요하다. 실제 원격 judge를 DB fence 안에서 호출하지 않도록 비동기 평가·로컬 판정 조회를 분리한다.
- **앱·자체 agent:** 제한 영어 intent/2–6노드·metadata 제안과 고정 docs guidance는 구현됐다. 범용 그래프 planner, 선택된 원격 장기 A2A/session/streaming/status/cancel, 실제 독립 업무 품질·고객 재사용/경제성은 남았다.
- **결제:** 합성 TEST_UNIT/local HMAC/70:30 원장을 외부 암호·PSP/facilitator·finality·환불/지급 adapter와 동일시하지 않는다. 선택된 실제 adapter 소스와 sandbox·법적/정산/세무 수용이 남으며 실거래 off를 유지한다.
- **신원 복구:** 현재 owner transfer와 유일 owner 신원 분실 복구는 다른 범위다. 오픈할 경우 별도 검증/승인/철회 절차가 필요하며 이메일 자동 병합은 하지 않는다.

## 남은 개발 권장 순서

동일한 POST139R 식별자를 유지하고 표시 순서만 바꿨다. 1·2·3번은 충돌 파일을 분리하면 병행한다. 소스 구현과 실제 활성화 순서를 분리하여 운영 자격 코드와 독립 증거 사이의 순환 대기를 만들지 않는다.

### 1. 현재 변경분 고정·정확성/UI 보완·CI 마감 · POST139R-01

- 다른 작업의 공개 report/availability/SQL 변경 완료본을 먼저 대조하고 해당 영향 회귀를 고정한다. 과거 1,313개로 새 변경을 승인하지 않는다.
- 기존 핵심 CI 누락 모듈과 새 영향 모듈을 목록에 연결하고 선택 누락을 검출한다. shard 중복·누락도 확인한다.
- 개인정보 요청의 허용 유형/JSON 검증·received/processing/completed 근거를 분리한다. 익명 opt-out은 로그인 없이 유지한다.
- corpus ID+hash 일치, manifest 재선택, 보관 admission의 정확한 입력 재검토/재개, replan diff/base revision을 한 관리자 흐름으로 보완한다.
- 이번 감사에서 R/N/AC 이력과 현재 단일 순서를 분리했다. 다음 구현 후에는 해당 finding과 source SHA만 갱신한다.

완료 기준: 새 변경+보완한 계약의 격리 API/브라우저/보안 회귀·공개 콘텐츠 검사와 CI 선택 무누락, 이후 지정된 인증 관리자/hosted CI 수용.

### 2. 초기 응답 성능·저장소/복구의 남은 소스 · POST139R-06

- 현재 진행 중인 성능·보고서 패치를 검토한 뒤 대표 카탈로그/증거 수의 격리 cold/warm 측정과 단계/SQL 계측을 한다. 같은 최적화를 중복 구현하지 않는다.
- 홈 HTML 전체 bootstrap 대기를 제한하고 최신 실패·canonical subject·권한 검증을 유지한다. timeout 증가만으로 완료하지 않는다.
- 전체 PostgreSQL이 목표인 경우 worker/server/backend 구성과 최종 writer 활성화·rollback 계약을 기존 adapter 위에 완성한다.
- 명시 retention 도구는 이미 있다. 남은 연구/admission/circuit 수명 cap·회전/보존과 재생방지 tombstone을 함께 점검한다.

완료 기준: 대표 규모 성능 기준과 부하/DR/RPO/RTO를 나누어 기록한다. 전체 PG 전환은 좁은 SQLite 읽기 파일럿의 필수 선행조건이 아니다.

### 3. 비공개 서버 조립·시험 대상 준비 · POST139R-02

- PrivateIntegrations를 cached platform 생성 전에 설치하는 검증된 단일 private builder/설정 진입점을 만든다. flag는 권한을 대신하지 않는다.
- 기존 lifecycle/worker/수신·평가 adapter를 재사용하고 public Workspace와 광고/실거래 off를 유지한다.
- 이미 미지정으로 확인된 IdP/host/평가자/수신처/Push/DB/결제 sandbox는 준비 목록만 유지한다. 독립 소스 작업을 중단하거나 비밀값을 채팅으로 수집하지 않는다.

완료 기준: 격리 조립·오설정/권한/해제/복원 검증. 실제 대상·책임·중단 조건은 실제 수용 전에 별도 확정한다.

### 4. 운영 품질 증거의 승인·승격 연결 · POST139R-03

- 기존 typed evidence plane에 독립 rubric/holdout·provenance·목적·현재 버전/권한·만료/철회를 묶은 서명 운영 자격 승격 계약을 추가한다.
- 현재 qualified_operating_evidence=False 경계를 단순 완화하지 않는다. 승인된 실제 증거가 없으면 계속 거부한다.
- 원격 독립 평가자는 비동기 producer로 실행하고 dispatch DB 트랜잭션에서는 검증된 로컬 current verdict만 짧게 조회한다.

완료 기준: 격리 승격/철회/삭제/복원/오래된 판정 차단 후, 운영 승격은 독립 품질 수용(POST139R-04)과 지정 환경 준비(POST139R-02)를 기다린다.

### 5. 대표 corpus·독립 품질·shadow 수용 · POST139R-04

- 이미 구현한 worker/MR/oracle/typed shadow를 재사용한다. 8쌍/16합성 평가를 실제 품질로 승격하지 않는다.
- 승인 corpus·독립 rubric/holdout·넓은 셀·오탐/coverage/불확실성·실제 지연/오버헤드 기준을 채운다.
- 실제 intervention 없는 prefix replay와 실제 개입 품질 지표를 계속 분리한다. 연구 UI/정확 corpus 보완은 1번과 중복하지 않는다.

완료 기준: 버전·목적별 독립 품질/지연 수용 근거. 대상 부재 중에는 격리 평가 계약·corpus 검증만 진행한다.

### 6. 고객 여정·비공개 수신/알림·SDK 파일럿 · POST139R-05

- 고객 조직 owner/member 권한으로 draft→test→immutable release→deploy/export를 기존 executor/release/meter에 연결한다. 고객을 staff로 만들지 않는다.
- private receiver app factory/host allowlist/key custody와 증거 변경 consumer·dedupe·철회 재검사를 추가한다. 지속 전달 권한은 기존 관리자 세션과 구분한다.
- 기존 공개 TaskUpdates는 재개발하지 않는다. 실제 Google/GitHub/HTTPS·수신처·Push 클릭·SDK 철회는 지정 비공개 환경에서 수용한다.
- 신원/유일 소유자 복구를 오픈 범위로 선택하면 증거·독립 승인·권한 철회를 설계한다. 이메일 자동 합병과 복원 권한 부활은 금지한다.

완료 기준: 조직 간 격리/권한/세션 철회/만료/restore와 실제 비공개 end-to-end 증빙. 공개 Workspace를 자동으로 열지 않는다.

### 7. 안전 라우팅·조기 종료·신뢰 표시의 선택된 운영 계층 · POST139R-07

- 기존 circuit core에 service/UI·신뢰 관측 소비·별도 승인 probe 생명주기를 연결한다. 새로운 업무 replay나 별도 실행기를 만들지 않는다.
- 운영 자격·threshold-bound validator·실제 baseline/개입 실험·명시 opt-in controller를 갖춘 뒤에만 실제 조기 종료를 도입한다.
- 공개 receipt/projection을 선택하면 offline helper 위에 키 신뢰/게시/만료·철회·노출 승인을 추가한다. 검토 replan UI는 1번 결과를 재사용한다.

완료 기준: 승격 기준·실제 false-stop/품질 손실·오버헤드 증거. default off, one-call/replacement0, unknown 재전송 차단을 유지한다.

### 8. 수요 기반 범용 생성·장기 profile·자체 agent · POST139R-08

- 현재 bounded intent/고정 guidance와 실제로 필요한 범용 그래프 제안/신규 업무 계약의 차이만 구현한다.
- 선정 제공자 계약에 맞춘 원격 A2A status/cancel/idempotency/session/streaming profile을 하나씩 수용한다.
- 독립 업무 품질·동의된 고객 성공/지원/재사용을 수집한 뒤 예측 우선순위와 자체 agent 확대를 판단한다.

완료 기준: 선정 profile 적합성과 실제 고객 성과. 고정 metadata 제안·staff_reported를 범용 AI/실제 업무 성공으로 표시하지 않는다.

### 9. 선정 실제 결제 adapter·sandbox·정산 · POST139R-09

- 기존 TEST_UNIT 원장·protocol fixture를 재사용한다. 선정 네트워크/PSP/facilitator의 암호·external event·finality·환불/지급 adapter를 추가한다.
- 정산/세무/법적 기준과 외부 대사를 정한 뒤 승인 sandbox에서 검증한다. 실거래는 별도 승인 전 off다.

완료 기준: 합성 대사와 실제 sandbox 계약/환불/지급 대사를 구분한다. G2·법적 조건·별도 거래 승인 전 상용 완료로 선언하지 않는다.

## 2차 설계 추적 요약

- **P2-01 실행 증거·품질 이력** — 구현: typed lineage·목적별 암호화 보존·삭제/철회·현재 출처 연결. 남은 소스: 운영 자격 승인·승격 producer, 외부 평가 비동기화와 로컬 verdict 조회, 장기 보존·회전. 실제 수용: 독립 평가자·실제 다중 노드 corpus·버전/목적별 품질 수용.
- **P2-02 지속 평가·독립 품질** — 구현: 기존 worker·고정 MR/oracle·이산 셀·합성 8쌍/16평가·coverage 우선순위. 남은 소스: manifest 재선택·정확한 corpus ID, 넓은 MR/표면/예측 우선순위의 선택된 추가 profile. 실제 수용: 독립 rubric/holdout·실제 오탐/coverage·지연/오버헤드.
- **P2-03 신뢰 페이지·검증 배지** — 구현: 비공개 trust preview·서명 근거·offline Ed25519 helper. 남은 소스: 공개 projection/badge/receipt 경로·키 관리·신뢰 게시·현재 철회 계약. 실제 수용: 공개할 근거·키 소유자·노출 정책 별도 승인.
- **P2-04 안전한 admission·예측 라우팅** — 구현: 단일 호출·replacement0·서명 admission·기본 off circuit/probe core. 남은 소스: 보관 ticket 재검토/재개, circuit service/UI·검증 관측 소비·probe 생명주기, 예측 profile. 실제 수용: 독립 운영 자격·주/대체 비교·입력 공유·threshold 승인.
- **P2-05 검토된 앱·워크플로우 생성** — 구현: 제한 영어 intent·2–6노드 검토 새 초안·typed shadow·prefix 반사실 replay. 남은 소스: 재계획 diff/base revision, authority-bound 실제 조기 종료 validator/controller, 선택된 범용 planner. 실제 수용: 실제 개입·품질 손실/false-stop/오버헤드 수용; 현재 실제 지표 null.
- **P2-06 고객 로그인·SDK 배포** — 구현: Google/GitHub BFF 연동 코드·고객 조직 초안·관리자 발급 release·SDK 실행/철회. 남은 소스: 비공개 조립, 고객 권한의 시험→release→배포/내보내기, 선택된 원격 장기 profile·소유권 복구. 실제 수용: 지정 HTTPS/IdP 계정·외부 host 실제 실행/철회.
- **P2-07 검증된 수신·변경 알림** — 구현: 공개 TaskUpdates/주소 인증/Push test-click·관리자 조회; 별도 비공개 sender/receiver core. 남은 소스: 비공개 receiver app 조립·증거 변경 consumer·세션과 구분한 목적별 지속 전달 권한. 실제 수용: 실제 검증 수신처·TLS·Push 장치 왕복; 광고 off.
- **P2-08 자체 agent·개발 지원** — 구현: 고정 guidance/docs·제한 메타데이터 제안·기존 지원 이력. 남은 소스: 신규 제공자/업무 계약·일반 그래프 제안·동의된 실제 고객 성과 수집. 실제 수용: 독립 업무 성공·지원/재사용 cohort·경제성; staff_reported는 분리.
- **P2-09 성능·저장소·보안·복구** — 구현: 영속 큐/체크포인트/outbox·보수 복원·finite SQL/native 계약·명시 retention 도구. 남은 소스: 현재 공개 delta 검증·CI/개인정보 계약, HTML 성능, 전체 PG worker/server·전환/rollback. 실제 수용: 대표 규모/부하·DR/RPO/RTO·authenticated 관리자·hosted CI.
- **P2-10 조건부 마켓·정산** — 구현: TEST_UNIT exact/batch·local HMAC·기존 70:30 원장·합성 환불/복원 대사. 남은 소스: 선정 네트워크/PSP/facilitator의 암호·finality·환불/지급 adapter. 실제 수용: 선정 sandbox·법적/정산/세무 계약·G2 및 별도 거래 승인.

## 반복·중복을 줄이는 완료 계약

- 이 보고서의 source finding을 같은 작업 식별자 아래 닫는다. executor/worker/evidence/원장/공개 알림을 새로 만들지 않는다.
- 기능 소스, 격리 회귀, 지정 환경 실제 수용, 공개/실거래 활성화를 각각 기록한다. 환경을 기다린다는 이유로 소스 누락을 완료로 바꾸지 않는다.
- 묶음의 변경 SHA를 고정한 뒤 영향 회귀와 API/브라우저 보안·콘텐츠 검사를 함께 마감한다. 새 변경·실패·미해결 우려가 없는 검증은 반복하지 않는다.
- 이번 감사/계획 문서만으로는 서버 재시작이 필요 없다. 제품 소스를 반영하는 후속 묶음을 마감할 때만 사용자 터미널의 재시작/새로고침을 별도 안내한다.
- 실제 IdP/hosting/평가자/수신처/Push/DB/결제 sandbox 미지정은 해당 실제 수용만 막는다. 이를 성공으로 가정하지 않으며 같은 입력을 반복 요청하지 않는다.

## 원본·한계

구조화 대조: [design-implementation-audit.json](<저장소>/docs/design-implementation-audit.json). 실행 큐: [REMAINING_WORK_BATCHES.md](<저장소>/docs/REMAINING_WORK_BATCHES.md). 세부 감사: [evidence-reliability.json](<저장소>/reports/design-implementation-audit-2026-10-19/evidence-reliability.json), [platform-acceptance.json](<저장소>/reports/design-implementation-audit-2026-10-19/platform-acceptance.json), [baseline-public.json](<저장소>/reports/design-implementation-audit-2026-10-19/baseline-public.json).

검토한 경로에 대해 확인한 결과이며 모든 분기·미래 요구의 누락 부재를 수학적으로 보장하지 않는다. 이번 정적 대조를 전 소스 보안감사·새 동적 검사·운영 품질/SLA 인증으로 표현하지 않는다. 공개 Workspace·광고·실거래는 계속 off이며, 고객 Google/GitHub는 프론트엔드, 관리자는 기존 개별 로그인/desktop을 유지한다.

## 감사 산출물 검증

계획 JSON의 원본/캐시 일치, 단일9개 작업 순서와 구현/실제 활성화 의존성의 순환 부재, 근거108개 파일·행과 보고서 링크 존재, 현재 공개 HTML 미러 동기화·literal Hangul 부재를 정적으로 확인했다. Canvas3개의 TSX 구문과 기존2개 계획 Canvas의 내장 캐시 일치도 확인했다. 제품 동적 회귀·보안 재시험 결과가 아니다. [검증 기록](<저장소>/reports/design-implementation-audit-2026-10-19/artifact-verification.json)을 따른다.
