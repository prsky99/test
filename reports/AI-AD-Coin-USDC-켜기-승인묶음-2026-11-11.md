# USDC 유료 예약 켜기 승인 묶음 (2026-11-11, PM이 사용자에게 올릴 것)

결제 스위치(`AD_COIN_PAID_BOOKING_ENABLED`)를 켜기 전에 사용자가 한꺼번에 승인할 항목이다. 지금은 모두 꺼짐 또는 미적용 상태다.

| # | 항목 | 내용 | 바뀌는 곳 | 되돌리기 |
|---|---|---|---|---|
| 1 | 받는 지갑 주소 | 운영 받는 지갑의 Base 주소 1개. 키는 서버에 두지 않는다 | `gateway-data/agentcon.env`의 `AD_COIN_PAID_PAY_TO`(git 제외) | 줄 지우기 |
| 2 | 결제 표 만들기 | `ad_coin_v2.adc2_paid_bookings`. 리허설(`db_change_rehearsal`) → 승인 → `check` → `migrate-paid` | 운영 DB(ad_coin_v2 스키마, public 무변경) | 비어 있을 때 `DROP TABLE ad_coin_v2.adc2_paid_bookings` |
| 3 | 노출 집계 표 | `ad_coin_v2.adc2_sponsored_impressions`(`migrate-impressions`, 같은 절차) | 운영 DB | `DROP TABLE IF EXISTS ad_coin_v2.adc2_sponsored_impressions` |
| 4 | 약관 9항 | `reports/AI-AD-Coin-USDC-유료예약-설계-2026-11-11.md` 6절의 영어 문구 | 광고주 약관(공개 화면) | 문구 내리기 |
| 5 | 처리방침 결제 기록 조항 | 아래 영어 초안 | `/new/en/privacy.html`(공개) | 문구 내리기 |
| 6 | OFAC 목록 | 공개 OFAC SDN 가상자산 주소를 `gateway-data/ofac/eth_addresses.txt`에 받는다. 8일 넘게 오래되면 결제를 확정하지 않고 검토로 보낸다 | 파일 하나(git 제외) | 파일 지우기(그러면 모든 결제가 검토로 감) |
| 7 | 데몬 재설치 | 확정 대기 재확인, 기한 만료, 정산, 보고서 발행 | launchd adcoin-worker | 이전 버전 폴더로 재설치 |
| 8 | 스위치 켜기 | `AD_COIN_PAID_BOOKING_ENABLED=1`, 가격은 기본 5 USDC | agentcon.env | 0으로 |

## 처리방침 추가 조항 초안 (영어 공개 문구, 승인 뒤 게시)

> **Advertiser payments in USDC.** When an advertiser pays for a Sponsored placement in USDC on Base, we record the paying wallet address, the transaction hash, the amount, the time we confirmed it and the Korean won value at that time (from a public exchange price). We use these records to confirm the booking, to prevent a payment from being used twice, to return payments when a placement fails on our side, to meet tax and accounting duties and to answer the advertiser's questions. We check the paying wallet against public sanctions lists (the OFAC Specially Designated Nationals list of digital currency addresses); a match is reviewed by our staff before a booking is confirmed. Wallet addresses and transactions are public on the blockchain; we do not ask for card details and we never hold advertisers' funds. We keep payment records for five years, then delete them. We do not sell or share them, except when the law requires it.

## 한국어 대조 (사용자 검토용)

- **기록하는 것:** 광고주가 Base의 USDC로 Sponsored 칸을 결제하면 다음을 기록한다. 보낸 지갑 주소, 거래 해시, 금액, 확정 시각, 그 시각의 원화 환산(공개 거래소 시세).
- **목적:** 예약 확정, 중복 사용 방지, 플랫폼 사정일 때의 반환, 세무·회계 의무, 광고주 문의 응대
- **제재 대조:** 보낸 지갑을 공개 제재 목록(OFAC SDN 가상자산 주소)과 대조한다. 걸리면 사람이 확인한 뒤에 확정한다.
- **공개성:** 지갑 주소와 거래는 블록체인에 공개되어 있다.
- **받지 않는 것:** 카드 정보는 받지 않고, 광고주 자금을 보관하지 않는다.
- **보관:** 5년 보관 뒤 삭제한다. 법이 요구할 때 말고는 팔거나 넘기지 않는다.

## 확인 결과

- 지금 `/new/en/privacy.html`에는 지갑, 거래 해시, USDC, 제재, 원화라는 말이 없다(검색 0건).
- 이 조항 없이 결제를 켜면 수집 항목이 공개되지 않은 상태가 된다. 그래서 조항 게시를 스위치 켜기보다 먼저 해야 한다.
