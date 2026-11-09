# AI AD Coin 화면 문구 묶음 (법률 검토용 초안)

- **작성:** 2026-11-09, AI AD Coin 팀. 변호사 검토 전 초안이다.
- **출처:** 실제 화면 소스에서 뽑았다.
  - v1 광고주 콘솔: `advertiser_page.py`
  - v1 사람 화면: `page.py`
  - v2 보상 화면: `v2/web/index.html`, `app.js`
- **원칙:**
  - 공개 화면은 영어 전용이다. 원문은 그대로 두고, 한국어 뜻과 검토 포인트를 붙였다.
  - 지금은 모두 비공개 시험이다. 운영에서 AD Coin 기능은 꺼져 있다.
- **같이 봐야 할 것:** Chat 업그레이드 확인 영역의 문구는 공용 Chat 화면 소스에 있어 이 묶음에 아직 넣지 않았다. 다음 판에 추가한다.

## 1. 광고 표시와 추천 독립성

| 화면 | 원문 | 뜻 | 검토 포인트 |
|---|---|---|---|
| v2 제안 카드 | "Sponsored offer" | 후원 제안 | 표시 위치(카드 맨 위)와 문구가 추천·보증 심사지침의 "쉽게 알아볼 수 있는 표시"에 맞는가 |
| v2 광고 본문 | "Advertisement" | 광고 | 같음 |
| v2 바닥글 | "Advertising is optional. Recommendations remain independent." | 광고는 선택이고 추천은 독립적이다 | "독립적"이라는 주장을 입증할 수 있는가(`selection_digest` 기록) |
| v2 사이드바 | "Closed test · No cash value" | 비공개 시험, 현금 가치 없음 | 시험 단계 표시로 충분한가 |
| v1 광고주 | "Your ad never changes which agent is recommended; every view is approved and rewarded, and invalid views are refunded." | 광고는 추천을 바꾸지 않고, 모든 노출은 사람이 승인해 보상되며, 무효 노출은 환불된다 | 광고주에게 하는 약속. "never"라는 단정이 적절한가 |
| v1 사람 | "Sponsors can pay for work you already chose. They never change which agent was recommended or how well it works." | 후원자는 이미 고른 작업 비용을 낼 수 있고, 추천이나 성능을 바꾸지 않는다 | 같음 |

## 2. 보상 조건과 동의

| 화면 | 원문 | 뜻 | 검토 포인트 |
|---|---|---|---|
| v2 제안 | "View the ad for at least 15 seconds. No purchase, click or answer is required. You can stop at any time." | 최소 15초 보면 된다. 구매·클릭·답변은 필요 없고 언제든 멈출 수 있다 | 보상 약정의 핵심 조건. 약관과 일치해야 한다 |
| v2 제안 | "Review & allow ad" / "Decline" | 검토 후 광고 허용 / 거절 | 동의 버튼. 미리 선택된 값이 없어야 한다(다크패턴) |
| v2 확인 | "Review before you allow" · "Confirm your choice" | 허용 전에 검토, 선택 확인 | 2단계 동의 |
| v2 진행 | "Visible time · the service confirms the reward" | 보인 시간을 서비스가 확인해 보상한다 | 판정 주체가 서비스임을 알림 |
| v2 결과 | "Your reward is confirmed. It belongs to you." | 보상이 확정되었고 당신의 것이다 | 확정된 보상은 되돌리지 않는다는 설계와 일치 |
| v2 결과 | "This view needs a review. Its reserved reward is being preserved." | 이 노출은 검토가 필요하다. 예약된 보상은 보존된다 | 검토 기간과 결과 통지 방법을 약관에 적어야 한다 |
| v2 결과 | "The viewing conditions could not be confirmed. No reward was issued." | 조건을 확인하지 못해 보상하지 않았다 | 거절 사유 안내가 충분한가 |
| v2 중복 | "the same request will not award coins twice." | 같은 요청으로 두 번 보상하지 않는다 | — |
| v1 사람 | "Approve and view (15 seconds)" / "Keep the free result" | 승인하고 보기(15초) / 무료 결과 유지 | 거절해도 불이익이 없음을 명확히 하는가 |

## 3. 선택권과 철회

