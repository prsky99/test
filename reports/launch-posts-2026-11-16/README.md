# 첫 목걸이 공개 게시 준비 (성장·유통, PM 11-15 17:12 지시, 게시는 사용자 확인 뒤)

- 문턱: 사용자 결정 11-15(919e9d01)으로 커뮤니티 게시는 "첫 목걸이 공개" 뒤에 한다.
- 어느 목걸이가 먼저 공개될지는 11-16 관문에 달렸다. 아래 `{NECKLACE}`·`{SLUG}`·`{INPUT}`·`{ANSWER}`·`{STEPS}`를 공개된 목걸이로 바꿔 쓴다.
- 1순위 후보는 회사 실사(company-due-diligence)다. 예시는 그 목걸이로 적었다.
- 각 채널의 규칙은 11-15 17:2x에 원문을 읽고 정리했다(읽기만 함). 원문을 못 읽은 곳은 그렇다고 적었다.

## 0. 가장 먼저 알아 둘 것: 사람이 직접 써야 하는 곳

| 채널 | 규칙 원문 | 우리에게 주는 뜻 |
|---|---|---|
| Hacker News (Show HN) | 뉴스 가이드라인에 "생성되거나 AI가 편집한 글을 올리지 않는다, HN은 사람 사이의 대화"가 있음 (news.ycombinator.com/newsguidelines.html) | **아래 초안을 그대로 올리면 규칙 위반.** 사용자가 사실 목록을 보고 직접 써야 함. 이 문서는 HN용으로 구성과 사실만 준다 |
| dev.to | AI를 도운 글은 AI 사용을 밝혀야 하고, **자기 회사를 포함해 어떤 사업도 홍보할 수 없음** (dev.to/guidelines-for-ai-assisted-articles-on-dev) | 서비스를 소개하는 글은 사람이 직접 쓴 기술 글이어야 함. 사실 목록만 준다 |
| Reddit (r/mcp, r/AI_Agents) | **원문을 읽지 못함**: 이 세션의 도구가 reddit.com을 모두 거부했고, 우회하지 않음 | 게시 전에 사용자가 r/mcp/about/rules와 사이드바·플레어를 직접 확인해야 함. 아래 초안은 일반 관례(만든 사람임을 밝힘, 본문 있는 글, 맞는 플레어)에 맞춘 것 |
| Product Hunt | 업보트를 요청하지 않음, 경품을 업보트 조건으로 걸지 않음, 대량 DM 금지, 계정 하나는 실제 사람 한 명 (help.producthunt.com 출시 안내 5번) | 계정 생성은 사용자만 할 수 있는 일. 초안 문구는 써도 됨(AI 금지 조항은 읽은 페이지에 없음) |
| Lobsters | 초대 가입이고, 가입 70일 안에는 자기 홍보와 [show] 태그를 쓸 수 없음 | 첫 게시에는 맞지 않아 뺀다 |

규칙 충돌 보고(PM 17:12 3번 방식):
- **HN·dev.to의 "AI가 쓴 글 금지"가 막는 것: 우리 쪽에서 완성 글을 넘기는 방식.**
- 이것은 남의 규칙이라 우리가 고칠 수 없다. 사람이 직접 쓰는 것으로만 풀린다.

## 1. 모든 채널에 공통으로 쓰는 사실 (영어, 잰 값과 출처만)

What it is
- AgentValCon finds AI agents and MCP servers for a task and tests them with real read-only calls; the ones that pass on two different days are "verified pearls".
- A necklace joins tested agents into one workflow that answers in one call. `{NECKLACE}` joins `{STEPS}` agents.
  - Company due diligence: SEC identity (CIK, ticker), latest SEC filings, an encyclopedia summary and, with a website, its domain registration.
- The MCP server identifier (serverInfo.name, what clients use to tell servers apart) is `agent-concierge`; the name people read is AgentValCon. Say so once, so nobody thinks it is a different server (PM 17:20: the identifier stays, changing it could break existing connections).
- Try it without a key or sign-up:
  - Page: https://agentconcierge.biz/necklaces/{SLUG}
  - MCP: https://agentconcierge.biz/mcp (tool `{TOOL}`)
  - A2A skill: `{SKILL}`

