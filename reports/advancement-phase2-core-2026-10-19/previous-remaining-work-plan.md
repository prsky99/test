# 남은 운영 수용·조건부 확대 작업 순서

2026-10-19 · 현재 소스 묶음 v1.37 · 사용자가 승인한7개 실행 묶음의 소스/격리 검증을 진행했다. 최종777개 입력·97모듈 동일소스 영향 범위 **1,604개 통과**, 실패/error/skip0(813.977초)로 마감했다. v1.36의 동결723개 입력·21모듈404개 통과 기록은 당시 이력으로 보존하며 새 시험 수로 합산하지 않는다.

현재 가능한 소스는 마감했으며 아래7개는 각 소스 결과와 남은 실제 수용 조건이다. 정적43개 Python raw High0/Medium92/Low55의147개 관찰을 각각 검토했고 자동 억제0, JavaScript6개 구문 통과, 공개 콘텐츠78개 위반0·HTML mirror 일치를 확인했다. 이는 전체 플랫폼 취약점0이나 운영 침투 인증이 아니다. [최종 근거](../reports/advancement-batch7-2026-10-19/verification.json).

**재시작 후 현재 확인:** 2026-10-19 사용자 재시작·관리자 새로고침 뒤 읽기 표본13건이 모두 통과했다. health/관리자200, 관리자 자산5개 현재 소스 일치, 새 비공개 API의 비인증401, 공개 고객 페이지/인증404를 확인했다. 로그인된 관리자·실제 IdP/제공자 수용과 구분한다. **추가 재시작은 필요 없다.** 직전777개 동결 입력 중 제품3개와 별도 스크립트2개가 달라져 현재 성능 변경분은 별도 영향 범위 검증이 필요하다. 과거1,604통과를 이 변경분의 새 결과로 사용하지 않는다.

**지속 조건:** Workspace access는 계속 비공개, 관리자는 데스크톱 기준이다. 현재 정확한 추천·품질·사용성에 우선하며 실제 과금·지급·광고는 활성화하지 않는다.

[재시작 표본 확인](../reports/remaining-work-plan-2026-10-19/restart-readonly.json) · [v1.36 검증 이력](../reports/advancement-pg-compatibility-2026-10-19/README.md) · [v1.37 근거](../reports/advancement-batch7-2026-10-19/) · [기계 계획](platform-advancement-plan.json) · [2차 설계](PLATFORM_ADVANCEMENT_PHASE2_DESIGN.md)

## 재시작 이후 현재 권장 순서

[읽기 확인](../reports/remaining-work-plan-2026-10-19/post-v137-restart-readonly.json) · [현재 우선순위와 조건](../reports/remaining-work-plan-2026-10-19/post-v137-priority.json)

1. **최근 변경분 회귀·관리자 운영 수용·CI 마감** (N01 · N08) — 재시작 읽기 표본13건은 통과했다. 직전 동결 후 바뀐 프론트 상태 갱신·비동기 방문 기록·시작 prewarm의 영향만 먼저 확인한다. 큐 포화/종료·DB thread 소유권·기록 유실·현재 검증 표시와 초기 응답을 점검하고 로그인된 데스크톱 관리자 기능·권한·철회 수용 및 hosted CI를 마감한다.

2. **외부 환경 준비와 기능별 실제 연동 수용** (N02 · N03 · N04 · N05 · N06 · N07 · N11) — 비공개 Google/GitHub·HTTPS SDK2/BFF origin, 키/보존/복구 책임, 승인된 제공자·독립 검토자·허용 corpus, 목적별 검증 수신처를 정한다. 대상이 준비된 순서로 로그인/조직/배포/철회, 제공자 소유 증명·품질, 알림 수신과 명시 opt-in 읽기 shadow/canary를 검증한다. 브라우저 Push는 전달된 시험 알림 클릭까지 확인한다.

3. **평가 근거·코호트·원본 보존 계약 확장** (P2-01 · N06) — 완료된 bounded metadata rollup을 재사용하고 evaluator/cohort/source-retention 자격과 원본 보존·삭제·철회 의미를 추가한다. 표본 분모·버전·실패/unknown·독립 검토 상태를 분리하며 근거 소실 시 현재 품질 인증을 차단한다.

