# 등록 채널별 제출물 완성본 (2026-11-09, 게시 승인 대기)

11-09 헌장 변경("합법 범위 안에서 공격적으로")에 따라 **등록할 수 있는 합법 채널 전부**를 준비했다. 사용자는 각 절의 값을 그대로 붙여 넣고 제출만 하면 된다. 게시·계정은 사용자 몫이다.
- 형식은 11-09에 각 채널 공개 페이지에서 확인했다. 확인하지 못한 칸은 "(미확인)"으로 적었다.
- 유료 즉시 게시($29~$39)는 쓰지 않는다(11-10 사용자 결정: 수익 전 지출 0). 무료 경로만 쓴다.
- 아이콘: `deploy/distribution/icon-512.png`, `icon-256.png`, `icon.svg` (Pearl 로고).

## 공통 문구 (영어, 그대로 사용)
- **Name:** Agent Concierge
- **One-liner (≤100자):** Find AI agents, MCP servers and x402 APIs for a task, ranked by recorded checks and quality.
- **Short description (≤160자):** Remote MCP server that recommends checked AI agents and MCP servers for a task, with the latest recorded health, trial and execution checks.
- **Long description:**
  Agent Concierge catalogs about 258,000 public A2A agents, MCP servers and x402 APIs and keeps checking them: health checks for every listing, read-only trial calls where safe, and execution checks against published tools. Ask for an agent by task and get up to three candidates ranked by the latest successful check, recent activity and quality grade, with the check type and date. A check records what happened when it ran; it does not guarantee that an agent works now. Search needs no sign-in.
- **MCP URL:** `https://agentconcierge.biz/mcp` (streamable HTTP, no authentication)
- **Website:** https://agentconcierge.biz/  **Docs / setup:** https://agentconcierge.biz/connect
- **A2A Agent Card:** https://agentconcierge.biz/.well-known/agent-card.json
- **Tools:** search, find_agents, chat, whats_new, search_workflows, workflow_details (read-only discovery); call, run_workflow (user-started execution); subscribe, report
- **Tags:** agent-discovery, mcp-directory, a2a, search, aggregator, verification
- **Category (선택형일 때):** Search (없으면 Other / Developer Tools)
- **Publisher:** Agent Concierge, https://agentconcierge.biz
- **Contact email:** contact@agentconcierge.biz (사이트 공개 주소, 11-10 사용자 결정)

---

## 진행 상황 (11-10 갱신, 처음 작성 11-09 22:08 KST, `scripts/directory_presence.py`로 매일 확인)
| 곳 | 상태 |
|---|---|
| 공식 MCP Registry | **게시 완료** `biz.agentconcierge/agent-concierge@1.0.0` (12:48 UTC, 커밋 c6bb85aa) |
| Glama | **자동 반영 완료**: https://glama.ai/mcp/connectors/biz.agentconcierge/agent-concierge (Registry에서 가져감, 상태 "아직 시험 안 됨"). 6번 제출은 필요 없음 |
| A2A Registry | **제출 완료 (11-10)**: 카드 검사 결과 Conformant. 검토 대기 id 7082c1bf-781d-4422-9261-08c5f41bdca4 |
| a2a.directory | **게시 완료 (11-10)**: 검증을 통과해 바로 공개됨 |
| mcpservers.org | **무료 제출 완료 (11-10)**: 카테고리 Search, 원격 URL /mcp, 2주 안에 심사, 승인 메일은 contact@ |
| MCP Market | **건너뜀 (11-10)**: 원격 MCP는 $69 유료 게시만 있고, 무료 대기열은 GitHub 저장소 제출만 받음(GitHub 미사용 결정) |
| mcp.so | **건너뜀 (11-10)**: 원격 서버 양식에 "$39 결제 후 게시"만 있음. 무료 경로는 Google 로그인(계정 생성)이 필요할 수 있음 |
| PulseMCP | 아직 없음. 재개 시 자동 수집 예정 |

## 1. 공식 MCP Registry — 게시 완료
- 제출물: `deploy/mcp-registry/server.json` (스키마 검증 완료). 절차: `deploy/mcp-registry/README.md` 3절 명령 6줄.
- 효과: PulseMCP가 재개 시 자동 수집, Glama·mcpservers.org가 Registry 이름을 참조한다.

## 2. mcpservers.org (wong2/awesome-mcp-servers의 공식 제출 경로) — https://mcpservers.org/submit
| 칸 | 값 |
|---|---|
| Server Name | Agent Concierge |
| Category | Search |
| Short Description | 공통 Short description |
| Repository, Website or Documentation | https://agentconcierge.biz/connect |
| Official MCP Registry Name (optional) | biz.agentconcierge/agent-concierge |
| This server supports remote connections | 체크 |
| Contact Email | contact@agentconcierge.biz |
| Submission plan | Free (2주 내 검토). Premium $39는 지출 승인 필요 |

## 3. jaw9c/awesome-remote-mcp-servers (GitHub PR) — 원격 전용 서버의 정식 목록
> **보류 (11-10 사용자 결정 "깃허브 공개하지 않음"):** GitHub 계정으로 하는 PR과 소개용 저장소는 하지 않는다. 아래는 결정이 바뀔 때를 위한 참고용이다.

