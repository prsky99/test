# 첫 매출: 제공자 대상 외부 연락 초안 (AI AD Coin, 2026-11-17, PM 10:5x 승인 ④)

**초안만이다. 보내거나 게시하지 않는다.** 실행은 PM을 거쳐 사용자 확인을 받은 뒤에 한다(외부 게시·연락은 사용자 확인 사항).

## 누구에게, 어떤 길로
- 대상: 카탈로그에서 활성 등급 A 이상이고, 목걸이 카테고리(web_search, security, dev_tools, travel_maps_weather, education_culture, commerce_marketing)에 속하는 공개 에이전트의 제공자.
- 우리가 가진 연락 수단은 없다. 방문자와 제공자의 메일을 모으지 않기 때문이다(11-10, 11-15 결정).
- 쓰는 길은 하나다: 제공자가 자기 사이트에 공개한 연락 주소. 보내는 쪽은 `contact@agentconcierge.biz`다(11-10 결정).
- 쓰지 않는 길(PM 11-17): 공개 저장소의 이슈나 토론. GitHub을 유입 채널로 쓰지 않는다는 사용자 결정(11-10)이 있고, 남의 저장소에 홍보 이슈를 여는 것은 스팸이다.
- 하지 않는 것: 대량 발송, 같은 제공자에게 두 번 이상 보내기, 사람이 아닌 에이전트 엔드포인트로 홍보 메시지 보내기.
- 수량: 10곳 이하.
- 보내는 시점: 첫 목걸이가 공개되고, 목걸이 응답의 광고 노출 숫자(잰 값)가 생긴 뒤.
- 실행: 사용자 확인을 받은 뒤(PM이 모아서 묻는다).

## 본문 (영어, 수정해 쓸 틀)

Subject: A labelled Sponsored spot after agent answers in {category}

Hi {provider},

AgentValCon (agentconcierge.biz) checks public A2A and MCP agents and answers other agents' "which agent should I use" calls. {agent_name} is in our catalog with grade {grade} (latest check {date}; report: {report_url}).

We now sell one labelled "Sponsored" spot after our MCP and A2A answers in the {category} category — including the answers of our necklaces (workflows that chain several tested agents in one call). The offer sits in its own `sponsored` field after the results, and it never changes results, tests or ranking. Each offer also shows your agent's own measured grade and test score, even when they are low.

- Price: 5 USDC on Base per placement per day, or a custom plan sized to your budget. You pay once per booking from your own wallet: no prepaid balance, no subscription, no stored funds.
- What you get: impressions and clicks counted the same way for everyone, listed at agentconcierge.biz/ads/library.
- How: agentconcierge.biz/advertise

If this is not for you, no reply is needed and we will not write again.

— AgentValCon, contact@agentconcierge.biz

## 보내기 전에 넣을 것 (지어낸 숫자 없음)
- `{grade}`, `{date}`, `{report_url}`는 그 제공자의 실제 기록에서 채운다.
- 노출 수나 효과 숫자는 넣지 않는다. 오늘 밤 목걸이 광고 칸이 나간 뒤 잰 값이 생기면 그것만 쓴다(PM 지시: 잰 값만).
- 11-18 계정 없는 견적 API(B)가 나가면 "How" 줄에 API 두 번 호출 경로를 더한다.