4. **지속 평가와 운영 저장소·복구 검증** (P2-02 · P2-09 · N03 · N08) — 승인 corpus의 budget/jitter/중복 방지/kill switch와 누락 coverage를 추가한다. 저장소는 완료된 native consumer·이전/대사·암호화 복원 소스를 재사용하고 대표 부하·검색/권한 동등성·전환/rollback·RPO/RTO·DR/HA를 승인된 대상에서 확인한다. 실제 정책·인프라에 필요한 차이만 개발한다.

5. **신뢰 화면·만료 배지·안전한 예측 라우팅** (P2-03 · P2-04) — 현재 증거만 표시하는 정제된 상세/만료 배지와 규칙 기반 offline/decision shadow를 먼저 만든다. 현재 권한·동등 계약·입력 공유·unknown 경계를 유지하며 실사용 대체 호출은 별도 동의와 실제 수용 후 제한한다.

6. **앱 생성·템플릿·배포 수명주기 확대** (P2-05 · P2-06 · N04 · N09) — 기존2–6노드 typed SDK2/BFF와 고객 조직 기능을 재사용해 목적→계약→검토→시험→릴리스, 소수의 수용된 템플릿, SDK/profile 호환·발급/철회/만료·rollback 지원의 부족한 부분을 확장한다. 새 agent 교체는 새 revision 비교 시험으로 다룬다.

7. **검증된 머신 알림·Webhook/A2A Inbox 확대** (P2-07 · N07) — 기존 주소 인증·작업 알림을 재사용하고 증거 버전/기한·서명 event·nonce/replay·audience·중복 방지·수신 상태를 명확히 하는 machine 구독 envelope를 확장한다. 수락을 업무 완료로 표시하지 않고 unknown을 자동 재발송하지 않는다.

8. **자체 에이전트·개발지원·고객 성과 검증** (P2-08 · N11) — 기존 docs MCP·AI 안내를 재사용해 좁은 읽기 업무와 검토 가능한 patch 지원을 개선한다. 자체 agent도 동일한 소유권·독립 평가·추천 기준을 적용하고 업무 성공·지원 부담·재사용 cohort를 측정한다.

9. **실제 계약·결제·환불·지급과 조건부 상용화** (P2-10 · N10 · N12) — 완료된 TEST_UNIT 원장·모의 계약·서명 이벤트를 재사용하고 실제 계약/배분/세무·결제사 sandbox·환불/지급·unknown 대사·지원/중단/rollback을 따로 수용한다. 제한 profile의 G2와 별도 실거래 승인 후에만 실제 거래를 검토하고 실제 성과로 G3 확대를 판단한다.

**즉시 진행:** 1번 변경분 검증을 먼저 마감하고 **3번을 다음 신규 개발**로 진행한다. 2번 외부 환경 준비/실제 수용과4번의 운영 저장소 준비는 병행한다. 이후3→4→5, 3→6·7, 6→8 순서로 확대하고9번은 마지막 조건부 단계다. 장기 프로토콜·자동 교체·대규모 템플릿은 실제 수요와 별도 계약이 생겼을 때 진행한다.

아래 상세7개는 **이미 개발한 묶음의 결과와 운영 잔여 설명**이며 위9개가 현재 권장 순서다. 기존N/P2 식별자는 범위 추적에 유지한다.

아래7개는 실행 묶음이며 새로운 R/AC 티켓이 아니다. 기존N01~N12 번호는 범위 추적에 유지한다. **7개 묶음에서 현재 가능한 소스와 최종 영향 범위 검증을 함께 마감했다.** 남은 것은 실제 외부 환경의 수용·운영 책임과 별도 조건부 확대이며 검증한 소스를 재개발하지 않는다. 실제 환경이 필요한 수용은3번 준비 자료로 분리한다. 전체7개 운영 완료·전체PG 준비·2차 제품 출시를 선언하지 않는다.

