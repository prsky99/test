# 개발 완료를 위한 최종 권장 작업 순서

> 2026-10-20 사용자 범위 결정: 실제 고객을 가상 고객으로 대체하고 별도 로컬 PostgreSQL에서 검증했다. ChatGPT는 보류, Gemini/Claude 구독 로그인은 제외하고 기록만 유지, 결제·hosted CI·동료 승인은 보류한다. [현재 범위와 결과](DEVELOPMENT_REMAINING_AFTER_RESTART.md)를 우선하며, 아래 원래 42개 요구와 과거 실제 수용 조건은 추적 이력이다. 이번 가상 검증을 운영 실검증으로 승격하거나 보류 항목을 자동 재개하지 않는다.

최신 대조: [남은 개발 작업·권장 순서](REMAINING_DEVELOPMENT_REVIEW.md) · 2026-10-19. Google/GitHub 기본 로그인, 실제 10개 샘플, 로컬 AI 생성 3개, ChatGPT 계정 연결의 후속 증거를 반영한다. 아래 과거의 6노드·로컬 모델 실패·실제 로그인 대기 설명은 현재 지원/수용 상태와 구분한다. 기존 42개 요구와 원래 필수 수용 조건은 유지한다.

2026-10-19 · 2026-10-19-final.1 · 수정 범위 구현·격리 검증 반영 / 전체 개발 완료 선언 아님

이 문서를 **기존 설계 개발 마감의 단일 실행 순서**로 사용한다. 기존 POST139R-01~09는 요구사항 추적 ID로 유지하고, 아래 1~9는 의존관계에 맞춰 다시 묶은 마감 순서다. 작업을 새로 추가하거나 기존 필수 범위를 차기로 넘긴 계획이 아니다.

기존 원본: [플랫폼 설계](PLATFORM_ADVANCEMENT_DESIGN.md), [2차 설계](PLATFORM_ADVANCEMENT_PHASE2_DESIGN.md), [R&D 계약](PLATFORM_RND_REFINEMENT.md), [구현 감사](design-implementation-audit.json). [기계 판독 원본](development-completion-plan.json).

현재 실행 상태: [42개 요구별 코드·검사·미수용 조건](development-completion-execution.json), [이번 수정·검증 보고서](../reports/development-completion-2026-10-19/README.md), [동료 인계 시나리오](../reports/development-completion-2026-10-19/peer-handoff.md).

사용자 재시작·새로고침 후 [읽기 전용 확인](../reports/development-completion-2026-10-19/post-user-restart/README.md)을 추가했다. 최신 제품 소스 수정 이후 시작된 프로젝트 프로세스, 인증된 관리자 개요, 공개 홈과 조회 API 응답을 확인했다. 재시작 확인은 마쳤으며 실제 비공개 연동 수용·hosted CI·동료 승인은 기존 조건으로 남긴다. 정확한 메모리 내 모듈 버전을 프로세스 시작 시각으로 단정하지 않는다.

최신 [직접 전체 검증](../reports/development-completion-2026-10-19/final-whole/README.md)을 완료했다. 선택309개 모듈을 중복 없는4개 분할로 실행해 **고유5,570개 전부 통과**, 실패/error/skip0, 이전 결과 재사용0이다. 기존5,554개 case 누락0이며 현재 보고서 subject pruning16개가 추가됐다. 별도 보완27개와 과거 실행은 합산하지 않는다. source1,019개 지문·최초 목록4개 보완 시점과 재검사를 기록했고 source 변경을 발견하지 않았다. 이번 작업에서 제품·서버 설정 변경이나 추가 재시작은 없었다.

