# 자율형 에이전트의 현재 방문·탐색·재방문 경험

확인일: **2026-10-25, Asia/Seoul**. 공개 운영 서비스의 API, 별도 검사용 대화 세션, 새 비로그인 Chromium에서 확인했다. 서비스 소스·배포·권한은 변경하지 않았다.

**결론:** 방문한 에이전트에게 목적별 이용 방법을 안내하고, 개별 에이전트와 워크플로우를 검색·추천하고, 이전 문맥을 이어가는 경로는 현재 동작한다. 다만 **외부 홍보·유입 성과는 입증하지 못했고, 워크플로우의 가장 적합한 1순위 선정과 Chat 원문 설명의 금액 관련 표현에는 개선점이 있다.**

자율형 에이전트는 사람용 화면 메뉴를 반드시 클릭하는 것이 아니라, JSON Entry·LLM 안내·MCP/A2A를 읽고 다음 API를 선택한다. 사이트 방문만으로 외부 업무가 실행되거나 연락처 등록·광고 동의가 생성되는 구조는 아니다. 검색·추천과 실제 제공자 실행 성공을 구분한다.

## 1. 알려지고 홍보되고 있는가

발견 가능하도록 준비된 것은 확인했다. 공개 홈페이지의 Link 헤더, `robots.txt`, sitemap, `llms.txt`, Agent Card, MCP manifest가 응답한다. robots는 Googlebot·OAI-SearchBot·GPTBot·PerplexityBot·ClaudeBot 등의 공개 문서 접근을 허용하며 고객·실행·알림 경로를 구분한다. Agent Card는 에이전트 검색, 워크플로우 검색, 기억·업데이트, 연락 기능을 설명한다.

하지만 **접근 허용과 실제 홍보 성과는 다르다.** 이번 웹 검색의 `site:agentconcierge.biz`, `"agentconcierge.biz" AI agent workflow`는 결과가 없었다. 이는 제한된 검색 도구에서 결과를 받지 못했다는 의미이고, 모든 검색엔진 미등록·방문자 0명을 증명하지 않는다. Search Console, 외부 Registry의 실제 게시/승인, 출처별 신규 에이전트·재방문·목적 달성 지표는 이번에 조회하지 않아 홍보 효과를 확정할 수 없다.

본 검사용 User-Agent와 내부 검사는 외부 자연 유입으로 계산하면 안 된다. 공식 디렉터리 게시·검색 도구 색인 확인·동의 기반 업데이트가 후속 유입 관리 대상이다. 광고 전달은 현재 안내상 비활성이다.

## 2. 첫 접속에서 무엇을 해야 하는지 아는가

**동작 확인.** `GET /api/agent/v1/entry`와 `GET /.well-known/agent-entry.json`이 목적별 동작 5개를 반환한다.

1. 관련 에이전트 1개 추천: `POST /chat`.
2. 여러 후보 탐색: `GET /api/explore?q=...`.
3. 워크플로우 템플릿 찾기: `GET /api/workflows/templates?q=...`.
4. 이전 작업 이어가기: `GET /api/agent/v1/resume`.
5. 동의된 작업 업데이트 확인: `GET /api/task-updates`.

JSON 홈에도 같은 목적별 동작, REST 요청 형식, MCP/A2A 주소, 세션 유지 방법이 나온다. 첫 `hello`는 작업을 설명하거나 워크플로우를 요청하라고 답한다. MCP manifest와 실제 tools/list에는 `search_workflows`, `workflow_details`를 포함한 **13개 도구**가 있다.

이 경로는 현재 구현된 안내다. 별도 고도화 설계에 제안된 모든 prepare/run/task/passport 기능이 구현됐다는 뜻은 아니다.

## 3. 다시 방문할 때 빠르게 목적을 이어갈 수 있는가

**현재 대화/선택의 재개는 동작한다.** 검사 세션에서 워크플로우를 추천받고 `details 1`, 세션 헤더를 사용한 resume를 호출했을 때 같은 템플릿과 definition hash를 받았다. `changed=false`로 실제 변경이 없다는 정보와 다음 동작 `what's new`가 반환됐다. 세션 없는 resume는 예상대로 **401**이었다.

에이전트는 처음 받은 세션 정보를 안전하게 보관하고 `X-Visitor-Token` 전송에 사용해야 한다. 답변 문장에서는 검사 토큰이 노출되지 않았다. 재방문 홈의 인사 문장 자체는 첫 방문과 같지만 목적별 동작을 다시 제공한다.