현재 격리 근거는 일반/기존 private archive53개, P2-01 evidence29개, TEST_UNIT sandbox core23개 및 별도 desktop browser3개다. 서로 중복될 수 있는 개별 시험을 최종 통합 수로 더하지 않는다. 현재 PostgreSQL2922개 고정 SQL쌍/164개 table과 조사된78개 호출 메서드의 미구현0, 실제 consumer·이전 준비·별도 typed SDK2 소스를 마감했다. table/SQL 수를 전체 운영 준비로 해석하지 않는다. 최종777개 입력·97모듈 동일소스 영향 범위 **1,604개 통과**, 실패/error/skip0(813.977초)이며 개별/과거 시험 수는 더하지 않는다.

## 1. 현 버전 운영 수용·CI 마감 (N01)

재시작·관리자 주요 스크립트 반영·기본 접근 차단은 읽기 전용 확인했다. 남은 작업은 로그인된 관리자 세션의 주요 기능·권한·철회 수용과 저장소 CI 실행 결과 확인이다. 현재 readiness 화면은 실제 외부 증빙이 없는 항목을 미검증으로 유지하고 운영 기능을 활성화하지 않는다. CI 실행기는 기본 단일 실행을 유지하면서 명시적1-based file shard를 지원하고 GitHub workflow를4개 job으로 나눴다. 실제207모듈 목록의52/52/52/51 분할·정확한 합집합/중복0·잘못된 범위/빈 shard 안전성 등21개 격리 시험을 확인했다. job당40분 제한은 유지하며 hosted CI 시간/성공을 측정한 결과는 아니다.

완료 기준: 현재 지원 기능의 운영 점검 기록과 hosted CI 결과를 남긴다. 읽기 smoke를 로그인된 실행·운영 전체 수용으로 확대 해석하지 않는다.

필요한 조건: 기존 관리자 세션과 검증 대상 / 저장소·CI 실행 권한

병행·선행: 검증한2번 소스를 재사용하며3번 외부 환경 준비와 병행한다. v1.37 재시작 읽기 확인은 완료했으며 현재 변경분 회귀·인증 운영 수용·hosted CI를 각각 확인한다.

## 2. PostgreSQL 소스 마감·운영 이전 수용 준비 (N08 · N03)

조사된78메서드 구현과 private worker/archive를 재사용한다. 이번 묶음에서2922개 고정 SQL쌍/164개 table·호출 메서드 미구현0을 대사하고 실제 consumer의 finite SQL 분기·SQLite/PG 동등성, 명시적 source/target 복사·대사·준비 승인, 일반 archive credential/현재 복원 소유권·배포 차단의 소스를 마감했다. 공개 추천/URL 중복 조회, 관리자 방문 에이전트·테스트/대체 후보·GC·비교/RAG와 기존 공개 조회를 실제 native 경로로 검증했다. Chat 추천 metadata는 native read snapshot에서 현재 자료를 읽고 후보의 원래 SQLite 시간/JSON 판별식만 검증된 memory TEMP/savepoint에 재사용한다. 순위 산정은 기존 Python을 유지하며 다른 consumer는 고정 native 조회/FTS projection을 쓴다. 지원하지 않는 SQL은 계속 차단한다. 최종 동일소스 통합을 통과했으며 이 구조 수치는 전체 application/운영 준비 판정이 아니다. 일반 archive는 caller-owned 연결과 일회용 목적별 credential provider, mandatory AES-GCM archive, 고정 tool argv/비밀 pgpass, 외부 control schema의 pending/failed/quarantined gate·현재 소유자 재승인까지53개 격리 시험을 통과했다. 이 API의 존재가 실제 운영 backup 승인이나 연결을 의미하지 않는다.

완료 기준: 검토된 경로와 남은 지원 범위를 명시하고, 무중복·철회 보존·실패 rollback·복원 격리·검색/권한 동등성을 격리 시험한다. 전체 준비 판정은 실제 근거가 있는 범위에만 부여한다.

필요한 조건: 소스·합성/소유 복사본 검증은 완료 / 실제 운영 연결·전환·지원 범위 수용은 별도 권한·대상 필요

