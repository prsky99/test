# 남은 작업의 단일 권장 순서

최신 실행 안내: [남은 개발 작업·권장 순서](REMAINING_DEVELOPMENT_REVIEW.md) · 2026-10-19. 이 문서의 이전 snapshot을 근거로 완료한 로그인·샘플·로컬 AI 생성이나 이미 구현된 복구/제어 경로를 다시 개발하지 않는다. 실제 통합 미시험과 추가 소스 연결을 구분한 최신 목록을 따른다.

> **최종 개발 마감 순서:** [개발 완료 최종 계획](DEVELOPMENT_COMPLETION_PLAN.md)의 1~9단계를 따른다. 아래 POST/R/N/AC 순서와 수용 기록은 기존 요구·구현 이력 대조용으로 보존한다. 원래 필수 범위를 제외하거나 개발 완료를 선언한 것은 아니다.

<!-- RND_CURRENT_SOURCE_START -->
### 수용 snapshot 및 재시작 후 점검 · 2026-10-19

**v1.41의 수용 당시 선택된 제한 source**를 동결 입력 957개·영향 모듈 142개·고유 회귀 **2,206개 통과**로 통합 확인했다. 실패/error/skip0·source drift0이며 [최종 검증](../reports/advancement-completion-2026-10-19/verification.json)과 [수용 source snapshot](../reports/advancement-completion-2026-10-19/accepted-source-snapshot.json)에 기록했다. exact corpus·manifest/admission/replan, 운영 자격·로컬 verdict, 비공개 조립/고객 authoring/목적별 알림, circuit 수동 제어, Privacy 검토, bounded bootstrap, 선택형 model proposal, 별도 opt-in public receipt, 수동 remote A2A polling UI/API, offline EIP-3009 crypto의 제한 범위다. **전체 설계 완료나 실제 운영 수용은 아니다.**

최종 native 내부 계약 93개는 해당 pytest 범위 안의 중첩 검사이며 회귀 2,206개에 더하지 않는다. 과거 v1.40의 1,313개·native80개·재시작 읽기38개와 component 재실행도 합산하지 않았다. 수용 당시 공개 콘텐츠 87개 위반0·SQL catalog 3238 statements/205 tables 정합성을 확인했다. scratch115,009건 HTML181.514/29.381ms 두 표본은 collector 경합·운영 p95/SLA/HA 수용 근거가 아니다.

재시작 후 [읽기 전용 점검](../reports/advancement-completion-2026-10-19/POST_RESTART_VERIFICATION.md)은 **46/46 통과**했고, 추가 변경의 격리 영향 회귀는 **15개 모듈·고유270개 통과**로 모듈별 최신 결과를 교체했다. 이 수를 기존2,206개에 더하지 않는다. 현재 프로세스의 HTML 함수 hash는 이전 수용본과 일치하고 현재 소스와 다르다. 보안 격리 대상의 과거 목록 재노출은 소스/격리 회귀에서 보완됐으며 새 SQL은 catalog3239/205에 등록됐다. 이후에도 다른 작업의 소스 변경과 catalog manifest 차이가 관측되어 **현재 전체 소스 승인과 최신 운영 반영은 보류**한다.

남은 항목은 **지정 대상이 필요한 실제 수용**과 **선택된 조건부 추가 source**다. persistent 전체 PostgreSQL cutover/rollback·HA, actual early-stop controller·threshold/실제 개입 증거, A2A session/streaming, 실제 first-party 업무 성과, actual PSP/finality/refund/payout, sole-owner recovery는 남아 있다. 제한 profile이나 callback 주입을 이 전체 범위의 완료로 표시하지 않는다.

기존 POST139R ID는 요구 추적에 유지하며, 최종 실행 순서는 [개발 완료 최종 계획](DEVELOPMENT_COMPLETION_PLAN.md)의 1~9단계를 따른다. R/N/AC와 아래 과거 절은 이력이다. 공개 Workspace·광고 전달·실거래 off, 고객 로그인 프론트엔드 전용, 개별 관리자/desktop을 유지한다. 사용자 재시작 보고를 확인했다. **다른 수정 마감 → catalog 재생성/정합성 → 최종 변경분 검증 → 사용자 터미널 재시작·새로고침 한 번**으로 묶은 뒤 현재 build의 인증된/비공개 수용을 확인한다. 에이전트가 운영 서버를 재시작하거나 운영 DB·외부 제공자·실거래를 조작하지 않았다.
<!-- RND_CURRENT_SOURCE_END -->

## 진행 원칙

