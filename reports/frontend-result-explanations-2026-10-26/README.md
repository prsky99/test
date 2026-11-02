# Frontend result explanations — 2026-10-26

## Result and review scope

사용자가 반영한 `explore-protocol-scope-20261026-r1`은 frontend private readiness와 실제 Chrome Computer Use에서 확인했다. [읽기 확인 결과](previous-deployment.json)는 `ready=true`, 예상 release 일치다. 최초 HTML은 lazy shell이므로 shell에 탐색 DOM이 없다는 사실을 배포 실패로 판단하지 않았다.

실제 로그인된 Workspace의 Overview, Create with AI, My workflows, 저장 워크플로우 상세, Templates, Plan & credits 및 이력을 조사했다. 공개 Home, Explore, Chat, Workflows, Test, Agent Status도 실제 브라우저에서 확인했다. Chat에서 읽기 전용 날씨 추천 검색 1회만 수행했다. 실제 계정의 가입·크레딧·워크플로우·실행 권한을 변경하거나 모델/외부 에이전트를 실행하거나 알림을 발송하지 않았다.

이번 범위는 **내부 선택·집계·상태 규칙을 사용자에게 설명하고, 실제 표기 불일치를 수정하는 작업**이다. 알고리즘·약관·크레딧 정책·실행 권한·폴백 승인을 새로 설계하는 작업으로 확장하지 않았다.

## Changes

- **Explore:** 기존 범위 배지에 더해 Pearl에서 실제로 보이는 기본 프로토콜 버튼도 `Any`에서 `A2A + MCP`로 변경했다. 명시적 x402 선택과 기존 범위 안내를 유지한다.
- **Home:** 전체 카탈로그에는 A2A/MCP/x402와 이용 불가 항목이 포함되며, 기본 Explore와 안전 필터 때문에 수가 달라질 수 있음을 설명한다. 현재 집계와 하루 단위 검색용 snapshot을 구분한다. 상태를 새로 고쳐도 daily snapshot의 원래 기록 시각을 덮어쓰지 않는다. 미확인 지표를 임의로 채우지 않는다.
- **Agent Status:** connection reachability와 실제 task check의 차이를 유지하고, Unknown에 retired/unclassified 상태가 포함됨을 설명한다. 기존 API 집계 값은 바꾸지 않는다.
- **Chat:** `Find one agent`/`Selecting one agent`를 최대 3개 추천과 맞는 문구로 수정했다. 작업 적합성을 먼저 확인하고, 프로토콜 내 성공 검증 시각 → 활동 → 품질 순서임을 안내한다. 유효한 최근 실행 증거 시각을 보여 주어 `No published report`와 실행 검증을 구분한다. 워크플로우 추천은 작업 범위·불필요한 단계·갱신 시각 기준을 안내한다. 금액·결제·방문자 식별자·원시 JSON을 추가하지 않았다.
- **Public Workflows:** 로딩 중에 `No published workflows`가 표시되던 문제를 수정하고, 유효한 선택이 준비되기 전 Run/Download를 비활성화한다. 브라우저에 보관된 선택 복원인지 기본 선택인지 설명한다. 전체 workflow steps와 agent steps를 구분한다.
- **Workspace library / Templates:** 같은 에이전트를 두 번 쓰는 것을 `2 agents`로 잘못 표현하지 않고 `2 agent steps`로 표시한다. Custom workflows와 Saved template workflows가 별도 그룹임을 설명한다. 템플릿 검색/카테고리 일치 수와 전체 공개 수를 구분하고 검색 대상도 안내한다.
- **Workspace AI:** 생성 버튼의 역할·가입 상태·연결 준비·작업 입력·입력 공유 동의·요청 처리 중 상태를 기존 권한 값에 맞춰 설명한다. `Refresh availability` 동작을 명확히 한다. 모델/런타임 이름이나 구성을 공개하지 않는다.
- **Credits / navigation:** 신규 가입 지급분과 기존 계정 잔액을 구분하고, 계정 단위 잔액이 지급·조정·사용 이력으로 구성됨을 안내한다. 최근 100건·최신순·UTC 기준을 명시한다. 천 단위 구분과 사람이 읽는 상태명을 적용했다. 크레딧 화면에서 Templates/워크플로우로 돌아갈 때 검증된 기존 workspace 문맥을 유지한다.

Test의 예제 선택·입력 및 결과 출처, Workspace의 실행/입력 공유/폴백 동의 안내는 기존 의미를 유지했다. 정적 About/Learn/등록 및 푸터의 설명은 이번 결과 선택 규칙 수정 대상이 아니다.

## Regression discovered and resolved

기존 검색 회귀에서 도구 설명의 대문자 `Weather`가 소문자 정규식 조건과 일치하지 않는 결함을 확인했다. 도구 목적 설명을 기존 다른 입력과 같은 소문자로 정규화했다. 이 수정 후 드러난 `over the x402` / `with x402` 표현도 A2A 직접 실행으로 잘못 간주하지 않도록 기존 타 프로토콜 실행 판별식을 보완했다. 명시 x402의 실제 기능 매칭은 유지하고, 기본 검색에서 x402를 제외하는 정책은 유지한다. `test_public_ux_closeout.py`의 두 운송 프로토콜 회귀가 통과한다.

