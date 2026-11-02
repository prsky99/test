# 워크스페이스 사용성 분석·설계·개선 (2026-10-21)

대상: 고객 워크스페이스(워크플로 작성 화면 `/customer/organizations/{ws}/flows`, 조직 화면). 운영 워크스페이스에서 10단계 워크플로를 실제로 불러와 데스크톱(1440px)·모바일(390px)로 측정하고, 코드와 테스트로 원인을 확인했습니다.

## 1. 내부 점검에서 찾은 문제

| # | 상황 | 문제 | 심각도 |
|---|---|---|---|
| U1 | 단계가 많아질 때 | 미리보기가 한 줄 가로 스크롤이라 10단계 중 데스크톱 5개, 모바일 2개만 보임. 스크롤 표시 없음 | 높음 |
| U2 | 저장한 워크플로를 연 뒤 AI로 새로 만들 때 | 이름 칸이 비어 있지 않아 **이전 워크플로 이름으로 새 워크플로가 저장**됨(운영에서 같은 이름 2개 발생) | 높음 |
| U3 | 단계 편집 | 단계마다 원시 JSON 입력칸 4개가 그대로 노출. 10단계면 모바일 높이 약 8,600px. 단계 제목이 모두 "Research search"로 같아 구분 불가 | 높음 |
| U4 | 실행 결과 | "step_5 · dispatched" 같은 내부 상태값 노출, 실행되지 않은 단계는 아예 안 보임, 실패 이유 안내 없음 | 중간 |
| U5 | 단계 순서 | 같은 깊이 단계가 문자열 순서(step_1 → step_10 → step_2)로 표시 | 중간 |
| U6 | 저장 목록 | 최근 6개만 카드로 보이고 나머지 32개는 드롭다운에서만 접근 | 중간 |
| U7 | 시험용 워크플로 정리 | 보관(비활성화) 기능이 화면에 없음. 서버 API는 고객 계정에서 **항상 403**(권한 확인이 트랜잭션 밖에서 실행되는 결함) | 중간 |
| U8 | 1단계 워크플로 검토 | 이유 없는 일반 오류(400). 서비스 정책은 2~10단계 | 낮음 |
| U9 | 실행 전 | 몇 개 에이전트를 부르는지, 얼마나 걸리는지 안내 없음 | 낮음 |
| U10 | AI 제안 | 지원하지 않는 요청(항공권 예약, 가격 비교, 이메일 발송)을 문서 검색으로 바꿔 제안 | 높음 |
| U11 | AI 제안 | 여러 대상(3개·10개 주제)을 요청해도 항상 2단계로 축소 | 중간 (이번 범위 밖) |
| D1~D3 | 실행 안정성 | 같은 에이전트 연속 호출 시 상대 제한, 상대 오류가 "결과 미확인"으로 표시, 오류 1회로 에이전트 제외 | 높음 |

## 2. SNS·커뮤니티 조사 (n8n·Make·Zapier 사용자)

Reddit은 조사 도구에서 접근이 차단되어, n8n 커뮤니티 포럼과 G2·Capterra 리뷰, 커뮤니티를 인용한 분석 글로 대신했습니다.

| 사용자 요구 | 근거 | 워크스페이스 적용 |
|---|---|---|
| 큰 워크플로를 읽기 쉽게(자동 배치) | n8n 사용자: 30개 이상 노드 정리에 15분~1시간 소요, 자동 배치 요청 | U1 미리보기 줄바꿈 그리드, 단계별 검색어 표시 |
| 복잡한 워크플로 디버깅·단계별 실행 기록 | G2 리뷰(디버깅 시간), 에이전트 관측성 자료(단계별 기록) | U4 단계별 상태 문구·실패 안내·미실행 단계 표시 |
| 실패 지점부터 다시 실행 | n8n "Add retry from node" 등 요청 다수, 현재는 처음부터 재실행 | 이번엔 "잠시 후 새 테스트" 안내. 실패 단계부터 재실행은 전체 그래프 동의 구조라 후속 과제 |
| JSON 대신 이해하기 쉬운 입력 | n8n 폼 JSON 정의 혼란 사례 | U3 "Search text" 칸 + 원시 데이터는 Advanced로 접음 |
| 이름·목적 관리(누가 무엇을 만들었는지) | n8n 포럼: 명명 규칙이 있어도 정리가 어려움 | U2 이름 결함 수정, U6 목록 더보기, U7 보관 |
| 크레딧 사용 예측·사전 경고 | 크레딧 과금 도구 불만(사전 경고 없음, 실패·재시도 과금) | 차감 직전 확인 창(완료), U9 실행 전 호출 수·예상 시간 |

## 3. 설계와 구현