병행·선행: 완료된 소스를 재사용하며3번 외부 준비와5번 운영 측정을 병행한다. 운영 DB를 자동 전환하지 않는다.

## 3. 인증·키·배포·제공자·평가 자료 준비 (N02 · N03 · N04 · N05 · N06 · N11)

실제 Google/GitHub 설정, 별도 호스팅 SDK2 검증 origin, 키 보관·회전·데이터 보존 책임, 제공자 동의/소유 증명, 독립 평가자·자료와 지원 문서를 준비한다. 이미 구현된 조직·권한·키링·모의 원장·AI 안내는 반복 개발하지 않는다. 현재 preparation은 서버 코드가 주입한 typed ConfigurationCheck의 workspace/purpose·현재 설정/기한을 읽기 전용 검사하며 sources=None이면 누락으로 표시한다. 기존 readiness 선언은 별도로 미검증 상태를 유지하고 참조 제출을 실제 외부 검증으로 승격하지 않는다. 실제 IdP/SDK2 및 승인된 제공자·알림·결제 sandbox 미지정을 누락 조건으로 남긴다.

완료 기준: 기능별 실제 시험 대상·책임자·설정·평가 기준이 정해져 있고 누락 조건을 기록한다. 비밀값을 문서나 채팅에 적지 않는다.

필요한 조건: 실제 IdP 설정·허용 redirect/origin / 키·보존·복구 책임 정책 / 동의한 제공자·검토자·허용 자료

병행·선행: 1~2번부터 병행한다. Workspace access는 계속 비공개이며 인증 수용은 격리/staging 범위로 준비한다.

## 4. 승인된 대상의 제한 서비스 운영 검증 (N01 · N04 · N05 · N06 · N07 · N11)

실제 제공자 소유 증명과 독립 품질 평가를 확인한 대상부터 SDK2 인증·실행·철회, 읽기 전용 shadow/canary, 예약·동의된 알림 전달, AI 지원/자체 docs 에이전트의 실제 품질을 검증한다.

완료 기준: 입력 공유/전달 동의·unknown 재호출 차단·기한·철회·중단/rollback을 확인하고 G0/G1을 지원 기능별로 판정한다. 실제 cohort 관찰과 초기 지원 준비를 기록한다.

필요한 조건: 검증할 실제 제공자·배포·수신처 및 목적별 권한 / 사용자 opt-in·관찰 기간

병행·선행: 모든 후속 개발이나 전체 PG/HA 완료를 현재 서비스의 일률적 선행 조건으로 묶지 않는다. 공개 Workspace 해제·광고·과금은 포함하지 않는다.

## 5. 운영 저장소 성능·백업·전환·재해 복구 수용 (N03 · N08)

합성5,000개씩 동일 fixture의 실제 카탈로그 조회를 측정했다. SQLite ingest2.903초·검색 중앙값4.783ms·Explore cold14.359ms·Insights cold28.083ms, PostgreSQL ingest7.905초·검색 중앙값9.866ms·Explore cold86.036ms·Insights cold115.230ms다. 적격 fixture 준비3.065초/10.680초는 ingest와 분리했다. PG fixture UPDATE가 기존5초 제한에 걸려 준비를100행 묶음으로 나눴으며 제한을 올리지 않았다. 이 결과는 운영 용량·지연 SLA·경합/HA 인증이 아니다. [측정 원본](../reports/advancement-batch7-2026-10-19/catalog-benchmark.json)을 보존한다.

명시적 일반 backup/restore API와 source/target 대사·writer fence·전환/rollback 준비는 운영 연결 없이 소스·격리 검증을 완료했다. 새 대상의 gate를 격리 완료/현재 소유자 재승인 전까지 닫고 옛 실행·grant·수신처·배포/결제 권한을 부활시키지 않는다. 실제 RPO/RTO·작업 창구·장애 전환/복귀는 승인된 운영 대상에서 별도로 측정한다.

완료 기준: 성능·용량·RPO/RTO·복원/rollback·HA의 실제 측정과 담당자/운영 절차를 남긴다. source profile 통과를 운영 HA로 표시하지 않는다.

