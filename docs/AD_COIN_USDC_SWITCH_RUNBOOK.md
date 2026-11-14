# USDC 광고 결제 스위치 켜기·끄기 (한 장, 2026-11-14)

**근거**
- 사용자 결정 11-14: 관문 없이 지금 켠다(헌장 9bdc36cc). 결제 안정 기준은 운영 지표로 본다.
- 결제는 예약 1건 = 결제 1건이다. 선충전, 코인 판매·보관, 환전, 자동 송금은 하지 않는다.
- 받는 지갑 주소는 사용자가 넣는다. 개인키는 서버에 두지 않는다. 환불 송금은 사용자가 직접 한다.

## 설정이 있는 곳

| 파일(git 제외) | 내용 | 누가 읽나 |
|---|---|---|
| `gateway-data/usdc-receive-address.txt` | 받는 주소 1개(`#` 줄은 메모), 0600 | frontend·데몬 |
| `gateway-data/sponsored.env` | `AD_COIN_PAID_BOOKING_ENABLED=1`(켬). 선택: `AD_COIN_PAID_PRICE_USDC`, `AD_COIN_PAID_MIN_CONFIRMATIONS`, `AD_COIN_PAID_RPC_URL`, `AD_COIN_OFAC_LIST`(절대 경로) | frontend(시작할 때), 데몬(파일이 바뀌면 5초 안) |
| `gateway-data/ofac/eth_addresses.txt` | OFAC 주소 목록, 매일 06:20 갱신 | frontend·데몬(2일 넘게 오래되면 모든 결제가 검토로 감) |

`agentcon.env`에는 결제 설정을 넣지 않는다. 그 이름을 모르는 버전이 시작을 거부하기 때문이다(f7cd7a83).

## 켜기

1. 켜기 전 점검: `.venv/bin/python -m scripts.ad_coin_paid_switch_check before`
   - 확인 항목: OFAC 24시간 안 갱신, 받는 주소 파일(OFAC 아님), sponsored.env, 결제 흐름·체인 시험 보고서 7일 안 통과, 데몬
   - 0이 아니면 켜지 않는다.
2. `gateway-data/sponsored.env`에 `AD_COIN_PAID_BOOKING_ENABLED=1` 한 줄을 넣는다(0600 유지).
3. frontend를 배포한다. 활성 버전을 무변경 복제한 뒤 `deploy`한다. `restart`는 쓰지 않는다. 데몬은 파일을 스스로 다시 읽는다.
4. 켠 직후 점검: `.venv/bin/python -m scripts.ad_coin_paid_switch_check after`
   - 공개 주소에서 견적·결제 경로가 열렸는지(401·403, 404 아님), 2초 안인지, Sponsored API를 본다.
5. 첫 실제 결제는 PM이 추적한다. 운영자 화면 `/ad-coin/v2/admin`의 "USDC 결제 검토"에서 본다.

## 끄기 (되돌리기)

1. `gateway-data/sponsored.env`에서 `AD_COIN_PAID_BOOKING_ENABLED` 줄을 지운다(또는 `=0`).
2. frontend를 배포한다(위 3과 같음). 견적·결제 경로가 404로 돌아간다. 데몬은 5초 안에 결제 처리를 멈춘다.
3. 이미 받은 결제와 예약은 지우지 않는다(5년 보존). 확정된 예약 처리는 PM이 정한다(그대로 노출하거나 환불).

## 결제가 맞지 않을 때 (자동으로 검토 상태가 됨)

| 경우 | 예약 상태 | 운영자 할 일 |
|---|---|---|
| 덜 냄·더 냄 | review(amount_mismatch) | 확정 또는 환불(refund → 사용자가 직접 송금 → refunded와 거래 해시 기록) |
| 견적 만료 뒤 결제 | review(late_payment) | 칸이 비어 있으면 확정, 아니면 환불 |
| 다른 토큰 | 결제로 보지 않음(견적 그대로) | 광고주가 요청하면 그 토큰을 직접 돌려줌 |
| 같은 결제를 두 번 | 두 번째 거부(payment_already_used) | 없음 |
| 제재 주소 | review(sanctions_match) | 확정·환불하지 않고 PM에 보고 |
| 원화 시세를 못 가져옴 | review(krw_rate_unavailable) | 시세를 확인하고 확정 |

결과표: `reports/ad-realign-2026-11-14/payment-flow-tests.json`, `payment-chain-check.json`
