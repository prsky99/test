# 계정 없이 쓰는 광고 견적 API (AI AD Coin, 2026-11-17, PM 10:5x 승인 B)

목표: 에이전트가 사이트 계정이나 브라우저 세션 없이, API 호출만으로 광고 1칸을 사고 결제까지 끝내게 한다.
- 지금 경로는 8단계이고 로그인과 CSRF가 필요하다. 그래서 7일 동안 방문한 에이전트 1,017개 가운데 광고 경로에 닿은 것이 0이다.
- 11-18 낮 묶음에 내는 것이 목표다.

원칙은 그대로다.
- 연락처와 계정을 받지 않는다.
- 건별 USDC on Base로 받고, 선충전·잔액·보관·환전은 없다.
- 받는 지갑의 개인키는 서버에 두지 않는다.
- 광고 문구는 금지 규칙(`ad_rules.py`) 검사와 사람 심사를 거친다.
- 제재 주소 대조, 원화 환산, 거래 해시 기록은 공용 결제 엔진이 그대로 한다.

## 1. 표 변경이 필요한가: 필요 없음(기존 표로 된다)

| 필요한 것 | 기존 표·코드 |
|---|---|
| 주체(누가 샀나) | `adc2_principals`. 사이트 로그인 다리(`site_session`)처럼 서버 비밀 HMAC으로 id를 만든다. 입력은 그때 한 번만 보여 주는 읽기 키다. 읽기 키는 저장하지 않으므로 해시 칸도 필요 없다. |
| 광고주 | `adc2_advertisers`. 공개 신청 경로(`advertiser_applications.screen_application`)의 검사를 통과하면 바로 승인된다(11-15 결정). |
| 캠페인·문구 | `adc2_campaigns`, `adc2_campaign_revisions`, `adc2_reviews`. 승인돼야 견적을 낼 수 있다(`paid_bookings.quote`의 `campaign_not_bookable`). |
| 견적·결제 | `adc2_paid_bookings`, `adc2_paid_plans`. 공용 결제 엔진(11-18 배포)을 쓴다. |
| 감사 | `adc2_audit_log`, `keyless_offer_submitted` 등 |

따라서 운영 DB 구조 변경, 리허설, 복구 SQL이 모두 필요 없다. 새 등록 SQL이 생기면 `sql_registry.json`에 더하고 release_gate로 확인한다.

## 2. 흐름: 호출 3번, 그 사이에 심사 대기 1번

"2번 호출"로 줄일 수 없는 이유: 견적은 승인된 캠페인에만 낼 수 있다. 또 심사 전에 돈을 먼저 받으면 거절될 때 환불 송금이 생기고, 그 송금은 사용자가 직접 해야 한다.

1. `POST /api/ad-coin/v2/sponsor` `{name, text, url, category, region, day | budget_usdc}`
   - 검사: 금지 규칙, 공개 주소(`check_public_url`), 이름 검사, IP당 하루 한도
   - 만드는 것: 주체(HMAC) → 광고주(자동 승인) → 캠페인 → 심사 대기열
   - 응답: `order_id`, `status_url`, `read_key`(이때 한 번만 보여 줌), `state: in_review`
2. `GET /api/ad-coin/v2/sponsor/{order_id}` (헤더 `X-Read-Key`)
   - 승인 전: `in_review`
   - 승인되면: 견적. 금액(고유 끝자리), 받는 주소, 체인 8453, 토큰, 만료, `quote_id`
     - 하루 1칸이면 예약 견적, 예산을 냈으면 맞춤 계획 견적
   - 거절되면: 이유. 돈은 아직 오가지 않았다.
3. `POST /api/ad-coin/v2/sponsor/{order_id}/payment {tx_hash}` (헤더 `X-Read-Key`)
   - 공용 결제 엔진으로 확인한다.
   - 이후 상태와 노출·클릭 수는 2번 주소에서 본다.

- 심사 대기를 줄이는 길: 자동 심사 스위치(`AD_COIN_AUTO_REVIEW_ENABLED`)를 켠다.
  - 키 추가 코드(e98ee3a6)가 r11로 네 역할에 나간 뒤 PM이 켤 수 있다.
  - 켜면 규칙을 통과한 문구는 바로 승인돼 1→2가 곧바로 이어진다.
  - 규칙에 걸린 문구만 사람이 본다.

## 3. 남용 방지
- 읽기 키가 없으면 그 주문을 볼 수도 바꿀 수도 없다. 비교는 상수 시간으로 한다.
- 읽기 키를 잃으면 주문을 복구할 수 없다. 연락처를 받지 않기 때문이고, 응답과 화면에 그렇게 밝힌다.
- 열린 견적 한도는 지금 규칙 그대로다(광고주당 5). 여기에 IP당 하루 주문 생성 한도를 더한다(값은 설정 키, 기본 5).
- Early-Data 요청과 QA 헤더 요청은 아무것도 쓰지 않는다(74470308과 같은 규칙).
- 심사를 통과한 캠페인의 표시 예산(플랫폼이 부담하는 2 atom)은 시스템 주체가 연다(PM 11-17 결정, 1안).
  - 함수는 `start_display_budget`이고, 감사 기록은 `keyless_budget_started`다.
  - 서버가 구매자 대신 사람 확인(human challenge)을 만들고 스스로 답하던 경로는 이것으로 바뀌었다(지움).
  - 이 경로는 키 없는 주문이 만든 캠페인, 2 atom 표시 예산만 연다.

## 3-1. 운영자 내림 뒤 (PM 11-17 결정)
- 운영자가 광고주를 내리면(takedown) 그 주문은 다시 열지 않는다. 재개는 없다.
- 아직 나가지 않은 유료 칸은 `refund_due`가 된다.
- status 주소(`GET /api/ad-coin/v2/sponsor/{order_id}`)는 `state: taken_down`을 보여 준다.
  - 함께 보여 주는 것: 환불할 예약이나 계획의 id, 금액, 상태(`refund_due` 또는 `refunded`)
  - 안내 문구: 환불은 검토 뒤 운영자가 결제한 주소로 직접 보낸다. 서버에 맡겨 둔 돈은 없다. 새 견적은 내지 않는다.
- 같은 주문은 다시 견적을 내지 않고, 캠페인도 다시 켜지 않는다. 결제 요청은 `409 order_taken_down`으로 거절한다.
- 환불 송금은 사용자가 직접 한다.

## 4. 순서
1. 11-17: 이 설계를 PM에 보고한다. 코드와 시험(SQLite·PG)을 쓴다.
2. 11-18 오전: 공용 결제 클래스를 다시 얹은 뒤 그 위에 결제 단계를 연결한다. 결제 시험 7개 파일, 이 기능의 시험, release_gate를 돌린다.
3. 11-18 낮 묶음: 배포한다. 에이전트 문서 4곳에 이 API를 넣고, A2A 카드에 "quote a sponsored placement" skill을 더한다.