선택된 제한 source의 최종 통합 검증을 완료했다. 이미 구현한 executor·evidence plane·worker·원장·TaskUpdates를 반복 개발하지 않는다. 아래 동일 POST 식별자·순서는 실제 수용과 선택된 조건부 추가 source의 단일 큐다. 외부 대상 부재를 구현 완료로 바꾸거나 합성 자료를 실제 수용으로 승격하지 않는다.

## 1. 현재 변경분·정확성·관리자 흐름·CI 통합 마감

**POST139R-01 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- 개인정보 요청 허용 유형·중복 JSON 키/비유한 값 차단, 익명 opt-out receipt와 실제 처리 완료 근거를 구분하는 공통 계약. 익명 opt-out에 고객 로그인을 추가하지 않는다.
- 연구 manifest 재선택, 분석의 corpus ID+hash 일치, prepared admission의 정확한 입력 재검토/재개, replan diff/base revision을 기존 관리자 흐름에 연결한 후보.
- 기존 핵심 및 이번 영향 모듈의 공통 회귀 선택과 누락/중복 검출을 보완한 후보. 정적 선택 목록과 hosted CI 실행 결과는 별개다.
- 관리자 Privacy 행별 native dialog에서 fresh current request/body/status를 읽고 notes10..2000+별도64hex reviewed completion evidence로 단건PATCH한다. 초기24hex receipt와 실제완료근거를 구분하고 조회만으로변경하지않으며 response미확정 자동재시도0, 명시current read/회원세션철회/목록timer중모달유지를 연결한 후보.
- 기존 Privacy 요청의 중앙 검토 dialog에 status 조회·검토 메모·64hex SHA-256 완료 근거·PATCH/reload를 연결했다. 접수 receipt와 실제 처리 완료 증거를 분리하고 익명 opt-out을 유지한다.

조건부 source·남은 범위:

- 수동 검토 note/proof hash는 실제 데이터 삭제·제공 처리 자체를 자동화한 증거가 아니다. 선택한 실제 privacy operation이 자동 처리를 요구하면 별도 실행기/증거 연결을 설계한다.

실제 대상·운영 수용:

- 지정된 인증 관리자 환경에서 현재 build를 수용
- 현재 source를 실행한 hosted CI 결과
- 실제 privacy 처리 절차와 완료 증빙의 운영 책임자

새 executor·privacy 요청 저장소를 만들지 않고 기존 요청 테이블·공통 검사·관리자 모달·CI entrypoint를 유지한다.

## 2. 초기 HTML 성능·PostgreSQL 경계·복구/보존

**POST139R-06 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- 초기 HTML bootstrap 대기·동시 작업·inline payload를 제한하고 지연 데이터는 기존 API로 hydrate한다. 완료된 bootstrap job을 stale 권한/품질 증거 cache로 재사용하지 않는 후보.
- 명시 선택된 native application Store 및 durable runtime profile, caller-owned Store를 받는 compose_worker/run_worker 경계. 현재 CLI --db는 여전히 SQLite 진입점이다.
- 이전 copy/reconcile/prepare와 제한된 held-scope native binding을 재사용한다. 반환값의 cutover_authorized/operating_enabled=False를 유지한다.
- 운영 DB를 쓰지 않은 115,009건 scratch 카탈로그에서 HTML 181.533/27.955ms 두 표본을 수집했다. 1,000 evidence·200 canonical report를 포함하며 collector 경합·운영 p95/SLA/HA 수용은 측정하지 않았다.

조건부 source·남은 범위:

- 전체 서비스 PostgreSQL 전환을 목표로 하면 main server·collector·scheduler·worker의 일관된 backend 선택, 실제 writer 소유권 활성화/반환·rollback·종료/복구 절차를 완성해야 한다. native 함수나 단일 transaction binding을 production cutover로 표기하지 않는다.
- 전체 연구/admission/circuit 상태의 수명 cap·정리·재생방지 tombstone 수명 정합성을 검토하고 부족한 경계만 추가한다. 기존 retention·quarantine 도구를 다시 만들지 않는다.
- 현재 고정 build의 동시 collector/검색/평가 부하, 반복 cold/warm 분포·p95·용량·DR/RPO/RTO를 지정 환경에서 수용한다. 두 scratch HTML 표본을 운영 SLA로 확대하지 않는다.

실제 대상·운영 수용:

- 승인된 DB/백업/복구 대상·전환 창
- 동시 부하·용량·검색 표본·RPO/RTO 기준
- 키/복구/최종 writer·rollback 책임자

