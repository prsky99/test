# AI AD Coin Sponsored 예약 광고주 약관 조항 초안 (사용자 승인 요청)

- **작성:** 2026-11-10, AI AD Coin 팀. PM 결정 ⑥에 따라 쓴 초안이다. **사용자 승인 전에는 공개하지 않는다.**
- **적용 대상:** 광고주 콘솔의 Sponsored 하루 예약 화면과 광고주 약관. 공개 문구라서 영어로 쓴다.
- **바탕 결정(PM 11-10):** 하루 1칸 50코인, 예약한 캠페인만 노출, (분류, 지역)마다 하루 2칸, 새 광고주 첫 예약 하루 지원
  - 환불: 플랫폼 사정이면 전액, 하루 전 취소도 전액, 광고주가 스스로 멈추면 환불 없음
- **지금 상황:** 광고주 약관 문서가 따로 없다. 그래서 이 조항은 "Sponsored placements" 절로 새로 넣는다. 다른 광고주 조항(심사, 금지 광고 등)은 이번 범위가 아니다.

## 승인받을 문구 (영어, 공개용)

> ### Sponsored placements paid with coins
>
> **1. What coins are.** Coins are platform credits that Agent Concierge grants to advertisers, for example when an account is approved or when a listed agent passes verification. Coins have no cash value. They cannot be bought, sold, cashed out, exchanged for money or cryptocurrency, or transferred to another account. Agent Concierge does not sell coins.
>
> **2. What you can book.** You can book a Sponsored placement for one day (UTC) for an approved, active campaign, for one task category and one broad region. Each task category and region has a limited number of placements per day. Bookings open from tomorrow up to 30 days ahead.
>
> **3. Price.** The price is shown before you confirm a booking and is deducted from your coin balance when you confirm. The current price is 50 coins per placement per day. We may change the price for future bookings; a confirmed booking keeps its price.
>
> **4. How placements appear.** Sponsored placements are labelled "Sponsored" and appear next to, never inside, agent recommendations. Booking a placement never changes which agents are recommended or how they are ranked. We do not guarantee any number of views or clicks.
>
> **5. Cancellation.** You can cancel a booking until the day before it starts (UTC) and get all of its coins back. Bookings cannot be cancelled on the day itself.
>
> **6. When coins are returned.** If we cannot show your placement for reasons on our side, for example we reject or suspend the campaign, or the Sponsored area is unavailable for more than one hour that day, all coins for that day are returned to your balance. If you pause or end the campaign yourself, coins are not returned.
>
> **7. First booking support.** A new advertiser's first one-day booking may be paid from the platform's growth budget instead of your balance, once per advertiser and while that support is available.
>
> **8. Records.** Every booking, cancellation and return is recorded in your coin history.

## 한국어 대조 (사용자 검토용, 공개하지 않음)

1. **코인이란:** 플랫폼이 광고주에게 주는 크레딧이다(계정 승인, 등록 에이전트 검증 통과 등). 현금 가치가 없다. 사고팔기, 현금화, 돈이나 가상자산으로 교환, 다른 계정으로 이전이 모두 안 된다. 플랫폼은 코인을 팔지 않는다.
2. **예약 대상:** 승인된 활성 캠페인을 하루(UTC) 단위로, 작업 분류 하나와 넓은 지역 하나에 예약한다. (분류, 지역)마다 하루 칸 수가 정해져 있다. 내일부터 30일 안까지 예약할 수 있다.
3. **가격:** 확정하기 전에 가격을 보여 주고, 확정할 때 잔액에서 뺀다. 지금 가격은 하루 1칸 50코인이다. 앞으로의 예약 가격은 바뀔 수 있지만, 확정한 예약은 그 가격을 유지한다.
4. **표시 방식:** "Sponsored" 라벨을 붙이고 추천 결과 옆에만 보인다. 추천이나 순위에는 영향이 없다. 노출 수나 클릭 수는 보장하지 않는다.
5. **취소:** 시작 전날(UTC)까지 취소하면 전액 돌려준다. 당일에는 취소할 수 없다.
6. **반환:** 플랫폼 사정(반려, 정지, 그날 Sponsored 영역이 1시간 넘게 멈춤)이면 그날 몫을 전액 돌려준다. 광고주가 스스로 멈추거나 끝내면 돌려주지 않는다.
7. **첫 예약 지원:** 새 광고주의 첫 하루 예약은 광고주 잔액 대신 성장 예산으로 낼 수 있다. 광고주당 1번이고, 지원 재원이 있을 때만 된다.
   - 한 달 상한(성장 예산의 10%)은 운영 규칙이라 약관에 숫자를 넣지 않았다.
8. **기록:** 예약, 취소, 반환은 모두 코인 내역에 남는다.

## 승인 전에 볼 점

- **1항의 "Agent Concierge does not sell coins":** 헌장 1절(판매·현금화·교환 금지)을 약관으로 약속하는 문장이다. 나중에 코인 판매를 검토하려면 약관을 바꿔야 한다.
- **4항의 "노출 보장 없음":** 하루 정액 방식이라 노출 수와 대금이 연결되지 않는다.
- **6항의 "1시간 넘게":** 작업자는 Sponsored 영역이 꺼져 있던 시간을 기록으로 판단한다. 구현에서는 운영자가 반환 사유를 기록하는 방식으로 시작한다(아래 참고).
- **법률 검토:** 변호사 검토 없이 쓴 초안이다. 헌장의 "규제 영역 회피" 원칙에 따라 돈과 교환할 수 없는 크레딧으로만 설계했다.

## 구현과의 관계

- 시험 모드 구현은 이 승인과 상관없이 지금 진행한다(PM 결정). 화면에 이 문구를 넣고 공개하는 것은 승인과 v2 재가동이 모두 끝난 뒤다.
- "1시간 넘게 멈춤"의 자동 판정은 처음에는 하지 않는다.
  - 작업자는 반려·정지 상태만 자동으로 판정한다.
  - 장애로 인한 반환은 운영자가 `platform.operate` 권한으로 예약별 반환을 실행한다. 사유는 감사 로그에 남는다.
