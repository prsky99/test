# 구글 검색 "agent concierge" 대응 (PM 11-14 02:2x, 성장·유통)

PM이 확인한 사실은 다음과 같다.
- 홈은 색인돼 있다.
- 사이트맵은 다시 제출했다.
- 색인 250쪽, 미색인 492쪽이다.
- "agent concierge" 평균 순위는 11위(11-09~10)다.
- 11-10부터 core update가 진행 중이다(약 11-24 종료).

원인 후보는 두 가지다. ① 자동 생성 상세 페이지 약 1만 개가 사이트 전체 품질 신호를 낮췄다. ② 일반 단어 브랜드라 브랜드 신호가 약하다.

## A. 브랜드 신호 (구현, 낮 frontend 묶음에 넣을 예정)

| 항목 | 전 | 후 |
|---|---|---|
| 홈 title(서버 `PAGES`, 화면 전환 JS, 정적 HTML) | Agent Concierge — Connected Intelligence, with Evidence | **Agent Concierge: Find AI Agents & MCP Servers by Task** |
| og:title·twitter:title | 위와 같음 | 새 title과 같음 |
| og:site_name | Agent Concierge | 그대로(이미 맞음) |
| WebSite JSON-LD | name만 | name "Agent Concierge", alternateName ["AgentConcierge", "agentconcierge.biz"], url, publisher |
| Organization JSON-LD | name·url·logo | + alternateName, description, email contact@agentconcierge.biz, sameAs |
| 첫 화면 글자 | H1 위 머리말 "For developers and AI agents" | **"Agent Concierge · For developers and AI agents"**(H1 바로 위, 9개 화면의 홈 패널 모두) |

- sameAs에는 실제로 있는 공식 프로필 하나만 넣었다. MCP Registry 항목 `https://registry.modelcontextprotocol.io/v0.1/servers/biz.agentconcierge%2Fagent-concierge/versions/latest`이고, 공개 API로 200과 active 상태를 확인했다.
- 시안(`new/design/pages/01-home-full.png`)에도 H1 바로 위에 작은 머리말 자리("CONNECTED INTELLIGENCE")가 있다. 배치는 그대로이고 글자만 바뀐다. 전후 사진은 PM에 따로 붙인다.
- 시험: `tests/test_brand_signals.py`. 웹어워드 3단계 문구 스크립트의 원래 있던 실패(홈 리드 문장이 바뀐 뒤 교체 항목이 맞지 않음)도 함께 고쳤다.

## B. 색인 품질: 상세 페이지 기준과 쪽수 (안, PM 결정 뒤 적용)

기준 데이터는 11-12 18:14 스냅샷(`task-pages.json`, 정리 뒤)이다. 사이트맵은 9,885개이고, 그중 `/agent/<id>`가 9,237개다.

| 묶음 | 쪽수 | 안 |
|---|---|---|
| `/agent/<id>` x402 | 5,239 | **noindex**, 사이트맵에서 뺌(수집 중지·등급 상한 B) |
| `/agent/<id>` A2A·MCP 가운데 설명 40자 미만이거나 MCP 도구 0개 | 44 | noindex |
| `/agent/<id>` A2A·MCP 가운데 같은 이름이 둘 이상인 것의 나머지(점수 가장 높은 하나만 남김) | 87 | noindex(남긴 페이지를 canonical로 가리키는 안도 가능) |
| `/agent/<id>` 남는 것(A2A 1,149·MCP 2,849에서 위를 뺀 것) | **3,867** | 색인 유지 |
| 비교 `/agents/compare/a-vs-b` 중 한쪽이 x402 | 214 | noindex |
| 비교 나머지 | 351 | 유지 |
| `/agents/best/<cat>/x402` | 20 | noindex |
| best 나머지·category 20·task 202·보고서 | 60+20+202+… | 유지 |

- 사이트맵 합계는 약 9,885개에서 약 4,300개로 준다(−56%).
- 스냅샷 카탈로그는 이미 시험 호출이 성공하고 헬스가 정상인 것 위주다(8,954/8,956 trial_ok, 8,932 healthy). 그래서 "시험 호출·헬스 이력 없는 페이지" 기준으로 빠지는 쪽수는 거의 없다. 가장 큰 기준은 x402다.
- 적용 방법(PM 결정 뒤)
  - 해당 페이지 응답에 `<meta name="robots" content="noindex, follow">`와 `X-Robots-Tag: noindex`를 넣는다. 링크는 따라가게 둔다.
  - 사이트맵(`growth_catalog.sitemap_paths`)에서 같은 기준으로 뺀다.
  - 페이지 자체와 에이전트 API는 그대로 둔다. 사람과 에이전트는 계속 쓸 수 있다.

## C. "/" 콘텐츠 협상 (조사, 바꿀 경우 안)

공개 주소 11-14 02:1x, 같은 `/`에 Accept와 UA만 바꿔 요청했다.

| 요청 | 응답 |
|---|---|
| Accept 없음 | **JSON**(6.8KB) |
| `*/*` | **JSON** |
| Googlebot(일반 Accept: text/html,…,*/*;q=0.8) | HTML(132KB) |
| Googlebot + `*/*` | **JSON** |
| Bingbot + `*/*` | **JSON** |
| facebookexternalhit, Twitterbot, Slackbot + `*/*` | **JSON** |
| curl 기본 | **JSON** |

- 위험
  - 일반 Googlebot은 HTML을 받는다.
  - 하지만 `*/*`를 보내는 크롤러는 JSON을 받는다. Bing(→ ChatGPT 검색·DuckDuckGo), 소셜 미리보기 봇이 여기에 해당한다.
  - JSON에는 title, og, 구조화 데이터가 없다. 그래서 미리보기와 다른 검색엔진의 홈 이해가 깨질 수 있다.
  - 11-13 홈에는 bingbot 1회, Googlebot 1회가 왔다.
- 지금 규칙(`front.py` root): Accept에 text/html이 있고 application/json이 첫 항목이 아니면 HTML, 그 밖은 JSON이다. Markdown은 따로 준다.
- 안: Accept에 `application/json`이 명시되고 text/html보다 앞설 때만 JSON을 준다. Accept 없음과 `*/*`는 HTML을 준다.
- 에이전트 쪽 영향
  - `/`에 Accept 없이 오는 스크립트·에이전트는 HTML(132KB)을 받게 된다.
  - 외부 `/` 요청은 하루 script 0~6, other 16~24, verifier 11~14, ai_bot 2건(11-11~13)이다. 이 가운데 JSON에 기대는 수는 기록에 Accept가 없어 모른다.
  - 기계용 입구는 이미 따로 있다: `/.well-known/agent-card.json`, `/llms.txt`, `/api/agent/v1/entry`, HTML의 `<link rel="alternate" type="application/json" href="/">`.
  - 바꾸기 전에 Accept별 `/` 요청 수를 하루 세는 기록을 먼저 넣자(작은 변경). 그 뒤 결정하는 것을 권한다.

## D. 측정

- 매일 한 줄씩 현황판에 적는다: Search Console 실적("agent concierge" 노출·클릭·평균 순위, 색인/미색인 쪽수).
- Search Console은 사용자 Chrome의 로그인 화면에서 읽기만 한다.
- 구글 검색 결과를 자동으로 긁는 순위 확인은 하지 않는다. 약관 위반 위험이 있고 봇 확인에 걸린다.
- 판정은 core update가 끝난 뒤(약 11-24)에 한다.