| 화면 | 원문 | 뜻 | 검토 포인트 |
|---|---|---|---|
| v2 설정 | "Receiving an offer and allowing an ad are separate choices. You review every ad before it appears." | 제안을 받는 것과 광고를 허용하는 것은 따로 선택한다. 모든 광고는 보이기 전에 검토한다 | 동의를 나눠 받는 구조 |
| v2 설정 | "Share only the context you select to find relevant offers:" (Task category / Language / Broad region) | 선택한 맥락만 공유한다 | 맞춤형 광고 지침의 동의·거부권 |
| v2 설정 | "Only the task category, language and broad region you choose are shared. Your conversation stays private." | 고른 작업 분류·언어·넓은 지역만 공유하고 대화는 비공개다 | 개인정보 처리방침과 일치해야 한다(`AD_COIN_PRIVACY_FLOW.md`) |
| v2 설정 | "Stop receiving ads" · "Turning off offers stops new ads. It does not remove rewards you have already earned." | 광고 받기 중단. 이미 받은 보상은 남는다 | 철회 효과 안내 |
| v2 설정 | "Daily offer limit / Daily ad limit / Ads from one campaign per day / Daily viewing limit (seconds)" | 하루 제안·광고·캠페인별·시청 시간 한도 | 사용자 통제 수단 |

## 4. 금전 가치 표시

| 화면 | 원문 | 뜻 | 검토 포인트 |
|---|---|---|---|
| v2 잔액 | "Test coins are not redeemable. Agent payments are not enabled in this test." | 시험 코인은 상환되지 않고, 에이전트 결제는 이 시험에서 열려 있지 않다 | 선불·가상자산 오인 방지 |
| v2 바닥글 | "Closed test. Coins and budgets have no cash value. No real deposits, redemptions or agent payments are available here." | 현금 가치 없음, 실제 입금·상환·결제 없음 | 같음 |
| v2 광고주 | "This form does not deposit or issue real funds." | 이 양식은 실제 자금을 넣거나 발행하지 않는다 | — |
| v1 사람 | "Budgets and coins are virtual, payments are closed and nothing here has cash value." | 예산과 코인은 가상이고 결제는 닫혀 있다 | — |
| v1 사람 | "Coins earned through your agents are kept in your name. You can move them between your wallets or call them back at any time." | 에이전트가 번 코인은 당신 명의이고, 지갑 간 이동·회수가 가능하다 | **이전 가능성**은 선불전자지급수단 판단의 쟁점이다. 실가치 전에 문구와 기능을 함께 검토해야 한다 |
| v1 광고주 | "Unverified accounts serve up to 20,000 won a day." | 미인증 계정은 하루 2만 원까지 노출 | 시험 단계인데 원화 금액을 표시함. 가상 금액임을 함께 적어야 하는가 |
| v1 광고주 | "Closed test: budgets are virtual and nothing is charged." | 예산은 가상이고 청구되지 않는다 | — |
| v1 광고주 | "Budget is held for this campaign and returned if you stop it." | 예산은 캠페인에 묶이고 중지하면 돌려준다 | 실가치 전환 시 환급 약정이 된다 |

## 5. 광고 심사와 제한

| 화면 | 원문 | 뜻 | 검토 포인트 |
|---|---|---|---|
| v1 광고주 | "Medical, political, adult, gambling, weapon and drug categories are not available. Ads are reviewed before they serve." | 의료·정치·성인·도박·무기·약물 광고 불가, 광고는 사전 심사 | 금지 범주가 충분한가(금융상품·가상자산 광고 등) |
| v2 광고주 | "Create an offer, request an independent review and approve the exact budget before activation." | 제안을 만들고 독립 심사를 요청하고, 정확한 예산을 승인한 뒤 활성화 | "independent"라는 표현이 사실과 맞는가 |
| v2 광고주 | "Plain text only. Viewing requires 15 seconds. The standard reward split applies." | 일반 텍스트만, 15초, 표준 보상 배분 적용 | 배분 비율을 광고주에게 공개하는 위치 |

## 6. 공개 화면에서 정리할 문구(내부·개발 용어)

공개 화면에 주석, 시스템 정보, 개발 정보를 넣지 않는 규칙(11-05)에 어긋나는 문구다. 운영자 화면(`/ad-coin/admin`, 한국어)으로 옮기거나 쉬운 말로 바꾼다.

| 원문 | 문제 |
|---|---|
| "Register verified relay partner gateways, dispatch offers across A2A/MCP protocols, and audit agent escrow mandates." | 프로토콜 이름과 내부 개념 |
| "Agent-to-Agent (A2A)", "Model Context Protocol (MCP)", "Revenue share (bps)", "Endpoint URL" | 운영자용 설정 |
| "Independent double-entry verification proving beneficial atoms, clearing pools, and campaign budgets balance to zero." | 원장 내부 구조 |
| "Platform Ledger & Reconciliation Audit", "Run Full Reconciliation", "Platform Statistics" | 운영자 기능 |
| "Mandate & Escrow Overview", "Receipts and mandates" | 내부 용어(사람용에는 "spending limits" 같은 쉬운 말이 맞다) |
| "Run A/B experiments, analyze stage conversion dropoffs, and monitor budget pacing velocity." | 광고주용으로는 가능하지만 용어가 어렵다 |