한계는 **최근 문맥을 이어가는 기능**이라는 점이다. 여러 장기 작업을 독립적으로 저장·예약·완료하는 Task Passport나 무기한 기억을 검증한 것이 아니다. 세션을 잃거나 만료되면 기존 문맥 복원이 제한된다. 웹훅/A2A/브라우저 알림은 별도 목적 동의·주소 인증이 필요하며 이번에는 신청/전송하지 않았다.

## 4. Explore에서 목적에 맞게 검색되는가

운영 API의 네 질의에서 관련 후보를 확인했다.

- `weather forecast`: 날씨 예보 관련 API.
- `research papers`: 학술 논문 검색 관련 에이전트/API.
- `npm package`: 패키지 정보·검색 관련 API.
- `PDF invoice extraction to JSON`: 문서/PDF/송장 처리 관련 후보.

프로토콜·카테고리·검증 필터를 제공한다. **검색 결과는 후보 목록이며 지금 실제 작업이 성공한다는 증거는 아니다.** 네 질의 표본으로 전체 카탈로그의 정확도·재현율을 보장할 수 없다. 검증·최근 활동·품질 등급도 업무별 결과 품질을 직접 입증하지 않는다.

## 5. Chat이 자연어로 정확한 에이전트를 안내하는가

다음 세 표본은 요청 능력과 관련된 단일 에이전트 및 플랫폼 Gateway 연결 주소를 반환했다. 측정한 세 추천 응답은 약 **1.0~1.9초**였으며 부하/SLA 측정치는 아니다.

- 도쿄 예보를 제공하는 MCP 에이전트 → **Smarter Weather [MCP]**, A등급.
- 논문 검색, Any Protocol → **Paper Finder [MCP]**, A등급.
- PDF 송장의 JSON 추출에 필요한 에이전트, Any Protocol → **com.mart402/docs [MCP]**. 설명에 PDF parse/OCR/invoice checks가 있다. 실제 PDF 입력·JSON 출력 스키마 충족은 실행하지 않아 검증하지 않았다.

기본 프로토콜도 확인했다. 새 질문에서 논문 검색을 요청하고 프로토콜을 생략하면 **academic-research-intel [A2A]**, 명시적 Any이면 **Paper Finder [MCP]**를 받았다. 요청 범위가 다르므로 두 결과의 등급 차이를 곧바로 순위 오류로 해석하지 않는다.

**추가 발견:** 기본 A2A 결과의 Capability 문장에 `via x402 micropayments`라는 제공자 원문이 표시됐다. MCP/A2A/x402 같은 기계 프로토콜 정보는 유지하되, Chat 화면과 답변에서 결제·과금 표현을 숨기라는 현재 제품 정책에 맞춰 이 원문 표현을 정리할 필요가 있다. 이는 이번 확인에서 수정하지 않았다.

## 6. Workflows에서 템플릿 검색·추천이 되는가

**이전의 단순 문자열 검색 공백은 해결되어 있다.** 현재 API와 실제 비로그인 Chromium 화면에서 공통 검색을 확인했다.

- `papers`: 관련 템플릿 **13개**.
- `나라 지표`: API에서 관련 템플릿 **7개**.
- `Find a workflow that researches technology news and papers`: API와 화면에서 **5개**.
- 이메일 송장을 Slack으로 전송하는 미지원 워크플로우: API와 화면에서 **0개**.

같은 자연어 요청을 Chat과 MCP `search_workflows`로 보냈을 때 모두 `find_workflow`/`matched`와 템플릿 1개로 연결됐다. 템플릿 상세 API도 현재 정의와 기록된 준비 상태를 반환했다. 화면 검색은 실제 API 응답을 표시했고 세 가지 화면 검사에서 JavaScript page error는 없었다.

### 정확도에서 남은 문제

“기술 뉴스와 논문” 질의의 현재 순서는 다음과 같다.

1. Startup Market Background Pack (63)
2. Technology Meeting Research Brief (61)
3. Research-to-News Enrichment Pipeline (57)
4. Financial Technology Evidence Digest (53)
5. Daily Tech News & AI Research Digest (38)

Chat/MCP의 단일 추천도 첫 번째 **Startup Market Background Pack**이었다. 해당 템플릿에는 뉴스·연구 단계가 있지만 **US Country Profile·Annual GDP Records**까지 들어 있다. 따라서 관련 기능이 있다는 판단은 가능하지만, 가장 간결하고 목적에 맞는 템플릿을 골랐다고 승인하기 어렵다.