native application Store/runtime·고정 SQL catalog·migration 준비·복구 도구 위에 부족한 운영 전환 경계만 추가한다. 전체 PostgreSQL 전환은 좁은 SQLite private pilot의 필수 선행조건으로 만들지 않는다.

## 3. 검증된 비공개 조립 진입점

**POST139R-02 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- PrivateDeployment/PrivateIntegrations를 cached platform 생성 전에 설치하는 configure_private 및 compose_private. 명시 HTTPS/Host·공유 lifecycle·고객 앱/수신기 앱 분리, callback query 정리, 이미 생성된 graph 재설정 거부. 서버 listener나 환경/비밀값 자동 탐색은 하지 않는다.
- 기존 평가 worker·operating qualifier·metadata consumer·typed remote task bindings·model proposer를 검증된 trusted configuration에서 주입한다. 각 None/False 기본값은 계속 비활성이다.

조건부 source·남은 범위:

- 선택된 제한 source의 추가 구현은 없다.

실제 대상·운영 수용:

- Google/GitHub frontend 전용 client/redirect·시험 계정
- 명시 customer/receiver HTTPS origin·TLS ingress·key custody
- 독립 evaluator/qualifier·목적별 수신처·Push·DB·선정 payment sandbox의 소유자

기존 graph·router·start_for/close_for를 재사용하고 production public app은 열지 않는다. Private SDK 패키지는 고정 agentconcierge.biz gateway를 사용하므로 임의 test host만으로 SDK roundtrip 수용을 주장하지 않는다.

## 4. 운영 증거 자격·현재 판정의 로컬 소비

**POST139R-03 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- typed OperatingEvidenceApproval·현재 증거/버전/목적/승인 hash/만료·철회를 묶는 운영 qualification 저장/철회 계약과 private API/UI 후보. 관리자 입력만으로 독립 판정을 대신하지 않는다.
- current_report는 신뢰된 로컬 verdict producer를 DB transaction 밖에서 호출해 signed bounded cache를 준비한다. 별도 운영 자격 승격의 trusted qualifier도 transaction 밖에서 검토한다. 최종 projection/dispatch는 current local verdict만 짧게 검사하고 원격 judge를 호출하지 않는다.

조건부 source·남은 범위:

- 선택된 제한 source의 추가 구현은 없다.

실제 대상·운영 수용:

- 승인 corpus·독립 rubric/holdout·목적별 provenance/retention 기준
- 실제로 독립적인 qualifier 및 평가 환경
- 현재 버전·승인 hash에 묶인 실제 수용 근거

기존 typed evidence plane·평가 worker를 유지한다. configured hook/격리 approved fixture를 실제 운영 품질 성공으로 승격하지 않으며 미설정 qualified_operating_evidence=False를 유지한다.

실제 수용 선행: POST139R-02, POST139R-04.

## 5. 대표 corpus·독립 품질·shadow 실제 수용

**POST139R-04 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- 기존 worker/MR/oracle/typed shadow와 exact corpus·manifest UI 보완을 그대로 재사용한다. 새로운 평가기나 별도 trial ledger를 도입하지 않는다.

조건부 source·남은 범위:

- 승인할 새로운 업무 계약·oracle·MR가 기존 news/docs 범위를 넘으면 필요한 validator/adapter/holdout 계약을 추가한다. 기존 좁은 구현이 모든 도메인에 일반화된 것으로 표기하지 않는다.
- 실제 intervention controller는 7번 source 잔여로 모으고 여기서는 독립 품질/coverage/불확실성/실제 지연 수용 설계만 연결한다.

실제 대상·운영 수용:

- 대표 corpus와 독립 rubric·holdout 승인
- 승인된 실제 MCP 제공자·목적별 호출 권한
- 넓은 실험 셀·오탐/coverage/불확실성·지연/오버헤드·중단 기준

합성 pass/fixture coverage를 실제 품질·SLA로 표기하지 않는다. corpus/UI 보완은 1번 결과를 재사용하고 실수용이 없는 넓은 연구 범위를 단순 설정 완료로 분류하지 않는다.

실제 수용 선행: POST139R-02.

## 6. 고객 authoring·비공개 수신·목적별 자동 알림·SDK

**POST139R-05 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- 고객 조직 active owner/editor/runner로 draft→exact input prepare/test→owner immutable release→exact HTTPS origin deployment/SDK ZIP를 기존 execution/release/meter 위에 연결한 private API/English UI 후보. customer를 staff로 변환하지 않는다.
- 별도 HTTPS/Host receiver ASGI factory와 fresh 명시 purpose grant를 사용하는 bounded changed-evidence worker. session과 구분된 GrantActor/current owner·revision·expiry·restore·withdraw 검사, 기존 event dedupe/receipt/unknown-no-resend를 재사용한다.

