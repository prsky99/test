# 제공자 입구 화면 초안 (성장·유통, 2026-11-15, 11-19 frontend 묶음 대상)

- 근거
  - PM 10:57 배정. 매출 전면 조사 3.3절 "제공자가 들어올 입구가 없다".
  - 에이전트 팀 설계 `docs/PROVIDER_SELF_CLAIM.md`. 1단계는 A(well-known 파일)와 C(프로토콜 안 표시)이고, 공개 "확인됨" 표시는 없습니다.
  - 고객 API: `agent_market/provider_self_claims_service.py`, `/api/customer/provider-claims`.
- 이 문서는 화면 초안과 문구만 담습니다. 구현은 에이전트 팀 API가 굳고(11-17), DB 표가 승인된 뒤(11-18)에 11-19 묶음으로 합니다.
- 공개 문구는 영어이고, 설명은 한국어입니다.
- 디자인 시스템(Pearl Connection 틀·공용 assets)과 화면 정책(영역별 로딩, 화면을 덮는 팝업 없음, 고정 내용은 HTML로 바로)을 따릅니다.

## 1. 에이전트 페이지 입구 (`/agent/<id>`, 증거 페이지와 Listing 페이지 둘 다)

- 지금 줄(c6798d67)은 이렇습니다.
  - 문구: `Is this your agent? See how it is verified · Advertise in Sponsored`
  - 두 페이지 모두에 들어가고, 광고 링크에는 `?from=agent-page`가 붙습니다.
- 바꿀 줄(초안): 맨 앞에 확인 링크를 하나 더합니다. 나머지 두 링크와 문구는 그대로입니다.

```
Is this your agent? Prove you run it · See how it is verified · Advertise in Sponsored
```

- `Prove you run it`의 연결 주소
  - `/customer/provider-claims/start?agent=<id>`
  - 로그인하지 않았으면 고객 로그인을 거쳐 같은 주소로 돌아옵니다.
- 정할 것(에이전트 팀·운영 쪽)
  - 로그인 뒤 돌아오는 인자 이름
  - 이 화면 경로를 고객 워크스페이스 안에 둘지
- 이 줄은 공개 페이지에 있으므로 확인 여부를 보여 주지 않습니다(PM 결정 3). 확인된 제공자가 와도 같은 줄입니다.
- 에이전트를 측정하는 숫자(점수·순위)는 이 줄과 섞지 않습니다.

## 2. 시작 화면 (`/customer/provider-claims/start?agent=<id>`, 로그인 필요)

고정 내용은 HTML로 바로 나오고, 자원 이름과 방법 선택만 그 영역 안에서 불러옵니다.

```
Prove you run <agent name>

This shows that you can change something at the agent's address right now. It does not
change its grade, rank, tests or recommendations, and nothing about it is shown publicly.

How do you want to prove it?
( ) Publish a file on your site                 <- well_known (A)
    https://<origin>/.well-known/agentvalcon-claim.json
    Covers every listed agent on this origin.
( ) Add a marker inside the agent               <- protocol (C)
    MCP: in the initialize result (instructions or _meta). A2A: in the agent card extensions.
    Covers this agent only. Use this on shared hosting.

[ Get my one-time value ]
```

- 공유 호스트(`shared_host_use_protocol`)면 A를 막고, 안내 한 줄과 함께 C만 고를 수 있게 합니다.
- MCP·A2A가 아닌 자원(`protocol_needs_mcp_or_a2a`)이면 C를 막습니다.

## 3. 게시 안내 (준비 응답 `instructions`를 그대로 보여 줌)

```
Your one-time value is shown only now. Copy it before you leave this page.

Publish exactly this JSON at
https://<origin>/.well-known/agentvalcon-claim.json
{"profile":"agentvalcon-provider-claim-v1","claim":"<claim id>","nonce":"<nonce>"}
Serve it with HTTP 200, no redirect, at most 4 KiB.

This request stays open for 24 hours. When the file is live, press Check.
[ Check now ]   [ Withdraw ]
```