공개 TLS/보안 헤더·응답별 nonce·no-store와 내용 있는 정적 script3개 일치를 읽기 전용으로 확인했다. 이는 실제 백엔드 로드 버전이나 보호된 IdP/수신처/기기 수용 증거를 대신하지 않는다. Medium231개 위치별 문맥 분류를 기록하고 경고를 숨기지 않았다. [실행 현황](development-completion-execution.json)에는 실제 비공개 HTTPS/IdP·독립 평가·수신/Push·지정 DB/DR·금융 sandbox·hosted CI/동료 signoff 등 원래 종료 조건만 남긴다. Stripe 가입 자격은 현재 확인되지 않았고 기존 로컬 모델의 실제 응답 시험은 미통과다. 전체 개발/실제 수용 완료로 표시하지 않는다.

기록상 제한 구현 13건은 재사용하고, PA-04/PA-05의 같은 PostgreSQL 잔여는 중복 개발하지 않는다. 감사 6건에 포함되지 않은 실제 early-stop·자동 circuit·신뢰 키 게시의 잔여도 빠뜨리지 않는다. 과거2,206개/추가270개 검증 수로 현재 전체 기능을 완료 처리하지 않는다.

## 최종 작업 순서

### 1. 최종 범위·변경분·완료 판정 고정

기존 추적 ID: POST139R-01 · 설계: P2-01, P2-09

- R-01~10/G0·P2-01~10·기존 R&D 계약을 요구 ID별로 한 번 대조하고, 원래 필수·조건부 요구를 빠짐없이 이번 마감표에 연결한다. 이미 종결한 제한 구현은 재개발하지 않는다.
- 다른 작업의 완료된 변경을 통합하고 최근 schema 차단·보고서 이력·로딩·관리자 화면·개인정보 요청 변경의 최종본을 정한다. 생성 SQL catalog와 HTML mirror의 정합성을 맞춘다.
- 지원 업무 계약·프로토콜 profile·최대6노드·허용 분기/field mapping·자체 agent 납품 대상·호환 SDK를 유한하게 고정한다. 설계에 없던 계약·지갑·모델·기능을 추가하지 않는다.
- 각 하위 요구에 현재 코드·남은 변경·검사·외부 의존·종료 증거를 배정한다. 이 목록 확정 이후 새 개선 제안을 자동 편입하지 않는다.

**종료 조건**

- 필수 요구에 미분류·누락·중복이 없고 모든 잔여가 3~8번의 구체적인 소스 작업 또는 2/9번의 외부 수용에 연결된다.
- 원래 필수 범위의 임의 차기 이관 없이, 구현 지원 범위와 최종 검사가 고정된다.

**산출물:** 요구사항-구현-검사 대조표, 통합 기준 소스, 고정 지원 profile

### 2. 실제 연동 사양·시험 환경·책임자 일괄 확정

기존 추적 ID: POST139R-02, POST139R-03, POST139R-04, POST139R-05, POST139R-06, POST139R-07, POST139R-08, POST139R-09 · 설계: P2-01, P2-02, P2-03, P2-06, P2-07, P2-09, P2-10

- Google/GitHub 고객 로그인 client·redirect·시험 계정과 비공개 HTTPS customer/receiver origin, 보호된 agentconcierge.biz gateway 시험 라우팅을 확정한다.
- DB/HA·백업·복구 대상과 writer/rollback 책임자, 키 보관·회전·신원 복구 권한의 소유자를 정한다.
- 독립 corpus·rubric/holdout·평가자/qualifier, 승인 model/A2A endpoint, 수신 webhook/A2A inbox·Push 장치와 호출/전달 동의를 정한다.
- PSP/facilitator·network/asset·sandbox·event/finality/refund/payout 사양과 7:3 기준액·정산 책임을 고정한다. 원래 조건부 항목은 조건을 충족시켜 닫으며 조용히 제외하지 않는다.
- 필요한 입력은 한 번의 목록으로 모으고 설정 저장 위치를 사용한다. 비밀값을 문서·공개 소스·채팅에 기록하지 않는다.

**종료 조건**

- 각 외부 의존에 대상·담당·필요 입력·수용 검사·진행 상태가 지정된다.
- 제공자별 소스 구현에 필요한 사양은 해당 구현 착수 전에 확정된다. 미선정 항목은 명명된 대기로 기록하며 전체 완료로 표시하지 않는다.

