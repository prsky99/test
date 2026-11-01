# Agent Concierge — Research Design Refinement

> **최종 개발 마감 순서:** [개발 완료 최종 계획](DEVELOPMENT_COMPLETION_PLAN.md)의 1~9단계를 따른다. 아래 POST/R/N/AC 순서와 수용 기록은 기존 요구·구현 이력 대조용으로 보존한다. 원래 필수 범위를 제외하거나 개발 완료를 선언한 것은 아니다.

<!-- RND_CURRENT_SOURCE_START -->
### 수용 snapshot 및 재시작 후 점검 · 2026-10-19

**v1.41의 수용 당시 선택된 제한 source**를 동결 입력 957개·영향 모듈 142개·고유 회귀 **2,206개 통과**로 통합 확인했다. 실패/error/skip0·source drift0이며 [최종 검증](../reports/advancement-completion-2026-10-19/verification.json)과 [수용 source snapshot](../reports/advancement-completion-2026-10-19/accepted-source-snapshot.json)에 기록했다. exact corpus·manifest/admission/replan, 운영 자격·로컬 verdict, 비공개 조립/고객 authoring/목적별 알림, circuit 수동 제어, Privacy 검토, bounded bootstrap, 선택형 model proposal, 별도 opt-in public receipt, 수동 remote A2A polling UI/API, offline EIP-3009 crypto의 제한 범위다. **전체 설계 완료나 실제 운영 수용은 아니다.**

최종 native 내부 계약 93개는 해당 pytest 범위 안의 중첩 검사이며 회귀 2,206개에 더하지 않는다. 과거 v1.40의 1,313개·native80개·재시작 읽기38개와 component 재실행도 합산하지 않았다. 수용 당시 공개 콘텐츠 87개 위반0·SQL catalog 3238 statements/205 tables 정합성을 확인했다. scratch115,009건 HTML181.514/29.381ms 두 표본은 collector 경합·운영 p95/SLA/HA 수용 근거가 아니다.

재시작 후 [읽기 전용 점검](../reports/advancement-completion-2026-10-19/POST_RESTART_VERIFICATION.md)은 **46/46 통과**했고, 추가 변경의 격리 영향 회귀는 **15개 모듈·고유270개 통과**로 모듈별 최신 결과를 교체했다. 이 수를 기존2,206개에 더하지 않는다. 현재 프로세스의 HTML 함수 hash는 이전 수용본과 일치하고 현재 소스와 다르다. 보안 격리 대상의 과거 목록 재노출은 소스/격리 회귀에서 보완됐으며 새 SQL은 catalog3239/205에 등록됐다. 이후에도 다른 작업의 소스 변경과 catalog manifest 차이가 관측되어 **현재 전체 소스 승인과 최신 운영 반영은 보류**한다.

남은 항목은 **지정 대상이 필요한 실제 수용**과 **선택된 조건부 추가 source**다. persistent 전체 PostgreSQL cutover/rollback·HA, actual early-stop controller·threshold/실제 개입 증거, A2A session/streaming, 실제 first-party 업무 성과, actual PSP/finality/refund/payout, sole-owner recovery는 남아 있다. 제한 profile이나 callback 주입을 이 전체 범위의 완료로 표시하지 않는다.

기존 POST139R ID는 요구 추적에 유지하며, 최종 실행 순서는 [개발 완료 최종 계획](DEVELOPMENT_COMPLETION_PLAN.md)의 1~9단계를 따른다. R/N/AC와 아래 과거 절은 이력이다. 공개 Workspace·광고 전달·실거래 off, 고객 로그인 프론트엔드 전용, 개별 관리자/desktop을 유지한다. 사용자 재시작 보고를 확인했다. **다른 수정 마감 → catalog 재생성/정합성 → 최종 변경분 검증 → 사용자 터미널 재시작·새로고침 한 번**으로 묶은 뒤 현재 build의 인증된/비공개 수용을 확인한다. 에이전트가 운영 서버를 재시작하거나 운영 DB·외부 제공자·실거래를 조작하지 않았다.
<!-- RND_CURRENT_SOURCE_END -->

### 역사적 RND r1 설계 근거 · 제품 v1.39 / 2차 설계 2.0-draft.3

아래 r1의 문서 전용·다음 개발 표현은 당시 기록이다. 현재 source 후보와 남은 순서는 위 배너와 정규 JSON을 따른다.

