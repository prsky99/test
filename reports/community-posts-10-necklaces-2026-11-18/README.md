# 목걸이 10개 공개 뒤 커뮤니티 게시 초안 (성장·유통, 사용자 결정 11-18 PM 11:56)

- 결정: 커뮤니티 게시는 **공개된 목걸이가 10개 이상이 된 뒤**에 한다. 초안은 지금 쓰고, 게시는 그때 사용자 확인을 받은 뒤 한다. 첫 목걸이 공개 때의 초안(reports/launch-posts-2026-11-16 7절)은 목걸이 하나짜리라 10개 런치에는 이 문서를 쓴다.
- 숫자는 **우리가 잰 값만** 쓴다. 아래 `{…}` 칸은 그날 목걸이별 측정 줄에서 그대로 옮기고, 재지 않은 값은 비워 둔다. 일반론("faster/cheaper")은 쓰지 않는다(근거: 다중 에이전트가 토큰을 더 쓴다는 2026 연구들, reports/necklace-marketing-2026-11-18 2절).
- **사람이 직접 쓰는 곳:** Hacker News는 AI가 만든 글을 금지한다(뉴스 가이드라인, 11-15 확인). 그래서 HN은 완성 글이 아니라 **사실표와 제목 후보**만 주고 사용자가 자기 말로 쓴다. Reddit은 서브레딧마다 자기 홍보 규칙이 다르므로, 게시 전에 사용자가 각 서브레딧 규칙·플레어를 직접 읽고 맞춘다(11-15 기록: 이 세션 도구가 reddit.com을 읽지 못했다). X는 글자 수와 링크만 맞춘다.

## 0. 지금(11-18) 이미 잰 값 — 출처와 시각을 붙여 쓴다
| 사실 | 값 | 출처 |
|---|---|---|
| 카탈로그 활성 항목 | A2A 245,033 · x402 104,550 · MCP 44,797(합 394,380) | 운영 DB 읽기 집계, 11-18 11:5x |
| 공개 진주 | 63(최종 26 + 검증 37), 서로 다른 에이전트 60, 서로 다른 역할 26 | gateway-data/pearls/public-pearls.json, 11-18 오전 |
| 진주 기준 | 점수 85점 이상 + 서로 다른 날 2회 성공(정확도 확인 필수) | /methodology, verify-snapshot rules |
| 목걸이 관문 | 시험 60회 중 57회 이상 통과(95%), 95번째 백분위 응답 5초 이하 | agent_market/necklaces/gate_rules.py |
| 서버 이름 | 사람이 읽는 이름은 AgentValCon, MCP 식별자는 `agent-concierge`(처음 한 번 밝힌다) | server.json 1.1.0 |
| 접속 | `https://agentconcierge.biz/mcp`(키·가입 없이, 목걸이 실행은 지금 무료) | llms.txt |
- 카탈로그 수는 게시 당일 다시 센다(매일 바뀐다). 진주 수도 당일 `/api/pearls/public`의 counts로 다시 쓴다.

## 1. 공통 사실표 (모든 채널 앞에 둔다, 영어)
- What it is: AgentValCon finds AI agents and MCP servers for a task and tests them with real read-only calls. An agent becomes a verified pearl after scoring at least 85/100 on two different days.
- What a necklace is: three or more tested agents joined into one workflow, so one call replaces finding, calling and merging several servers yourself.
- The gate: a necklace opens only after at least 57 of 60 test runs pass (95%) with a 95th-percentile response of 5 seconds or less.
- What we measured per necklace (fill from each necklace page, only values that exist): `{necklace}` — answer accuracy `{x of y checks}`, time `{origin path s / public s}`, tokens `{with / without}` against doing the same task yourself.
- Free while in launch. Paid only after 300 successful runs and 20 different callers per necklace (the rule is public).
- Try without a key: `https://agentconcierge.biz/mcp`, tool names `necklace_<slug>`; the pages: `https://agentconcierge.biz/necklaces/<slug>`.
- Limits we state: some members are our own agents still under verification, and the page shows which; DKIM and other checks a necklace does not do are listed on its page.

## 2. Hacker News — Show HN (사용자가 직접 쓴다)
- 제목 후보(80자 안):
  1. `Show HN: Ten tested agent workflows behind one MCP server, free while in launch`
  2. `Show HN: We test MCP servers with real calls and join the passing ones into workflows`
  3. `Show HN: AgentValCon – verified agent "necklaces" with measured accuracy and time`