**산출물:** 한 번에 처리할 외부 연동·시험 사양 묶음; 공통 소스 개발과 병행

### 3. 전체 저장소·서버·워커·보존·복구 구현 마감

기존 추적 ID: POST139R-06 · 설계: P2-09

- 기존 native Store·SQL catalog·migration을 재사용해 main server·collector·scheduler·worker의 backend 선택을 일관되게 연결한다. SQLite 전용 CLI 경계를 포함한다.
- writer drain/fence·단일 소유권 승격·변경 캡처 대사·rollback·종료/재기동을 완성한다. PA-04/PA-05는 같은 구현으로 한 번만 처리한다.
- 실행/체크포인트·평가·routing/shadow·admission/circuit 상태의 보존/정리와 replay tombstone 수명을 맞춘다. 진행/unknown 작업의 근거를 지우거나 재전송하지 않는다.
- 선정 저장소/HA profile의 백업·암호화 복원·권한 철회·fresh ownership·복구 후 재활성화 경계를 연결하고 대표 부하/DR 시험 경로를 준비한다.

**종료 조건**

- 지원 backend에서 실제 서버/수집기/스케줄러/워커 진입점과 검색·권한·실행 의미가 일치한다.
- 전환·rollback·재기동·복원 격리·정리/재생방지 시험이 통과하고, 지정 환경의 RPO/RTO·부하 수용 결과가 따로 연결된다.

**산출물:** 일관된 저장소 실행 경로, writer 전환/복구 절차와 시험

### 4. 평가·독립 품질·운영 증거·적응형 우선순위 연결 마감

기존 추적 ID: POST139R-03, POST139R-04 · 설계: P2-01, P2-02

- 기존 typed lineage·평가 worker·qualification·로컬 verdict를 실제 선정 evaluator/qualifier에 연결한다. dispatch의 DB fence 안에서는 원격 심판을 호출하지 않는다.
- 고정한 업무별 validator·oracle/MR·corpus/rubric/holdout과 반복/fault 평가·coverage/불확실성·지연 집계를 연결한다.
- 설계된 적응형 평가 우선순위를 현재 사용·실패·변경·증거 만료·제공자 budget에 묶어 구현하고, 근거 없는 예측값이나 성공 날짜를 만들지 않는다.
- 현재 버전·목적·승인·만료·철회에 따른 운영 자격의 생성/소비를 끝까지 확인한다. 실제 업무 성공, schema 통과, 전달 수락을 분리한다.

**종료 조건**

- 지원 계약의 정확한 입력·버전·결과에 독립 판정과 평가 provenance가 연결된다.
- 실패/unknown/미평가·holdout 오염·철회·만료·budget·지연 검사가 통과하고 실제 평가 결과와 합성 결과가 구분된다.

**산출물:** 실제 평가 연동, 운영 자격 판정 경로, 평가/측정 결과

### 5. 장기 A2A·분기 워크플로우·자체 agent·개발 지원 완성

기존 추적 ID: POST139R-08 · 설계: P2-05, P2-06, P2-08

- 선정된 장기 A2A profile의 session/multi-turn·status/cancel·streaming/resume·idempotency·장기 lease·절대 deadline·late artifact 처리를 구현한다. 기존 단발 polling을 다시 만들지 않는다.
- 기존 typed DAG·최대6노드·literal/projection·허용 branch를 모델 제안/고객 authoring까지 연결한다. 목적→계약/후보→입력·차이 검토→새 revision→명시 시험/릴리스 흐름을 완성한다.
- 에이전트 교체는 새 revision의 비교 시험으로 처리하고, 실행 중 pin이나 입력 공유·권한·예산을 자동 변경하지 않는다.
- 지원센터의 승인 corpus 검색·설명·검증 가능한 JSON patch 제안·검토 후 새 초안/시험을 연결한다. 자동 shell·권한 증설·게시를 추가하지 않는다.
- 설계의 좁은 읽기 업무 중 1번에서 고정한 자체 agent를 실제 업무 구현으로 납품하고 공통 품질 평가·추천 순위를 적용한다. 안내 문서만으로 대체하지 않는다.
- 동의된 지원 해결·업무 성공·수정 횟수·재사용/cohort·운영 부담의 수집/분석을 구현한다. 장기 성과는 실제 자료가 쌓인 뒤 측정하며 결과를 꾸미지 않는다.

