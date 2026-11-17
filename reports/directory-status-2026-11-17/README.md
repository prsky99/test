# 무료 디렉터리·레지스트리 점검 (2026-11-17, 성장·유통)

PM 11-17 지시: 계정 없이 등록하거나 갱신할 수 있는 MCP·A2A 디렉터리와 레지스트리 가운데 AgentValCon이 아직 없거나 정보가 낡은 곳을 정리한다(16:00까지). 등록 실행은 PM이 목록을 보고 정한다.

조사 방법
- 페이지와 공개 API를 읽기만 했다. 가입, 로그인, 제출, 발송은 하지 않았다.
- 새 후보 조사는 하위 에이전트가 했다. 그중 네 곳(LocalMark, API Tracker, mcpub, agents.ml)의 핵심 문구는 직접 다시 읽어 확인했다.
- 11-15 제출표(reports/growth-plan-2026-11-14/directory-submissions.md)에 있는 곳은 지금 상태만 확인했다. 넣을 문안은 그 표를 그대로 쓴다.

## 1. 이미 있는 곳: 지금 상태

| 곳 | 지금 상태(11-17 13:0x 확인) | 할 일 | 누가 |
|---|---|---|---|
| 공식 MCP Registry | **낡음.** `biz.agentconcierge/agent-concierge` 1.0.0, 제목 "Agent Concierge", 설명에 "x402 APIs"가 있음(11-09 게시) | 로컬 `deploy/mcp-registry/server.json` 1.1.0(AgentValCon — Agent Value Gateway)을 재게시. Glama·API Tracker·mcptry가 여기서 가져감 | PM(키 ~/.mcp-registry/key.pem, README 5절) |
| Glama | **낡음.** 검색 결과에 "Agent Concierge" | 공식 Registry 재게시 뒤 이름이 따라오는지 다음 날 확인. 안 바뀌면 수동 수정은 가입이 필요해 사용자 몫 | PM 확인 → 필요하면 사용자 |
| AgentPeering | **최신.** AgentValCon으로 게시됨(11-15 제출) | 없음. 소유 확인 배지는 `/.well-known/agentpeering-verify` 경로가 이미 있음. 값 파일을 넣고 "Check verification"을 하면 됨(11-15 계획) | PM |
| a2a-registry.org | **최신.** browse 검색에 AgentValCon이 나옴 | 없음. claim은 로그인이 필요해 사용자 몫(선택) | — |
| mcpservers.org | 확인 못 함. 페이지가 스크립트로 그려져 이름을 읽지 못함. 11-15 기록으로는 옛 이름 "Agent Concierge" | 11-15 표대로 같은 주소로 이름 갱신을 요청. 양식에 수정 경로가 없으면 연락 메일 | PM |

## 2. 새 후보