초기 신규 UI 검사의 잘못된 탐색 selector와 중복 snapshot fixture를 수정했다. Busy 상태 검사는 실제 UI와 같은 `sync()` 경로를 사용하도록 보완했다. 실패를 숨기거나 기대 결과를 완화하지 않았다.

## Validation

- [Public browser/UI/security](public-browser.log): **96 passed**. published/embedded 탐색 범위, 375px 레이아웃, 메타데이터, CSP/XSS, Chat 증거, daily timestamp 보존, 지연된 템플릿 로딩과 버튼 상태를 검증했다.
- [Workspace browser](workspace-browser.log): **20 passed**. 가상 고객으로 역할·입력 공유 동의·처리 중 상태·검색 범위·단계 수·크레딧 가입/종료·workspace 링크 문맥을 확인했다. 기존 320–760px 및 light/dark 메뉴 회귀를 포함한다.
- [API / authorization / recommendation / metadata](api-security.log): **283 passed**. 격리 DB와 합성 제공자 응답을 사용했다.
- [SQL catalog boundary](catalog-regressions.log): **20 passed**.
- 위 네 그룹 **419 passed, failed/skip 0**. FastAPI TestClient의 httpx deprecation warning이 남으며 기능 실패는 아니다.
- [공개 콘텐츠 검사](content.log): **292 files, violations 0**. Python/JavaScript 구문, embedded/extracted HTML 동일성, Pearl 43 HTML 빌드 통과.
- [PostgreSQL SQL catalog](sql-catalog-check.log): **3,802 statements / 232 tables**, 현재 소스와 일치. 소스 fingerprint를 갱신했으며 새 SQL/스키마는 없다. DB 이전이나 전체 DB 리허설은 필요하지 않다.
- [변경 모듈 Bandit](bandit.json): 1건 B608. `customer_typed_authoring_view.py:15`의 HTML/JavaScript 전체 문자열을 SQL로 분류한 기존 패턴이다. 해당 `page_for`는 HTML 응답만 생성하고 SQL 실행을 하지 않으며 이번 변경은 단계 수 문구뿐이다. 무시 주석을 추가하지 않았고 원본 결과를 보존했다. 나머지 선택한 모듈에는 발견 사항이 없다. 이 결과를 전체 플랫폼 무취약 보장으로 해석하지 않는다.

운영용 `.venv`에 pytest/Playwright가 없어, 이전 검증 릴리스에 있던 테스트 도구만 `/private/tmp/ac-front-ux-test-tools-20261026`에서 재사용했다. 현재 운영 Python 및 프로젝트 패키지를 사용했고 운영 의존성은 수정하지 않았다. 임시 테스트 도구는 배포 패키지에 포함하지 않는다.

## Rollout

**`frontend-result-explanations-20261026-r1`** 패키지를 생성하고 해시를 검증했다. [release.json](release.json)에 결과를 기록한다. 이번 새 수정본의 실제 로그인 화면 반영은 운영 배포 후 확인할 수 있다. 현재까지의 실제 Computer Use는 문제 재현/원인 확인이고, 수정 후 검증은 격리 Chromium/API 검사다.

프로젝트 서버는 재시작·교체하지 않았다. frontend만 반영하면 되며 admin/jobs/execution 및 DB 변경은 필요 없다.

```bash
cd <저장소>
./agentcon deploy frontend frontend-result-explanations-20261026-r1
```

배포 후 공개 화면과 로그인된 Workspace 탭을 전체 새로고침한다.

## Operator deployment verification

사용자 배포 후 `frontend-result-explanations-20261026-r1`, `ready=true`, 패키지 해시 일치를 확인했다. [운영 읽기 점검](deployed-smoke.json)은 **9건 통과 / 실패 0건**이다. 크레딧 페이지의 새 설명과 inline workspace 탐색 코드, 비인증 private workflow 접근의 303 로그인 안내도 확인했다.

실제 Chrome 전체 새로고침 후 Home의 현재/일일 집계 구분과 원래 snapshot 시각, Explore의 A2A + MCP 버튼/범위, Workflows의 브라우저 선택 복원 설명과 전체/에이전트 단계 수, Chat의 Find matches, Agent Status의 Unknown 설명을 확인했다. 실제 워크플로우 실행·저장·권한 발급·크레딧 변경은 수행하지 않았다.

추가 Chat 검색 및 로그인된 Workspace 재점검 중 Computer Use가 Chrome의 사용자 변경을 두 번 알렸다. 사용자 조작과 충돌하지 않도록 추가 탐색을 중단했다. 따라서 이번 배포 후 **로그인된 Workspace 화면 전체의 재확인은 미완료**이며, 배포 콘텐츠/권한 점검과 앞선 격리 브라우저 검증을 구분한다. 최초 HTTP 점검에서 가정한 두 standalone workspace asset 경로는 실제 제공 경로가 아니었다. 소스가 inline으로 제공됨을 확인하고 올바른 전달 방식으로 검사했으며 최초 기록도 보존했다.
