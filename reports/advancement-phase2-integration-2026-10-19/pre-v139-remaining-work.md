# 재시작 이후 남은 작업의 권장 순서

2026-10-19 · 제품 소스 v1.38 · 공개 Workspace access는 계속 비공개, 관리자는 기존 개별 로그인·데스크톱 기준이다.

사용자 서버 재시작·관리자 새로고침 후 **읽기 표본18/18건 통과**: health/관리자200, 관리자 자산5개 현재 소스 일치·CSP nonce, 새 비공개 API 비인증401, 공개 고객/auth404를 확인했다. 검증 입력638개 변경0이다. 제품 소스 수정이나 전체 회귀 재실행은 하지 않았으며 **이번 계획 갱신에는 추가 재시작이 필요 없다.** 읽기 표본은 인증된 기능·실제 외부 연동·운영 전체 수용을 뜻하지 않는다.

[재시작 표본](../reports/remaining-work-plan-2026-10-19/post-v138-restart-readonly.json) · [기존 동일소스 검증1,787건](../reports/advancement-phase2-core-2026-10-19/verification.json) · [구조화 계획](platform-advancement-plan.json) · [2차 설계](PLATFORM_ADVANCEMENT_PHASE2_DESIGN.md)

기존 평가/코호트/원문 보존, budget/coverage, 비공개 trust/offline shadow, 템플릿3개·SDK 관리, 서명 notice·지원 관측은 구현된 범위 그대로 재사용한다. **남은 것은 외부 환경 검증만이 아니다.** evaluator/worker, 영속 receiver, 범용 증거·앱·장기 profile·공개 신뢰/실사용 라우팅은 현재 제한 구현을 넘어서는 후속 소스가 있다.

## 1. 인증된 관리자 기능 수용·hosted CI 마감

**지금 수용** · N01

읽기 표본18건은 완료했다. 다음은 실제 관리자 계정의 조회/편집/권한 철회/이력 유지·모달/세션 전환을 지정된 비공개 시험 작업공간에서 확인하고 hosted CI 결과를 확보한다.

완료 기준: 인증 기능/철회 결과와 hosted CI 로그. 재시작 표본을 전체 운영 수용으로 사용하지 않는다.

병행/선행: 2번 환경 준비와3·4번의 격리 소스 작업을 병행한다. 운영 데이터나 권한을 임의로 바꾸지 않는다.

필요 입력: 지정된 비공개 관리자 시험 작업공간 / 저장소 CI 실행 환경.

## 2. 비공개 시험 환경·운영 책임 확정

**병행 준비** · N02 · N03 · N04 · N05 · N07

Google/GitHub 등록, 정확한 HTTPS SDK2/BFF origin, 키 보관/보존/복구 책임, 승인 제공자·독립 평가자/corpus·목적별 검증 수신처를 지정한다. 공개 Workspace는 계속 off다.

완료 기준: 기능별 시험 대상·허용 범위·책임/중단 기준. 설정 존재와 실제 성공 증빙을 분리한다.

병행/선행: 현재 실제 대상이 없다는 사용자 답변을 유지한다. 설정값이나 환경을 임의 생성해 실제 수용으로 표시하지 않는다. 비밀값은 채팅에 수집하지 않는다.

필요 입력: IdP 등록/호스팅 설정 위치 / 운영 책임자·보존/복구 정책 / 승인된 제공자·수신처·평가 범위.

## 3. 실제 평가 adapter·기본 off 평가 worker 연결

**다음 신규 개발 1순위** · P2-01 · P2-02 · N06

완료된 계획/코호트/암호화 원본·평가 budget/coverage를 재사용해 좁은 MCP 읽기 계약의 신뢰된 evaluator/authorizer adapter와 실행 worker를 연결한다. 성공 여부와 독립 업무 품질·출처/미평가를 분리한다.

완료 기준: 현재 권한·단회 dispatch·호스트 예산·누락 coverage·중단/복구를 검증하고 실제 승인 평가 근거를 별도 기록한다.

병행/선행: adapter/worker 수명주기·취소/철회·중복/unknown 검사는 격리 데이터로 먼저 개발 가능하다. 실제 자동 평가 활성화/품질 인증은2번 대상과 수용 이후다.

필요 입력: 좁은 허용 계약·평가 rubric/corpus / 독립 평가자 자격/권한 정책 / 제공자 호출 예산·허용 주기.

## 4. 머신 알림 durable receiver·발송/검증 adapter 연결

**신규 소스와 실제 수신 수용** · P2-07 · N07

기존 주소 인증과 서명 envelope를 재사용해 event/nonce/dedupe의 원자적 영속 claim 후 receipt를 발급하는 receiver를 구현한다. 현재 목적·제공자 소유 증명·수신처 proof를 확인하는 sender/verifier와 실제 Inbox 규격을 연결한다.

