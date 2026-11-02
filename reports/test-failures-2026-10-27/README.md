# 남은 실패 테스트 정리 (2026-10-27)

전체 테스트 587개 파일을 브라우저 묶음(165개 파일, 순차)과 비브라우저 두 묶음으로 나눠 실행했다. 실패한 테스트는 하나씩 다시 실행해 실제 실패만 골랐다. 운영 서비스를 실제로 제어하는 테스트가 없음을 먼저 확인했고, 실행 중 서비스 PID 변화는 아래 "확인하지 못한 것" 외에는 다른 작업자의 정상 배포(`registration-hardening-20261027-r1`)였다.

## 제품 결함 수정 (운영 반영에 배포 필요)

| 영역 | 문제 | 수정 |
|---|---|---|
| 공개 Explore | `autonomous-agent-interop-20261027-r2` 이후 릴리스에서 검색 중앙 로딩 표시가 빠짐. 작업 트리의 퇴행한 `operating.js`가 패키징되었고 현재 운영에도 없다 | `extracted_html.txt`·`front.py` HTML에 로딩 두 줄을 복구하고 `new/build_en.py`로 `operating.js`만 재생성. 다른 작업자의 미완성 소스가 반영된 `sign-in-live.js`·`workspace-live.js`는 이전 빌드로 되돌림 |
| 공개 메타데이터 | `public_metadata.apply()`가 `agent:compact-mcp`·피드 링크를 스크립트 문자열 안의 첫 `</head>`에 넣어 내장 프로그램을 변형 | 스크립트를 복원하기 전에 삽입 |
| 관리자 전역 검색 | "워크플로" 검색이 "페이지를 찾을 수 없습니다"로 끝남(`#/customers/workflow-search` 별칭 누락) | `screens.js` 별칭에 `customers/workflow-search → W01` 추가 |
| 관리자 게이트웨이 | 화면 통합 후 `#/gateway`(실행 이력 W04)에서 시간대별 호출 표본 그래프가 사라짐 | W04 목록 화면에 직원용 `gatewayDetails` 영역 추가(뷰어·단건 상세에는 표시하지 않음) |
| 고객 작업공간 | guided 실행 확인창에 어댑터 입력 안내(논문 색인 검색·200자 제한)가 없음 | prepare 응답의 `destinations[].input_notice`를 "Provider notice" 행으로 표시(textContent) |
| 리허설 도구 | `rehearse_workflow_postgres`가 로케일 없이 postmaster를 띄워 macOS에서 실패 | 하위 환경에 `LC_ALL=C`, `LANG=C` 지정 |
| SQL 카탈로그 | 다른 작업자가 `dashboard.py` 관리자 에이전트 목록에 `r.description`을 추가했지만 카탈로그를 갱신하지 않음 | 카탈로그 재생성(문장 수 3,801 유지) |

## 의도된 변경에 맞춘 테스트 갱신

- 공개 서비스 첫 화면이 P07(탐색·생성 품질)로 바뀜 → P01 하위 메뉴를 열도록 수정.
- 노드 상태 문구 현지화: `unrecorded` → `실행 기록 없음`.
- A2A에서 다른 클라이언트가 같은 contextId를 보내면 -32602로 거부(하이재킹 방지).
- 등록 시 동의·분류가 필수가 됨. 사설 주소 오류 문구는 `PRIVATE_DESTINATION`.
- 사이트맵에 카테고리 랜딩 페이지가 포함됨.
- SWR 캐시 키 v6, "25 published templates", 카드 문구 "N agent steps", 푸터 항목이 링크로 바뀜, 쿠키 동의가 미리 저장된 경우 배너가 나오지 않음.
- 작업 알림 버튼이 답변 아래 한 번만 표시됨. 관리자의 알림 중지 시 변경 사유를 입력함.
- 레시피 불러오기가 끝난 뒤 입력하도록 대기. guided 작업공간 흐름(수동 생성 → 검토 → 저장 확인 → 실행 확인).
- 로그인 이동 주소에 같은 사이트의 `next` 경로가 붙음.
- 알림 테스트의 로컬 프록시가 운영과 같은 신뢰 Origin(`https://agentconcierge.biz`)으로 전달함. 새 Origin 검사 자체는 그대로 둠.