| # | 설계 | 구현 위치 |
|---|---|---|
| U1 | 미리보기를 `auto-fill` 그리드로 줄바꿈, 단계마다 검색어 또는 입력 출처 표시, "10 of 10 steps · up to 10 agent calls per test" | `customer_typed_authoring_view.py`, `workspace-pearl.css` |
| U2 | AI 생성 시 이름 칸이 비었거나 열어 둔 워크플로 이름과 같으면 목표 문장으로 새 이름 | 같은 파일 |
| U3 | 단계 제목 "Step 3 · Research search · Docker documentation", "Search text" 칸이 정확한 입력(JSON)의 `query`를 함께 수정, 이전 단계 결과를 쓰는 단계는 읽기 전용으로 출처 표시, 원시 JSON은 "Advanced: exact step data"로 접음 | 같은 파일 |
| U4 | 실행 요약(전체 완료/실패/미확인/60초 초과) + 단계별 "Completed / Failed / Skipped / Outcome not confirmed / Not reached", 실패·미확인은 색으로 구분(다크 테마 포함) | 같은 파일, CSS |
| U5 | 표시만 의존 깊이 → 숫자 순 정렬(서버 정규 순서는 저장 서명과 연결돼 변경하지 않음) | 같은 파일 |
| U6 | "Show 12 more of N remaining" 버튼, 검색 시 초기화 | 같은 파일 |
| U7 | "Retire selected workflow" + 확인 창(Keep / Retire). 서버: 편집자 권한 확인을 보관 트랜잭션 안으로 이동 | 같은 파일, `workspace_typed_flows.py`, `customer_authoring.py` |
| U8 | 2단계 미만이면 요청 없이 "A workflow needs two to ten steps" 안내, 2단계에서 단계 삭제 버튼 비활성 | 같은 파일 |
| U9 | 테스트 영역에 "This test calls up to N agents in order and usually finishes within about S seconds" | 같은 파일 |
| U10 | 각 절의 동작 부분만 보고 예약·구매·결제, 메시지 발송·게시, 가격 비교를 "지원 안 함"으로 안내(주제어는 제외: "결제 사기 논문"은 허용) | `workspace_goal_coverage.py` |
| D1 | 같은 에이전트 최소 1.25초 간격(프로세스 전체), 중지·제한 시간 준수 | `workspace_typed_flows.py` |
| D2 | 결과 기록 시점에는 에이전트 상태 재검증 생략(다음 호출 전 검증은 유지) → 상대 오류는 "실패" | 같은 파일 |
| D3 | 유효한 성공 직후의 일시적 오류 1회는 호출 가능 유지, 2회 연속·확정 오류는 제외 | `capability_registry.py` (+ SQL 카탈로그) |

## 4. 검증

- 브라우저·단위 테스트: 워크스페이스 관련 99건, 레지스트리·실행·추천 296건 통과.
- 추가 테스트: 10단계 미리보기 전부 표시·단계 제목·결과 요약·단계 상태·보관(취소/확인), 호출 간격, 일시 오류 허용 범위, AI 범위 판정(오탐 포함).
- 공개 콘텐츠 점검 238개 파일 위반 0, 변경 화면 한글 0자, 스크립트 문법 통과.
- 서버 재시작 후 반영(화면 CSS는 즉시 반영).

## 5. 남은 과제

- U11 AI 여러 대상 분해(예: 10개 주제 → 10단계): 제안 모델 프롬프트·검증 보강 필요.
- 실패 단계부터 다시 실행: 전체 그래프 동의·티켓 구조 변경이 필요.
- 실행 중 단계별 실시간 진행 표시: 실행이 하나의 요청으로 끝나는 구조라 비동기 상태 조회가 필요.
- 저장 목록 카드에 마지막 테스트 결과·날짜 표시.
- 동시 작업: 11:22 이후 다른 작업자가 워크스페이스 관리 파일을 수정 중이라 SQL 카탈로그 재생성(문장 3,518 → 3,639)은 하지 않았음.

## 출처