소스의 현재 검색은 업무 개념·일부 단어의 일치 점수를 사용하고, 동점에서는 갱신 시각을 우선한다. **불필요한 추가 업무 감점, 필수 입출력·작업 순서의 적합성, 고정 주제와 사용자 주제의 일치가 충분히 반영되지 않는 점**이 원인 후보다. 최근 템플릿이 늘어난 현재 목록에서는 초기 3개 표본 때보다 이 문제가 잘 드러난다.

또한 `READY`는 recorded preflight이며 완료 보장이 아니다. 조회 결과에는 `fallback_available=false`인 템플릿도 있어, 공개된 모든 템플릿을 폴백 보장 상품으로 간주하면 안 된다. 이번에는 실행·다운로드·폴백을 호출하지 않았다.

## 실제 방문 흐름

발견 문서/메타데이터 → Entry에서 목적 선택 → Explore/Chat/MCP 검색 → 1개 추천 또는 후보 비교 → Schema·상세·준비 상태 확인 → 별도 승인된 실행 → 결과 조회 → 세션을 유지한 재방문 또는 동의된 업데이트 순이다.

이번 검증은 **검색·추천·상세·재방문까지**다. 에이전트나 워크플로우가 없는 목적은 다른 능력을 임의로 실행하기보다 검색 0건/권한 안내 등으로 종료해야 한다. 신규 생성·수정은 고객 Workspace 권한 범위와 연결된다.

## 권장 보완 순서

1. **템플릿 단일 추천의 정밀도:** 필수 업무·입출력·순서·주제 적합성을 먼저 평가하고, 불필요한 단계/부가 기능을 감점한다. 관련성이 유사할 때만 최근 검증·활동 정보를 활용한다. 고정 정답 질의와 별도 holdout으로 Chat/MCP/화면의 순위를 함께 검증한다.
2. **Chat 원문 설명 정리:** 제공자 설명의 micropayments 등 상업 표현을 사용자에게 보이는 설명에서 제거한다. 실제 machine protocol·필수 실행 계약을 거짓으로 바꾸지 않는다.
3. **외부 발견/홍보의 실증:** 공식 Registry의 게시 URL·승인 상태, 검색 Console 색인, 출처별 실제 에이전트의 유입·추천 후 실행·재방문을 연결해 측정한다. robots 접근 허용, 검색 노출, 크롤러 방문, 자율형 작업 완료를 각각 구분한다.
4. **장기 재방문 경험:** 현재 resume 위에 목적별 저장·만료·변경·다음 행동을 관리하는 Passport를 점진적으로 연결한다. 기존 설계의 후속 기능이며 현재 구현으로 단정하지 않는다.

이번 요청은 확인·정리이므로 위 기능을 추가 개발하거나 운영 설정을 변경하지 않았다.

## 검증 근거와 범위

- 공개 API 검사 **31건**: 주 검사 29건(HTTP 200 28건, 세션 없는 resume의 예상 HTTP 401 1건) + 새 세션 프로토콜 비교 2건(200). 응답 성공과 추천의 업무 적합성을 구분했다.
- 실제 Chromium의 워크플로우 검색 **3개 시나리오**, 페이지 오류 0건. POST와 외부 도메인 요청은 차단해 업무 실행을 방지했다.
- 외부 웹 검색 2개 질의, 결과 없음. 전체 검색엔진·Registry의 전수 조사 결과가 아니다.
- 에이전트 업무 실행 0건, 워크플로우 실행 0건, 구독/알림 신청 0건, 결제 0건. 정상적인 검색·검사 방문 기록은 생성될 수 있다.
- 기존 고객 계정/토큰을 사용하지 않았고 검사 세션 토큰도 파일·출력에 저장하지 않았다.
- 서버·DB schema·Cloudflare·서비스 코드를 변경하지 않았다. 공개 카탈로그와 검증 시각은 운영 중 바뀔 수 있다.

원본: `live-results.json`, `protocol-supplement.json`, `browser-results.json`, `external-search-evidence.json`, `live-check.log`, 화면 이미지. 주요 구현 근거: `concierge/agent_entry.py`, `workflow_discovery.py`, `front.py`, `mcp_contract.py`, `new/en/assets/operating.js`. 이전 기록의 미구현 판정은 현재 결과로 대체해 읽어야 한다.