## 남은 항목

- **`test_workspace_runtime_support_browser::test_native_runtime_policy_needs_fresh_consent_and_records_one_real_logical_run`:** 실행 후에도 런타임 미터가 `operations=0`을 돌려줌. 화면 캐시 문제가 아니라 미터 집계 쪽 문제이며, 첫 전체 실행부터 있던 실패다. 다른 작업자가 작업 중인 영역(workspace advancement)이라 수정하지 않았다.
- **`test_log_retention_policy`·`test_workspace_platform_integration`:** 병렬 실행 중에만 실패하고 단독으로는 통과한다(다른 작업자가 파일을 동시에 수정하던 시점).
- **execution 워커 08:56 재시작 (원인 확인, 수정·배포 완료):**
  - **경위:**
    1. jobs 워커의 벡터 정리(`postgres_ann.cleanup`)가 쓰기 잠금을 잡은 채 embeddings 18만 행 전체를 비교했다. 병렬 테스트 부하 속에서 5초 `statement_timeout`을 넘겼다(PostgreSQL 로그 08:56:43).
    2. 그동안 execution 워커의 `workflows.run_due()`가 1초 `lock_timeout`에 걸려 `statement_failed`가 났다(08:56:41).
    3. 백그라운드 루프가 이 예외를 처리하지 않아 프로세스가 비정상 종료했고, launchd가 14초 뒤 재시작했다.
  - **기존 발생:** 같은 형태가 00:58, 07:37, 10월 25일에도 있었다.
  - **수정:**
    - 정리 대상은 쓰기 잠금 없이 읽기 전용으로 찾고, 대상이 있을 때만 같은 조건을 다시 확인하며 짧게 삭제한다.
    - execution 루프는 저장소의 일시 오류에서 그 회차만 건너뛰고 2초 뒤 다시 시도한다. `ServiceControl`·소유권 오류는 기존처럼 종료한다.
  - **테스트:** `tests/test_postgres_ann.py` 7건, `tests/test_postgres_reconnect.py`에 루프 회복 테스트 추가.

## 배포 (2026-10-27 12:47~12:49, 사용자 요청)

다른 작업자 릴리스에 이미 포함된 수정(공개 메타데이터, 관리자 별칭·게이트웨이 그래프, 리포트 페이지)은 제외했다. 아직 운영에 없던 것만 각 서비스의 현재 릴리스 위에 정확한 치환으로 적용했다.

| 패키지 | 기반 | 배포 대상 |
|---|---|---|
| `stability-fixes-frontend-20261027-r1` | `workspace-entry-20261027-r3` | frontend (무중단, 이전 슬롯 보존) |
| `stability-fixes-payment-20261027-r1` | `payment-hardening-20261027-r2` | admin (무중단), execution |
| `stability-fixes-jobs-20261027-r1` | `registration-hardening-20261027-r1` | jobs |

- **포함한 수정:** Explore 로딩 복구(HTML 두 곳·`operating.js`·매니페스트 해시), 작업공간 실행 확인창의 제공자 안내, 벡터 정리 잠금 단축, execution 루프 회복.
- **SQL 카탈로그:** 재생성했고 SQL 문 수는 그대로다. frontend 기반 릴리스는 고객 식별 관련 소스 해시가 갱신되지 않은 상태였는데, 재생성으로 함께 맞춰졌다(문장 이름 번호만 바뀌고 SQL은 같다).
- **배포 전:** 패키지마다 관련 테스트 41건 통과.
- **배포 후:** 공개 `operating.js`에 로딩 코드가 있고, 네 서비스 로그에 오류가 없으며, Chat이 정상 응답(추천 3건)한다.

## 검증

- 비브라우저: 두 묶음 합계 8,079건 통과. 실패 4건 중 2건은 수정했고 2건은 단독 실행 시 통과.
- 브라우저: 수정한 파일과 작업공간·관리자 관련 72개 파일을 순차 재실행해 463건 통과. 이후 세션 개인정보 테스트를 수정해 통과했고, 위의 런타임 미터 1건만 남았다.
- 공개 프론트엔드 콘텐츠 검사: 309개 파일, 위반 0. JS 구문 검사 통과.