- 근거: punkpeye/awesome-mcp-servers는 "원격 전용은 awesome-remote-mcp-servers로"라고 안내한다. 11-09에도 커밋이 있다(열린 PR 1.1k라 병합은 느릴 수 있음).
- 주의: 기준 문구는 OAuth를 요구하지만 표에는 "Open" 항목이 많다. 우리는 검색에 인증이 없으므로 "Open"으로 적는다. 거절되면 그대로 둔다.
- 추가할 표 줄(README 표 끝, "Open" 항목 묶음 근처):

```
| Agent Concierge | Search | `https://agentconcierge.biz/mcp` | Open | [Agent Concierge](https://agentconcierge.biz) |
```

- 커밋 메시지: `Add Agent Concierge`
- PR 제목: `Add Agent Concierge (agent and MCP server discovery)`
- PR 본문:

```markdown
Adds **Agent Concierge**, a remote MCP server for finding AI agents and MCP servers by task.

- **URL:** `https://agentconcierge.biz/mcp` (streamable HTTP)
- **Authentication:** Open — discovery tools are read-only and need no sign-in.
- **Maintainer:** Agent Concierge (https://agentconcierge.biz)
- **Official MCP Registry:** `biz.agentconcierge/agent-concierge`

**What it does:** catalogs about 258k public A2A agents, MCP servers and x402 APIs and keeps a check history for each (health checks, read-only trial calls, execution checks). `search` / `find_agents` return up to three candidates with the latest check type and date.

**Maintenance:** checks run continuously; public status with a 30-day observed availability: https://agentconcierge.biz/status.json

**Example usage:**
    claude mcp add --transport http agent-concierge https://agentconcierge.biz/mcp
Then ask: "find an MCP server that returns Japanese weather forecasts".

Setup for other clients: https://agentconcierge.biz/connect
```

## 4. mcp.so — https://mcp.so/submit?type=remote-server
| 칸 | 값 |
|---|---|
| Type | Remote Server |
| Name | Agent Concierge |
| Repository URL* | 필수 표시. https://agentconcierge.biz/connect 를 넣는다(GitHub 저장소는 쓰지 않음, 11-10). 거절되면 보류 |
| Server URL | https://agentconcierge.biz/mcp |
| Description / Tags | 공통 문구 (미확인: 정적 페이지에 칸이 보이지 않음) |
| Plan | 무료 검토(있으면). $39 즉시 게시는 지출 승인 필요 |

## 5. MCP Market — https://mcpmarket.com/submit
- 토글: **Remote MCP**, **MCP Server**
- URL: https://agentconcierge.biz/mcp (원격 토글에서 받는 칸이 무엇인지는 미확인)
- Plan: Free Queue (평균 4~6주). $29 Get Listed Now는 지출 승인 필요.

## 6. Glama — 자동 반영됨 (아래는 참고용)
- 칸은 미확인. 공통 문구, MCP URL, Website, 아이콘을 넣는다. 로그인 필요.
- Glama는 "승인된 streamable HTTP 커넥터만" 공개한다고 밝힘 → 검토 대기.

## 7. A2A Registry — https://a2aregistry.org/submit/
- Canonical Agent Card URL: `https://agentconcierge.biz/.well-known/agent-card.json` → "Inspect card"로 증거를 본 뒤 등록.

## 8. a2a.directory — https://a2a.directory/submit
| 칸 | 값 |
|---|---|
| Agent Name * | Agent Concierge |
| Agent Card URL * | https://agentconcierge.biz/.well-known/agent-card.json |
| Description | 공통 Short description |
| Website URL | https://agentconcierge.biz/ |
| Icon (emoji) | 🦪 |
| Publisher Name * | Agent Concierge |
| Publisher URL | https://agentconcierge.biz |
| Contact Email * | contact@agentconcierge.biz |

## 9. 지금은 제출 경로가 없는 곳 (자동 또는 대기)
| 곳 | 상태 | 할 일 |
|---|---|---|
| PulseMCP | 신규 제출 중단(9-03부터). 공식 Registry 자동 수집 예정 | 1번만 하면 됨 |
| Smithery | 10-31 프록시 종료, 공개 레지스트리로만 남음. 제출 페이지 404 | 월 1회 다시 확인 |
| punkpeye/awesome-mcp-servers | 설치형 저장소 전용 | 공개 소개 저장소와 설치형 패키지(SDK 초안)가 생기면 Aggregators 절에 PR |
| appcypher/awesome-mcp-servers | 8-01 보관(읽기 전용) | 없음 |
| cursor.directory, turbomcp(mcp.run) | 11-09 확인 실패(429·다른 도메인) | 다시 확인 |
| ERC-8004(8004scan) | 온체인 등록, 가스비 지출 | 지출 승인 시 |

## 10. 권장 제출 순서 (한 번에 30분 이내)
7 → 8 → 2 → 3 → 5 → 4 (1·6은 끝남). 제출 날짜를 WORKLOG에 남기면 0단계 계측으로 채널별 효과(MCP clientInfo 이름, 리퍼러 없는 신규 클라이언트)를 비교할 수 있다.