완료 기준: 재시작/동시 수신·replay·만료/철회·응답 유실·unknown 무재송을 검증한다. 브라우저 Push는 실제 시험 알림 클릭 확인까지 별도로 한다.

병행/선행: 3번과 독립적인 receiver/중복·동시성 검증을 먼저 개발 가능하다. 실제 발송은2번 지정 대상에서 별도 수용한다. 기존 웹훅을 새로 중복 구현하지 않는다.

필요 입력: 검증된 목적별 수신처 / 영속 replay 보존/receipt/status 계약 / 현재 발송 동의/철회 정책.

## 5. Google/GitHub·SDK2/BFF·템플릿 실제 배포 수용

**대상이 준비되면 수용** · P2-05 · P2-06 · N02 · N04 · N09

기존 고객 조직·별도 typed SDK2·3개 템플릿을 실제 비공개 HTTPS/BFF에서 로그인→검토/시험→릴리스/발급→실행/상태→철회/만료/복원 순서로 검증한다. 공개 SDK1.x와 다운로드 호환은 유지한다.

완료 기준: 조직 격리·세션/PKCE·한도·SDK 호환/중지 후 기존 이력·복원 후 새 권한 수용. 공개 Workspace는 계속 닫는다.

병행/선행: 4번 실제 알림 수신과 같은 비공개 파일럿 묶음에서 진행한다. 프론트 고객 인증을 관리자 로그인에 적용하지 않는다.

필요 입력: 정확한 origin/redirect/BFF / 승인된 테스트 계정·제공자 / 배포/복구 책임자.

## 6. 운영 저장소·성능·백업/복구 수용

**병행 준비·지정 대상 검증** · P2-09 · N03 · N08

완료된3033 SQL쌍/189테이블·이전/대사·암호화 복원 소스를 재사용해 대표 부하·검색/권한 동등성·writer drain/전환/rollback·실측 RPO/RTO·DR/HA를 확인한다.

완료 기준: 실제 측정/복구 기록과 명시적 중단·rollback 기준. 구조/격리 결과를 전체 운영 준비로 해석하지 않는다.

병행/선행: 대상·목표 준비는2번과 병행한다. 모든 제한 파일럿에 전체 PostgreSQL 전환을 일률적으로 선행시키지 않는다. 운영 전환은 별도 승인 대상이다.

필요 입력: 승인된 DB/복구 대상과 운영 창 / 대표 부하·검색 표본 / 키/복구 소유자·RPO/RTO.

## 7. 신뢰 화면·단일 선택 라우팅의 조건부 확장

**근거 확보 후 신규 개발** · P2-03 · P2-04

현재 비공개 trust 미리보기·규칙 offline/shadow를 재사용한다. 필요한 공개 projection/badge, 실제 단일 선택 admission/opt-in canary·circuit breaker/별도 probe는 아직 후속 소스다. 고정 예측 모델은 시간 분할 검증과 실제 수요가 있을 때 별도 추가한다.

완료 기준: 선택 제공자 최대1회·추가 전환0·R-06 budget 상호 배타·unknown 무재호출과 baseline 대비 실제 품질/지연 검증.

병행/선행: 비공개 소스/격리 시험부터 가능하다. 공개 Workspace·공개 배지/신뢰 API·실사용 자동 전환은 임의로 활성화하지 않는다.

필요 입력: 현재 버전의 독립 품질 근거 / 승인 호환 제공자·입력 공유 범위 / 실제 baseline 비교와 별도 노출/실행 승인.

## 8. 증거·앱 생성·자체 agent/지원 성과의 수요 기반 확장

**파일럿 수요에 맞춘 선택 개발** · P2-01 · P2-05 · P2-06 · P2-08 · N11

현재 평가 원본 연결은 단건 private MCP, 앱 생성은 영어 keyword 규칙/고정2노드 템플릿3개, 지원 성과는 staff 관측이다. 필요한 순서로 typed 다중 노드 증거→추가 계약/자연어 구성→장기 A2A/session/streaming profile→자체 agent 독립 평가·실제 업무/재사용 cohort를 확장한다. 기존2–6노드 projection/branch는 재개발하지 않는다.

완료 기준: 원본/입력 공유·버전 고정·출처/품질·철회/복원과 실제 성공까지 시간·지원 부담·재사용을 각각 검증한다.

병행/선행: 전부를 기본 파일럿의 필수 선행으로 묶지 않는다. 효과가 확인된 소수 계약/템플릿부터 개발하고 자체 agent도 같은 평가/추천 기준을 적용한다.

필요 입력: 실제 고객 업무와 수정/지원 기록 / profile별 status/cancel/idempotency 계약 / 평가/분석 목적·보존 동의.

## 9. 실제 계약·결제 sandbox·환불/지급과 조건부 상용화

**마지막 조건부 단계** · P2-10 · N10 · N12