- C의 MCP 안내: `Put agentvalcon-claim=<nonce> in the initialize result (instructions or _meta). Do not put it in a tool description: tool descriptions are stored and shown publicly.`
- C의 A2A 안내: `Add {"uri":"https://agentconcierge.biz/ext/provider-claim/v1","params":{"nonce":"<nonce>"}} to capabilities.extensions in your agent card.`
- 일회용 값은 이 화면에서 한 번만 보입니다. 다시 열면 값은 없고 "새 값 받기"만 있습니다(서버는 해시만 저장).
- 확인 버튼은 누를 때만 요청을 한 번 보냅니다. 자동 재시도는 없습니다. 진행 표시는 버튼 옆에 작게 둡니다.

## 4. 내 에이전트 (`/customer/provider-claims`)

| 칸 | 내용 |
|---|---|
| 목록 | 에이전트 이름, 방법, 범위(origin 또는 자원 하나), 상태, 만료일. 상태 문구: `Waiting for your file` / `Verified until <date>` / `Lapsed: the last two checks failed` / `Expired: not checked within 24 hours` / `Withdrawn` |
| 에이전트 하나 열기 | 시험 기록(헬스 상태, 최근 오류 코드, 마지막 시험 호출, 시험 보고서 v2 점수와 실패 사유), 재시험 대기열 위치와 예상 시각, 정정 요청 |
| 정정 요청 폼 | Field(name, description, category), proposed text(1,000자), evidence URL(선택). 보낸 뒤 상태: `Received` / `Under review` / `Decided` (권고 내용은 보이지 않음, PM 결정 5) |
| 안내 | `Verification never changes grades, ranks or test results, and paying never moves a retest.` |

## 5. 사유 코드 → 화면 문장 (영어)

| 코드 | 문장 |
|---|---|
| `provider_claims_not_available` | Provider verification is not open yet. |
| `resource_not_found` / `invalid_resource` | We could not find this agent in the catalog. |
| `resource_not_public_https` | Only agents at a public HTTPS address can be verified. |
| `shared_host_use_protocol` | This address is shared hosting, so a file cannot tell its customers apart. Use the marker inside the agent. |
| `protocol_needs_mcp_or_a2a` | A marker inside the agent works for MCP servers and A2A agents only. Publish the file instead. |
| `already_verified` | You have already verified this. |
| `too_many_claims` | You have 20 open requests. Withdraw one first. |
| `claim_not_found` / `claim_not_pending` | This request is no longer open. Start a new one. |
| `claim_changed` | The agent's address changed since you started. Start a new request. |
| `too_many_checks` | You have used today's 10 checks. Try again tomorrow. |
| `origin_checked_recently` | This site was checked less than a minute ago. Wait a minute and check again. |
| `request_failed` | We could not reach the file or the agent. Check that it is live, then press Check again. |
| `response_too_large` | The answer was larger than 4 KiB. Serve only the JSON shown above. |
| `not_public_address` | The address did not resolve to a public internet address. |
| `call_budget_refused` | We have checked this domain enough for today. Try again tomorrow. |
| `resource_moved` | The agent's address moved off this site, so it is no longer covered. |
| `busy` | We are busy right now. Try again in a few seconds. |
| `rate_limited` | Too many requests. Wait a minute. |
| 그 밖의 확인 실패 | The value we found did not match. Copy it again exactly, then press Check. |

## 6. 에이전트 팀과 맞출 것 (설계 문서가 굳으면 이 초안을 고침)

1. 로그인 뒤 돌아오는 방식과 고객 화면 경로 이름. 위 `/customer/provider-claims/...`는 가안입니다.
2. 확인 실패의 세부 사유 코드 목록. 위 5절에 없는 코드가 나오면 문장을 더합니다.
3. 혜택 응답(`benefits`)의 필드 이름. 시험 기록·대기열 위치·정정 상태를 화면 칸에 맞춥니다.
4. 표가 없을 때(409)는 입구 줄을 숨기지 않습니다. 시작 화면에서 "아직 열리지 않음"을 보여 줍니다. 공개 링크가 404로 끝나지 않게 하기 위해서입니다.