이 문서는 사용자가 제공한 「초격차 기술 심층 조사 및 단계별 R&D 실행 연구 계획서」를 기존 설계에 반영하는 보완 계약이다. 별도 제품 로드맵을 만들지 않는다. 실행 순서의 권위 문서는 [현재 작업 순서](REMAINING_WORK_BATCHES.md), 연구 하위 과제의 구조화 원본은 [platform-rnd-refinement.json](platform-rnd-refinement.json)이다. 기존 POST139R-01~09, P2-01~10, N01~12 식별자를 유지한다.

제품 코드는 변경하지 않았다. v1.39의 관련 649개 입력·32모듈·483개 회귀와 native PostgreSQL 63개 계약, 직전 재시작 읽기 22/22건은 기존 검증 이력이다. 이번 문서 보완에서 다시 실행하거나 새 성과로 합산하지 않는다. 운영 서버·DB·외부 제공자·알림·실거래를 조작하지 않으며 추가 재시작도 필요 없다.

## 1. 반영 결정과 근거의 한계

첨부의 신뢰성 실험, 단계 관측, 서버 중심 보안, 프로토콜별 정산 연구 방향은 채택한다. 논문의 실험 결과를 플랫폼의 완료 기능이나 보장으로 바꾸지는 않는다. 현재 범용 자연어 합성·진행 중 세션 hot-swap·실제 70:30 정산·유료 무중단 SLA는 구현/운영 완료가 아니다. 현재 앱 선택은 영어 keyword와 고정 템플릿 3개이며, 실사용 예측 라우팅은 아닌 offline/decision shadow다.

