# 자율형 Agent의 첫 방문·탐색·재방문 경험 확인

> 후속 개발 반영: 이 문서는 개발 전 방문 검증 기록이다. 목적별 Entry·Workflow 검색·Chat/MCP 연결·재방문 문맥의 수정과 운영 검증은 [개발 결과](<저장소>/reports/autonomous-agent-development-2026-10-25/README.md)에 정리했다.

확인일: 2026-10-25, Asia/Seoul. 운영 공개 API·검사용 Chat 세션·Computer Use의 실제 Workflow 화면을 확인했다. 서비스 코드는 수정하지 않았다.

**현재는 Agent가 서비스를 알고 방문하면 개별 Agent를 찾고 연결 정보를 받는 흐름이 동작한다. 다만 신규 Agent에게 서비스를 알리는 외부 유입 증거, 목적별 빠른 안내, 자연어 Workflow 템플릿 추천에는 보완이 필요하다.**

## 1. 자율형 Agent에게 알려지고 홍보되는가

발견을 위한 준비는 있다. 실제 공개 응답에서 Agent Card, MCP manifest, `llms.txt`, `llms-full.txt`, sitemap을 가리키는 Link header를 확인했다. robots는 Googlebot·GPTBot·OAI-SearchBot·PerplexityBot·ClaudeBot 등을 포함해 공개 페이지 접근을 허용하고, 계정·Workspace·실행 및 task-update 경로는 별도로 제한한다. 홈페이지와 Agent Card는 서비스 역할 및 A2A·MCP 연결을 설명한다.

이는 **크롤러가 읽을 수 있고 방문한 Agent가 연결 입구를 발견할 수 있다는 확인**이다. 크롤러가 실제 방문했다거나 외부 Agent가 스스로 서비스를 선택해 유입됐다는 증거와 구분해야 한다.

이번 웹 검색에서 `"agentconcierge.biz"`, `"Agent Concierge" "agentconcierge.biz" MCP` 두 질의는 검색 결과가 없었다. 제한된 검색 결과이므로 전체 검색엔진 미등록을 단정할 수 없다. 외부 Registry 게시 상태, 검색 유입, Agent별 활성 재방문과 전환은 이번에 검증한 자료로 확인되지 않았다. 광고 전달도 기존 안내상 비활성이다. 별도의 운영 로그·검색 Console·외부 디렉터리 게시 증거 없이 “Agent에게 홍보되고 있다”고 평가할 단계는 아니다.

## 2. 처음 접속하면 무엇을 할지 알 수 있는가

`GET /`에 `Accept: application/json`을 보내면 다음을 받는다.

- “Describe the task. I will return one best available agent.”라는 안내.
- 작업을 설명하라는 질문과 날씨 API 예시.
- REST `POST /chat`, A2A Agent Card·메서드, MCP endpoint와 도구 목록.
- 첫 대화 응답의 Visitor token을 다음 요청의 전송 정보로 유지하는 방법.
- Agent Card·LLM 안내·OpenAPI 문서의 주소.

첫 인사 `hello`도 같은 간단한 작업 안내를 반환한다. 기본적인 “무엇을 하는 서비스인지, 어디에 요청할지”는 이해할 수 있다.

부족한 부분은 **“개별 Agent 검색 / 여러 후보 탐색 / Workflow 템플릿 찾기 / 이전 작업 이어가기”라는 목적별 선택 안내**다. 첫 JSON에는 Explore·템플릿 API 바로가기가 없고, LLM 안내에는 사람용 메뉴 페이지는 있으나 해당 API의 구체적 호출법이 빠져 있다. MCP 도구 11개와 Agent Card의 skill에도 Workflow 템플릿 검색 전용 기능은 없다.

단, 첫 안내가 연결한 `/openapi.json`에서는 `/api/explore`, `/api/workflows/templates`, Workflow 실행·결과 API를 찾을 수 있다. 기계적으로 접근 불가능한 상태가 아니라, 안내 문서를 더 읽고 조합해야 하는 구조다.

