# 개선 확인 12차 대응 (2026-10-30)

대상: 사용자가 전달한 `개선 확인 12차` 남은 작업. **Explore 항목(느린 검색 꼬리, `translte`·`gihtub` 오타, `8004`, 검색 결과별 카테고리 값)은 다른 세션이 작업 중이라 제외**했다.

## 조치

| 항목 | 원인(운영에서 재현) | 조치 | 파일 |
|---|---|---|---|
| 24px 미만 타깃 76개 | 1) 상단 "Test" 탭 폭 22px(9개 화면 × 데스크톱·다크), 2) 커스텀 선택 상자 뒤에 숨긴 원본 `select`(`#xKind`·`#chatProtocol`·`#regKind`, 26×22·2×2)가 측정에 잡힘 | 헤더 탭 `min-width:24px`, 숨긴 원본 select는 `clip-path:inset(50%)`(표준 숨김 방식, 이미 `aria-hidden`·`tabindex=-1`) | `new/en/assets/pearl-live.css` |
| Chat PostgreSQL MCP 0건 | "find a PostgreSQL MCP server"의 기능어가 제품 이름 `postgresql`뿐. 제품 이름만으로는 DB 도구가 후보에 안 들어옴("PostgreSQL database"는 정상) | Chat 검색에서만, 기능어가 DB 제품 이름뿐이면 `database`를 덧붙임 | `agent_market/concierge/fast_chat.py` `retrieval_text` |
| Chat 메일(“email sending …”) | `sending`이 `send`와 맞지 않아 "before sending"을 설명에 쓴 검증 도구(`validate_email`)가 발송 도구보다 앞섬 | Chat 검색에서만 `<명사> sending` → `send <명사>`(동사 먼저. r1의 `email send`는 운영에서 send_feedback·delete_account가 나와 r2에서 고침) | 같은 곳 |
| llms.txt 경로가 OpenAPI에 없음 | `/api/agent/v1/entry`·`badge/{id}.svg`·`openapi.json`은 v1 계약에만 있고 주 `/openapi.json`에서 빠짐 | v1 계약의 정의를 주 OpenAPI에도 실음 | `agent_market/concierge/public_api_schema.py` |

Explore와 같이 쓰는 `search_terms`·`discovery.candidates`는 건드리지 않았다(보정은 Chat 검색 직전에만).

## 이미 해결돼 있던 것(운영 확인)
- 상세 API 한도 헤더: `/api/agents/{id}`, `/api/agent/v1/entry`, 배지 모두 `RateLimit`·`RateLimit-Policy`가 있음.
- Chat SPF/DKIM → DMARC Shark, 이미지 생성 → Suede AI Agent, 사이트 감시 → Shiftmoor.

## 손대지 않은 것
- **메일 1위 Axis Iliad:** 운영 카탈로그에 검증된 메일 발송 전용 서비스가 없어 발송 도구가 있는 묶음형이 남은 자리를 채운 것. 데이터 문제.
- 크롤러 본문(같은 HTML), 카테고리 페이지 150단어 미만: 콘텐츠 작업이라 이번에 하지 않음.

## 시험
- 새 시험 `tests/test_qa12_chat_gaps.py` 4개. Chat 2개는 수정 전 실패·수정 후 통과 확인.
- Chat·선택 관련 15개 파일 389개, OpenAPI 관련 16개 파일 371개 통과. 실행 전후 launchd PID 변화 없음.