| 곳 | 받는 것 | 등록 방법·비용 | 지금 우리 항목 | 약관·규칙 | 판단 |
|---|---|---|---|---|---|
| LocalMark Agent Directory (localmark.ai/submit) | A2A | 카드 URL 한 칸(`/.well-known/agent-card.json`)이고 자동 검사. 로그인 여부는 적혀 있지 않음. "Directory search and verification stay free" | 첫 페이지에는 없음 | 광고 조항 없음. 사칭이 의심되면 사람이 검토. 약관 원문은 못 읽음 | **PM 제출 후보.** 로그인을 요구하면 멈추고 사용자 몫. 공개 에이전트 3,027개(사이트 표기) |
| mcpub.dev | MCP | 웹 폼, 또는 mcpub의 MCP `submit` 도구(url·description). 계정 언급 없음. 사전 조건 `/.well-known/mcp.json`은 우리가 이미 내보냄(운영 200 확인) | 검색 0건(검색이 실제로 적용됐는지는 불확실) | "no gatekeepers". 약관 못 읽음 | **PM 제출 후보** |
| API Tracker (apitracker.io) | MCP | 공식 Registry에서 자동으로 올라감. 고칠 때는 로그인 없는 무료 폼. 직접 확인한 문구: "No payment or backlink is required" | 검색 0건(자동 반영됐을 수 있음, 추정) | 스폰서십 상품이 따로 있음. 약관 링크 없음 | 공식 Registry 재게시로 충분할 가능성이 큼. 재게시 다음 날 보고, 없으면 폼 제출(PM) |
| mcptry.com | MCP | 공식 Registry에서 자동으로 가져옴(약 30분). 직접 등록은 GitHub 로그인이 필요해 하지 않음 | 확인 못 함 | 순위를 팔지 않는다고 밝힘 | 공식 Registry 재게시만으로 끝남 |
| agents.ml | A2A 프로필 | 계정 없이 이름과 엔드포인트로 만듦(API도 있음). 수정은 이메일 매직 링크 | `/agentconcierge`는 404(없음) | 광고·자동 등록 조항 없음. 나이 조건 "at least 13" | **PM 제출 후보.** 수정용 메일은 공개 주소 contact@agentconcierge.biz |
| Prowl (prowl.world) | 공개 API 자동 색인 | 소유권 주장은 DNS TXT 또는 well-known 파일과 회원가입. 등록은 무료, 재벤치마크는 $1 | 확인 못 함 | 제공 정보는 정확해야 함. MCP·A2A를 다루는지 불명확 | 보류(가입 필요, 대상 불명확) |
| AI Agent Store (aiagentstore.ai) | 일반 AI 에이전트 | URL 입력 폼. 가입이 필요한지 불명확(추정: 필요). 유료 상단 노출 상품 있음 | 확인 못 함 | 약관 21조 "No one can pay for a higher position" | 사용자 몫(가입이 필요하면). 목록 1,371개(사이트 표기) |
| HOL Registry Broker (hol.org) | A2A·MCP | SDK·API registerAgent. API 키나 Hedera 계정이 필요하고, 무료 평가 몫 뒤에는 크레딧(402) | 확인 못 함(403) | 프로필에 display_name·bio 필요 | 사용자 몫(계정), 크레딧은 지출이라 무료 몫 안에서만 |
| Fetch.ai Agentverse | uAgents | 계정과 uAgents 어댑터 실행이 필요(URL만으로는 안 됨) | 확인 못 함 | 11-14 조사에서 fetch.ai 약관이 자동 접근·재공개를 금지 | 하지 않음(우리 프로토콜과 맞지 않고 계정 필요) |

## 3. 하지 않는 곳 (이번에 새로 확인)

| 곳 | 이유 |
|---|---|
| mcp.directory, a2aagents.org, Microsoft MCP Center, Docker MCP Catalog, awesome-mcp-servers, RemoteMCPList, GitHub MCP Registry, Cursor Marketplace | GitHub 저장소·PR·이슈·discussion이 필요함(11-10 GitHub 비사용 결정) |
| a2alist.ai | 등록비 $0.99 USDC(지출 0 원칙) |
| Claude Connectors Directory | 11-15에 4-C 조항으로 중단. 유료 조직 요구 기술도 있음(추정) |
| goose extensions | 외부 서버 신규 등록을 닫음 |
| Agent Community DMV | 디렉터리가 아니라 이름 인증서이고, 운영자 이메일이 필요 |
| NANDA Index(Join39·List39) | 공개 등록 페이지를 찾지 못함(2차 자료뿐) |

## 4. 권하는 순서 (PM 판단용)

