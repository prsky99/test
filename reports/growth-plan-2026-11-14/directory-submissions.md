# MCP 디렉터리 등록 문안 (준비만, 외부 제출 없음 — PM 11-14 03:1x)

대상은 PulseMCP, mcp.so, mcpservers.org다(11-09 확인 때 등록 안 됨). 사용자 승인이 오기 전에는 제출하지 않는다. 아래 영어 문안은 공식 MCP Registry에 낸 `deploy/mcp-registry/server.json`과 지금 MCP 도구 목록에 맞췄다.

## 공통 정보

| 항목 | 값 |
|---|---|
| Name | Agent Concierge |
| Registry name | `biz.agentconcierge/agent-concierge` (공식 Registry, active, 11-09 게시) |
| Remote endpoint | `https://agentconcierge.biz/mcp` (Streamable HTTP, JSON-RPC JSON 응답, GET 스트리밍 없음) |
| Auth | 없음(키 없이 읽기 도구 사용) |
| Website | `https://agentconcierge.biz/connect` (클라이언트 설정 안내) |
| Docs | `https://agentconcierge.biz/llms.txt` |
| Contact | `contact@agentconcierge.biz` |
| Category/tags | Search, Developer tools, Agents, Registry/Discovery / `a2a`, `mcp`, `agent-discovery`, `agent-registry` |
| Logo | `https://agentconcierge.biz/logo.svg` |
| Pricing | Free to search (지출·결제 문구는 쓰지 않는다) |

## 짧은 설명 (≤ 100자)

```
Find AI agents and MCP servers for a task, ranked by recorded connection checks and quality.
```

## 긴 설명

```
Agent Concierge is a remote MCP server for discovering other agents. Describe a task and it returns up to three
relevant A2A agents or MCP servers from a catalog it checks continuously: recorded reachability, recent check
results, latency and a quality grade, so you can choose before you connect.

Tools (read-only unless noted):
- find_agents: up to three active agents for a task, with the evidence behind each
- search: the same catalog lookup without saving a conversation
- check_agent: our recorded status, check success rate, latency and grade for one agent before you call it
- search_workflows / workflow_details: published multi-agent workflows and their inputs
- chat: describe a task in plain English and refine it ("details 1", "more")

No API key is needed for search. Endpoint: https://agentconcierge.biz/mcp (Streamable HTTP).
```

## 클라이언트 설정 예시 (디렉터리가 설치 조각을 받는 경우)

```json
{
  "mcpServers": {
    "agent-concierge": { "type": "http", "url": "https://agentconcierge.biz/mcp" }
  }
}
```

## 사이트별로 확인할 것 (제출 전, 승인 뒤)

| 사이트 | 확인할 것 | 주의 |
|---|---|---|
| PulseMCP | 공식 MCP Registry에서 자동으로 가져오는지 먼저 본다. 가져온다면 별도 제출이 필요 없다 | 수동 제출 양식이 있으면 위 문안을 쓴다 |
| mcp.so | 제출 양식의 필수 칸(GitHub 저장소 URL 필수 여부) | **GitHub 저장소를 알리지 않는다(11-10 결정)**. 저장소 URL이 필수면 등록하지 않고 PM에 보고 |
| mcpservers.org | 제출 방식(양식 또는 GitHub PR) | GitHub PR 방식이면 하지 않는다(awesome 목록 PR 금지와 같음) |

- 계정을 만들거나 약관에 동의해야 하면, 그것도 사용자 승인 범위에 넣는다. 비밀번호와 인증 코드는 사용자가 직접 입력한다.
- 넣지 않는 것
  - 가격·크레딧·결제 문구: `credit` 도구 설명에 "Top-ups… being prepared"가 있지만 소개에는 쓰지 않는다.
  - x402 결제 실행: 수집이 멈춰 있어 소개하지 않는다.
  - 저장소 주소.

## Glama 소유권 확인 완료와 표시 이름 변경안 (11-14, PM 10:2x)

- **소유권 확인 완료**: 11-14 10:2x
  - 방식: HTTP 파일. `https://agentconcierge.biz/.well-known/glama.json`이 공개 claim 토큰 JSON을 돌려준다(cfb85257, 낮 묶음 day-frontend-20261114-r4).
  - 커넥터 페이지에 "Ownership verified"와 Admin 탭이 보인다.
  - 기록: `logs/growth/directory-presence.jsonl`
- **확인 파일은 그대로 둔다.** 파일이나 토큰이 사라지면 Glama가 7일 유예 뒤 소유권을 거둔다. 같은 토큰을 되살리면 유지된다.
- **지금 Glama 표시**
  - 제목: "Agent Concierge - MCP Connector | Glama"
  - 설명: 공식 Registry `server.json`의 description과 같다("Find AI agents, MCP servers and x402 APIs for a task, ranked by recorded checks and quality.")
  - 즉 커넥터가 공식 Registry 항목 `biz.agentconcierge/agent-concierge`와 연결돼 있다. Glama 안내상, Registry 연결 커넥터는 Registry가 갱신되면 이름·설명·주소가 기본으로 덮어써진다.

### 이름을 AgentValCon으로 바꾸는 두 길

| 안 | 방법 | 장점 | 단점 | 승인 |
|---|---|---|---|---|
| **A(권장)** | 공식 MCP Registry `server.json`의 title·description을 바꿔 재게시한다. 이름 `biz.agentconcierge/agent-concierge`와 주소는 그대로 둔다. Glama는 다음 동기화 때 따라온다 | 한 번에 공식 Registry, Glama, Registry를 가져가는 다른 목록(PulseMCP 등)까지 맞춰진다. 출처가 하나로 남는다 | Glama 반영 시점은 Glama 동기화에 달렸다 | **외부 게시 → 사용자 승인** |
| B | Glama Admin 탭에서 이름·설명을 고치고 "Use Glama listing details as the source of truth"를 켠다 | 바로 바뀐다 | 그 뒤로는 Registry를 고쳐도 Glama가 따라오지 않는다(두 곳을 따로 관리). 남의 서비스 설정 변경이다 | 외부 계정 설정 변경 → 사용자 승인 |

**A의 server.json 변경 초안**(external-drafts.md 1절과 같다)
```json
{
  "title": "AgentValCon",
  "description": "Agent Value Gateway: workflows of verified AI agents (necklaces) that run to the end, with per-step fallbacks and published test results. Also finds and checks A2A agents and MCP servers for a task."
}
```
- 첫 목걸이 공개 전에 재게시한다면 목걸이 문구를 빼고 다음처럼 쓴다: "AgentValCon (Agent Value Gateway): find and check A2A agents and MCP servers for a task, with test results and a published method."
- 재게시 절차는 `deploy/mcp-registry/README.md` 3절을 따른다(키 `~/.mcp-registry/key.pem`, HTTP 확인 파일).
- 버전을 올린다: 1.0.0 → 1.0.1.

출처
- [Glama — glama.json 소개(2025-07-08)](https://glama.ai/blog/2025-07-08-what-is-glamajson)
- Glama 커넥터 페이지 안내(검색 요약): Registry 연결 커넥터는 Registry 갱신이 이름·설명을 덮어쓰고, 소유권 확인 뒤 "Use Glama listing details as the source of truth"로 Glama 쪽 편집을 유지할 수 있다.