필요한 조건: 원본/대상 DB·writer 배제·작업 창구 권한 / 대표 트래픽·용량·RPO/RTO 목표 / backup/HA 인프라·운영 자격증명

병행·선행: 4번 서비스 검증과 병행 가능하다. 현재 서비스를 운영 PG로 자동 이전하지 않는다. 제한 파일럿은 선택한 운영DB/profile의 안정성을 판정하며 전체PG 전환·범용HA 완성을 일률적 필수 조건으로 강제하지 않는다.

## 6. 필요한 워크플로우 확장·2차 설계 확정과 착수 (N09 · N11 · P2-01)

기존 private typed MCP를 별도2~6노드 SDK2 release/export와 고객 BFF로 연결했다. 성공한 고정 graph/version 실행만 release로 만들고 전체 대상·literal 입력·선택 prior-output/분기를 검토한 실행별 동의, 매 dispatch와 성공 확정의 현재 고객/조직·배포·pin 검사를 유지한다. 기존 단건 SDK2·SDK1/공개 다운로드는 별도 계약을 보존한다. 별도 typed SDK2의 API/BFF/실제 ZIP·관리자 desktop102개 격리 시험과 native PG 생성 BFF/동의·2노드 실행·replay/철회6개 중첩 계약을 확인했다. 개별 근거를 최종 통합 수로 더하지 않으며 실제 IdP/호스팅 수용과 구분한다.

P2-01 보존 증거 요약은 현재 membership/version/기한·원본 보존·논리 실행 중복 제거·unknown 충돌·철회 tombstone을 확인하는 읽기 API/관리자 데스크톱으로29개 격리 시험을 통과했다. 출력 복호화나 새 품질/실행 성공 증거를 만들지 않으며 operating qualification은 false다. 전체 P2-01 평가자/cohort/source-fidelity와 장기 세션·streaming은 잔여다.

완료 기준: 공유 동의·버전 pin·철회·만료·조직 격리·복원·기존 다운로드 호환을 범위별로 검증한다. 증거 요약이 새로운 성공/품질 증거를 만들어 내지 않는다.

필요한 조건: 확대할 실제 provider schema·승인·성공 근거 / SDK2/private 확대의 권한 계약 / 장기 프로토콜은 실제 수요·조회/취소/중복 방지 계약

병행·선행: 검증한 typed SDK2와 P2-01 요약 소스는 반복 개발하지 않는다. 별도2차 설계의 평가/cohort/source-fidelity·신뢰성 또는 장기 프로토콜 확대를 새 범위로 진행하며 실제 제공자·부하 조건을 각각 충족한다. 2차 설계안을 제품 출시로 표시하지 않는다.

## 7. 실제 결제·계약·지급과 상용 확대 (N10 · N12)

TEST_UNIT 계량·균형 원장·모의70:30 계약을 재사용하는 서버 서명 sandbox event adapter를 추가했다. current owner·intent 만료/withdrawal·동의·event dedupe/CAS를 검사하고 capture/refund 원장·receipt·감사를 같은 transaction에서 확정한다. core23개와 실제 관리자 desktop browser3개에서 확인했으며 응답 불확실성은 자동 재전송하지 않는다. 이는 내부 TEST_UNIT 모의 adapter이며 실제 결제사 event 검증·금전·provider payout·법적 계약/세무 수용이 아니다. 실제 제공자와 승인된 시험 대상이 정해진 뒤 별도 검증한다.

완료 기준: 초기 지원 준비와 G2를 갖춘 제한 파일럿 이후 실제 반복사용·업무 성공·운영 근거로 G3 확대를 판단한다. 4주 cohort 전체 성과를 초기 G2의 일률적 선행 조건으로 강제하지 않는다.

필요한 조건: 법적 계약·배분/세무/환불/지급 정책 / 실제 결제 제공자·거래 승인·대사 근거

병행·선행: 현재는 정확한 추천·품질·사용성에 우선한다. 과금·지급·광고를 이번 계획 작성으로 활성화하지 않는다. 범용 장기 프로토콜 전체 구현을 제한 상용화의 필수 조건으로 강제하지 않는다.