## 배포 (2026-10-30)
- `qa12-frontend-20261030-r1`: 활성 `explore-a1-frontend-20261030-r9`에 3개 파일만 얹음. `verify_release` 통과, r9 대비 차이 3개 파일.
- `qa12-frontend-20261030-r2`: r1에 `fast_chat.py`(어순 수정)만 바꿔 얹음. 현재 활성 slot a=r2, b=r1(r9 대체).
- SQL 매니페스트는 **재생성하지 않고 r9 것을 유지**: 재생성하면 front.py가 f-string(`REPORT_COLUMNS`)으로 쓰는 보고서 조회 SQL 1개가 빠짐(빌더가 못 읽음). 바꾼 파일에는 SQL이 없고, 런타임은 `source_manifest` 해시를 검사하지 않음.
- 운영 확인: "find a PostgreSQL MCP server" → ai.duvera/gateway(`postgres__sql_read`), "email sending MCP server" → 발송 도구 3개, `/openapi.json`에 v1 entry·openapi·badge, 내장 브라우저 측정 24px 미만 타깃 Explore·Chat 0개("Test" 탭 24px).
- **주의:** Explore 세션이 다음 frontend 릴리스를 r9 기준으로 만들면 이 변경이 되돌아감. `qa12-frontend-20261030-r2` 기준으로 만들어야 함.

## CORS 절충안 (2026-10-30, 사용자 결정)
- `/chat`과 `/mcp`를 **모든 사이트**에 `Access-Control-Allow-Origin: *`로 연다. 쿠키·`Authorization`은 앱에 넘기지 않아 항상 익명 방문자로 처리된다. 프리플라이트 허용 헤더: content-type, accept, x-visitor-token, mcp-session-id, mcp-protocol-version, last-event-id(`authorization`·`idempotency-key`는 거절).
- `/mcp`에서 다른 사이트가 부를 수 있는 도구는 읽기 전용만: hello, chat, search, find_agents, whats_new, credit, search_workflows, workflow_details. call·adapt_rest(실행), subscribe·verify_contact(연락처), report(피드백)는 403(JSON-RPC -32001, 이유를 읽을 수 있게 CORS 헤더 포함). 배치 안에 섞어도 거절.
- 페이지 출처(Origin)별 분당 60회(인스턴스 단위), 넘으면 429 + `Retry-After`. 본문 256KB 초과는 413.
- `/a2a`, `/`(POST)와 허용 목록(`AGENT_BROWSER_ORIGINS`, 현재 없음)의 기존 동작은 그대로.
- 코드 `agent_market/concierge/agent_http.py`, 시험 `tests/test_public_cross_site_cors.py`(기존 차단 시험은 `/a2a`·`/`로 범위 조정), 설계 문서 `docs/AUTONOMOUS_AGENT_ADOPTION_DESIGN.md` 갱신.
- 시험: Origin을 쓰는 비브라우저 시험 72개 파일 1,586개 통과(22분).
- 허용 요청 연락: 접근 로그에 Origin이 남지 않아, 지금까지 허용을 요청한 사이트가 있는지 알 수 있는 기록은 없다.

### 배포
- `qa12-cors-frontend-20261030-r1`: 활성 `explore-a1-frontend-20261030-r11`(내 r2 기준으로 Explore 세션이 만든 것) + `agent_http.py`.
- `qa12-cors-frontend-20261030-r2`: + `fast_chat.py`. r11 이후 공용 검색 색인에서 `postgresql`이 `postgres`와 안 맞아 "PostgreSQL database"까지 0건이 되어, Chat 검색어에서 `postgresql` → `postgres`로 맞춤.
- 현재 활성 slot a=`qa12-cors-frontend-20261030-r2`, b=`qa12-cors-frontend-20261030-r1`(r11 대체).
- 운영 확인: 외부 Origin 프리플라이트 204·`*`, authorization 요청 403, `/chat`·`/mcp tools/list` 200·`*`, `/mcp call` 403(-32001), `/a2a` 403, 사이트 자체 Chat 화면 정상, "find a PostgreSQL MCP server" → ai.duvera/gateway.

