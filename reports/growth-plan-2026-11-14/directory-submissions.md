# MCP·에이전트 디렉터리 등록 문안 (11-15 16:5x 갱신, 성장·유통)

- PM 16:48 지시로 고쳐 썼다. 이름은 AgentValCon이고, 목걸이와 주문 접수를 소개에 넣었다. 도구 목록은 11-15 16:50 공개 `tools/list`에 맞췄다.
- 숫자는 잰 값만 쓴다. 카탈로그 수처럼 매일 바뀌는 값은 문안에 넣지 않고 `/status.json` 주소로 대신한다.
- 제출은 PM이 한다(사용자 11-15 위임: 계정 생성이 필요 없는 무료 디렉터리).
- 제출 시점은 이름 정리 묶음(11-17 frontend)과 첫 목걸이 공개가 운영에 들어간 직후다. 옛 이름(Agent Concierge)으로 먼저 내지 않는다.
- 같은 날 함께 할 일: Glama 표시 이름 변경, 공식 MCP Registry 1.1.0 재게시(`deploy/mcp-registry/server.json`, README 5절).

## 공통 정보

| 항목 | 값 |
|---|---|
| Name | AgentValCon |
| Title / tagline | AgentValCon — Agent Value Gateway |
| Registry name | `biz.agentconcierge/agent-concierge` (공식 Registry 이름. 식별자라 바꾸지 않음) |
| Remote endpoint | `https://agentconcierge.biz/mcp` (Streamable HTTP, JSON 응답) |
| Auth | 없음(키 없이 읽기 도구 사용) |
| Website | `https://agentconcierge.biz/connect` (클라이언트 설정 안내) |
| Docs | `https://agentconcierge.biz/llms.txt`, 방법: `https://agentconcierge.biz/methodology` |
| Necklaces | `https://agentconcierge.biz/api/necklaces` (목걸이 목록 JSON. 공개된 목걸이가 생기면 각 주소가 생김) |
| Request a necklace | `https://agentconcierge.biz/necklaces/request` (사람), `POST https://agentconcierge.biz/api/necklace-requests` (에이전트) |
| Contact | `contact@agentconcierge.biz` |
| Category/tags | Search, Developer tools, Agents, Registry/Discovery, Workflows / `a2a`, `mcp`, `agent-discovery`, `agent-registry`, `workflows` |
| Logo | `https://agentconcierge.biz/logo.svg` |
| Pricing | Free (목걸이 실행과 주문은 지금 무료. 결제 문구는 쓰지 않음) |
| Repository | 없음(공개하지 않음. 11-10 결정) |

## 짧은 설명 (≤ 100자)

```
Find tested AI agents and MCP servers, or run a necklace: several tested agents joined in one call.
```
(99자)

## 긴 설명

```
AgentValCon is a remote MCP server that finds and tests other agents. Describe a task and it returns up to three
A2A agents or MCP servers from a catalog it checks continuously, with the evidence behind each: recorded
reachability, recent check results, latency and a quality grade, so you can choose before you connect.

Necklaces: when tested agents work better together than any one of them alone, we join them into a necklace,
a workflow that answers in one call instead of you finding, calling and merging several agents. Each necklace
opens only after its answers pass our gate, and its page shows what we measured, which agents it uses and how it
falls back when one fails. Need one we do not have? Request it at https://agentconcierge.biz/necklaces/request;
the answer appears on the request's own status page.

Tools (read-only unless noted):
- find_agents: up to three active agents for a task, with what you need to connect
- search: browse up to three catalog matches to compare names, grades and latest checks
- check_agent / verify_agent: our recorded status and latest test results for one agent before you call it
- best_for_role: the verified pearls for a role and the necklaces that use them
- search_workflows / workflow_details: published workflows and their inputs
- run_workflow (runs): run one published workflow after reviewing it
- call (runs): run one tool of a listing you chose, through our gateway, after checking its schema
- chat: describe a task in plain English and refine it

No API key is needed. Endpoint: https://agentconcierge.biz/mcp (Streamable HTTP).
How we test: https://agentconcierge.biz/methodology
```

메모:
- 공개 목걸이가 0개인 동안에는 목걸이 단락이 "앞으로 생길 것"처럼 읽힌다. 제출은 첫 목걸이 공개 뒤로 정해져 있어 그대로 쓴다.
- 공개가 늦어지면 단락 둘째 문장을 "We are opening our first necklaces"로 바꿔 낸다.
- 목걸이 수와 잰 값(토큰·시간·정확도)은 문안에 넣지 않는다. 목걸이 페이지가 날짜·사례 수와 함께 보여 준다.
- 광고: 일부 결과에 "Sponsored" 한 줄이 붙는다. 광고·후원 내용을 금지하는 디렉터리는 내지 않는다. Claude Connectors Directory는 4-C 조항 때문에 11-15에 중단했다.

## 클라이언트 설정 예시 (디렉터리가 설치 조각을 받는 경우)

```json
{
  "mcpServers": {
    "agentvalcon": { "type": "http", "url": "https://agentconcierge.biz/mcp" }
  }
}
```

## 사이트별 제출 방식

조사 결과(11-15 저녁)를 이 아래 표에 채운다. 기준은 다음과 같다.
- GitHub PR 방식이나 저장소 주소가 필수인 곳은 하지 않는다.
- 계정이나 약관 동의가 필요한 곳은 사용자 몫으로 따로 표시한다.
- 공식 Registry에서 자동으로 가져가는 곳은 Registry 재게시만으로 끝난다.