## 반복 작업을 줄이는 진행 방식

- 완료한78개 조사 Store 메서드·고객 조직/권한·키링·private worker/archive·typed MCP·TEST_UNIT·AI 안내·모의 계약은 재개발하지 않는다.
- 각 소스 묶음에서 계약·백엔드/API·관리자 데스크톱·철회/복원·보안·격리 동적 시험·문서를 함께 마감한다.
- 변경 영향 범위로 소스를 고정해 한 번 검증하고, 소스가 다시 바뀌거나 실패가 있을 때만 해당 범위를 재검증한다. v1.36의404개를 새 수에 합산하거나 계획 문구 수정만으로 같은 전체 검사를 반복하지 않는다.
- 이번 사용자 재시작/새로고침을 다시 요구하지 않는다. 이후 새 서버 import 소스를 개발한 묶음의 종료 시에만 필요한 재시작을 한 번 안내한다.
- 외부 설정/제공자 수용을 기다릴 때 검증한2번·typed SDK2·P2-01 요약 소스를 반복 개발하지 않는다. 별도2차 설계의 평가/cohort/source-fidelity·신뢰성 확대는 새 범위로 진행한다. 운영 수용 완료·전체1차 완료·2차 제품 출시를 혼동하지 않는다.

## 기존 업무 식별자별 상태 참고

### N01 · 현 버전 인증 운영 수용·G0 잔여 정리

사용자 재시작·정적 반영/기본 접근 경계 확인; 인증된 운영 수용·hosted CI 잔여

v1.36 사용자 재시작 이후 서버 시작 시각·주요 관리자JS3개와 health/admin200·비인증 workspace401·공개 고객404를 표본 확인했다. 이 기록은 이후 v1.37 소스 반영 증명이 아니다. 전체 관리자 실행 수용/hosted CI는 별도다. 공개 Workspace access는 계속 비활성이고 Google/GitHub 설정만으로 열리지 않는다. v1.37 사용자 재시작·새로고침 후13개 읽기 표본을 확인했다. 최근 성능 변경분 검증과 인증된 운영 수용은 별도다.

### N02 · 고객 인증·조직 권한·BFF

고객 소유 조직·초대·역할·탈퇴 소스 구현; 공개 접근 보류·실제 IdP 수용 잔여

Google OIDC/GitHub OAuth 고객 인증과 고객 owner/editor/viewer/runner 조직·정확한 고객ID 초대·수락/거부/철회·최종 owner 보호/이전·탈퇴/계정 비활성·세션/BFF 철회를 구현했다. 직원 신원과 구분하며 execute-only 토큰은 소유자 관리 권한을 갖지 않는다. 삭제 tombstone은 재로그인으로 권한이 부활하는 것을 막는다. 물리 backup 전체 삭제나 IdP 상실 복구를 자동 추정하지 않는다. 공개 Workspace access는 명시적 출시 승인 전까지 기본 비활성이다. 현재 customer opaque ID 실행·동의/replay·철회는 native PG 합성 profile에서도 확인했다. 실제 IdP 운영 수용과 구분한다.

### N03 · 비공개 실행 보존·쿼터·unknown 대사

버전 키링·선택형 출력/백업 암호화·보존·복원 경계 소스 구현; 운영 키/보존 정책 수용 잔여

bounded ticket/output 정리·서명 tombstone·unknown 메모에 선택형 버전 키링과 이전키 검증 기한/철회, AES-256-GCM private output/backup 암호화, manifest 검증·복원 차단을 추가했다. 운영 키링은 변경하지 않았고 별도 설정 없이는 암호화를 주장하지 않는다. 암호화 backup의 staging 평문 물리 삭제나 포괄적 개인정보 삭제를 보장하지 않는다. 키 변경은 runtime 재구성/재시작 후 반영한다. native private/offline archive에서도 SIGKILL·unknown·키 회전/철회/변조·fresh-target quarantine과 ciphertext/held ledger 보존을 검증했다. 일반 caller-owned credential provider·서명/암호화 archive·외부 restore gate·현재 소유자 재승인 API도53개 격리 시험으로 검증했다. OS/DB identity·wrong credential·expiry·동시 ownership·corrupt archive·실패 rollback·unknown 보존과 fresh target/no-overwrite를 포함한다. 실제 운영 credential·키 보관/회전·RPO/RTO/DR 수용은 별도다.