- [ReliabilityBench v1](https://arxiv.org/html/2601.06112v1)의 반복·변형·장애 세 축을 실험 설계에 활용한다. 제한된 합성 도메인의 실험으로 임의 제공자 간 상태 이식이나 무조건적 대체 우월성을 주장하지 않는다. [τ-bench](https://arxiv.org/html/2406.12045v1)의 `pass^k`는 k회 모두 성공하는 일관성 지표이며 하나 이상 성공하는 `pass@k`와 구분한다.
- [DynSTEER v1](https://arxiv.org/html/2609.14637v1)의 34.51%, [v2](https://arxiv.org/html/2609.14637v2)의 45.41%, [v3](https://arxiv.org/html/2609.14637v3)의 전체 ToolSandbox 17.74%·SWE-bench Pro 8.40%는 버전과 분모가 다르다. 반사실적 replay의 절감과 실제 중단·실제 원가 절감을 구분한다. 이중 클록·단계 평가의 설계 영감만 채택하고 자체 비교 실험을 별도로 수행한다.
- [MechMath Agent Team](https://arxiv.org/html/2607.04394v1)의 Harness는 수학 연구 시스템의 구조적 사례다. [PANDA](https://arxiv.org/html/2609.38482v1)의 특정 장애 실험 완료율 100%는 정답률 100%나 서비스 SLA가 아니다. 병렬 중복 실행 제안도 현재 외부 단회 호출 경계를 넘겨 채택하지 않는다.
- [NetGPT](https://arxiv.org/html/2511.22217v1), [Self-Healing Router](https://arxiv.org/pdf/2603.01548), [DAG QA](https://arxiv.org/html/2603.14229v1), [AgentSkiller](https://arxiv.org/html/2602.09372v1)는 서로 다른 환경·검증 범위를 가진다. 최소 ID 전달·계획 검증·진행 로그의 원칙을 활용하되 외부 API의 무손실 재개 근거로 사용하지 않는다. `should_expose_answer`는 DAG QA의 기능이며 일반 실행 권한이 아니다.
- [MoFlow](https://arxiv.org/html/2609.38294v1)는 다목적 워크플로우 탐색 연구이지 지급 승인 규격이 아니다. 첨부가 EvoSteer로 인용한 [2609.38684](https://arxiv.org/abs/2609.38684)는 다른 연구이므로 기여도 정산 근거에서 제외한다.
- x402 v2의 [HTTP binding](https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/http.md)과 [batch-settlement scheme](https://github.com/x402-foundation/x402/blob/main/specs/schemes/batch-settlement/scheme_batch_settlement.md)은 실제 규격이다. 그러나 [exact scheme](https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact.md)의 지불과 작업 성공은 같지 않으며 실패 과금 0·자동 환불·자동 70% 지급을 보장하지 않는다. 구현 착수 때 mutable main URL 대신 정확한 commit/지원 binding을 고정한다.
- [MDN private elements](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Classes/Private_elements)는 언어 수준 캡슐화를 설명하며 DevTools 비밀 보관을 보장하지 않는다. `#private`·deepFreeze·네이티브 함수 검사는 서버 권한 경계를 대신할 수 없다.
- 53,820→2,001 토큰은 산술적으로 약 96.28% 감소다. 제공된 수치의 산술 검산일 뿐 자체 실측이 아니다. 거래량·시장 단가·최소 수수료·정산 시간·매출총이익 100%·99.99% SLA·보안 사고 0건은 검증 자료 없이 baseline/약속으로 쓰지 않는다.

출처별 버전·수치 정정·미확인 항목은 [논문 감사](../reports/rnd-design-refinement-2026-10-19/reliability-source-audit.json)와 [프로토콜/보안 감사](../reports/rnd-design-refinement-2026-10-19/protocol-security-source-audit.json)에 보존한다. 외부 출처의 존재, 재현 결과, 제품 구현, 실제 운영 수용을 별도 상태로 관리한다.

## 2. 재개발하지 않을 기반

- `workspace_typed_flows.py`: 2–6노드 typed 실행, 순환/스키마 검사, projection/조건 분기, 서명 상태·암호화 출력·현재 권한 fence. 연구용 별도 DAG 실행기를 만들지 않는다.
- `workspace_reliability.py`, `evidence_rollups.py`: 단건 MCP 원본-실행 binding, 목적별 보존/삭제·독립 판정·집계/철회. typed lineage adapter만 확장한다.
- `reliability_evaluation.py`, `reliability_evaluation_worker.py`: 승인 corpus/plan, 고정 시간 창·host budget/jitter·coverage, 기본 off technical evaluator와 worker. 별도 평가 scheduler를 만들지 않는다.
- `workflow_persistence.py`, `observability.py`: 단회 dispatch, checkpoint/fence·unknown·논리 operation/attempt·outbox. 연구 데이터의 출처로 참조하고 두 번째 실행 저널을 만들지 않는다.
- `workspace_machine_receiver.py`, `workspace_machine_adapters.py`: 검증 주소 proof·목적별 권한, 수신처별 파생 키, 원자적 영속 replay claim·수락 receipt. 새 A2A inbox 서버를 만들지 않는다.
- `workspace_release.py`, `workspace_typed_release.py`, `workspace_sdk_bff.py`, `gateway/webapp/sdk-v2.js`: same-origin BFF, PKCE 단회 code·제약 capability·현재 조직/릴리스/만료·논리 호출 한도. browser master key 은닉 기능을 새로 설계했다고 표현하지 않는다.
- `workspace_app_factory.py`: 고정 계약 템플릿 3개와 keyword 선택. 추가 intent 후보/검토 규칙만 차이로 개발한다.
- `workspace_metering.py`, `workspace_agreements.py`, `workspace_sandbox_payments.py`: TEST_UNIT·불변 모의 계약·70:30 정수 배분·환불/중복·unknown 대사. 새로운 금융 원장을 병렬로 만들지 않는다.

재사용 소스 대조의 초기 검토는 [소스 대조 이력](../reports/rnd-design-refinement-2026-10-19/reuse-gap-review.json)에 남긴다. 해당 보고서의 제안 alias는 비권위 이력이며 최종 하위 계약·순서·담당 산출물은 [구조화 원본](platform-rnd-refinement.json)을 따른다. 위 기반의 존재가 실제 IdP·독립 평가·외부 수신·결제·운영 DR 수용을 대신하지 않는다.

## 3. 공통 실행 증거 계약 — 다음 신규 개발

**기존 ID: P2-01-TYPED-EVIDENCE / POST139R-03.** 다른 연구의 선행 입력이 되는 하나의 lineage 형식을 먼저 정의한다. MR·Dual-Clock·라우팅·나중의 기여도 평가가 이 참조를 재사용한다.

하나의 논리 run 아래 node/attempt를 구분하고 다음 metadata를 버전 고정한다.

- workspace 범위, graph/release/definition revision, run/node/attempt identity, agent immutable version·schema hash·semantic contract revision.
- 원래 요청과 실제 resolved input의 구분, 분기 선택/미실행 이유, projection의 부모 node/field path, 관찰된 결과 source reference와 hash.
- 현재 실행/입력 공유/평가·보존 동의 목적과 revision, authority/fence, `prepared`/`dispatched`/확정 응답/checkpoint/terminal/unknown 근거와 관측 시각.
- raw event sequence, closed action sequence의 선택적 확장 자리, corpus/case/episode/MR/fault/oracle/milestone 참조. 아직 없는 이벤트를 추정 생성하지 않는다.
- technical result, independent quality, source fidelity, business outcome, delivery receipt, payment status를 별도 필드로 둔다. 동일 논리 run과 하위 시도를 성공 표본 여러 개로 부풀리지 않는다.

이는 새 공개 API/테이블의 구현 완료 선언이 아닌 profile 설계다. 기존 run/step/checkpoint 원본을 참조하며 보존 동의 없이 과거 출력을 복호화·복제하지 않는다. 원본 hash만 남고 자료가 삭제되면 품질은 unassessable이다. 필요한 source bundle은 기존 목적별 암호화 저장·기한·철회·삭제와 연결한다. 복원은 옛 서명/동의/authority를 되살리지 않는다.

최소 ID 전달은 workspace·purpose·revision·expiry에 바인딩된 서버 resolver로만 역참조한다. 고객 URL이나 임의 내부 ID를 따라가며 자료를 읽지 않는다. untrusted provider output은 서명된 정책/도구 승인으로 승격되지 않는다. 공개 projection은 내부 ID·입출력·개인정보·운영 정보를 포함하지 않는다.

수용 기준은 선형/분기/projection·확정 실패·부분 결과·unknown·순서 역전/늦은 이벤트·재시작/복원에서 원본 연결 재현, IDOR 차단, 현재 권한/동의/만료·철회/삭제·ETag 재검증이다. 실제 agent call을 추가해 증거의 빈 칸을 채우지 않는다.

## 4. RQ1 — Action-MR·상태 oracle·신뢰성 표면

**기존 ID: P2-02-ACTION-MR-ORACLE, P2-02-SURFACE-OFFLINE / POST139R-04.** 기본 off worker의 corpus와 budget을 확장한다.

평가 manifest에는 dataset/rubric/evaluator/oracle/mutator/fault 버전, 의미 보존 승인, seed, snapshot/초기 상태, reference time·timezone·locale, 읽기 계약·권한/예산을 고정한다. 상대 날짜 변환은 고정 기준 시각과 시간대에서만 동치로 취급한다. 먼저 docs/news의 소수 검증 가능한 변환부터 시작하고 첨부의 9개 변환·ε=.3을 한꺼번에 완료 조건으로 강제하지 않는다.

쌍의 판정값이 같다는 것만으로 성공 처리하지 않는다. 원본과 변형 모두 목표를 충족해야 하며 `false == false`는 양쪽 실패다. metamorphic relation 위반, 의미를 바꾼 잘못된 변환, oracle 오류, agent 실패, source 부족을 구분한다. 스키마/키워드 일치만으로 사실 정확도를 판정하지 않는다. oracle 범위를 넘는 업무 정확도는 독립 평가자·명시 rubric과 calibration이 없으면 미평가다. 심판 모델 사용 시에도 독립성/일치·오류/비용을 따로 검증한다.

반복은 별도 승인 평가 episode다. 실제 고객 입력이나 unknown 업무를 반복 전송하지 않는다. fixture의 429/timeout/부분 응답/schema drift/응답 유실을 seed 고정 fault adapter로 주입한다. 운영 제공자와 실제 고객 트래픽에 장애를 주입하지 않는다. 쓰기 상태 사전은 별도 승인된 격리 환경과 초기화 계약이 있어야 한다.

플랫폼의 최초 `R̂(contract, version, k, ε, λ)`는 이산 실험 셀의 관측치다. task별 k회 묶음 모두가 명시 목표를 통과했는지 보고하고 표본 수·반복/쌍 수·admitted/완료/실패/unknown·미평가·누락 coverage를 함께 보존한다. unknown을 성공으로 처리하거나 유리하게 분모에서 삭제하지 않는다. 미실행/취소는 계획·admission 분모를 함께 표시해 해석한다. 상관된 node/attempt를 독립 표본으로 취급하지 않는다. 분석계획 버전이 최소 표본·구간 추정/cluster 처리·도메인 구분을 고정한다.

ε는 해당 mutator 집합의 실험 강도이며 분야 공통 의미 거리가 아니다. k와 실험 격자가 이산이므로 초기에는 충분한 표본의 paired 차이·불확실성을 보고한다. 희소 셀을 보간한 편미분이나 RTT 변동만으로 장애 임박 확률/SLA를 주장하지 않는다. 예측은 시간 분할 holdout, calibration, false quarantine, lead time, host/공통 의존 상관과 실제 baseline 비교 이후 별도 승격한다.

평가는 추천 요청과 분리해 제한 자원으로 실행한다. Chat의 빠른 A2A 기본/명시 protocol·관련 에이전트 1개·최근 성공 우선 순서는 유지하며 연구용 LLM 심판·반복 호출을 추천 hot path에 추가하지 않는다. 증거 만료 시 날짜를 갱신해 최신 성공으로 꾸미지 않는다.

## 5. RQ2 — 관측 가능한 Dual-Clock·단계 감시

**기존 ID: P2-05-DUAL-CLOCK-SHADOW / POST139R-04.** 공통 lineage의 확장이다. 외부 agent의 숨은 사고 과정·내부 토큰·비공개 CoT를 수집하거나 존재하지 않는 `yield` 이벤트를 추정하지 않는다.

원시 event clock `k`는 컨트롤러가 실제 관찰한 authorized request·정책 차단·prepared/dispatched·응답/status·검증/checkpoint·취소/unknown metadata의 인과 순서를 기록한다. 위험 호출의 즉시 차단은 기존 결정론적 dispatch fence·kill switch·권한/스키마 검증을 재사용한다.

closed action clock `t`는 지원 profile의 확정 응답과 검증·영속 checkpoint가 완결된 경계에서만 진행한다. 확정 실패 응답과 성공은 다른 결과이며 unknown/부분/응답 유실은 성공 milestone이 아니다. MCP stateless와 향후 A2A task/session/streaming에 같은 call-return-yield 가정을 강요하지 않는다. 별도의 평가 revision/sequence는 t와 구분하며 모든 행동마다 LLM 심판을 동기 호출하지 않는다.

milestone specification은 입력·출처·허용 계약에서 작성한 목표/선행 관계·증거 조건·부분 결과 공개 정책을 고정한다. 평가용 reference/holdout 정답 경로를 planner/provider에 주지 않는다. 복수 합의가 참이라는 보장은 없으므로 생성 후보는 기존 deterministic compiler·cycle/schema/field/purpose 검사를 통과해야 한다.

첫 단계는 replay/shadow 관측이며 새 business call·중단 권한을 발급하지 않는다. 기존 whole-trajectory baseline과 paired 비교해 탐지 지연·오탐/누락·판정 오버헤드·unknown·실제 작업 결과를 기록한다. 반사실적 절감은 같은 궤적의 가상 중단 결과로 표시하고 실제 중단 실험과 합산하지 않는다.

## 6. 조기 종료·입장 라우팅·검토된 재계획

**기존 ID: P2-05-EARLY-STOP-PILOT, P2-04-SINGLE-ADMISSION, P2-05-REVIEWED-REPLAN / POST139R-07.** 공통 증거·shadow의 재현과 오탐 평가 이후 순차 승격한다.

명확한 정책/스키마 위반·권한 철회는 기존 차단기로 즉시 거부한다. 업무 정체·미래 실패 예측에 따른 조기 종료는 먼저 `would_stop`을 기록한다. 그 결과만으로 정상 run을 중단하지 않는다. 사전 고정한 오탐·성공 손실·오버헤드 기준을 통과한 좁은 profile만 명시 opt-in pilot으로 허용한다. 임계값/품질 개선 수치는 baseline 후 확정한다.

로컬 실행을 멈춰도 제공자 요청이 취소된 것은 아니다. 전송 후 결과 미확정이면 unknown/조정 필요로 남기고 자동 재전송·새 제공자·새 지급으로 바꾸지 않는다. 실제 cancel/status/idempotency는 지원 계약이 검증된 별도 장기 profile에서만 사용한다. checkpoint 재사용도 현재 권한·동일 pin·서명·절대 deadline과 기존 재개 가능 경계를 만족해야 한다.

예측 격리는 우선 다음 신규 admission에 적용한다. 최초 온라인 profile은 선택 제공자 1개·business call 최대1회·이후 replacement0회다. 기존 R-06 주→대체 profile과 상호 배타적이며 두 예산을 합치지 않는다. half-open probe는 별도 승인 평가 job으로 고객 업무를 복제하지 않는다. 공통 host/운영자 의존 관계는 실제 출처가 있는 범위만 사용한다.

Fixer는 알려진 순수·계약 보존 변환을 검토 가능한 proposal로 제시한다. semantic contract, schema/tool pin, 입력 공유, 금액·권한·서명·제공자·예산·사용자 의도를 조용히 수정하지 않는다. 변경은 새 draft/revision→기존 compiler 검증→변경점/입력 공유 검토→명시 시험/릴리스다. 진행 중 run은 원래 pin을 유지한다. 자동 팀 재조합·임의 세션 이식·중복 병렬 제공자 호출은 이 profile에 포함하지 않는다.

variable slimming은 승인된 projection/최소 참조로 구현한다. `should_expose_answer` 같은 provider 필드는 공개 승인으로 신뢰하지 않는다. 부분 결과는 허용된 output schema·목적/정제·현재 권한·표시 상태를 모두 통과한 별도 profile에서만 제공한다. 폴더 격리는 플랫폼이 제어하는 로컬 fixture에만 적용되며 원격 제공자를 sandbox하는 수단이 아니다. 향후 임의 코드 실행은 OS/container·네트워크/파일·자원 격리 계약이 별도로 필요하다.

## 7. RQ4 — SDK 위협모델 차이와 호환성

**기존 ID: P2-06-SDK-THREAT-DELTA / POST139R-05.** 기존 SDK2/BFF·PKCE·서버 capability·현재 권한/호출 한도를 기준으로 먼저 노출 artifact와 빠진 검사만 조사한다. 그 차이가 없으면 SDK를 다시 쓰지 않는다.

`#private`·bounded deepFreeze는 필요한 client robustness에 한정한다. 명세로 검증한 JSON 설정을 방어적으로 복사하고 깊이·노드/바이트 수·순환·prototype/getter 위험을 제한한다. 앱 전체 prototype/fetch/WeakMap 전역을 잠그거나 함수 `toString`을 침해 여부의 신뢰 근거로 사용하지 않는다. GC는 비결정적이고 private fields도 DevTools·XSS·확장 프로그램·네트워크 관찰에 대한 비밀 금고가 아니다.

긴 bearer·원본 제공자 secret은 ZIP/manifest/query/localStorage/browser에 넣지 않는다. 실제 권한은 HTTPS same-origin BFF 세션과 서버가 확인하는 app/release/graph/origin/audience/subject/scope/expiry/current policy에 둔다. CORS/Origin만으로 비브라우저 호출자의 인증을 대신하지 않는다. 호출 admission·한도 예약·소비는 기존 원자적 논리 실행 계량과 연결하고 재시도/동시성/철회/복원 우회 여부를 검증한다. 실제 금전의 spend limit·잔액/settlement 예약은 마지막 결제 profile의 별도 서버 정책이다. 유출된 제약 토큰도 허용 범위 안에서 오용될 수 있으므로 완전 차단을 약속하지 않는다.

제품 SDK 버전, gateway execution profile, MCP 날짜 revision, A2A protocol version, x402 version/scheme/network는 별도 호환 행렬로 고정한다. 현재 공개 SDK1.x 다운로드와 지원 MCP/A2A 동작을 일괄 최신으로 바꾸지 않는다. A2A inbox data/receipt profile과 일반 A2A 장기 업무 profile도 구분한다. 필요 변경은 새 SDK/profile·deprecation/rollback과 격리 conformance로 검증한다. 실제 Google/GitHub·HTTPS 배포 수용은 기존 비공개 파일럿에서 함께 수행한다.

## 8. RQ3 — 프로토콜·기여도·정산의 분리

**기존 ID: P2-10-PROTOCOL-SANDBOX → P2-10-SETTLEMENT-RECONCILIATION / POST139R-09.** 실제 결제는 가장 마지막 조건부 단계다. 기존 TEST_UNIT·모의 계약·원자적 ledger/event dedupe·누적 환불·unknown 대사를 재사용한다.

호환 행렬은 protocol/transport revision, scheme, asset/network/binding, facilitator·contract address/배포 revision, 구현 commit, 지원 국가/사업자·최소 정산 단위·finality 정의를 고정한다. `PAYMENT-REQUIRED`/`PAYMENT-SIGNATURE`/`PAYMENT-RESPONSE` 파싱, quote/mandate 권한, verify/commitment/claim/settle/finality, refund/payout는 각각 다른 검증 단계다. 헤더 지원이 에스크로·실결제·법적 정산 지원을 뜻하지 않는다.

execution/quality/business milestone, delivery accepted, payment authorized/committed/claimed/settled/finalized를 서로 승격하지 않는다. 하나의 논리 주문에 주/대체 attempt별 근거·upstream 청구·환불 가능성·정정 이력을 연결한다. 응답 유실 후 재결제하지 않고 원래 외부 event/거래 id로 조정한다. 재조정이 외부 요청을 반복하는 권한도 아니다.

70:30은 계약의 기준액·세금/수수료·원가/손실 부담·부분 성공·실제 기여자·분쟁·환불/지급·정수 반올림 책임이 고정돼야 한다. 마지막 성공 공급자에게 무조건 총액70%를 지급하지 않는다. 이미 비용이 발생한 실패 upstream의 청구를 플랫폼 코드로 없앨 수 없으며 보전/환불은 별도 계약과 원장 사실이다. x402 exact와 batch, MPP의 서로 다른 최소액·settlement/finality·refund 정책을 하나로 일반화하지 않는다. 시장 단가·sub-cent 호출·실시간 마진/차익거래는 실제 원가·계약·지원 수요 수집 후의 가설이다. 현재 Chat의 품질·관련성/최근 검증 우선 순서를 가격 최적화로 교체하지 않는다.

ERC-8004 등록·지갑·OIDC·ProviderClaims·계약 주체·실행/결제 권한은 서로 다른 증빙이다. 온체인 등록을 법인/품질/비악성 보증으로 보지 않는다. 개인정보·원문·철회 가능한 자료는 불변 체인에 저장하지 않는다. 공급자 계약·법률/세무·실제 sandbox 계정·사고 대응/rollback과 별도 거래 승인이 없으면 실제 금전·지급·광고는 off다.

## 9. 공개 offline receipt와 알림의 경계

**기존 ID: P2-03-PUBLIC-RECEIPT / POST139R-07.** 실제 제3자 이동식 검증 요구가 있을 때만 추가한다. SHA-256은 내용 무결성 hash이며 issuer 인증·업무 정답·법적 지급 증명이 아니다. 기존 수신처별 HMAC receipt는 공유키를 가진 신뢰 상대의 전달 수락 근거이며 공개 비대칭 서명이 아니다.

공개 검증이 필요하면 별도 profile의 canonical payload·공개키 서명·issuer/key ID·알고리즘/발급 범위·회전/신뢰키 배포·만료·철회 정책을 설계한다. 온라인 현재 상태를 확인하지 않은 offline 검증은 최신 철회 여부를 보장하지 않는다고 표시한다. 공개 payload에는 평가/보존 목적을 넘는 원문·내부 주체·수신처·비밀을 넣지 않는다. 공개 signing key/서비스가 이미 구현됐다고 간주하지 않는다.

기존 P2-07은 sanitized metadata와 별도 동의/검증된 목적 수신처를 유지한다. receipt는 수신일 뿐 업무 완료·독립 품질·정산 완료가 아니다. 연구 결과 알림도 목적별 허용 범위·만료·철회·서명 scope를 확인하며 영속 receiver를 다시 만들지 않는다. 브라우저 Push 시험 알림 클릭·별도 광고 동의는 그대로 유지하고 광고 발송은 비활성이다.

## 10. 자체 agent·투자/자금조달 연구

**기존 ID: P2-08-FIRST-PARTY-OUTCOMES / POST139R-08.** 기존 first-party docs 안내·지원/재사용 관측을 기반으로 실제 고객의 품질·수요·지원 부담을 확인한 소수 계약만 추가한다. OCR/웹 추출을 고마진 확정 분야로 선결정하지 않는다. 데이터 사용 권한·개인정보·출처·파일 악성 payload·SSRF·실제 오류율/원가를 평가한다. 자체 공급자도 같은 독립 평가·추천 규칙을 적용한다.

TIPS는 제품 개발 순서를 대체하는 일정/자금 약속이 아니다. [2026-188호 공식 수정 공고](https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1066440&cbIdx=310&parentSeq=1066440)와 [정부 공고 요약](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000119754)은 일반 최대8억원·딥테크 최대15억원·비R&D 최대3억원을 안내하지만, 서로 다른 대상과 선정 절차다. 요약상 비R&D에는 2025년까지 R&D 협약 완료 조건이 있어 신규 신청자가 자동으로8+3을 확보한다고 합산할 수 없다. 딥테크도 일반트랙 완료 등 별도 자격 심사가 필요하다.

이번 조사에서는 공식 상세 첨부의 전체 자격 조항을 읽지 못했다. 해외 매출/투자·지분·업력·후속 투자·중복지원·본인부담·예산/접수 시기 및 글로벌/스케일업의 최신 조건은 신청 당시 원문/전문기관 확인 대상으로 남긴다. 지원금 확보·최우수 졸업·후속 선정·특허 등록·논문 채택·매출/SLA 목표를 확정하지 않는다. 24/36개월은 funding scenario이며 인력·범위·표본과 실제 Gate 이후 기술 일정을 재산정한다. 특허/차별성/지원금 증빙 준비는 개발과 병행하되 기존 구현비와 연구 가설·실험비를 구분한다.

## 11. 반복·중복을 막는 실행 계약

1. 새 작업 전에 기존 canonical ID·profile·컴포넌트·산출물과 v1.39 hash 기반 검증을 찾는다. 첨부 RQ1~4는 분류 태그이며 별도 R/N 로드맵을 생성하지 않는다.
2. 하위 과제마다 기존 코드/검증 근거, 새로 바뀌는 계약, source 완료와 실제 수용, 진입/종료·중단 기준·외부 입력을 기록한다. 다른 연구가 같은 데이터가 필요하면 공통 lineage/projection을 참조한다.
3. 서로 다른 source revision·profile·목적 범위의 검증을 합쳐 현재 완료로 표시하지 않는다. 같은 산출물 identity에는 하나의 구현 owner·현재 상태를 둔다. 중복 과제는 alias 처리하고 새 독립 상태 머신/수신기/원장을 만들지 않는다.
4. 한 구현 묶음은 계약·core·API/관리자 desktop·권한/동의·철회/삭제/복원·SQLite/native parity·시큐어코딩·동적 API/브라우저·회귀·문서를 포함한다. DB 증분 시 기존 fixed SQL catalog/native rehearsal과 restore/retention을 함께 확장한다. 제안 객체는 아직 테이블 migration이 아니다.
5. 소스 고정 후 관련 회귀를 한 번 마감한다. 실패·새 source 변경·미해결 우려가 있을 때만 필요한 범위를 반복한다. 기존483건/63개 계약·22개 읽기 표본을 새 수로 합산하지 않는다. 문서만 바뀌면 문서/JSON/Canvas 정합성·소스 불변만 검사한다.
6. 외부 환경 부재는 해당 실제 수용만 대기시킨다. 승인된 fixture로 가능한 연구는 병행하되 실제 품질/거래/운영 수용을 생성하지 않는다. 모든 R&D·전체 PostgreSQL/HA를 소수 읽기 파일럿의 선행으로 강제하지 않는다.
7. 공개 Workspace·신뢰 API·실사용 자동 교체·실거래·광고는 문서 수정으로 활성화되지 않는다. 사용자 터미널 서버는 건드리지 않으며 실제 Python 변경이 있는 완성 묶음 끝에서만 재시작1회를 안내한다.

현재 권장 묶음은 **관리자/CI·환경 준비 병행 → typed 공통 증거 → MR/oracle·표면/단계 shadow 연구와 필요한 SDK 차이 병행 → 지정 환경 실제 품질/로그인·SDK/수신·복구 수용 → 검증 근거가 있는 제한 라우팅/조기 종료·검토 재계획 → 수요 기반 앱/장기 profile·자체 agent → 계약/프로토콜 sandbox·정산 대사**다. 정확한 기존9개 순서와 하위 과제는 구조화 원본 및 [현재 작업 순서](REMAINING_WORK_BATCHES.md)를 따른다.
