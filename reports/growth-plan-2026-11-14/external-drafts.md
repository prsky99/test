# 외부 게시 초안 (첫 목걸이 공개 11-21 대비, PM 연계 점검 11-14) — 게시하지 않음

모든 항목은 **초안**이다. 외부 게시·등록 갱신·커뮤니티 글은 사용자 승인 뒤에만 한다(PM이 모아서 묻는다).
- 지출 0, GitHub 홍보 금지(11-10), 런칭 글은 사용자가 직접 게시한다(11-10).
- 공개 문구는 측정값과 방법론 링크로만 쓴다. "best", "guaranteed", "#1", "100%"는 쓰지 않는다(초격차 전략).
- 홍보 단위는 목걸이 에이전트다. 개별 진주를 앞세우지 않는다.
- 문구 중심: **"Verified agents, strung into workflows that run to the end."**
- `{…}` 칸은 첫 목걸이가 95% 관문을 통과해 워크플로우 메뉴에 오른 뒤 실제 값으로 채운다(성장 계획 0-1절 절차). 채우지 못한 칸이 있으면 그 문장을 뺀다.

## 1. 공식 MCP Registry 설명 갱신 (`deploy/mcp-registry/server.json`)

이름 `biz.agentconcierge/agent-concierge`와 주소는 그대로 둔다. 바뀌는 것은 title과 description뿐이다. 재게시는 README 3절 절차를 따른다.

```json
{
  "title": "AgentValCon",
  "description": "Agent Value Gateway: workflows of verified AI agents (necklaces) that run to the end, with per-step fallbacks and published test results. Also finds and checks A2A agents and MCP servers for a task."
}
```
- description 길이: 레지스트리 제한 안(약 210자)
- 근거 링크(`/methodology`)는 11-18 페이지가 생긴 뒤 websiteUrl 후보로 다시 본다.

## 2. MCP 디렉터리 (mcpservers.org 심사 중, 그 밖은 해당 없음 — 11-14 03:3x)

**짧은 설명(≤ 100자)**
```
Workflows of verified AI agents that run to the end, with fallbacks and published tests.
```

**긴 설명**
```
AgentValCon is an agent value gateway. It tests public AI agents and MCP servers, keeps the ones that keep
working (pearls), and strings them into workflows that act as one new agent (necklaces). Each step has
alternates tried in order, and every necklace page shows its recent results: {passed}/{cases} test cases,
{delta} points above the best single agent for the same task, and its last retest time.

Tools:
- necklace_<name>: run a necklace (listed while it passes its retests)
- necklace_details: the agents and alternates behind a necklace, with test results
- find_agents / search: find agents for a task, with recorded checks
- check_agent: our recorded status for an agent before you call it

Endpoint: https://agentconcierge.biz/mcp (Streamable HTTP). No API key for discovery.
Method: https://agentconcierge.biz/methodology
```

## 3. A2A 등록처 두 곳 (카드 표기 갱신)

카드는 우리 서버에서 자동으로 바뀐다(이름 AgentValCon, 목걸이 기술). 등록처에 따로 적힌 이름과 설명이 있으면 아래 문구로 바꾼다.
```
AgentValCon — Agent Value Gateway. Necklaces (workflows of verified agents) you can run with
"run necklace <name> {...}", and agent discovery with recorded checks.
```

## 4. 커뮤니티 글 (게시는 사용자가 직접, 11-10 결정)

### 4-1. Show HN (제목 80자 이내)
```
Show HN: AgentValCon – workflows of tested AI agents that fall back per step
```
본문:
```
We test public AI agents and MCP servers every day and keep the ones that keep working. Then we connect
them into workflows ("necklaces") that act as one agent. Each step has alternates tried in order, so a
run can finish when one agent is down.

The first necklace, {name}, {summary}. In the last 7 days it passed {passed}/{cases} test cases, {delta}
points above the best single agent for the same task. Its page lists every agent it uses and its last retest:
https://agentconcierge.biz/necklaces/{slug}

How we test: https://agentconcierge.biz/methodology
You can run it from an MCP client (tool necklace_{tool}) or an A2A client ("run necklace {slug} {...}").
Discovery needs no key. Feedback on the method is welcome.
```

### 4-2. Reddit r/mcp
제목: `A remote MCP tool that runs a tested chain of agents with per-step fallbacks ({name})`
본문은 4-1의 둘째 문단부터 같은 내용에 MCP 설정 한 줄을 더한다.
```
claude mcp add --transport http agent-concierge https://agentconcierge.biz/mcp
```

### 4-3. X (280자)
```
{name}: a workflow of tested AI agents that falls back per step. {passed}/{cases} test cases passed this week,
{delta} points above the best single agent. Agents used and last retest: agentconcierge.biz/necklaces/{slug}
```

## 5. 승인 묶음 (PM이 사용자에게)

| # | 일 | 성격 |
|---|---|---|
| 1 | Registry title·description 재게시 | 외부 게시 |
| 2 | mcpservers.org 설명 갱신(심사 통과 뒤 수정 양식이 있으면) | 외부 게시 |
| 3 | A2A 등록처 두 곳 표기 갱신 | 외부 게시 |
| 4 | HN·Reddit·X 글 | 사용자가 직접 게시(11-10) |

- 시점: 첫 목걸이가 관문을 통과하고 메뉴에 오른 날(목표 11-21) 뒤
- 그 전에 바꿀 수 있는 것은 1(이름·설명)뿐이다. 목걸이가 없는 상태에서 목걸이 문구를 먼저 내지 않는다.