### N04 · 불변 실행 릴리스·비공개 SDK v2

단건 SDK2 유지·별도 typed SDK2 source/API/BFF/desktop/native 검증; 실제 IdP/별도 hosting 수용 잔여

현재 성공한 수동 MCP 단건 snapshot의 immutable release, origin별 배포 grant, 고객 전용 code/PKCE·서버 BFF·짧은 audience/scope, 실행별 별도 동의·idempotency·철회·복원 차단을 유지하고 버전 서명/암호화 연동을 검증한다. 기존 SDK1.0~1.3/공개 웹앱 다운로드 계약은 유지한다. 다단계 typed flow의 별도 SDK2 profile·whole-graph 동의·고객 BFF/복원 차단을 추가하고 격리 source/API/desktop/native 경로를 검증했다. 장기 stateful profile은 지원하지 않는다. 고객 공개 페이지/권한 API는 출시 보류다. 생성 SDK2의 BFF code exchange·동의·실행/replay·retained status·배포 철회는 격리 native PG/API transport로 검증했으며 실제 IdP/별도 hosting 수용을 대신하지 않는다.

### N05 · 제공자 소유권 확인·재검증

현재 HTTPS control·재인증·이전·만료/CAS 소스 구현; 실제 제공자·법적 소유 수용 잔여

서명된 HTTPS endpoint-control challenge·SSRF/DNS/redirect 차단·현재 binding/generation에 더해 재인증·도메인 변경·기한·새 owner target proof를 요구하는 CAS 이전을 추가했다. 이전 proof는 재사용하지 않고 복원 offer는 차단한다. control 증거를 법적 소유·품질·연락처 동의로 해석하지 않는다.

### N06 · 실제 품질 평가·모델/제공자 검증

사전 staff 평가 할당·점수/불일치 대사 소스 구현; 실제 독립 전문가·자료/품질 검증 잔여

private snapshot의 사전 예약과 별도 staff 실행자/검토자/조정자, retained run 출력·고정 rubric 점수·불일치 대사를 유지한다. 현재 자격/독립성/출처 trusted adapter는 실제 운영 증빙이 없으면 미설정/미검증이다. 합성 fixture나 서로 다른 계정은 독립 전문가·holdout·정확도를 증명하지 않는다.

### N07 · 읽기 폴백·예약/이벤트 실제 운영 수용·G1

제한 읽기 폴백·예약/이벤트 소스 구현; 실제 승인 cohort·G1 수용 잔여

news/docs readonly 승인 쌍·shadow·명시적 opt-in canary와 원래 deadline/unknown 경계를 유지한다. 실제 제공자 입력 전송·자동화/전달·장애 주입은 운영 수용용 현재 목적 권한이 있는 대상에서 별도 검증한다. 이번 묶음에서 운영 canary나 예약/결과 발송을 활성화하지 않는다.

### N08 · 전체 Store/PostgreSQL·부하·복구·HA

78/78 조사 메서드·2922 고정 SQL쌍/164 tables·실제 consumer/이전 준비 소스 마감; 전체 운영 이전·부하/DR/HA 미승인

기존 미지원28개를 추가한 v1.36의78개 concrete 메서드·native36/22/39/27 계약과21모듈404통과는 당시 근거로 보존한다. 현재는2922개 고정 SQL쌍/164개 table과 실제 관리자/공개 추천·중복 조회·방문 에이전트·GC/비교/RAG/SNS consumer·명시적 이전 준비를 추가 검증했다. 고정 SQL admission·실제 FTS weighting/current visibility·rollback epoch ABA·cursor cleanup poison·2,000건 초과 upper median, wrong-key mutation·손상 가상 계정 보존을 검증했다. caller-owned 연결/32byte key·명시 proxy를 유지하며 finite SQL/consumer 대사·명시적 복사/전환 준비 소스와 격리 native 근거를 마감했으며97모듈 최종 동일소스 통합을 통과했다. 별도 일반 archive credential provider와 restore gate/reapproval은 구현/격리 검증했다. 합성5,000행 카탈로그 측정은 실제 운영 용량·전환·대표부하/DR/HA 수용이 아니다. full_application_ready=false/operating_backup_ready=false이며 운영 DB/DSN/서버는 변경하지 않았다.

