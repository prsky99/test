# 광고주 연락·게시 초안 (PM 11-14, 사용자 지시 "광고를 통해 코인 매출을 올리는데 문제가 없게") — 보내지 않음

결제 준비는 AD Coin 팀이, 수요(광고주)는 성장·유통이 맡는다. 이 문서는 **초안**이다. 제공자에게 보내는 메일과 커뮤니티 게시는 외부 발송·게시라 사용자 승인 뒤에만 한다(PM이 모아서 묻는다).
- 후보 50곳: `logs/growth/advertiser-candidates-2026-11-14.md`(내부용, git 제외)
  - 기준: 활성 MCP 등급 A·시험 통과 가운데 공식 MCP Registry에 자기 웹사이트가 있는 조직, 조직당 한 곳
  - 개인 연락처는 넣지 않았다.
- 광고주 페이지: `/advertise`(85f93553, 다음 frontend 묶음). 신청과 예약은 AD Coin 흐름(`/ad-coin/v2#advertising`)을 쓴다.
- 지킬 것
  - 측정값만 쓴다. "best", "guaranteed", "#1"은 쓰지 않는다.
  - 광고가 검증·점수·진주·목걸이·순위에 영향을 주지 않는다는 것을 매번 적는다.
  - 결제 스위치가 꺼져 있는 동안 USDC 결제를 열린 것처럼 쓰지 않는다.
  - 받는 쪽이 원하지 않으면 다시 보내지 않는다.

## 1. 제공자 안내 메일 — **하지 않음(헌장 1절, PM 11-14)**

- 우리 광고 상품을 파는 영리 목적 메시지다. 공개 문의 경로로 보내도 사전 동의가 없으면 "동의 없는 광고성 메시지"(정보통신망법)에 걸린다. 그래서 보내지 않는다.
- 후보 50곳 목록(`logs/growth/advertiser-candidates-2026-11-14.md`)은 **연락용으로 쓰지 않는다.** 시장 규모 파악과, 아래 2절 화면 안내의 효과를 볼 때만 참고한다.
- 아래 메일 문안은 3절(제공자가 먼저 연락해 온 경우) 답장의 바탕으로만 남긴다.

## 2. 대안: 동의 기반이거나 우리 화면 안에서만

| # | 길 | 내용 |
|---|---|---|
| 1 | 진주 카드·에이전트 페이지 안내 | 각 `/agent/<id>` 페이지 아래에 제공자용 한 줄: "Is this your agent? See how it is verified · Advertise in Sponsored" → `/methodology`, `/advertise`. 우리 사이트 안이라 메시지 발송이 아니다 |
| 2 | 제공자가 먼저 연락한 경우의 답장 | 문의, 소유권 확인, 등록 요청처럼 제공자가 먼저 연락해 온 대화에서만, 답장 끝에 한 줄로 안내한다(3절) |
| 3 | 커뮤니티 게시 | 4절, 승인 묶음 ②(게시는 사용자가 직접) |
| 4 | 찾아오게 하기 | `/advertise`를 사이트맵·llms.txt에 넣었다(85f93553). 디렉터리 등록 설명에도 한 줄 넣는다(external-drafts.md 갱신 때) |

## 3. 제공자가 먼저 연락해 온 경우의 답장 끝 한 줄 (영어)

```
If you would like more people and agents to see {server name}, you can book a labelled Sponsored
placement; it never changes test results or rankings: https://agentconcierge.biz/advertise
```
- 질문에 먼저 답하고 맨 끝에 한 번만 붙인다. 상대가 원하지 않는다고 하면 다시 쓰지 않는다.

## (참고) 하지 않는 메일 문안 — 3절 답장의 바탕

보내는 주소는 `contact@agentconcierge.biz`(11-10 결정)다. 받는 곳은 후보 목록의 조직 웹사이트에 있는 공개 문의 경로뿐이다.

