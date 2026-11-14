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

## 1. 제공자 안내 메일 (영어, 조직의 공개 문의 경로로 한 번만)

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

## 2. 커뮤니티 게시 초안 (게시는 사용자가 직접, 11-10 결정)

### Reddit r/mcp
제목: `Sponsored placements for MCP servers on a discovery site that tests them (labelled, no effect on results)`
```
We run AgentValCon, which tests public MCP servers and A2A agents and lists them by task with the
results (method: https://agentconcierge.biz/methodology). Server makers asked how to get seen more,
so we opened Sponsored placements: one labelled card below search results and below Chat answers
for a task category. Ads never change test results, grades or the order of results, and we do not
track people for ads. {price line}. Details: https://agentconcierge.biz/advertise
```

### X (280자)
```
MCP server makers: you can now book a labelled Sponsored placement next to task search results on
AgentValCon. It never changes test results or rankings, and no ad tracking. {price line short}
agentconcierge.biz/advertise
```

## 3. 승인 묶음 (PM이 사용자에게)

| # | 일 | 성격 | 조건 |
|---|---|---|---|
| 1 | 후보 조직에 안내 메일(최대 50곳, 조직당 1회) | 외부 발송 | `/advertise`가 배포된 뒤. USDC 문구는 스위치 상태에 맞춤 |
| 2 | Reddit·X 게시 | 사용자가 직접 게시 | 같은 시점 |

- 시점: `/advertise` 배포 뒤. 결제 스위치를 켜기 전에 보내면 "USDC payments open soon" 문구를 쓴다.
- 측정: 신청 수(AD Coin 광고주 신청 기록), `/advertise` 방문 수(트래픽 기록), 예약·결제 수(AD Coin 팀)