### N09 · 워크플로우·제품·장기 프로토콜 범위 확대

비공개6노드 typed MCP·별도 SDK2 export 소스/격리 검증; 공개/stateful 확대 잔여

고정 계약 news/docs/products의 승인된 readonly MCP를 최대6노드 DAG로 저장·불변 version pin·조건 분기·schema-known 출력 projection으로 연결한다. whole-graph 준비 후 모든 대상/해석 입력을 검토하고 별도 1회 공유 동의로 실행한다. 매 호출 전후 현재 권한/증거/제어, 60초 전체/12초 노드/최대6호출, 공유 concurrency·unknown/복원 차단·private 결과를 검증한다. 임의 DAG script나 세션 이식·streaming/장기 A2A·쓰기·결제는 지원하지 않는다. 별도2~6노드 SDK2 DAG export·고객 BFF·whole-graph 동의와 native/desktop/API 격리 검증을 추가했다. 실제 별도 hosting/IdP 수용은 잔여다.

### N10 · 모의 사용량·균형 원장·대사

논리 실행/실제 dispatch별 자동 TEST_UNIT 계량·균형 원장 소스 구현; 실제 결제 event/상거래 수용 잔여

current owner가 목적별 동의로 기한/한도 있는 policy를 승인하면 private 단건·typed flow admission/dispatch/terminal과 동일 transaction에서 논리 run/실제 시도/성공1회 TEST_UNIT을 기록한다. 실패/unknown은 성공 사용량0, replay dedupe·서명/균형·orphan 검사를 적용한다. 복원 후 policy는 폐기하고 expired metadata recovery는 재호출하지 않는다. 기존 수동 원장·대사/역분개는 별도이며 서버 서명 TEST_UNIT sandbox event adapter는 이번에 추가했지만 실제 결제사 adapter·과금·지급은 없다.

### N11 · AI 개발지원센터·자체 에이전트

명시적 공개 목적만 공유하는 AI 안내·검토 patch와 자체 docs MCP 소스 구현; 공개 출시·실제 품질/cohort 잔여

고정 도움말과 사용자 공개 목적만 설정된 모델에 전달하며 private draft/ID/input을 보내지 않는다. 별도 동의·응답 크기/압축/JSON/출처 제한·현재 context 재검사 후 미검증 안내와 name/description 검토 proposal만 만든다. 적용은 별도 동의이며 실행/게시하지 않는다. 고정 public docs.search.v1 자체 MCP는 실제 initialize/list/call/source route를 구현하되 기본 off이며 자동 catalog 승인/랭킹하지 않는다. 실제 모델 품질·고객/자체 agent 출시·4주 cohort는 별도다.

### N12 · 조건부 상용 파일럿·마켓플레이스 확대

불변 모의 제공자 계약·70:30 배분/공제/부분환불·관리자 검토 소스 구현; 실제 계약/결제·G2/G3 잔여

현재 endpoint-control proof와 owner authority epoch에 묶은 immutable agreement version, 구조화 TEST_UNIT terms와 70% provider/30% platform, 공제→세금→잔액 배분·누적 부분환불·event dedupe/CAS·서명 균형 원장을 제공한다. quote는 읽기이며 capture/refund/revoke는 별도 동의다. 문서 참조/hash는 법적 서명이 아니고 모든 DTO는 legal verification unverified/actual money false다. 서버 서명 TEST_UNIT sandbox intent/capture/refund/receipt/withdrawal은 원장과 원자적으로 연동하고 복원 후 옛 intent를 영구 차단한다. 실제 계약·결제·provider payout·광고·자동 G2/G3는 활성화하지 않는다.