- 사실표(위 1절)를 그대로 쓰고, 사용자가 자기 말로 첫 글을 쓴다. 넣을 것: 왜 만들었는지 한 단락, 직접 쓴 것과 비교한 측정 한 가지(`{measured}`), 한계 한 가지, "ask me anything".
- 첫 댓글(사용자): 관문 숫자와 /methodology 링크, 잰 값의 출처. 업보트·지인 동원은 요청하지 않는다.
- 하지 않는 것: 일반론, "best/fastest" 같은 말, 재지 않은 숫자.

## 3. Reddit
공통: 제목에 장점 형용사를 쓰지 않고 무엇을 했는지와 잰 값을 쓴다. 본문 끝에 "I'm the maker" 한 줄. 서브레딧 규칙(자기 홍보 허용 여부, 플레어, 요일 제한)은 게시 직전 사용자가 읽는다.

### r/mcp
- Title: `Ten MCP "necklaces": tested servers joined into one call (free, no key) — here is what we measured`
- Body (영어):
```
I'm the maker. AgentValCon tests MCP servers and A2A agents with real read-only calls and keeps the ones that pass on two different days (85+/100) as "verified pearls". A necklace joins three or more of them into one workflow, so one tool call replaces finding, calling and merging several servers yourself.

Ten are open now: {slug list with one line each}.
What we measured per necklace, against doing the same task yourself: {table: accuracy / time / tokens — only values we have}.
Gate before a necklace opens: at least 57 of 60 test runs pass (95%), p95 response 5 s or less.

No key: https://agentconcierge.biz/mcp (tools named necklace_<slug>). Free while in launch.
Limits: {members still under verification are marked on each page; the checks a necklace does not do are listed on its page}.
Missing a necklace you need? https://agentconcierge.biz/necklaces/request
```

### r/LocalLLaMA
- 관점: 로컬 모델에서 쓰는 쪽. 목걸이가 모델 호출을 대신하지 않고 **도구 호출 한 번**으로 끝난다는 점과 토큰 측정만 쓴다.
- Title: `One MCP call instead of 3-4 server calls: measured tokens and accuracy for ten tested workflows`
- Body: 위 r/mcp 본문에서 "tokens: {with / without}"를 맨 앞에 두고, 로컬 모델 클라이언트(`mcpServers` 설정 조각 1개)를 넣는다. 토큰 숫자는 **우리가 잰 것만**, 모델 이름과 측정 방법을 밝힌다. 측정이 없는 목걸이는 숫자를 쓰지 않는다.

### r/AI_Agents
- 관점: 에이전트 개발자가 도구를 고르는 문제. "어느 서버가 믿을 만한지 매번 직접 시험하지 않아도 된다"가 아니라 "우리가 시험한 결과와 날짜를 공개한다".
- Title: `We published test results for the MCP servers behind ten workflows (pass counts and dates per agent)`
- Body: 진주 페이지 하나의 예(`Passed N of M role tasks · confirmed on D different days · last checked <date>`)를 보여 주고, 10개 목록과 관문 숫자를 붙인다. 질문 하나로 끝낸다: "Which job should the next necklace cover?"(주문 제작 링크).

## 4. X (스레드, 사용자 계정)
1. `We test MCP servers with real calls and join the passing ones into workflows. Ten are open now, free while in launch, no key. {link /necklaces}`
2. `Gate before a necklace opens: at least 57 of 60 test runs pass (95%), p95 response 5 s or less. Every necklace page shows the runs, the agents used and the fallbacks.`
3. `Measured against doing the same task yourself: {one measured line}. Only values we measured.`
4. `Try: https://agentconcierge.biz/mcp — tools named necklace_<slug>. Tell us which workflow to build next.`
- 이미지: 목걸이별 공유 카드(OG 이미지)는 11-21 시안 뒤에 만든다. 그 전에는 이미지 없이 올린다.

## 5. 게시 전 체크(사용자 확인 때 함께 본다)
1. 공개 목걸이 수가 10 이상이고 각 목걸이 페이지에 잰 값이 있다(없는 값은 글에서도 뺀다).
2. 카탈로그·진주 수를 당일 값으로 바꿨다.
3. 각 채널 규칙(HN 가이드라인, Reddit 서브레딧 규칙·플레어)을 사용자가 직접 확인했다.
4. 일반론과 재지 않은 숫자가 없다. 미리보기 상태(Preview)인 목걸이는 "정식 공개"라고 쓰지 않는다.
5. 연락처는 받지 않는다는 원칙에 맞게, 글 안의 연락 방법은 사이트의 주문 제작 주소와 contact@agentconcierge.biz뿐이다.