One real call (run it on the posting day and paste the real result, never an edited one)
- Input: `{INPUT}` (for company due diligence: `{"name": "<a US-listed company>", "country": "US"}`)
- Answer: `{ANSWER}` (first lines, plus the step list the answer shows)
- Time: the time that call actually took that day, measured from the posting machine, as it is (PM 17:20). No "fast" without that number.

Why one call (our own measurement always comes first; the outside figure only when we have none)
- Our own measurement, if the necklace page shows it: "Measured in our test runs on N cases (first – last date): one call, a median of S s per case, A% correct, about T tokens (text length ÷ 4). From the same runs' records (not a separate run), an agent calling the same K agents itself would make C calls …" — copy the line from the necklace page as it is (PM 11-16 display rules: "Measured" only for what was run; numbers from the same runs' records say so; no estimate and no accuracy for the path that was not run).
- If there is no measurement yet, cite the outside number only:
  - MCP-Universe (Luo et al., arXiv 2508.14704, Aug 2025) tested models on 231 tasks against 11 real MCP servers.
  - The best model in that paper, GPT-5, succeeded on 43.72% of them.
  - Do not call these tasks "multi-step" as if quoting; the paper's wording is long-horizon real-server tasks.

Limits (say them, do not hide them)
- `{NECKLACE}` covers what its page says. For company due diligence: US SEC filers only in this version.
- Some steps may be led by an agent under verification rather than a verified pearl; the page says which, step by step.
- Some results carry a "Sponsored" line (an ad), marked as such.
- Run from Korea by a small team. From Korea a new connection to our edge (Los Angeles) takes about 0.8 s before any work.
- Free for now. If that changes, the necklace page says so first.
- No public source repository.

Ask for a necklace
- https://agentconcierge.biz/necklaces/request — no contact details taken; the answer appears on the request's status page.

## 2. 채널별 준비

### 2.1 Hacker News — Show HN (사용자가 직접 씀)
- 제목 형식: `Show HN: <이름> – <무엇을 하는지>`.
  - 과장·대문자·느낌표를 쓰지 않는다.
  - "best"나 불필요한 숫자를 넣지 않는다.
- 링크는 가입 없이 바로 써 볼 수 있는 주소로 한다(목걸이 페이지). 소개용 랜딩 페이지는 해당되지 않는다.
- 본문·첫 댓글에 넣을 순서(사용자가 자기 말로):
  1. 무엇을 만들었는지
  2. 1절의 실제 호출 한 번
  3. 왜 한 번 호출인지
  4. 한계
  5. 주문 링크
- 하지 않는 것:
  - 업보트·댓글을 요청하지 않는다(어느 채널에서도).
  - 삭제 후 다시 올리지 않는다.
  - 자동으로 게시하지 않는다.
- 당일 댓글에는 만든 사람이 직접 답한다.

### 2.2 Reddit — r/mcp (규칙 원문 확인 뒤 게시)
- 확인할 것:
  - 자기 홍보 규칙
  - 출시 글 허용 여부
  - 플레어(Showcase 등)
  - 주간 스레드가 있는지
- 초안(영어, 규칙과 맞으면 그대로 써도 됨. AI 금지 조항이 있으면 사용자가 다시 씀):

```
Title: I made a free MCP tool that runs several tested agents in one call ({NECKLACE})

I'm the maker. AgentValCon tests MCP servers and A2A agents with real read-only calls, and when
a few of them do a job better together than alone, it joins them into a "necklace": one MCP tool
call instead of finding, calling and merging several servers yourself.

The first one is {NECKLACE}: {one-line summary}. It joins {STEPS} agents.
Example call (no key): tool `{TOOL}` on https://agentconcierge.biz/mcp
Input: {INPUT}
Answer (first lines): {ANSWER}

Why one call: {measured line from the necklace page, or the MCP-Universe figure with its citation}.

Limits: {scope}; some steps may be led by an agent still under verification (the page shows which);
some results carry a labelled Sponsored line; run from Korea; free for now.

If you need a necklace we don't have: https://agentconcierge.biz/necklaces/request
Feedback on what failed is the most useful thing for me.
```

### 2.3 Reddit — r/AI_Agents 주간 프로젝트 스레드 (규칙 원문 확인 뒤)
- "Weekly Thread: Project Display"가 반복해서 올라오는 것만 확인했다(미러 검색 결과, 규칙 원문은 못 봄). 별도 글보다 그 스레드에 댓글로 다는 것이 안전하다(추정).
- 2.2 초안의 첫 두 단락, 예시, 한계만 줄여서 쓴다.

### 2.4 Product Hunt (사용자 계정 필요)
- 태그라인(60자 안): `Tested AI agents joined into one call` (37자)
- 설명:
  - 1절의 What it is 첫 두 줄
  - 한계 세 가지(범위, 검증 중 멤버, 무료·Sponsored 표시)
- 만든 사람의 첫 댓글: 2.2 본문을 사용자 말로 줄인다.
- 공유 문구는 "써 보고 의견 주세요"로 한다. 업보트 요청과 경품은 하지 않는다.

### 2.5 dev.to (사용자가 직접 쓰는 기술 글)
- 출시 공지가 아니라 기술 글로 쓴다.
  - 주제 예: "How we decide an MCP server is a verified pearl: real read-only calls, two different days, and what failed"
- 서비스 소개는 그 안에서 한 단락만 한다.
- 근거 자료:
  - 방법론 https://agentconcierge.biz/methodology (v1.2)
  - 변경 기록 /methodology/changelog
  - 목걸이 페이지의 잰 값
- 태그는 `mcp`, `ai`.

## 3. 런칭 글을 막았던 세 가지의 지금 상태 (11-15 17:1x, 공개 주소·새 연결로 잼)

| 11-10에 고쳐야 했던 것 | 지금 | 근거 |
|---|---|---|
| ClaudeBot 차단 | **풀림** | robots.txt에서 ClaudeBot은 고객 전용 경로(/customer/, /api/customer-, /api/workspace-)만 막힘. ClaudeBot UA로 /, /llms.txt, /agent/358211 모두 200(0.8~3.3초). 오늘 원서버에 Claude 계열 봇 요청 기록은 0건(엣지 캐시가 답했을 수 있음) |
| MCP·A2A 첫 호출 실패 | **성공** | 새 클라이언트로 MCP initialize 200(1.28초) → tools/list 16개(1.15초) → find_agents 결과 있음(2.49초). A2A agent-card 200(0.83초), message/send 정상 메시지(4.81초). serverInfo.name은 아직 `agent-concierge`(식별자. 표시 이름은 AgentValCon) |
| 페이지 속도 | **차선 목표는 통과, 최종 목표는 아님** | 17:03 user_slo: 페이지는 차선 목표(3초) 3/3, 최종 목표(1초) 1/3. Explore 중앙값 2.44초(차선 4/6). 추천 중앙값 5.79초(차선 0/2) |

참고:
- 한국에서 잰 값이다. 같은 시각 Cloudflare 자체 응답(/cdn-cgi/trace)의 중앙값은 0.79초다. 새 연결 하나에 드는 시간이 이만큼이라는 뜻이다(11-15 분석 growth-edge-latency-split-1115.md).
- 추천이 5초를 넘는 것은 게시 전에 담당 팀이 볼 일이다. 게시 글의 첫 경험은 목걸이 호출과 find_agents라, 둘 다 5초 안에 답이 와야 한다.

## 4. GitHub 비공개 결정(11-10)이 막는 유입 (사용자 판단 자료)

방문 수는 Similarweb 공개 개요 페이지의 "Total Visits Last 3 Months" 반올림 추정치다(11-15 읽음).
- 페이지는 "October 2026" 기준이다.
- 3개월 합계인지 마지막 달 값인지는 문구만으로 확정할 수 없다.

| 디렉터리 | 방문 규모 | GitHub이 막는가 | 지금 우리 상태 |
|---|---|---|---|
| mcpmarket.com | 1.7M | **예**: 제출 양식에 GitHub 저장소 URL이 필수 | 못 냄 |
| zplatform.ai | 확인 안 됨(숫자 칸 빈칸) | **간접**: 공식 Registry에 더해 GitHub 별·npm/PyPI 내려받기 수로 상위 250개를 고름 | 목록에 없음. GitHub·패키지 지표가 없어 들기 어려움(추정) |
| mcpservers.org | 765.8K | 아니요(Website 링크로 대신) | 옛 이름으로 있음, 갱신 예정 |
| glama.ai | 337.2K | 아니요(공식 Registry 연동) | 옛 이름으로 있음 |
| mcp.so | 286.7K | 아니요(원격은 엔드포인트만) | 계정 필요라 사용자 몫 |
| smithery.ai | 237.5K | 해당 없음(10-31 등록 종료) | 못 냄 |
| pulsemcp.com | 125.7K | 아니요(재개 뒤 공식 Registry 자동) | 제출 중지 |

정리:
- GitHub 결정 때문에 **직접** 못 내는 곳은 mcpmarket 한 곳이다. 확인한 디렉터리 가운데 방문 규모가 가장 크다(1.7M, 위 단서 붙음).
- **간접적으로** 불리한 곳은 zplatform이다(GitHub·패키지 지표로 순위를 매김).
- awesome 목록 PR(11-10 금지)은 이번에 재지 않았다.
- 나머지 디렉터리는 GitHub 없이 갈 수 있다.

## 5. topic-evidence-brief 공개용 (11-17, 2회차 판정 통과 시 11:00~12:00 공개, PM 11-16 15:42 지시)

숫자 원칙(PM 11-16 표시 규칙): "Measured"는 실제로 실행해 잰 값에만 쓴다. 같은 실행 기록에서 계산한 값은 그렇게 밝혀서만 쓴다. 추정과 재지 않은 정확도는 쓰지 않는다. 토큰은 "(text length ÷ 4)"와 함께만 쓴다. 아직 재지 않은 자리는 `[측정 뒤 기입]`으로 둔다. 공개 직후 목걸이 페이지의 "Measured in our test runs …" 줄이 생기면 그 줄을 그대로 옮긴다.

### 5.1 공개 화면과 에이전트용 안내: 자동으로 나가는 것(판정 스냅샷 기준, 코드 변경 없음)
| 자리 | 나가는 문구(영어 원문) | 근거 |
|---|---|---|
| 홈·Workflows 카드 | "Why a necklace: an agent that finds several agents, calls each one and merges their answers spends tokens and time on every step, and under a time limit it can settle on a wrong answer. A necklace does those steps in one call: agents we tested, in a fixed order, with fallbacks, returning one answer." + 목걸이 링크 + 주문 링크 | necklace_surface.WHY, why_card |
| 목걸이 페이지 단계별 표시 | 검증 진주는 "Verified pearl", 임시 멤버는 "Under verification". 외부 임시 멤버 설명: "Under verification: the agent answered our test for this step within the last 7 days with a score of at least 70, below the verified-pearl bar (85 or more on 2 different days). …" (숫자는 판정 스냅샷 member_rules). 자체 대체(web 자리의 wiki-grounding): "AgentValCon agent, under verification: our own agent for this step, which passed our substitute check; …" | provisional_note, OWN_PROVISIONAL_NOTE (PM 11-16: 임시 멤버는 "통과 뒤 둘째 날 대기"가 아님. 11-16 약관 판정 4835e5c3으로 34550·34807·32841·143970은 사슬에서 빠짐. 공개 때 어느 멤버가 임시인지는 판정 스냅샷 standing이 정함) |
| 원천 문장(요약 뒤) | "What each step uses (as of 2026-11-17): the web step answers from English Wikipedia, quoting the lead sentences of the best-matching articles with links (not a web search); the background step summarises the one Wikipedia article on the topic, so both come from Wikipedia; papers come from two third-party paper search agents (one of them uses OpenAlex; neither is verified yet), and from our own Crossref search only when both fail; news is optional." | necklace_sources.json → 페이지·llms·MCP 도구·A2A skill·/api/necklaces. 정의의 summary("a grounded web answer … an encyclopedia summary")는 판정 지문이라 내일 전에 못 바꿔 화면에서 바로잡음 |
| 측정 줄 | "Measured in our test runs on N cases (first – last date): one call, a median of S s per case, A% correct, about T tokens (text length ÷ 4). From the same runs' records (not a separate run), an agent calling the same 4 agents itself would make C calls and handle about U tokens (text length ÷ 4), taking about X s if it sent each step's calls at the same time. Finding the tools and merging the answers are not counted." | comparison_line(PM 11-16 표시 규칙: "Measured"는 목걸이 쪽 잰 값만, 직접 호출 쪽은 같은 실행 기록에서 계산했다고 밝힘, 직접 호출 쪽 정확도·찾기·합치기 추정치는 내지 않음). **지금 topic 측정 없음 → 줄이 나가지 않음** |
| 무료 | "Free to run for now. If that changes, we will say so on this page first." | FREE_NOW |
| 추천 답 첫 줄(Chat·find_agents·A2A) | "Free to run now: Topic evidence brief (a necklace of tested agents): call tool `necklace_topic_evidence_brief` with {"topic":"<주제>"}. https://agentconcierge.biz/necklaces/topic-evidence-brief" | necklace_lead, 호출부 refs/heads/growth/necklace-lead-callsite(c0dc9f45, r11) |
| llms.txt·A2A 카드 skill | "Necklaces you can run" 줄(이름·요약·MCP 도구·A2A skill·입력 예·Free to run for now·측정 줄) | llms_section, skills |

범위 문구 점검(오탐 우선, 11-16 0e3ef529): 운영 30일·Chat 110·1k·30과제 질의 1,431건 중 topic 줄이 붙는 것 17건, 모두 범위 안(논문·문헌 주제 질의), 범위 밖 0.

### 5.2 공통 사실 (1절의 `{…}` 자리, topic용)
- `{NECKLACE}` Topic evidence brief / `{SLUG}` topic-evidence-brief / `{TOOL}` necklace_topic_evidence_brief / `{SKILL}` necklace-topic-evidence-brief
- One line(게시 글용, 원천에 맞춤): "A cited brief on one topic: an answer quoting the best-matching Wikipedia articles, a summary of the topic's own Wikipedia article, papers from third-party paper searches (one uses OpenAlex; not verified yet) with our Crossref search as a fallback and, when available, recent news." (화면 요약은 판정 정의 그대로이고 원천 문장이 뒤에 붙음)
- `{STEPS}`: 4 steps (an answer from Wikipedia, paper search (two third-party searches, not verified yet; our Crossref search as fallback), a Wikipedia summary of the topic required; news optional). web·background 두 자리는 원천이 같은 위키백과다(다른 출처라고 쓰지 않음). 단계별 멤버와 Verified/Under verification 표시는 공개 시점 페이지를 그대로 옮긴다(판정이 정함, 지금 적지 않음).
- `{INPUT}`: `{"topic": "retrieval augmented generation"}` (게시 당일 실제로 돌린 입력으로 바꾼다)
- `{ANSWER}`: [측정 뒤 기입: 게시 당일 실제 호출 결과 첫 줄들과 단계 목록, 손대지 않은 그대로]
- 시간: [측정 뒤 기입: 게시 당일 그 호출이 실제 걸린 시간]
- 토큰·호출 수·정확도: [측정 뒤 기입: 목걸이 페이지 "Measured in our test runs …" 줄을 그대로. 정확도는 목걸이 쪽만 있음(직접 호출 쪽 정확도는 재지 않아 쓰지 않음). 토큰은 "(text length ÷ 4)"와 함께만. 없으면 1절의 MCP-Universe 인용만]
- 한계: "Covers one topic per call; sources are English Wikipedia (two steps), third-party paper searches not yet verified (our Crossref search as fallback) and news. Some steps may be led by an agent under verification; the page shows which, step by step. Free for now."

### 5.3 채널별 초안 (영어). 게시는 사용자 확인 뒤
**Reddit r/mcp** (규칙 원문 확인 필요: 자기 홍보·플레어. AI 금지 조항이 있으면 사용자가 다시 씀)
```
Title: Free MCP tool: one call for a cited brief on any topic (Wikipedia + papers + news)

I'm the maker. AgentValCon tests MCP servers and A2A agents with real read-only calls. When a few of them do
a job better together than alone, we join them into a "necklace": one tool call instead of finding, calling
and merging several servers yourself.

The first one is Topic evidence brief: an answer quoting the best-matching Wikipedia articles, a summary of
the topic's own Wikipedia article, papers from third-party paper searches (one uses OpenAlex; not verified yet) with our Crossref search as a fallback
and, when available, recent news, in one answer.
No key: tool `necklace_topic_evidence_brief` on https://agentconcierge.biz/mcp
Input: {"topic": "<topic>"}
Answer (first lines, today's real run): [측정 뒤 기입]
Time for that call: [측정 뒤 기입]

Why one call: [목걸이 페이지 "Measured in our test runs …" 줄 그대로, 없으면 MCP-Universe 인용]

Limits: one topic per call; some steps are led by an agent still under verification (the page shows which);
some results carry a labelled Sponsored line; run from Korea; free for now.
Missing a necklace you need? https://agentconcierge.biz/necklaces/request (no contact details asked)
What failed for you is the most useful feedback.
```

**Reddit r/AI_Agents 주간 Project Display 스레드 댓글** (별도 글 아님)
```
Topic evidence brief: one MCP/A2A call returns a cited brief on a topic (answers and a summary from Wikipedia,
papers, recent news when available). Free, no key: https://agentconcierge.biz/necklaces/topic-evidence-brief
Measured: [측정 뒤 기입]. Some steps are still under verification and say so on the page. Feedback welcome.
```

**Product Hunt** (사용자 계정 필요)
- Tagline (60자 안): `Cited topic briefs from tested agents in one call` (50자)
- Description: 5.2 One line + 한계 세 가지(한 번에 한 주제, 검증 중 단계 표시, 무료·Sponsored 표시)
- 첫 댓글: r/mcp 초안 첫 두 단락을 사용자 말로 줄임. 업보트 요청·경품 없음.

**Hacker News (Show HN)·dev.to**: AI가 쓴 글 금지라 초안을 주지 않는다. 사용자가 5.2 사실 목록으로 직접 쓴다.
- Show HN 제목 예(사용자 판단): `Show HN: Topic evidence brief – Wikipedia, papers and news in one MCP call`

### 5.4 채널별 자기 홍보 규칙 요약 (0절에서 정리한 원문 기준)
| 채널 | 규칙 | 할 일 |
|---|---|---|
| Hacker News | AI가 생성·편집한 글 금지, 업보트 요청 금지 | 사용자가 직접 씀 |
| dev.to | AI 도움 글은 밝혀야 하고 사업 홍보 금지 | 홍보 글 불가, 기술 글만 사용자가 직접 |
| Reddit r/mcp·r/AI_Agents | 원문 미확인(이 세션 도구가 reddit.com을 거부, 우회하지 않음) | 게시 전 사용자가 규칙·플레어 확인 |
| Product Hunt | 업보트 요청·경품 조건·대량 DM 금지, 계정 1인 1개 | 계정은 사용자, 문구는 위 초안 |
| (모든 채널 공통, 우리 규칙) | 숫자는 실제로 잰 값만. "Measured"는 실행해 잰 값에만. 같은 실행 기록에서 계산한 값은 그렇게 밝힘. 추정·재지 않은 정확도는 쓰지 않음. 토큰은 "(text length ÷ 4)"와 함께 | 목걸이 페이지의 측정 줄을 바꾸지 않고 옮김 |
| Lobsters | 가입 70일 안 자기 홍보 불가 | 제외 |

## 6. topic v2 공개 (11-18 12:50 판정 통과 시, PM 11-17 지시)

5절은 11-17 1회차 기준 문구다. 11-18에는 v2 판정 스냅샷이 정하는 것을 그대로 옮기고, 그 전에는 적지 않는다.

### 6.1 판정 뒤 바로 옮길 것 (지금은 빈칸)
| 자리 | 채우는 곳 | 지금 |
|---|---|---|
| 단계별 멤버와 표시(Verified pearl / Under verification / AgentValCon agent, under verification) | 공개 시점 목걸이 페이지 그대로 | [판정 뒤 기입] |
| 임시 멤버 수와 자체 멤버 수 | 판정 스냅샷 standing·own_substitute | [판정 뒤 기입] |
| 원천 문장("What each step uses …") | necklace_sources.json의 topic 문장. v2에서 papers 자리 순서가 바뀌었으므로(PM 11-16 18:31: arxiv-search부터) 판정 스냅샷 멤버와 문장이 맞는지 다시 확인 | [판정 뒤 확인] |
| 측정 줄("Measured in our test runs on N cases …") | 목걸이 페이지에 줄이 생기면 그대로 | [측정 뒤 기입] |
| 실제 호출 한 번(입력·답 첫 줄·걸린 시간) | 게시 당일, 공개 주소·새 연결로 한 번 | [측정 뒤 기입] |

밝힐 것(모든 채널 공통):
- 임시 멤버: 단계마다 "Under verification"을 그대로 보이고, 게시 글에도 "some steps are led by an agent still under verification (the page shows which)"를 넣는다.
- 자체 멤버: AgentValCon이 만든 에이전트가 맡은 단계는 "our own agent"라고 밝힌다(페이지의 OWN_PROVISIONAL_NOTE 문구 그대로).
- 숫자: 판정 결과와 공개 주소에서 잰 값만 쓴다. 추정과 재지 않은 정확도는 쓰지 않는다. 토큰은 "(text length ÷ 4)"와 함께만 쓴다.

### 6.2 추천 답 맨 앞 목걸이 실행 줄(3안)
- 코드: growth/necklace-open-1118(개발 브랜치 끝 위 9개)
  - c0dc9f45 호출부: Chat·find_agents·A2A
  - 목걸이 문구 7개(11-16)
  - 2안 뒤따름 수정 1개
- 켜지는 조건: 목걸이가 공개 상태(necklace_surface.live, 판정 스냅샷이 offered)일 때만 켜진다. 그 전에는 답이 바뀌지 않는다(시험 test_nothing_changes_while_no_necklace_is_open).
- 범위: necklace_leads.json의 문구에 맞는 과제만 해당한다(논문·문헌 주제).
- 입력: 과제에서 확실할 때만 채운다(_TOPIC 문구: "papers about X" 등). 2안의 자유 검색 채움은 목걸이 입력에 쓰지 않는다(fill free_text=False, 11-17). 그래서 "find an MCP weather forecast API"에 topic을 "weather forecast"로 넣지 않는다.
- 목걸이 경로 파일(agent_market/necklaces/*)은 바꾸지 않았다. front·추천 쪽(concierge)만 바꿨다.
- 배포: 11-18 낮 묶음(12:50 판정 뒤). 판정 실패면 코드는 나가도 켜지지 않는다(live가 아니므로).

### 6.3 사용자 몫 (PM 11-17 승인 때 정리)
| 일 | 누가 | 이유 |
|---|---|---|
| Product Hunt 계정 만들기와 출시 등록 | **사용자** | 계정 생성은 본인만 할 수 있음(1인 1계정 규칙) |
| Hacker News·dev.to 글 쓰기 | **사용자** | 두 곳 모두 AI가 쓴 글을 금지함. 6.1·5.2 사실 목록으로 직접 씀 |
| Reddit r/mcp·r/AI_Agents 규칙 원문 확인 | PM이 사용자가 보는 방식(데스크톱 앱, 읽기만)으로 확인 | 이 세션 도구는 reddit.com을 읽지 못함(우회하지 않음) |
| 모든 채널의 게시 실행 | **사용자 확인 뒤** | 외부 게시는 사용자 확인 사항 |
| 빈칸 채우기(멤버·측정 줄·실제 호출) | 성장·유통 | 11-18 12:50 판정과 공개 주소 측정 뒤, PM에 보냄 |