조건부 source·남은 범위:

- 유일 소유자/신원 분실 복구를 실제 출시 범위에 포함하면 신뢰할 독립 복구 authority·증거·취소/이의 제기·기존 권한 철회와 그 구현을 별도로 설계해야 한다. 현재는 off이며 이미 있던 co-owner/owner transfer를 sole-owner recovery로 표기하지 않는다.
- 현재 narrow single-task customer journey 밖의 typed multi-node authoring·공동 편집·장기 작업 고객 UI가 선택되면 기존 snapshot/typed runtime 위에 별도 범위 계약이 필요하다.

실제 대상·운영 수용:

- 실제 Google/GitHub 로그인과 보호된 customer HTTPS ingress
- 고정 agentconcierge.biz gateway의 보호된 시험 라우팅·SDK2 BFF/cookie/CORS/철회 수용
- 검증 수신처 webhook/A2A inbox·키 custody·서명/재생 방지 수용
- native PushSubscription·실제 전달 test notification 클릭 확인·철회 수용

기존 executor/release/SDK/meter/TaskUpdates/receiver/event ledger를 재사용한다. automatic grant는 metadata 목적만 허용하며 marketing·업무 재실행·payment 권한을 부여하지 않는다.

소스 선행: POST139R-02.

실제 수용 선행: POST139R-02.

## 7. 선택된 circuit 운영 계층·조기 종료·신뢰 게시

**POST139R-07 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- 기존 circuit core의 private service/UI 상태·명시 policy·retained observation ingestion·별도 승인 probe binding/완료 refresh를 연결한 후보. UI가 신규 업무나 probe를 자동 dispatch하지 않는다.
- 기존 offline portable receipt helper 위에 별도 opt-in create_trust_app. 정확 projection hash+audience disclosure authority, current key publication/revocation approval, exact HTTPS host·rate bound·응답 직전 현재 승인 재확인. main public app 자동 mount/키 생성은 없다.

조건부 source·남은 범위:

- 실제 early-stop을 선택하면 threshold-bound validator, opt-in controller, 실제 baseline/개입 lineage 및 provider별 cancel 확인·late result 처리·false-stop/성공 손실/judge overhead 수집 경계를 구현해야 한다. 현재 prefix replay는 actual_interventions=0이며 remote task cancel API만으로 업무 조기 종료 controller가 생기지 않는다.
- circuit의 automatic current-observation consumption/probe scheduling을 출시 범위에 포함한다면 현재 수동 ingest/bind/refresh와 구분한 목적 권한·bounded scheduler·dedupe 구현이 필요하다.
- 공개 trust app을 운영하려면 실제 current disclosure/key authorizer·회전/폐기·key discovery 저장소를 trusted callbacks로 연결해야 한다. factory callback 계약만으로 production publisher가 완성된 것으로 표기하지 않는다.

실제 대상·운영 수용:

- 운영 자격과 독립 품질 수용
- 선택 threshold·중단 기준·허용 probe/실제 개입 시험
- 공개 노출 승인·issuer/audience·키 보관/게시/회전 책임자

circuit·evaluation·admission·portable receipt core를 재사용한다. 공개 신뢰 표시 off와 실제 개입 off를 유지하고 기존 offline 표시를 실제 SLA로 바꾸지 않는다.

소스 선행: POST139R-03.

실제 수용 선행: POST139R-03, POST139R-04, POST139R-05.

## 8. 제한 모델 제안·A2A polling profile·자체 agent 성과

**POST139R-08 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- optional model_proposer는 승인된 public objective·candidate rid/contract·news/docs 입력 schema만 공유하고 기존 deterministic compiler/review/new draft에 연결한다. graph/session/URL/private output은 공유하지 않고 제안이 실행/릴리스 권한을 주지 않는다.
- 명시 TaskBinding과 암호화 key가 있을 때만 private A2A 0.3 JSON-RPC message/send·tasks/get·tasks/cancel API. 버전 pin·정확 authority/kill switch·bounded fixed HTTPS·encrypted output·unknown 자동 재전송 금지. DTO streaming=False. 별도 desktop private modal은 fresh unchecked send/poll/cancel 동의와 현재 revision·retained history를 구분한다.
- 기존 first-party public guides 및 staff-reported support outcome ledger는 유지된다. 이는 독립 업무 품질/고객 business outcome을 검증하는 agent와 구분한다.
- named staff desktop에 resource/version 옵션, retained list/detail, 매 액션 미선택 동의와 revision-bound send/poll/cancel 모달을 연결했다. 자동 polling/resubmit·public route·가상 binding은 없고 unknown/terminal·scope 변경을 차단한다.

