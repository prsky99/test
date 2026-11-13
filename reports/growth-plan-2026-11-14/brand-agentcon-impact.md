# 브랜드 Agentcon 적용: 바꿀 곳과 영향 (PM 11-14 04:3x 4번, 조사만)

사용자가 브랜드를 **Agentcon**으로 정했다. 공개 화면 적용 방식은 PM이 사용자 확인을 받는 중이다. 이 문서는 **화면을 바꾸지 않고** 바꿀 곳과 영향만 정리한다.
- 권장안(전략 7절): 이름은 Agentcon으로 하고, "Agent Concierge"는 alternateName과 부제로 남긴다.
- 바꾸지 않는 것: 도메인 `agentconcierge.biz`, MCP Registry 이름 `biz.agentconcierge/agent-concierge`, 연락 메일 `contact@agentconcierge.biz`.

2026-11-14 작업본 기준으로 "Agent Concierge"가 나오는 곳을 셌다.
- 공개 HTML 43개(화면당 13~45회, 대부분 머리글·바닥글·메타)
- `agent_market` 파이썬 72개 파일
- 시험 23개 파일

## 1. 바꿀 곳 (권장안 기준)

| # | 곳 | 지금 | 권장안으로 바꾸면 | 파일 |
|---|---|---|---|---|
| 1 | 화면 title(9개 화면, 서버 `PAGES`·화면 전환 JS·정적 HTML 세 곳이 같아야 함) | "… — Agent Concierge", 홈은 "Agent Concierge: Find AI Agents & MCP Servers by Task" | "… — Agentcon", 홈은 "Agentcon: Verified AI Agent Workflows (Agent Concierge)" 같은 형태로 옛 이름을 한동안 함께 표기 | `public_metadata.py` PAGES, `new/en/assets/operating.js`, `new/en/*.html` |
| 2 | og:title·twitter:title·og:site_name | Agent Concierge | Agentcon | 같은 세 곳 |
| 3 | 구조화 데이터 Organization·WebSite | name "Agent Concierge", alternateName ["AgentConcierge", "agentconcierge.biz"] | name "Agentcon", alternateName ["Agent Concierge", "AgentConcierge", "agentconcierge.biz"] | `public_metadata.py` BRAND, BRAND_ALIASES |
| 4 | 첫 화면 머리말(H1 위) | "Agent Concierge · For developers and AI agents" | "Agentcon · Agent Value Gateway" + 부제 "formerly Agent Concierge"(기간 한정) | 9개 화면 홈 패널, `tests/test_brand_signals.py` |
| 5 | 머리글 로고 글자·바닥글 저작권 줄 | Agent Concierge | Agentcon | `new/en/*.html` 43개(공용 머리글·바닥글 조각에서 생성되는지 확인 필요), `footer.html` |
| 6 | 소셜 카드 그림 | 그림 안 글자 "Agent Concierge" | 새 그림(디자인 시스템 Pearl Connection) | `new/html/assets/social-card.svg/.png`, `new/en/assets/social-card.svg` |
| 7 | A2A 에이전트 카드 name | "Agent Concierge" | "Agentcon" | `front.py` 카드(724·737행 부근) |
| 8 | MCP serverInfo | name `agent-concierge`, title "Agent Concierge (for AI agents)" | name은 **그대로**(클라이언트 설정 키와 Registry 이름이 이것), title만 "Agentcon (for AI agents)" | `front.py` initialize(3590·3609행 부근) |
| 9 | llms.txt·llms-full.txt 머리 | "# Agent Concierge" | "# Agentcon (formerly Agent Concierge)" | `front.py` 497·595행 부근 |
| 10 | 성장 페이지(task·best·compare·category·agent 상세) title·머리글 | "… | Agent Concierge" | "… | Agentcon" | `growth_pages.py`, `growth_catalog.py` |
| 11 | 공식 MCP Registry `server.json` title | "Agent Concierge" | "Agentcon"(이름 `biz.agentconcierge/…`는 그대로). **재게시는 외부 게시라 사용자 승인** | `deploy/mcp-registry/server.json` |
| 12 | 연결 안내 명령 | `claude mcp add … agent-concierge https://agentconcierge.biz/mcp` | 그대로 둘 것을 권함. 키 이름은 사용자 설정에 남는 값이라, 바꾸면 기존 사용자 설정과 안내가 어긋남 | `/connect`, llms |
| 13 | 워크스페이스·고객 화면 문구(로그인, 메일 머리, 워크플로우 제품 꾸러미) | Agent Concierge | Agentcon(공개 화면 뒤 두 번째 묶음) | `agent_market/customer_*`, `workspace_*`, `workflow_product*` 등 약 60개 파일 |

## 2. 바꾸지 않을 것 (권장)

| 곳 | 이유 |
|---|---|
| 도메인·메일·Registry 이름 | PM 지시. 바꾸면 검색·등록 연속성이 끊김 |
| 우리 요청의 User-Agent(`AgentConcierge-DataAgents/1.0` 등 5종) | 상대 서버의 허용 목록·로그에 이 이름으로 남아 있음. 바꾸면 차단·재확인 위험. 나중에 따로 결정 |
| Python 연동 패키지 이름 `agent_concierge` | PyPI 게시는 보류 상태(11-10). 게시할 때 정함 |
| MCP serverInfo name `agent-concierge` | 위 8번 |
| 운영 내부 이름(agentcon 명령, 로그 경로) | 이미 agentcon |

## 3. 영향

| 영향 | 내용 | 줄이는 방법 |
|---|---|---|
| 구글 검색 신호 | 11-14 A안으로 "Agent Concierge" 신호(title·JSON-LD·첫 화면)를 막 넣었다. core update는 약 11-24까지다. title에서 옛 이름을 한 번에 빼면 "agent concierge" 검색의 연결이 약해질 수 있다 | alternateName에 옛 이름을 남긴다. title·머리말에 기간을 정해 옛 이름을 함께 쓴다(권장: core update 끝 + 4주). Search Console로 "agentcon"과 "agent concierge"를 함께 본다 |
| "Agentcon" 이름 충돌 | 같은 이름을 쓰는 다른 행사·제품이 있을 수 있다(검색으로 확인하지 않았다) | 적용 전에 PM이 상표·검색 결과를 확인한다(무료 검색만) |
| 외부 등록처 표기 | 공식 MCP Registry, mcpservers.org(심사 중), A2A 등록처 두 곳에 "Agent Concierge"로 남아 있다 | 등록처 갱신은 외부 게시라 사용자 승인. 목걸이 개별 등록과 묶어 한 번에 |
| 시험 | 브랜드 문자열을 고정한 시험 23개 파일(`test_brand_signals`, 웹어워드 문구, public metadata 등) | 적용할 때 같은 커밋에서 고친다 |
| Chat·추천 답 | 답 본문에 브랜드가 거의 없다(llms·카드 머리 정도) | Chat 비교 새 실패 0을 게이트에서 확인 |
| 캐시 | 엣지·브라우저 캐시의 옛 title·카드 | 배포 뒤 공개 주소에서 title·JSON-LD·카드·llms를 다시 읽어 확인 |

## 4. 적용 순서 (사용자 확인 뒤)

1. 1묶음(공개 화면 frontend): 표의 1~5, 7~10. 게이트 시험과 Chat 비교를 거친다.
2. 2묶음: 소셜 카드 그림(6), 워크스페이스·고객 화면(13).
3. 외부 등록처 표기(11과 등록처): 사용자 승인 뒤, 목걸이 등록과 함께.