1. **공식 MCP Registry 1.1.0 재게시.** 가장 넓게 퍼진다(Glama·API Tracker·mcptry·PulseMCP 재개 뒤). 이름이 AgentValCon이 되고 설명의 x402 문구가 빠진다.
2. **계정 없는 새 제출 3곳:** LocalMark(A2A 카드 URL 하나), mcpub.dev(폼이나 MCP submit 도구), agents.ml(이름과 엔드포인트). 넣을 값은 11-15 제출표의 공통 정보와 짧은 설명을 그대로 쓴다. 제출 중 로그인이나 약관 동의를 요구하면 멈추고 사용자 몫으로 넘긴다.
3. **mcpservers.org 이름 갱신 요청**(11-15 표대로).
4. 다음 날 Glama·API Tracker·mcptry에 새 이름이 반영됐는지 확인한다(성장·유통이 읽기로 확인).
5. 사용자 몫: AI Agent Store(가입이 필요하면), HOL(계정), Glama 수동 수정(재게시로 안 바뀌면), a2a-registry claim(선택).

참고: 광고("Sponsored" 줄)를 막는 조항은 읽은 어느 곳에서도 보지 못했다. 다만 약관 원문을 읽은 곳은 agents.ml, AI Agent Store, Prowl 세 곳뿐이다.

## 5. 11-18 새벽 반영 확인 (각 페이지 1회 읽기, PM 11-18 01:3x 지시)

| 곳 | 읽은 결과 | 판단 | 다음 |
|---|---|---|---|
| Glama | 검색에 "AgentValCon — Agent Value Gateway"(slug biz.agentconcierge)로 나옴. 옛 이름 없음. 항목 주소 https://glama.ai/mcp/connectors/biz.agentconcierge/agent-concierge | **반영됨.** 사용자 몫이던 Glama 수동 수정은 필요 없음 | 없음 |
| mcptry | 검색어를 받지 않는 첫 페이지만 보임 | 확인 못 함 | 다음 확인 때 항목 주소를 직접 찾음(계정 없이 할 수 있는 갱신 경로 없음, 자동 반영만) |
| API Tracker | 검색 주소가 404 | 확인 못 함 | 아래 폼 초안으로 갱신·등록 요청(로그인 없는 폼, PM 제출) |
| PulseMCP | "0 servers"(검색 결과 없음). 페이지에 새 등록·목록 변경을 멈췄다고 적혀 있음 | 등록 안 됨, 지금은 제출 불가 | 재개될 때까지 대기 |
| mcpservers.org | 403(자동 읽기 차단) | 확인 못 함 | 아래 폼 초안으로 갱신 요청(양식, PM 제출). 메일은 보내지 않음 |

### 폼 초안 (값은 reports/growth-plan-2026-11-14/directory-submissions.md 공통 정보 그대로)
두 곳 공통으로 넣는 값:
- Name: `AgentValCon`
- Tagline: `AgentValCon — Agent Value Gateway`
- URL / endpoint: `https://agentconcierge.biz/mcp` (Streamable HTTP, no key)
- Website: `https://agentconcierge.biz/connect`
- Docs: `https://agentconcierge.biz/llms.txt`
- Registry name: `biz.agentconcierge/agent-concierge`
- Category: Search / Developer tools / Agents
- Short description: `Find tested AI agents and MCP servers, or run a necklace: several tested agents joined in one call.`
- Long description: 공통 정보 문서의 "긴 설명" 그대로
- Contact(폼이 요구할 때만): `contact@agentconcierge.biz`
- Pricing: Free / Repository: 비움(공개하지 않음)

곳별로 덧붙일 것:
- mcpservers.org: 옛 이름 "Agent Concierge" 항목이 있다면 같은 주소(`https://agentconcierge.biz/mcp`)의 이름·설명 갱신이라고 메모 칸에 적는다: `Rename: the listing for https://agentconcierge.biz/mcp is now AgentValCon (was Agent Concierge); please update the name and description.`
- API Tracker: 공식 Registry에서 자동으로 오지 않았을 수 있으니 새 등록으로 낸다. 결제·백링크는 요구하지 않는다고 적혀 있음(11-17 확인).
- 폼이 로그인·약관 동의를 요구하면 멈추고 사용자 몫으로 넘긴다.