**종료 조건**

- 고정된 지원 profile과 분기 그래프를 실제 실행·취소/복구·비교 시험·릴리스까지 왕복 검증한다.
- 자체 agent는 정의된 업무 산출물을 내고 독립 평가 대상이 된다. 성과 수집/분석 기능은 시험되며 4주 실고객 성과는 별도 운영 관측으로 표시한다.

**산출물:** 장기 실행 profile, 설계 범위의 워크플로우 생성/지원, 자체 agent와 성과 수집

### 6. 고객·SDK·신원 복구·수신/알림 사용자 여정 완성

기존 추적 ID: POST139R-05 · 설계: P2-06, P2-07

- Google/GitHub 고객 로그인과 조직 owner/editor/runner 권한으로 여러 노드 작성→시험→불변 릴리스→배포/ZIP→철회/rollback을 연결한다. 기존 제한 경로·SDK/BFF를 재사용한다.
- 유일 소유자 신원 분실 복구를 선정 독립 authority·증거·검토·이의/취소·기존 세션/권한 철회에 연결한다. 기존 공동 소유자 이관으로 대신하지 않는다.
- 비공개 receiver·목적별 grant·변경 consumer를 실제 HTTPS 수신처와 연결하고 webhook/A2A inbox 검증·서명·재생 방지·수락/unknown·철회를 확인한다.
- 브라우저 알림은 native permission·PushSubscription·전달된 시험 알림 클릭까지 확인하며, 미확인/거부 요청 처리와 별도 광고 동의/철회를 유지한다.
- 보호된 agentconcierge.biz gateway와 외부 배포 앱의 실제 SDK 왕복·현재 origin/audience/권한·버전/철회를 검증한다. 기존 공개 SDK1/다운로드를 강제 교체하지 않는다.

**종료 조건**

- 고객 권한으로 작성·시험·배포·실행·철회가 왕복하고 조직 간 격리가 유지된다.
- 신원 복구와 수신처/Push 검증·철회가 지정 시험 환경에서 확인된다. 관리자 계정 체계는 바꾸지 않고 공개 Workspace는 닫아 둔다.

**산출물:** 실제 고객/SDK/복구/알림의 연결된 비공개 시험 여정

### 7. 자동 circuit·예측 라우팅·실제 조기 종료·신뢰 게시 완성

기존 추적 ID: POST139R-07 · 설계: P2-03, P2-04, P2-05

- 기존 circuit core 위에 현재 관측 자동 소비·별도 승인 half-open probe 예약·한도·dedupe·철회 경계를 연결한다.
- 고정 특징/모델의 offline 비교→대체 호출 없는 shadow→명시 opt-in canary를 구현한다. 최초 admission의 business call≤1·추가 교체0과 R-06 상호 배타를 유지한다.
- threshold-bound 실제 opt-in early-stop controller와 지원 제공자의 cancel 확인·늦은 결과·unknown 처리를 연결한다. would_stop replay를 실제 개입으로 세지 않는다.
- baseline/개입 lineage에서 오중단·성공 손실·탐지 지연·판정 overhead를 수집하고 기준 미달 시 승격을 차단한다.
- 신뢰 페이지/배지·공개 receipt의 실제 disclosure/key authorizer·키 보관/게시·discovery·회전/철회를 연결한다. 만료/철회 즉시 중립화하고 공개 노출은 별도 승인 전 off로 둔다.

**종료 조건**

- 지원 profile의 자동 circuit·단일 admission·실제 개입/취소·unknown/kill switch 시험과 독립 비교가 통과한다.
- 실제 키/노출 권한 경로가 작동하고 배지·receipt의 현재성/철회·비밀 비노출을 검증한다. 단순 callback 설치를 전체 완료로 간주하지 않는다.