## 3. 재방문 목적에 맞는 빠른 연결을 주는가

별도 검사 세션에서 날씨 Agent를 찾은 뒤 같은 세션 전송 정보로 `details 1`, `what's new`를 보냈다. 두 요청 모두 동일 작업과 MCP 문맥을 유지하면서 현재 관련 Agent를 안내했다. 응답 본문 문장에는 세션 token이 표시되지 않았다.

같은 세션으로 홈페이지를 다시 읽으면 세션을 인식하지만, 인사 문장은 첫 방문과 동일하다. “지난 작업”, “관련 검색 바로가기”, “이어갈 템플릿”, “저장된 목적별 호출 예시”가 구조화된 바로가기로 나오지는 않는다. 현재의 재방문 장점은 **세션과 작업 문맥을 유지하는 후속 명령**이며, 맞춤형 재방문 대시보드·목적별 바로가기와는 차이가 있다.

`what's new`는 이전 작업의 현재 후보를 재평가한다. 이번 응답은 같은 Agent였으며, 바뀐 사항만 비교한 차이 보고서나 반드시 새로운 후보를 뜻하지 않는다. 자동 알림은 목적·운영자 권한·목적지 검증을 거쳐 별도로 신청해야 한다.

## 4. Explore에서 목적에 맞는 Agent를 찾기 쉬운가

실제 운영 검색 다섯 질의를 확인했다.

- `weather forecast`: 상위 결과들이 날씨 예보 API였다.
- `research papers`: 논문 검색·학술 연구 관련 Agent들이 나왔다.
- `npm package`: 패키지 정보·검색·다운로드 통계 관련 API들이 나왔다.
- `서울 날씨`: 날씨 조회 관련 API들이 나왔다.
- `find an agent that searches scientific papers`: 논문 검색 관련 MCP·API들이 나왔다.

Protocol·category·verified·has_report 등의 query parameter도 OpenAPI에 공개되어 있다. 개별 Agent 탐색의 기본 목적별 검색은 확인한 표본에서 동작했다. 전체 데이터의 정확도·재현율을 측정한 결과는 아니며, 표시된 `total`은 일부 응답에서 추정치다. 검색 결과가 나오는 것과 지금 그 도구가 실제 실행된다는 사실은 별도로 확인해야 한다.

## 5. Chat에서 자연어로 원하는 Agent를 정확히 안내하는가

다음 두 요청에는 관련된 단일 후보와 플랫폼 Gateway 연결 정보를 받았다.

- “Find an MCP agent that provides a weather forecast for Tokyo” → **Smarter Weather [MCP]**. 실행 입력이나 실제 도쿄 예보를 받은 것이 아니라, 해당 능력을 가진 Agent를 추천받았다.
- “Find an agent that searches research papers” → **Paper Finder [MCP]**. Any Protocol 범위에서 관련 후보를 선택했다.

Protocol 선택, 확인 시각, 품질 등급, 연결 방식이 함께 안내됐다. 기본값은 A2A이므로 MCP·x402까지 포함해 탐색하려면 Any 또는 명시적 Protocol 선택이 중요하다.

현재 Chat은 모든 요청을 이해하는 범용 상담 LLM 대신 작업 정규화·관련성·검증 근거에 따른 Agent 추천 경로를 사용한다. 따라서 표본 성공을 복합 업무 전체의 정확한 이해로 확대하면 안 된다. 특히 “Workflow 템플릿 추천” 요청은 별도 intent로 분기하지 않아 실패했다.

## 6. Workflow 템플릿을 검색하고 추천받는가

현재 공개 템플릿은 다음 3개다.

- Daily Tech News & AI Research Digest
- Country & Economic Indicator Brief
- Package Metadata & Advisory Review

API와 Computer Use 화면에서 다음을 확인했다.

- `research`, `news` → 뉴스·연구 템플릿 1개.
- `papers` → 0개. 실제 템플릿 단계에는 Research Papers가 있지만 검색 대상은 이름·설명·태그여서 놓쳤다.
- `나라 지표` → 0개.
- “Find a workflow that researches technology news and papers” → 0개.