조건부 source·남은 범위:

- 원격 A2A session/multi-turn·SSE streaming/resume·provider-specific idempotency·장기 lease/late artifact 정책은 selected polling API와 다른 profile로 미구현이다. 실제 대상 선정 후 해당 profile 소스를 추가해야 한다.
- 범용 branching graph·새 업무 contract 자동 생성/validator·provider별 고객 authoring UI는 현재 bounded intent/compiler 범위를 넘는 소스 작업이다. model hook 설정으로 완성되지 않는다.
- 자체 business agent 확대, 동의된 독립 customer outcome/cohort·재사용/경제성·예측 우선순위의 측정/모델 계약은 남은 연구·소스이며 public guide 또는 staff_reported/unassessed outcome으로 대체할 수 없다.

실제 대상·운영 수용:

- 승인 public objective model adapter·데이터 공유/보존 정책
- 선택 A2A 0.3 test endpoint/current immutable version·암호화 키·test account
- 독립 업무 품질·실고객 동의 outcome·지원/재사용 측정 기준

기존 deterministic compiler·typed execution·admission·release를 유지한다. polling 좁은 profile을 streaming/session 전체 완료로 표기하지 않는다.

실제 수용 선행: POST139R-04, POST139R-05.

## 9. offline crypto와 실제 결제·환불·지급 adapter 분리

**POST139R-09 · 제한 source 통합 검증 완료 · 실제 수용/조건부 source 잔여**

통합 확인한 제한 source:

- 선정 test profile x402 v2 exact/EIP-3009 Base Sepolia USDC의 caller-pinned public envelope EOA 서명·chain/asset/amount/payee/expiry/nonce/URL 검증 helper와 private API/UI. private key/sign/broadcast/provider/RPC/ledger 권한 없음. 결과에 sender/nonce 원문을 남기지 않는다.
- 기존 TEST_UNIT exact/batch protocol fixture·원장·명시 권한·dedupe·정산 준비를 재사용한다. offline crypto 통과는 facilitator verification이나 settled payment가 아니다.

조건부 source·남은 범위:

- 실제 선정 PSP/network/facilitator verification/settlement adapter, 인증 external event·finality/reorg·환불/지급·부분 실패·중복 callback·대사/원장 변환이 미구현이다. 이는 credential 설정만으로 닫히지 않는 provider-specific source다.
- contract wallet·Permit2·다른 chain/asset 또는 batch crypto를 지원하려면 별도 pinned profile/validator와 검증이 필요하다. 현재 EOA exact 범위를 확장 해석하지 않는다.

실제 대상·운영 수용:

- 선택 PSP/facilitator/network의 승인 sandbox·시험 계정·asset/finality 기준
- 정산·환불·지급·법/세무·수수료 소유자와 대사 책임
- 실거래는 별도 명시 승인 전 off

TEST_UNIT 원장과 offline signature checker를 재작성하지 않고 실제 adapter를 명확히 분리한다. 서명 검증 성공·합성 event·sandbox 결과를 실제 결제 성공/환불/지급으로 표기하지 않는다.

실제 수용 선행: POST139R-04, POST139R-05, POST139R-06.

## 재시작과 후속 수용을 한 번에 진행

동결 source 957개·142모듈·고유 2,206개 통과를 마감했다. 새 source·실패·미해결 우려가 없는 검증은 반복하거나 합산하지 않는다. 사용자 터미널에서 서버 재시작·관리자 새로고침을 한 번 묶어 진행한 다음, 지정된 환경의 인증 관리자·고객/수신/IdP·SDK 수용을 동일 build에서 확인한다. 실제 대상이 없으면 해당 수용만 보류하고 합성 결과로 대체하지 않는다.

근거: [최종 검증](../reports/advancement-completion-2026-10-19/verification.json), [수용 snapshot](../reports/advancement-completion-2026-10-19/accepted-source-snapshot.json), [선택 회귀](../reports/advancement-completion-2026-10-19/selected-regression.json), [최종 summary](../reports/advancement-completion-2026-10-19/accepted-summary.json). 전체 PostgreSQL/HA·실제 조기 종료·streaming·first-party 업무 성과·실결제/환불/지급·sole-owner recovery는 명시적으로 선택할 추가 source다.