**산출물:** 운영 가능한 제어/개입/신뢰 게시 코드와 검증 결과; 활성화는 승인 범위만

### 8. 선정 결제사의 sandbox·정산·환불·지급 adapter 완성

기존 추적 ID: POST139R-09 · 설계: P2-10

- 2번에서 선정한 PSP/facilitator·scheme/network/asset profile의 quote/reserve/verify/execute/confirm/settle 경로를 실제 adapter로 구현한다.
- 인증된 외부 event·unique ID·finality/reorg·부분 실패·응답 유실·중복 callback과 원래 거래 ID 기반 대사를 연결한다. unknown에서 새 결제를 만들지 않는다.
- 계약에 고정된 7:3 기준액·attempt별 기여·환불/지급·정정 역분개·원장 잔액 대사를 구현한다. 마지막 성공 공급자에게 무조건 총액70%를 지급하지 않는다.
- 선정 sandbox에서 정상/실패/중복/유실/부분 환불·지급·대사를 검증한다. TEST_UNIT·offline signature 검사를 실제 결제 성공으로 대체하지 않는다.

**종료 조건**

- 선정 profile의 실제 sandbox adapter와 환불·지급·대사 시험이 통과한다.
- 실제 금전·지급·광고는 별도 명시 승인 전 비활성이다. 제공자 미선정이면 이 단계와 전체 개발 완료를 닫지 않는다.

**산출물:** 선정 제공자용 금융 adapter와 sandbox 정합성 증거; 실거래 off

### 9. 동일 버전 최종 검증·한 번 반영·동료 인계

기존 추적 ID: POST139R-01, POST139R-02, POST139R-03, POST139R-04, POST139R-05, POST139R-06, POST139R-07, POST139R-08, POST139R-09 · 설계: P2-01, P2-02, P2-03, P2-04, P2-05, P2-06, P2-07, P2-08, P2-09, P2-10

- 릴리스 후보 소스를 한 버전/commit 또는 SHA manifest로 고정한다. 다른 개발은 분리하고 필수 요구 불일치·확인된 보안 결함만 후보에 수정 반영한다.
- 요구 대조표의 기능/API/Chromium·보안 정적/동적·콘텐츠·조직/권한·실행/알림·금융 sandbox·대표 부하/DR·hosted CI를 같은 소스에서 마감한다. 변경 모듈 결과를 교체하고 중복 합산하지 않는다.
- 공개 Chat/Test/게시 workflow·웹앱 ZIP/List Your Agent/About/푸터와 관리자 방문 에이전트·고객 요청·워크플로우의 기존 사용자 시나리오를 회귀 확인한다.
- 중간 단계마다 프로젝트 서버를 재시작하지 않는다. 최종 후보 검증 후 사용자 터미널의 재시작·새로고침을 한 번 묶고 실제 버전/HTML·인증된 관리자/비공개 여정을 확인한다.
- 코드/버전·요구별 완료 증거·검사 결과·설정 항목명·실행/rollback·동료 검토 시나리오를 인계한다. 비밀·개인정보는 넣지 않는다.

**종료 조건**

- 고정 범위의 필수 소스 미구현·필수 검사 실패·확인된 차단 보안 결함이 남지 않고 동일 버전 반영이 확인된다.
- 개발 필수 비공개/선정 제공자 연동·독립 비교·Push·DB/DR·sandbox 시험의 미실행은 개발 완료로 닫지 않는다. 운영 활성화·실거래·장기 성과는 별도로 구분해 동료 검토 가능한 개발 완료본을 인계한다.

**산출물:** 고정 개발 완료본, 요구별 증거, 배포 확인, 동료 검토/복구 패키지

## 병행과 재시작 원칙