```
Subject: Your MCP server on AgentValCon — optional Sponsored placement

Hello {organization} team,

We list {server name} on AgentValCon, a gateway where people and AI agents look for agents by task.
In our latest checks it is active with grade {grade} ({score}/100): {listing URL}.
How we test: https://agentconcierge.biz/methodology

If you would like more people and agents to see it, you can book a Sponsored placement next to
search results and below Chat answers for your task category:
- It is always labelled "Sponsored" and never changes test results, grades or the order of results.
- {price line: "5 USDC on Base per placement per day, paid from your own wallet when you book." or,
  while USDC is not open, "USDC payments open soon; you can apply now."}
- Your report shows how many times it was shown each day. We do not track people for ads.

Details and the application: https://agentconcierge.biz/advertise

Your listing stays the same whether or not you advertise. If you do not want messages like this,
reply "no" and we will not write again.

AgentValCon
contact@agentconcierge.biz
```
- 보내기 전 확인
  - `{grade}`, `{score}`가 보내는 날의 공개 값과 같은지 본다.
  - 조직 사이트가 영업 연락을 받지 않는다고 적었는지 본다.
  - 한 조직에 한 번만 보낸다.
  - 보낸 날짜를 기록한다.
- 거절 기록: `logs/growth/advertiser-optout.txt`(조직 도메인만)

## 4. 커뮤니티 게시 초안 (승인 묶음 ②, 게시는 사용자가 직접, 11-10 결정)

**게시 전 확인할 홍보 규칙(11-14 조사)**
- Reddit 전체: 사이트 규칙이 자기 홍보를 금지하지는 않는다. 다만 홍보 비중을 낮게(대략 10% 이하) 두라는 안내가 있고, 실제 제한은 서브레딧마다 다르다. 서브레딧 차단은 영구적이다.
- r/mcp: 규칙 원문을 자동으로 읽지 못했다(reddit가 자동 읽기를 막음, 우회하지 않음). **게시 전에 사용자가 r/mcp 사이드바 규칙을 직접 확인한다.** 자기 홍보 금지, 지정 요일, 주간 홍보 스레드가 있으면 그 규칙을 따른다.
  - 글머리에 "I run AgentValCon"처럼 운영자임을 밝힌다.
  - 같은 글을 여러 서브레딧에 한꺼번에 올리지 않는다.
- X: 2026-03부터 'Paid Partnership' 표시 기능이 생겼다. 다만 이것은 남의 돈을 받고 하는 홍보용이고, 우리 서비스를 우리가 알리는 글에는 해당하지 않는다.
  - 일부 지역(영국·EU·호주)에서는 금융·암호자산 홍보가 제한된다는 보도가 있다. 그래서 **X 글에는 USDC·결제 문구를 넣지 않고** 페이지 링크만 둔다.
- 출처
  - [Reddit 자기 홍보 규칙 안내(redship, 2026)](https://redship.io/blog/reddit-self-promotion-rules-2026)
  - [X Paid Partnership 라벨(roboin, 2026-03)](https://roboin.io/article/en/2026/03/03/x-adds-ai-and-paid-partnership-labels-to-boost-content-transparency/)
  - [X 금융·암호 홍보 제한(Payment Expert, 2026-03)](https://paymentexpert.com/2026/03/03/x-bans-crypto-partnerships/)

### Reddit r/mcp
제목: `Sponsored placements for MCP servers on a discovery site that tests them (labelled, no effect on results)`
```
We run AgentValCon, which tests public MCP servers and A2A agents and lists them by task with the
results (method: https://agentconcierge.biz/methodology). Server makers asked how to get seen more,
so we opened Sponsored placements: one labelled card below search results and below Chat answers
for a task category. Ads never change test results, grades or the order of results, and we do not
track people for ads. {price line}. Details: https://agentconcierge.biz/advertise
```

### X (280자, USDC·가격 문구 없음)
```
MCP server makers: you can now book a labelled Sponsored placement next to task search results on
AgentValCon. It never changes test results or rankings, and there is no ad tracking.
agentconcierge.biz/advertise
```

## 5. 승인 묶음 (PM이 사용자에게)

| # | 일 | 성격 | 조건 |
|---|---|---|---|
| ~~1~~ | ~~후보 조직에 안내 메일~~ | **하지 않음(헌장 1절: 동의 없는 광고성 메시지)** | – |
| 2 | Reddit·X 게시 | 사용자가 직접 게시 | `/advertise` 배포 뒤, r/mcp 규칙 확인 뒤 |

- 시점: `/advertise` 배포 뒤. 결제 스위치를 켜기 전에 보내면 "USDC payments open soon" 문구를 쓴다.
- 측정: 신청 수(AD Coin 광고주 신청 기록), `/advertise` 방문 수(트래픽 기록), 예약·결제 수(AD Coin 팀)