## 남은 항목 처리 (2026-10-30 오후)
| 항목 | 결과 |
|---|---|
| 크롤러 본문(9개 화면 같은 HTML) | **이미 해결돼 있음.** 비활성 패널이 `<template>` 안에 있어, JS 없이 읽으면 화면마다 자기 H1(예: Explore "Find your next capable agent.", Chat "Start with the right agent.")과 다른 본문(667~1,204단어)이 나옴. `/`는 Accept에 따라 JSON/HTML을 나눠 주며 `text/html`을 보내는 크롤러는 HTML을 받음(`no-store`라 캐시 혼선 없음). |
| 카테고리 페이지 150단어 미만(20개 중 15개) | `agent_market/agent_access/pages.py`에 카테고리 정의 설명과 "How these listings are checked" 단락(Chat·Explore 안내 포함) 추가. 시험에서 20개 모두 150단어 이상. |
| Chat 사이트 감시+텔레그램 | `alert me on Telegram`의 "on" 뒤가 주제로 잘려 핵심어가 `alert`만 남아 날씨 경보 등이 나옴 → Chat 검색어에서 `send telegram message`로 바꿈(slack·discord·whatsapp·teams 동일). 복합 요청의 부분 검색은 `when/if …` 조건절을 뗌. 첫 부분만 맞는 결과가 나오면 빠진 부분을 1개 채워 부분마다 1개씩 보여 줌(`_cover_parts`). |
| 감사 스크립트 | `scripts/agent_discovery_audit.py`의 `mcp:origin-denial`을 새 CORS 정책(외부 출처의 `call`은 403)에 맞춤. `tests/test_agent_warning_resolution.py`가 `reports/agent-warnings-failures-2026-10-27/candidate-audit.json`을 다시 씀(시험 설계상). |

- 시험: Chat·CORS·발견 관련 20개 파일 490개 통과. 활성 릴리스 기반 스테이징에서 154개 통과.
- 배포: `qa12-rest-frontend-20261030-r1`→`r3`(감시 부분이 전체 문장 순위의 경쟁사 감시 도구로 가던 문제, 부분 검색 limit 1이 단독 질문과 다른 1위를 내던 문제를 r2·r3에서 고침). 이후 Explore 세션이 내 r3 기준으로 r14·r15를 만들어 **r15가 활성**(내 변경 5개 파일 모두 포함 확인).
- 운영 확인: "monitor my website and alert me on telegram when it goes down" → Shiftmoor(`check_page`) + FlowCastle(`send_message`), 카테고리 페이지 210~268단어.

## 재측정 (2026-10-30 16시, 활성 r15)
### UI/UX (`scripts/uiux_audit.js`, 40건)
| 지표 | 12차 | 지금 |
|---|---|---|
| LCP p75 / TTFB 중앙값 | 0.92 / 0.42초 | 0.42 / 0.34초 |
| CLS 최대 / INP 최대 | 0.055 / 104ms | 0.083 / 168ms(기준 이내) |
| axe serious·critical | 0 | 0 |
| 포커스 링 없음 | 0/983 | 0 |
| 24px 미만 타깃 | 76 | **0** |
| 가로 넘침 | 0 | 0 |
- 첫 실행에서 `/customer/sign-in`만 타깃 14·axe 4·포커스 83이 나왔는데, 감사 스크립트가 `<main>` 첫 버튼("Sign in with Google")을 눌러 **Google 로그인 페이지를 잰 것**이었다. 스크립트를 고쳐(다른 출처로 이동하면 원래 페이지를 다시 엶) 로그인 화면 4조건을 다시 재니 모두 0. 표의 "지금"은 이 값으로 바꾼 것.
- 포커스가 가려짐 1건씩: 모바일·320px의 learn, 320px의 agent-status(새 측정 항목, 12차 기준 없음).

### 에이전트 시나리오 (`scripts/agent_scenarios.py`, 76개)
- **PASS 69, WARN 7, FAIL 0** (12차 67/9). 그중 4건은 스크립트 판정 문제라 고침(`<template>` 내용까지 단어로 셈, OpenAPI 경로를 `badge`·`openapi`에서 잘라 비교, 상세 API 한도 헤더를 보지 않고 고정 문구, Origin 검사를 옛 정책으로 판정). 고친 판정으로 해당 묶음을 다시 돌리면 남은 WARN:
  - 도구 설명 지시문(`hello`) — 기존
  - 문서마다 카탈로그 수가 다름(일일 스냅샷과 실시간 수) — 기존
  - x402 501(검사 전용) — 정책
  - **다른 출처의 `/mcp` `call`이 200** — 아래.