- [Auto-Layout Nodes - PLEASE! (n8n Community)](https://community.n8n.io/t/auto-layout-nodes-please-got-created/44603)
- [n8n reviews (G2)](https://g2.com/products/n8n/reviews_and_filters?page=5)
- [n8n.io Reviews (Capterra)](https://www.capterra.com/p/198028/n8n-io/reviews/)
- [The Hidden Costs of n8n (metaflow.life)](https://metaflow.life/blog/The%20Hidden%20Costs%20of%20n8n%202353e8e596fd801f8e4cccb745d13817.html)
- [Add retry from node (n8n Community)](https://community.n8n.io/t/add-retry-from-node/5812)
- [Retry failed execution with currently saved workflow (n8n Community)](https://community.n8n.io/t/retry-failed-execution-with-currently-saved-workflow/143721)
- [Automatic Retry of Workflows (n8n Community)](https://community.n8n.io/t/automatic-retry-of-workflows/5310)
- [Form fields in json format not coherent (n8n Community)](https://community.n8n.io/t/form-fields-in-json-format-not-coherent/270883)
- [Agent observability (Make)](https://www.make.com/en/how-to-guides/agent-observability)
- [Monitoring your agents (Lindy docs)](https://docs.lindy.ai/testing/monitoring-your-agents.md)
- [Who can actually afford AI tools now? (UX Collective)](https://uxdesign.cc/who-can-actually-afford-ai-tools-now-d72041945c26)
- [Make.com alternatives after the credits switch (toolworthy)](https://www.toolworthy.ai/blog/make-com-alternatives)
- [Figma Make AI credit limits (Figma Forum)](https://forum.figma.com/share-your-feedback-26/figma-make-ai-credit-limits-not-feasible-51713/index7.html)

---

## 6. 남은 과제 진행 (2026-10-21 오후)

| 과제 | 결과 |
|---|---|
| AI 여러 주제 분해(U11) | 목표에 주제가 명시적으로 나열되면("for 3 topics: A, B and C", "A docs, then B docs", "documentation for A, B and C") 주제마다 검색 단계 1개(최대 10개, 모델이 고른 에이전트 사용). "then cross-check ..."처럼 후속 동작이면 모델 계획 유지 — `workspace_goal_coverage.topics`, `workspace_app_factory.py` |
| 실행 중 진행 표시 | 실행 요청이 열려 있는 동안 실행 기록을 1초마다 읽어 단계별 "In progress / Waiting / Completed"와 진행 중 진주(은은한 빛, 동작 줄이기 설정 시 정지) 표시 |
| 실패 후 다시 테스트 | 실패·시작 안 됨이면 "Test again" 버튼 → 새 테스트 입력 확인까지 한 번에(동의는 다시 필요) |
| 목록 카드 정보 | 마지막 수정 시각("Updated Oct 21, 01:08 PM") — 목록 API에 `updated` 추가 |
| 실패 단계부터 다시 실행 | **보류.** 실행은 워크플로 전체 입력에 대한 1회 동의·티켓·단계별 증거(시도 기록) 구조라, 이전 결과를 재사용하면 동의 범위와 증거 무결성이 달라짐. 별도 설계 결정 필요 |

## 7. 진주 목걸이 디자인

컨셉: 에이전트 = 진주, 워크플로(에이전트 연결) = 진주를 꿴 실. 어떤 진주도 혼자 떨어져 보이지 않게 함.

| 위치 | 적용 |
|---|---|
| 워크플로 미리보기 | 모든 진주를 금색 실 하나로 연결. 같은 줄은 살짝 처지는 곡선, 줄이 바뀌면 줄 사이 틈을 따라 돌아 다음 줄 첫 진주로 이어짐(설명 글자를 가로지르지 않음). 양 끝 잠금 고리. 진주마다 단계 번호. 모바일은 세로 한 줄 |
| 실행 결과 | 상단에 결과 목걸이(단계별 진주, 테두리 색: 완료 청록·실패 적색·미확인 호박색·건너뜀/미실행 흐림·진행 중 금색 빛). 아래 단계 목록도 왼쪽 세로 실에 진주가 매달린 형태 |
| 진행 단계(Design → Download) | 4개 진주를 한 줄 실로 연결 |
| 저장 목록 카드 | 작은 진주 3알 줄 |

- 라이트·다크 테마, 모바일(390px) 가로 넘침 없음, 동작 줄이기 설정 준수, 장식 그림은 보조기기에서 숨김.
- 공개 사이트 홈의 `.necklace-thread` 스타일과 이름이 겹쳐 실이 타원으로 그려지던 문제를 `flow-thread`로 분리해 해결.
- 스크린샷: `screenshots/` (격리된 테스트 환경, 합성 데이터).

검증: 워크스페이스 화면 테스트 28건, 서버·실행·제안 테스트 234건 통과, 공개 콘텐츠 점검 위반 0.

## 8. 운영 확인 (13:25 재시작 후)

- 진주 목걸이 미리보기: 10단계 모두 영역 안에 표시, 실 연결, "10 of 10 steps", 단계 제목에 검색어.
- **10단계 실제 실행 성공(약 13초)**: 오전에는 6번째 호출에서 상대 제한으로 실패 → 호출 간격 조절 후 10개 모두 완료. 실행 중 진주가 1초마다 진행 상태로 바뀜.
- AI 다중 주제 분해: "documentation for 3 topics: Docker, Kubernetes and Terraform" → 3단계, 이름은 목표 문장에서 생성.
- 지원 안 함 안내: "Book a flight ..." → "Booking, purchasing or payments", 크레딧 미사용.
- 세션 만료 시 작업 화면 → 로그인 화면(303, `result=expired`)으로 이동(이전: 원시 JSON 표시).
- 운영 확인 중 추가 수정(다음 재시작 후 반영): 목록 카드 날짜가 브라우저 언어(한국어)로 표시 → 영어 형식 고정, 실행 시작 직후 이전 결과가 1초간 보이던 현상 → 시작 즉시 전 단계 "Waiting".
- 참고: 서버 실행 순서는 저장 정의의 정규 순서(문자열 정렬)를 따라 step_10이 2번째로 실행됨. 화면 표시는 숫자 순이며 결과에는 영향 없음.
