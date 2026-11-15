# 매출 약관·광고 판매 정책 변경 초안 (AI AD Coin, 2026-11-15, PM 확정용)

- 근거: 사용자 결정 11-15(PM 11:3x 전달)
  1. 광고주 자격 제한 없음, 검사 통과 시 자동 승인
  2. 금액에 맞춘 광고 계획(계획 1건 = 결제 1건)
  3. 이용권: 제공자 10 USDC, 개발자 20 USDC, 30일
  5. 약관·환불 문구는 PM 재량
- 공개 문구는 영어, 설명은 한국어다. PM이 확정하면 아래 표의 담당 팀이 고친다.
- 반영 시점
  - 이용권 조항(A-2): 이용권 표가 생기고 스위치를 켤 때 함께 반영한다. 팔지 않는 상품을 약관에 먼저 쓰지 않는다.
  - 계획 문장: 계획 표가 생길 때 함께 반영한다.

| 위치 | 담당 | 반영 시점 |
|---|---|---|
| 공개 이용약관 `new/en/terms.html` "Sponsored content and advertisers" | 성장·유통(공개 화면) | 1번은 다음 frontend 묶음, 2·3번 문장은 해당 표가 열릴 때 |
| 작업 공간 광고 약관 `agent_market/ad_coin/v2/web/index.html` 9항 | AI AD Coin | 계획 표가 열릴 때 |
| 광고 안내 `agent_market/ad_coin/v2/web/advertise.html` 환불 문단 | AI AD Coin | 계획 표가 열릴 때 |
| 내부 판매 정책 `docs/AD_COIN_SALES_POLICY.md` | AI AD Coin | PM 확정 즉시(내부 문서) |

## A-1. 공개 이용약관: "Sponsored content and advertisers"

**지금**
> Sponsored content is labelled "Sponsored", appears separately from recommendations and never changes which agents are recommended. Advertisers and their content are reviewed before anything is shown. Advertisers book sponsored placements with coins they receive from AgentValCon through grants, provider rewards or activity. Coins are not sold and cannot be cashed out or exchanged for money. Placements that are not shown are refunded in coins. Budgets in the closed advertiser test are test credits with no cash value.

- 문제: 11-11에 "Updated (advertiser payments in USDC)"라고 날짜만 바꾸고, 본문에는 USDC 결제가 없다.
- "closed advertiser test" 문장도 낡았다.

**바꿀 문구**
> Sponsored content is labelled "Sponsored", appears separately from recommendations and never changes which agents are recommended, how they are ranked or their scores. AI agents may receive at most one Sponsored offer, in a separate field of the answer.
>
> Anyone can apply to advertise. Every application and every ad is checked against our ad rules before anything is shown; some are looked at by a person first, and we do not accept categories our ad rules exclude.
>
> Advertisers pay for placements in USDC on Base. Each payment is for one booking, or for one plan of several placements, and is made once for the exact amount quoted; there is no stored balance, no top-up and no automatic renewal, and any budget left over is not charged. Payments are never converted into coins. Advertisers may also use coins they receive from AgentValCon through grants, provider rewards or activity; coins are not sold and cannot be cashed out or exchanged for money.
>
> If we cannot show a paid placement for reasons on our side, we refund that placement in USDC to the wallet that paid; placements booked with coins are refunded in coins. We may decline payments from wallets on public sanctions lists.

- 날짜 줄: "Updated <반영일> (open advertising, plans and USDC payments)."

## A-2. 공개 이용약관: 새 조항 "Passes" (이용권 스위치를 켤 때)

**지금:** 없음

**새 문구**
> **Passes.** A pass adds features to your account for 30 days.
> - A provider pass costs 10 USDC and is available to accounts that have proved they run an agent. It gives alerts when your agent goes down, changes its tool fingerprint or changes grade, statistics on how often it is recommended, and an export of its test records.
> - A developer pass costs 20 USDC. It gives an API key with higher limits, answers without the Sponsored offer, and bulk access to the signed feed.
>
> A pass is paid once in USDC on Base for the exact amount quoted. It does not renew by itself, and there is no stored balance. A pass belongs to the account that bought it and cannot be resold or transferred. A developer key may be shared only within your organisation, and changes to a key can take up to one minute to apply everywhere.
>
> A pass never changes recommendations, grades, scores, rankings or the order of retests.
>
> We refund a pass to the wallet that paid if you ask within 7 days and have barely used it, or for the days a feature was unavailable for reasons on our side.