### 발견: 엣지 워커가 다른 출처의 `call`을 원 서버 검사 없이 처리
- 원 서버(127.0.0.1:8400)는 다른 출처의 `call`을 403(-32001)으로 막는다. 운영 응답은 Cloudflare 엣지 워커(`DIRECT_RESULTS_ENABLED`)가 `call`을 가로채 서명된 "준비" 요청을 원 서버에 따로 보내므로 브라우저 Origin이 빠져 출처 검사를 거치지 않는다. 응답에 CORS 헤더가 없어 페이지가 결과를 읽을 수는 없지만, 실행 요청 자체는 처리될 수 있다.
- 수정: `cloudflare/edge-gateway/worker.mjs` — 다른 출처 Origin이 있으면 원 서버로 그대로 넘김(시험 추가, 88개 통과). **엣지 배포 완료(2026-10-30, 사용자 승인).** 기준 `a6cc584d…`(qa10 `worker-candidate.mjs`)와의 차이는 4줄. `edge/cloudflare-release.py`(qa10 도구 복사, 고정 해시·활성 버전·바인딩 검사)로 업로드·전환: 새 버전 `05579c7d-0e6f-4e22-8c7e-bec36a3d9ad5` 100%, 바인딩 보존·라우트 변경 없음. 기록 `edge/worker-candidate.json`·`cloudflare-upload.json`·`cloudflare-deploy.json`. 되돌리기: `.venv/bin/python reports/improvement-check-12-2026-10-30/edge/cloudflare-release.py rollback --apply`.
- 운영 확인: 다른 출처 `call` → 403(-32001, `*`), Origin 없는 에이전트 `call` → 정상 처리(인자 오류 -32602), 다른 출처 `search` → 200, 같은 사이트 → 200. 시나리오 x402·mcp·a2a·rest 묶음 PASS 37, WARN 2(`hello` 지시문, x402 501 정책), Origin 검사 PASS.

## 후속 정리(2026-10-30 오후)
- 커밋: 하지 않음. 저장소는 로컬로 관리하는 방침(2026-10-20 결정). 대신 활성 r16에 이번 파일 5개가 같은 해시로 들어 있음을 확인.
- `hello` 도구 설명: "Start here." → "Optional greeting." (`agent_market/concierge/mcp_contract.py`). 시나리오의 지시문 WARN 대상.
- `/` 응답: HTML·JSON 응답에도 `Vary: Accept` (`agent_market/concierge/front.py`, 마크다운은 원래 있음).
- 카탈로그 수 WARN: 숫자 차이가 아니라 판정 오류. `/llms.txt`와 상태 화면이 같은 숫자 네 개(전체·도달 가능·상태 기록·x402)를 보여 주는데, 판정이 서로 다른 지표 네 개를 불일치로 셈 → 문서끼리 같은 묶음인지 보도록 `scripts/agent_scenarios.py` 수정. 홈·Explore·About도 같은 숫자.
- 메일 1위: 코드 수정 없음. 메일 전용 mifactory-email은 최근 실행 검사가 `invalid_input`이라 후보에서 들어왔다 빠졌다 함(메일 발송은 읽기 전용이 아니라 시험 호출하지 않음). 전용 서비스가 없을 때는 발송 도구가 있는 묶음형이 `tool` 근거로 나오는 설계대로의 결과.
- 시험: `tests/test_qa12_chat_gaps.py`에 2개 추가(`/`의 세 표현 모두 `Vary: Accept`, 도구 설명에 지시문 없음). 스테이징 트리에서 관련 117개 통과.
- 릴리스: `qa12-frontend-20261030-vary-r1`(활성 `explore-a1-frontend-20261030-r16` + 위 두 파일, 바뀐 파일 2개만). 사용자 승인 후 배포(슬롯 a, r16 보존). 운영 확인: `/`의 HTML·마크다운·JSON 모두 `Vary: Accept`, `hello` 설명 "Optional greeting.", Chat·화면 정상. 시나리오 mcp 17/17 PASS(지시문 PASS), llm_fetcher 6/6 PASS(카탈로그 수 PASS).