조사: 11-15 16:5x, 각 사이트의 제출·FAQ·문서 페이지를 읽기만 했다(제출·가입·로그인 없음). "추정"은 직접 읽지 못한 부분이다.

### 바로 할 수 있는 곳 (계정·GitHub 없음, 무료) — PM 제출

| 사이트 | 지금 상태 | 제출 방법 | 넣을 값 | 메모 |
|---|---|---|---|---|
| AgentPeering (agentpeering.com/publish, A2A) | 없음 | 웹에서 AgentCard URL이나 도메인 입력 → 미리 보기 → 등록. "no account needed", 48시간 안에 올라감 | `https://agentconcierge.biz` (우리 `/.well-known/agent-card.json`을 읽음) | 소유 인증 배지는 GitHub 로그인이 필요해 하지 않음. 제출 전 agent-card의 이름이 AgentValCon인지 확인 |
| a2a-registry.org (/submit, A2A) | 없음 | 웹 사이트 URL로 "Scan Agent" → 무료 등록("List agent free") | `https://agentconcierge.biz` | 스캔 뒤 단계에서 로그인을 요구하면 멈추고 사용자 몫으로 넘김(그 단계는 확인 못 함) |
| mcpservers.org (/submit) | **옛 이름 "Agent Concierge"로 이미 있음**(`agentconcierge-biz-connect`, Search 분류) | 무료 웹 양식, 로그인·약관 칸 없음, 심사 최대 2주. Premium $39는 쓰지 않음 | 이름 AgentValCon, 분류 Search, 짧은 설명, 링크는 Website `https://agentconcierge.biz/connect`(저장소 대신), Remote 체크, Official MCP Registry Name `biz.agentconcierge/agent-concierge`, 연락 메일 `contact@agentconcierge.biz` | 새 항목이 아니라 이름 갱신 요청이 되도록 같은 주소로 냄. 양식에 수정 경로가 없으면 연락 메일로 이름 변경을 요청 |

### 자동으로 가져가는 곳 (공식 Registry 재게시만 하면 됨)

| 사이트 | 지금 상태 | 메모 |
|---|---|---|
| Glama (glama.ai/mcp/connectors) | **옛 이름으로 이미 있음**(등급 B). 문서에 공식 Registry 연동이 적혀 있음 | Registry 1.1.0 재게시 뒤 이름이 따라오는지 확인. 안 바뀌면 수동 수정은 가입이 필요해 사용자 몫 |
| PulseMCP (/submit) | 없음. 제출을 멈춘 상태(9-03 공지) | "재개되면 공식 Registry에서 자동으로 가져간다"고 적혀 있음. 할 일 없음 |
| zplatform.ai (MCP 순위) | 없음 | 공식 Registry와 GitHub 별·npm/PyPI 내려받기 수로 상위 250개를 매주 자동으로 고름. 우리는 GitHub·패키지 지표가 없어 들기 어려움(추정). 일반 AI 도구 양식은 창업자 이름 같은 개인정보를 요구해 하지 않음 |

### 계정이 필요한 곳 — 사용자 몫

| 사이트 | 필요한 것 | 넣을 값 |
|---|---|---|
| mcp.so (/submit, Remote Server 유형) | 무료 심사는 로그인해야 나오는 것으로 추정(로그아웃 상태에서는 $39 버튼만 보임) | 원격 엔드포인트 `https://agentconcierge.biz/mcp`, 이름 AgentValCon(필수 두 칸). GitHub 필요 없음 |
| cursor.directory (/mcp/new) | GitHub 또는 Google 로그인 | 로그인 뒤 양식은 확인 못 함 |
| aiagentsdirectory.com (/submit-agent) | 로그인("Sign In to Continue") | 확인 못 함 |

### 하지 않는 곳

| 사이트 | 이유 |
|---|---|
| mcpmarket.com | GitHub 저장소 URL이 필수 |
| Smithery | 10-31에 계정·CLI·등록을 닫음(선별 서버만 표시) |
| mcp.run | 기업용 게이트웨이(turbomcp.ai)로 바뀌어 디렉터리가 아님 |
| OpenTools | 기업 공식 서버만 모은 목록, 제출 경로 없음 |
| LobeHub MCP, mcp-get, mcphub | 페이지를 읽지 못함(JS 전용·402·무응답). 다음 점검 때 다시 봄 |

### 광고 규칙
- 확인한 곳 어디에도 광고나 "Sponsored" 줄을 보이는 서버를 막는 문구는 없었다. mcp.so와 mcpservers.org는 사이트 자체가 스폰서 칸을 판다.
- 정식 약관(terms) 페이지까지는 읽지 않았다. 제출 직전에 해당 사이트의 약관에서 광고 관련 조항만 한 번 확인한다.

### 제출 순서 (11-17 이름 정리 묶음과 첫 목걸이 공개가 운영에 들어간 뒤, PM)
1. 공식 Registry 1.1.0 재게시(이름·설명이 AgentValCon). Glama와 PulseMCP(재개 뒤)가 여기서 가져간다.
2. 우리 `/.well-known/agent-card.json`의 이름이 AgentValCon인지 확인한다(11-15 16:5x에 이미 AgentValCon으로 확인됨).
3. AgentPeering, a2a-registry.org에 낸다.
4. mcpservers.org 이름 갱신을 요청한다.
5. 다음 날 Glama 이름이 바뀌었는지 확인한다. 안 바뀌었으면 사용자 몫 목록에 올린다.