1·2번을 먼저 묶어 처리하고 외부 준비는 공통 코드와 병행한다. 3·4번은 변경 파일을 분리해 병행하고, 5번 장기 실행/생성 뒤 6번 고객 여정과 7번 제어/신뢰를 연결한다. 8번 adapter 소스는 2번 해당 사양과 3번 저장소 경계가 준비되면 5~7번과 병행하며, 고객/권한/원장 최종 통합은 6·7번 결과를 사용한다. 공개 trust 활성화나 실거래 개통을 adapter 코딩의 선행조건으로 두지 않는다. 9번에서 최종 소스 고정·검증·사용자 재시작·인계를 묶는다.

검증 후보와 다른 개발은 별도 작업 공간/브랜치로 분리한다. 새로운 개선 제안 때문에 완료한 범위를 자동 재개하지 않는다. 확인된 결함은 해당 요구와 영향 범위를 기록해 수정하고, 영향을 받은 검사만 교체한다.

## 외부 준비가 없는 경우

2번의 필요한 제공자·시험 대상·책임자가 미정이면 해당 단계에 정확한 대기 사유를 기록한다. 제공자별 소스 미구현을 단순 설정 대기로 바꾸거나 mock 결과로 닫지 않는다. 전체 완료를 위해 필요한 외부 선택은 한 묶음으로 해결한다. 비밀값은 문서나 채팅에 받지 않는다.

## 완료 판정과 동료 인계

**개발 필수 시험:** 선정 제공자·비공개 HTTPS/IdP·독립 평가·수신/Push·DB/복구·금융 sandbox의 지원 기능별 실제 통합 시험은 개발 종료 조건이다.

**별도 운영 단계:** 실운영 DB 전환, 공개 Workspace/신뢰 표시 활성화, 실거래·지급, 실고객 장기 성과 관측은 별도 승인·일정으로 관리한다. 개발 필수 시험을 이 단계로 넘겨 생략하지 않는다.

- **개발 완료본:** 1~8번의 필수 소스와 지원 사양을 완성하고 선정 제공자의 비공개 통합·독립 평가·수신/Push·DB/DR·금융 sandbox 등 해당 기능의 개발 필수 시험을 같은 버전에서 통과한 완료본. 단순 mock/callback 구성이나 필수 실연동 미시험으로 미구현을 닫지 않는다.
- **실제 환경 수용:** 실운영 DB/writer 전환·운영 트래픽·공개 기능 활성화·실거래/지급 등 서비스 개통·운영 승격의 별도 승인과 수용. 이는 개발 필수인 비공개 통합/sandbox 시험을 생략할 근거가 아니다. 미실행은 운영 수용 미완료로 표시한다.
- **출시 후 성과:** 실고객 4주 cohort·수익/품질 향상 등 시간 누적이 필요한 성과. 수집·분석 코드는 이번 개발에서 완성하고 실제 성과는 축적 후 측정한다. 관측 대기로 코드 마감을 무기한 재개하지 않는다.

개발 완료본에는 코드/고정 버전, 요구별 구현·검사 대조표, 실제 실행/미실행 구분, 보안 검토, 배포·실행/rollback, 동료 검토 시나리오를 포함한다. 필수 소스 미구현을 남긴 상태로 개발 완료본이라고 표시하지 않는다.

## 유지하는 운영 결정

- The user subsequently requested direct Workspace development testing while keeping its public link hidden until completion is confirmed. Separate route/link settings preserve that choice. See [current test status](../reports/workspace-social-launch-2026-10-19/README.md).
- Advertising delivery and actual money remain disabled.
- Google/GitHub customer identity stays frontend-only; staff uses individual existing sessions and desktop.
- Unknown external outcomes are never automatically replayed.
- Public frontend remains English-only with Lucide, privacy/notification disclosures, synchronized HTML and gateway-only execution.

이번 작성에서는 제품 소스·운영 서버·운영 DB를 변경하거나 실제 호출·발송·결제를 실행하지 않았다. 지원 profile과 외부 사양이 확정되기 전에는 납기나 실제 성과를 추정해 완료로 표시하지 않는다.
