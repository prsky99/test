# "Agentcon" 이름 충돌 확인 (PM 11-14 05:4x, 성장·유통)

PM 지시: 화면을 바꾸기 전에 "AgentCon"이라는 기존 행사·제품·상표가 있는지, 검색 결과에서 얼마나 겹치는지 조사한다.
- 조사 방법: 무료 웹 검색 5회(11-14). 유료 상표 조사나 변리사 확인은 하지 않았다(지출 0).
- 작업본에 적용했던 브랜드 변경은 되돌려 보관했다(`gateway-data/brand/agentcon-brand-20261114.patch`). 확인이 끝나기 전에는 화면을 바꾸지 않는다.

## 1. 찾은 것

| 대상 | 무엇 | 우리와 겹치는 정도 |
|---|---|---|
| **AgentCon (Global AI Community)** | AI 에이전트를 만드는 개발자 대상의 무료 커뮤니티 행사 시리즈("AgentCon World Tour"). 한 목록 페이지 기준 67개 도시, 36개국. 2026년에도 London, Dallas, Bengaluru 등에서 열림. Microsoft 파트너 블로그가 2026 행사를 홍보하고, 일부 지역 행사는 Microsoft·AvePoint 등이 후원 | **매우 큼**: 같은 주제(AI 에이전트), 같은 대상(개발자), 같은 철자. "agentcon" 검색 결과의 대부분이 이 행사다 |
| agentcon.io | 2026-05-13~14에 열린 하루짜리 온라인 AI 행사(운영자·창업자 대상) | 큼: 같은 이름, 같은 분야. 도메인 agentcon.io를 이 행사가 쓴다 |
| agentcon.com, agentcon.ai | 검색으로는 주인을 확인하지 못함 | 모름 |
| 상표 "AGENTCON" | 검색 결과에서는 등록·출원 기록을 찾지 못함. 비슷한 것: AGENTC(출원, 2026-02 공고), AGENT RECON(미국·영국 출원), AGENTSY(등록) | 찾지 못했지만 이 검색이 상표 DB 전체를 보는 것은 아니다. 미국 USPTO, 영국 IPO, 한국 KIPRIS를 직접 봐야 한다(무료) |
| 제품 "Agentcon" | 같은 이름의 AI 제품 회사는 찾지 못함. 비슷한 이름: AgentConn(ComputeLeap), Agentrecon | 작음 |

## 2. 영향

- **검색**: "agentcon"으로 찾는 사람은 대부분 위 행사를 찾는다. 행사 쪽이 페이지·링크·역사가 훨씬 많아서 우리 사이트가 이 이름으로 첫 쪽에 오르기는 어렵다. 지금 "agent concierge"도 평균 11위인데, 브랜드 검색을 새로 시작하는 셈이 된다.
- **혼동**: 같은 분야(AI 에이전트)의 같은 철자다. 개발자·에이전트가 우리를 행사의 일부나 후원사로 오해할 수 있다. 반대로 행사 쪽에서 혼동을 문제 삼을 수 있다.
  - 미국은 등록 없이도 먼저 쓴 이름에 권리가 생길 수 있다.
  - 법적 판단은 하지 않았다. 법률 자문은 수익이 커진 뒤로 미루기로 한 사용자 결정이 있다.
- **에이전트 쪽**: llms.txt, A2A 카드, MCP 서버 이름은 에이전트가 이름으로 서비스를 고를 때 쓰인다. 이름이 겹치면 모델이 행사 정보와 섞어 답할 수 있다.

## 3. 안 (PM이 사용자에게)

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **1. 붙여 쓰는 표기로 구분(권장)** | 이름을 언제나 **"Agentcon Gateway"** 또는 **"Agentcon — Agent Value Gateway"** 한 덩어리로 쓴다. 로고 글자·title·JSON-LD name·카드 name 모두 같은 표기. "Agent Concierge"는 alternateName·부제로 유지. 도메인 agentconcierge.biz가 구분을 돕는다 | 사용자 결정(Agentcon)을 지키면서 행사와 갈라진다. 검색어 "agentcon gateway"는 겹치지 않는다 | 이름이 길어진다. 짧게 줄여 부르면 다시 겹친다 |
| 2. 이름 그대로 "Agentcon" | 05:2x 결정 그대로 | 짧다 | 검색·혼동 위험이 위와 같다 |
| 3. 공개 이름은 "Agent Concierge" 유지, Agentcon은 내부·부제 | 공개 첫 이름은 지금 그대로. "by Agentcon"이나 "Agent Value Gateway"를 부제로 | 11-14 검색 신호를 그대로 쓴다. 충돌 위험이 없다 | 사용자 결정(Agentcon)과 다르다 |

- 어느 안이든 적용 전에 USPTO·UK IPO·KIPRIS에서 "AGENTCON"을 무료로 직접 검색해 기록을 남기기를 권한다. 브라우저 검색만 하고 계정은 만들지 않는다.
- 안 1을 고르면 보관한 패치에서 이름 문자열만 바꾸어 다시 적용한다. 바뀌는 곳은 title, og:site_name, application-name, JSON-LD, 머리말, 카드, llms, 응답 이름이다. MCP serverInfo name은 PM 05:4x 동의대로 `agent-concierge`로 둔다.

## 출처
- [Global AI Community — AgentCon](https://globalai.community/events/agentcon/)
- [AgentCon 시리즈 소개](https://globalai.community/agentcon/)
- [Microsoft Partner News — AgentCon 2026](https://techcommunity.microsoft.com/t5/partner-news/microsoft-partners-accelerate-your-ai-journey-at-agentcon-2026/ba-p/4496752)
- [AvePoint — AgentCon 2026](https://www.avepoint.com/events/agentcon-conference-2026)
- [AvePoint — AgentCon 2025 Southeast Asia](https://www.avepoint.com/sg/blog/strategy-blog/agentcon-2025-southeast-asia-welcomes-agentic-ai)
- [Crunchbase — AgentCon Spring 2026 (agentcon.io)](https://www.crunchbase.com/event/agentcon-spring-2026)
- [Justia — AGENT RECON 상표](https://trademarks.justia.com/997/07/agent-99707900.html)
- [AGENTC 99217872](https://trademarkdir.com/trademark/agentc-99217872)