- "barely used"의 기준은 PM이 정한다. 제안: 개발자 키 호출 100회 미만, 제공자 내보내기 0회.

## B. 작업 공간 광고 약관 9항 "Paid Sponsored placements" (계획 표가 열릴 때)

**지금**
> Paid Sponsored placements are paid in USDC on Base at booking. Each booking is paid once, for its exact quoted amount, before it is confirmed; there is no stored balance and no top-up. Payments are not converted into coins, and coins cannot be bought. Refunds are made only for platform-side failures (for example, we reject or suspend the campaign or the Sponsored area is unavailable for more than one hour that day), to the wallet that paid. We may decline payments from wallets on public sanctions lists.

**바꿀 문구**
> Paid Sponsored placements are paid in USDC on Base at booking, either one day at a time or as a plan. A plan is several placements that we suggest from the budget, categories and regions you give. You pay a booking or a plan once, for its exact quoted amount, before it is confirmed. There is no stored balance and no top-up, and any part of your budget that a plan does not use is not charged. The price is 5 USDC per placement per day unless the quote says otherwise. Payments are not converted into coins, and coins cannot be bought. Refunds are made only for platform-side failures (for example, we reject or suspend the campaign or the Sponsored area is unavailable for more than one hour that day), for the placements affected, to the wallet that paid. We may decline payments from wallets on public sanctions lists.

- 효력 줄: "Term 9 applies from <반영일>."

## C. 광고 안내 `/ad-coin/v2/advertise` 환불 문단 (계획 표가 열릴 때)

**지금**
> USDC bookings: if we cannot show your placement for reasons on our side, for example we reject or suspend the campaign or the Sponsored area is unavailable for more than one hour that day, we refund the payment to the wallet that paid.

**바꿀 문구**
> USDC bookings and plans: if we cannot show a placement for reasons on our side, for example we reject or suspend the campaign or the Sponsored area is unavailable for more than one hour that day, we refund that placement to the wallet that paid. In a plan, the other placements still run.

## D. 내부 판매 정책 `docs/AD_COIN_SALES_POLICY.md` (PM 확정 즉시)

| 절 | 지금 | 바꿀 내용 |
|---|---|---|
| 4. 광고주 계정 | 카탈로그 제공자만, 운영자가 모든 신청 승인 | 누구나 신청한다. 이름만 필수이고, 웹사이트(공개 주소만)나 목록 주소는 선택이다. 아래 검사를 통과하면 바로 승인하고, 걸린 건만 운영자가 본다. 검사: 숨은 문자, 에이전트 조종·명령형 문구, 판매하지 않거나 사람 확인이 필요한 분류의 단어. 제재 대조는 USDC 결제마다 한다. (구현 bea8fd8f) |
| 2. 판매 상품 | 하루 1칸 5 USDC 단건 | 단건 5 USDC는 기준 단가로 그대로 둔다. 맞춤 계획: 예산·분야·지역을 받아 계획 2~3개를 제안하고, 고른 계획을 한 번 결제한다. 최소 10 USDC(2칸), 남는 예산은 받지 않는다. 묶음 할인은 처음엔 없다(설정값, PM 결정). |
| 2. 판매 상품(새 줄) | 없음 | 이용권: 제공자 10 USDC, 개발자 20 USDC, 30일, 결제 1건 = 이용권 1장(`docs/USDC_PASS_DESIGN.md`). |
| 7. 무효 노출과 환불 | 예약 단위 | 계획은 날짜 자리 단위로 환불하고, 나머지 자리는 그대로 나간다. 환불 송금은 사용자가 직접 하고, 운영자가 기록한다. |
| 6. 노출 규칙 | 광고는 유기 결과·점수·순위를 바꾸지 않음 | 그대로 둔다. 에이전트 응답의 광고 칸은 항상 나간다(11-15). 개발자 이용권만 비운다. |

## PM이 확정할 것
1. A-1 문구, 그리고 반영을 다음 frontend 묶음에 넣을지
2. A-2의 "barely used" 기준과 7일 기한
3. B·C 문구(계획 표가 열릴 때 반영)
4. D의 묶음 할인 없음 유지 여부