Computer Use로 Browse templates에 들어가 `research`를 입력하면 해당 템플릿 카드가 보였고, `papers`로 바꾸면 “No published templates match the selected filters.”가 표시됐다. 실행·다운로드 버튼과 템플릿의 단계는 표시되지만 이번 검토에서 실행하거나 다운로드하지 않았다.

**현재는 목록·category·단순 문자열 필터가 있으며, 목적을 이해하는 자연어 템플릿 추천은 연결되어 있지 않다.** 서버는 이름·설명·태그의 LIKE 검색, 브라우저는 같은 세 필드의 includes 필터를 사용한다. Agent 탐색의 다국어 정규화·의미 검색과 별도 경로다.

Chat에서도 재현했다.

- 영어로 뉴스·관련 논문의 Workflow 템플릿을 요청 → “No currently active, relevant agent found.”
- 한국어로 같은 취지의 템플릿을 요청 → 접근성 기술 논문 관련 개별 x402 Agent를 추천. 템플릿 응답은 없었고 요청의 복합 목적과 맞지 않았다.

필요한 템플릿이 이미 존재해도 Chat과 Workflow 검색이 연결되지 않아 발생한 사용자 여정의 공백이다.

## 우선 보완할 순서

1. **Workflow 추천 경로 연결:** Chat과 MCP에서 Agent 추천·템플릿 추천 목적을 구분한다. 기존 템플릿 검색 API를 먼저 노출하고 목적별 호출 예시를 안내한다.
2. **템플릿 검색 개선:** 이름·설명·태그뿐 아니라 노드 기능·입력·출력도 색인하고 다국어·동의어 정규화를 적용한다. 적합한 템플릿과 추천 이유·필요 입력을 함께 반환한다.
3. **첫 방문·재방문 안내:** 현재 있는 Explore·Chat·템플릿 API와 세션 재개 명령을 목적별 `quick_actions` 같은 구조로 안내한다. 신규 URL을 가정할 필요 없이 기존 API를 묶어 제공할 수 있다.
4. **외부 유입 증거 확보:** 공식 문서·Agent 설정 예시·Registry 게시 근거와 유입 출처, 추천 성공 후 재방문 지표를 별도로 기록한다. 무단 광고 발송 대신 검색·공식 안내·명시적 구독 경로를 사용한다.

위 항목은 이번 확인에서 도출한 개선 제안이다. 이번 작업에서 서비스 코드나 배포를 변경하지 않았다.

## 검증 범위와 기록

- 운영 공개 HTTP 확인: **27건, HTTP 200**. 업무 의미상 성공과는 구분한다. 템플릿 검색 0건도 HTTP 상태는 200이었다.
- 격리 회귀 검사: **43개 통과**. 기존 Agent 여정·발견 안내·다국어/의미 탐색 경계 검사다. 발견한 템플릿 추천 공백까지 해결됐다는 의미는 아니다.
- 실제 Computer Use: Workflow 기본 화면 → Browse templates → research → papers 검색.
- 외부 Provider 호출 0건, Workflow 실행 0건, 결제 0건. 검사 Chat은 별도 세션으로 수행했고 세션 token은 보고서와 로그에서 제외했다. 기존 사용자 세션을 사용하지 않았다.
- 서버·Jobs·Execution·Cloudflare·DB schema 변경은 없다. Explore 내부의 기존 검색 처리는 운영 서비스가 수행하며, 외부 Provider 업무 실행과 구분된다.

원본 근거: `live-journey.json`, `secondary-checks.json`, `browser-evidence.json`, `external-search-evidence.json`, `isolated-regressions.log`, 공개 안내 스냅샷 `llms.txt`·`llms-full.txt`.

핵심 소스: `agent_market/concierge/front.py`의 welcome·llms 안내·Explore/템플릿 API, `agent_market/concierge/fast_chat.py`, `agent_market/concierge/hybrid_explore.py`, `agent_market/gateway/store.py`의 list_workflows, `new/en/assets/operating.js`의 renderFrontTemplates.