기존 TEST_UNIT과 모의 계약/원장을 재사용하고 실제 공급자 계약·정산/세무 조건·결제사 sandbox·환불/지급·unknown 대사·지원/중단/rollback을 별도로 수용한다.

완료 기준: 실제 외부 event/금액 대사·중복/실패/unknown·환불/지급·명시적 상용 승인. G3 확대는 실제 성과로 판단한다.

병행/선행: 추천 정확도·응답 속도·업무 품질 파일럿을 우선한다. 실제 결제/지급/광고를 켜거나 Chat에 상업 표현을 추가하지 않는다.

필요 입력: 실제 계약/운영 정책 / 선정된 결제사 sandbox / G2 근거와 별도 실거래 승인.

## 착수와 반복을 줄이는 방식

- **즉시:** 1번 인증된 관리자/CI 수용과2번 시험 환경 준비를 병행한다. 실제 IdP/호스팅·승인 제공자/알림/결제 대상이 아직 없다는 기존 답변을 유지한다.
- **다음 신규 개발 묶음:** 3번 평가 adapter/worker와4번 영속 receiver를 기존 core 위에 개발하고, 기본 off·격리 데이터에서 권한/중복/unknown/복구·브라우저/API 보안까지 함께 마감한다. 실제 활성화는 지정 대상의 별도 수용 후다.
- **대상이 준비되면:** 4·5번 알림/SDK 실제 수용을 같은 파일럿에 묶고6번 운영 저장소 검증은 범위·목표에 맞게 병행한다.
- **선택 확대:** 7·8번 일반화·장기·공개/실사용 라우팅은 수요와 근거를 확보해 소수 계약부터 진행한다. 모두를 첫 파일럿의 필수 선행으로 묶지 않는다.9번 실거래는 마지막이다.
- 제품 source/API/UI/security/docs를 완성 묶음으로 처리한다. Python import 소스가 실제 바뀐 묶음에만 끝에서 사용자 재시작1회를 요청한다. 문서 변경·이미 반영된 동일 소스 때문에 재시작이나1,787건 전체 회귀를 반복하지 않는다.

## 아직 제한된 구현의 정확한 경계

- **P2-01:** 현재 원문/실행 binding은 단건 workspace_private_runs MCP다. typed 다중 노드·A2A/x402·장기 task 근거 연결은 후속 source profile이며 실제 corpus/독립 평가 수용도 남는다.
- **P2-02:** trusted evaluator/authorizer adapter와 자동 worker 운영 연결은 아직 없다. 기존 budget/jitter/coverage/일회 dispatch를 재사용하고 허용 corpus·주기·독립 자격 정책 아래 별도 개발·실제 수용한다.
- **P2-03:** 현재는 비공개 trust JSON/SVG 미리보기다. 공개 정제 projection/badge 경로와 실제 공개 수용은 후속 source/승인 대상이며 Workspace 공개 보류는 유지한다.
- **P2-04:** 현재는 규칙 offline/decision shadow이며 business call0이다. 실제 단일 선택 admission/opt-in canary·circuit breaker/probe·고정 모델은 별도 source/검증/승인 대상이다.
- **P2-05:** 현재는 고정2노드 literal 템플릿3개와 영어 keyword 선택이다. 일반 자연어 구성·추가 계약/템플릿은 수요 기반 후속 source이며2–6노드 typed projection/branch는 기존 구현을 재사용한다.
- **P2-06:** 실제 Google/GitHub·HTTPS SDK2/BFF·계정/조직 복구 수용이 남는다. 장기 A2A/session/streaming 등 새 profile은 status/cancel/idempotency 계약과 수요에 따른 후속 source다.
- **P2-07:** verify_envelope는 pure 검증이며 receiver의 영속 원자 event/nonce/dedupe claim과 receipt/status adapter는 후속 source다. 실제 sender/verifier·목적별 수신처 연결과 수용도 남는다. 광고는 비활성이다.
- **P2-08:** staff 지원 해결·반복 실행 이력은 업무 성공/고객 유지/품질이 아니다. 좁은 자체 agent의 실제 독립 평가와 목적별 동의된 업무/지원/재사용 cohort 측정이 남는다.
- **P2-09:** 대표 부하·전체 검색/권한 동등성·실제 전환/rollback·키/복구 책임·RPO/RTO·DR/HA 수용이 남는다. 격리 native 구현을 재개발하거나 전체 PG를 모든 파일럿에 요구하지 않는다.
- **P2-10:** 실제 법적/공급자/세무 조건·결제사 sandbox·외부 환불/지급/unknown 대사·G2/별도 실거래 승인·G3 성과가 남는다. TEST_UNIT은 모의 상태다.

[직전 권장9개 구현 결과](../reports/remaining-work-plan-2026-10-19/pre-post-v138-remaining-work.md)와 기존 검증은 이력으로 보존한다. 실제 결제·지급·광고·공개 Workspace를 이번 계획으로 활성화하지 않는다.
