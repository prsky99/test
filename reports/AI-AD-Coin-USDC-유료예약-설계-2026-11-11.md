# Sponsored 유료 예약(USDC on Base) 설계 메모 (2026-11-11)

- **요청:** 총괄 PM, 사용자 결정 11-11("수익부터 내서 운영비 보충, 신고·자문은 수익이 커질 때")
- **충돌 확인(PM이 정리할 것)**
  - CLAUDE.md와 헌장에는 아직 "수익과 지출은 코인으로만 한다. 달러·원화 같은 돈으로는 아직 거래하지 않는다"(11-10)가 남아 있다.
  - USDC는 달러 연동 자산이다. 이 기능은 그 규칙을 바꾸는 결정 위에 서 있다.
  - 그래서 **기본 꺼짐 스위치**로만 만들고, 켜기 전에 CLAUDE.md와 헌장 문구를 사용자 결정에 맞게 고쳐야 한다(PM 몫).

## 1. 구조 (사전 등록이 필요한 행위를 피함)

| 원칙 | 설계 |
|---|---|
| 예약 1건 = 결제 1건 | 견적에 금액과 기한을 붙이고, 그 금액이 확인되어야 그 예약만 확정한다. 남는 돈, 잔액, 충전이 없다 |
| 금지 | 선충전 잔액, AD Coin 판매나 전환, 고객 자산 보관, 환전, 송금 대행. 이를 만드는 코드 경로가 없다 |
| 장부 분리 | 새 표 `ad_coin_v2.adc2_paid_bookings` 하나. AD Coin 원장(`adc2_journals`)과 연결하지 않는다. 코인 예약 표와도 분리한다 |
| 받기만 함 | 받는 주소 하나(설정값). 서버에 개인키가 없다. 체인에 아무것도 보내지 않는다(`send_raw`를 쓰지 않음) |

## 2. 흐름

1. **견적:** 광고주가 캠페인, 날짜, 분류, 지역을 고른다.
   - `POST /api/ad-coin/v2/advertisers/{id}/paid-bookings`
   - 서버가 칸 여유를 확인하고 견적을 만든다: 금액, 받는 주소, 네트워크 Base, 토큰 USDC, 30분 기한.
   - 금액은 정가 5 USDC에 견적마다 다른 소액 꼬리(0.000001~0.009999 USDC)를 붙인 값이다. 예: 5.004217 USDC.
   - 꼬리 덕분에 입금과 견적이 1:1로 대응한다. 체인 메모는 USDC 전송에 없으므로 금액으로 대응한다.
2. **송금:** 광고주가 자기 지갑에서 그 정확한 금액을 Base USDC로 보낸다. 화면에는 네트워크와 금액을 크게 보여 준다.
3. **확인:** 광고주가 거래 해시를 붙인다(`POST .../paid-bookings/{id}/payment {tx_hash}`).
   - 서버는 기존 `chain.RPC.receipt`, 확인 블록 수, `chain.transfers_in`으로 다음을 확인한다.
     - 성공한 거래다.
     - 확인 블록이 충분하다.
     - 정해진 토큰(Base USDC 계약)으로 받는 주소에 **정확한 견적 금액**이 들어왔다.
     - 송금자가 한 명이다.
   - 확인 블록이 모자라면 `confirming`이 된다. 작업자가 다시 확인하고, 화면은 "확인 중"을 보여 준다.
4. **안전장치(무료)**
   - 송금 주소를 OFAC SDN 가상자산 주소 목록(공개 자료를 로컬 파일로 받아 둠)과 대조한다. 걸리면 확정하지 않고 `review`로 보내 운영자 화면에 띄운다.
   - 목록 파일이 없거나 오래됐으면 확정하지 않고 검토로 보낸다(실패 시 닫힘).
5. **확정:** 거래 해시는 유일 제약으로 한 번만 쓸 수 있다(중복 사용 차단). 예약이 `confirmed`가 되고 Sponsored 칸 수에 포함된다.
6. **기록:** 결제마다 받은 시각, 금액, 송금 주소, 거래 해시, 원화 환산(공개 시세: Upbit KRW-USDC 공개 시세. 못 받으면 비워 두고 내보낼 때 표시)을 남긴다. 운영자 화면에서 월별 CSV로 내보낸다.
7. **환불:** 플랫폼 사정(반려, 정지, 장애)일 때만 한다.
   - 운영자 화면 "환불 필요" 목록에 송금 주소, 금액, 거래 해시를 보여 준다.
   - 실제 송금은 사용자가 지갑에서 직접 하고, 환불 거래 해시를 기록한다. 자동 송금은 없다.

## 3. 상태

`quoted`(기한 30분) → `confirming` → `confirmed` → `served`
- 그 밖의 상태: `expired`(기한 경과), `review`(제재·목록 없음), `refund_due` → `refunded`

## 4. 운영 DB 변경 (사용자 승인 필요)

- 새 표 1개: `ad_coin_v2.adc2_paid_bookings`
  - 열: id, advertiser_id, campaign_id, day_ms, task_category, region, amount_units, pay_to, chain_id, token, state, tx_hash(UNIQUE), payer, krw_rate, quoted_ms, expires_ms, confirmed_ms, refund_tx_hash
  - 색인 2개
- v2 스키마 11
- 절차: `scripts.db_change_rehearsal run`으로 사본에서 운영 버전 앱 연결까지 통과 → 복구 SQL(표가 비어 있을 때 `DROP TABLE ad_coin_v2.adc2_paid_bookings`) → 사용자 승인 → 실행 직전 `check`
- public 스키마에는 아무것도 만들지 않는다(11-10 장애).

## 5. 설정 (기본 꺼짐)

| 설정 | 기본 | 의미 |
|---|---|---|
| `AD_COIN_PAID_BOOKING_ENABLED` | 0 | 라우트 미마운트 |
| `AD_COIN_PAID_PRICE_USDC` | 5 | 출시 가격(사용자 승인) |
| `AD_COIN_PAID_PAY_TO` | 없음 | 받는 주소. 없으면 켜지지 않음 |
| `AD_COIN_PAID_MIN_CONFIRMATIONS` | 3 | Base 확인 블록 |
| `AD_COIN_OFAC_LIST` | gateway-data/ofac/eth_addresses.txt | 제재 주소 목록 |

## 6. 약관 추가 조항 초안 (영어 공개 문구, 승인 뒤 게시)

> **9. Paid Sponsored placements.** Paid Sponsored placements are paid in USDC on Base at booking. Each booking is paid once, for its exact quoted amount, before it is confirmed; there is no stored balance and no top-up. Payments are not converted into coins, and coins cannot be bought. Refunds are made only for platform-side failures (for example, we reject or suspend the campaign or the Sponsored area is unavailable for more than one hour that day), to the wallet that paid. We may decline payments from wallets on public sanctions lists.

## 7. 두 번째 수익원 메모 (다음 순서)

- 에이전트용 x402 유료 도구: 기존 `PaymentVerifier`(서명 증명 포함)로 에이전트가 도구 호출마다 USDC를 낸다.
- 후보: 정밀 추천 리포트, 대량 비교 같은 자체 도구
- 같은 원칙(호출 1건 = 결제 1건, 잔액 없음)과 같은 기록·내보내기를 재사용한다.
