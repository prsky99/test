# AI AD Coin: r10 뒤 확인, 계획 표 리허설 준비, 첫 실제 결제 점검표 (2026-11-16, PM 15:42 지시)

실제 결제는 하지 않는다. 운영 DB는 `scripts.prod_ro_sql`로 읽기만 한다.

## 1. r10(22:00) 배포·데몬 재설치 뒤 확인 순서

r10에서 나가는 AD Coin 커밋은 e1407de6(결제 결함 수정), 5b0b8b9d(금지 문구 한 모듈)다. PM이 데몬을 새 frontend 버전으로 다시 설치한 뒤 아래 순서로 본다.

| # | 볼 것 | 방법 | 정상 |
|---|---|---|---|
| 1 | 데몬이 새 버전 폴더에서 도는지 | `launchctl list \| grep adcoin-worker` → pid, `ps -o command -p <pid>` | 명령줄 경로가 `gateway-data/services/releases/<r10 frontend 릴리스>/` |
| 2 | 데몬 점검 | `.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import ops_watch as w; print(w.check_adcoin_daemon()['problems'])"` | `[]`(running, plist 있음, 활성 frontend와 같은 코드) |
| 3 | 한 주기 로그 | `tail -20 logs/services/biz.agentconcierge.498590e0b3.adcoin-worker.log` | "Worker daemon started" 뒤 오류 없음. "Outbox pass failed", "Automatic review", "outbox_isolated" 줄 없음(자동 심사 스위치는 꺼짐) |
| 4 | 결제 대기열·환불 대기 | `.venv/bin/python -m scripts.prod_ro_sql deploy/ops/adcoin-review-queue.sql`, `… deploy/ops/adcoin-refunds-due.sql`, `… deploy/ops/adcoin-payments-today.sql` | 0 / 0 / 0(지금 실제 결제 0건) |
| 5 | 공개 광고 안내 | 내장 브라우저 `https://agentconcierge.biz/ad-coin/v2/advertise` 1건 | 200, "5 USDC" 기준 단가, "Anyone can advertise"(`ad-coin/v2/web/advertise.html`. 사이트 `/advertise`는 "Anyone can apply") |
| 6 | 작업 공간 | `https://agentconcierge.biz/ad-coin/v2` 1건 | 200, 콘솔 오류 0. 로그인 뒤 견적·결제 안내는 r10에서 바뀌지 않아 열리는지만 본다 |
| 7 | 운영자 화면 | `/ad-coin/v2/admin`(직원 로그인) 1건 | "USDC 결제 검토·환불" 영역이 열리고 "불러오기"가 빈 목록을 보여 줌. 불러오기는 운영자 로그인이 필요하다(11-16 21:38 PM 점검은 영역이 열리는 것까지) |

- 결제·견적 버튼은 누르지 않는다(실제 견적 행이 생기므로).
- 하나라도 정상과 다르면 데몬을 직전 버전(r9 폴더)으로 다시 설치하는 것이 되돌리기다: `bash deploy/launchd/install-adcoin-worker.sh day-frontend-20261116-r9`.

## 2. 맞춤 광고 계획 표: 사본 리허설 준비(11-18 00:30 → 오늘 밤 자리가 나면)

- 명령(운영·SRE 형식): `.venv/bin/python -m scripts.db_change_rehearsal run --command "python -m scripts.ad_coin_v2_migrate migrate-paid-plans --dsn-file {dsn_file} --key-file {key_file} --i-have-approval"`
- 만드는 것: `ad_coin_v2.adc2_paid_plans`, `ad_coin_v2.adc2_paid_plan_items`, 인덱스 3개. 트리거·함수는 없고 public 트리거 5개는 그대로다.
- 복구 SQL: `deploy/ad_coin/rollback-paid-plans-2026-11-15.sql`(두 표가 비었을 때만 DROP, 끝에 public 트리거 수 출력)
- 선행 조건: `.venv/bin/python -m scripts.prod_ro_sql -c "SELECT to_regclass('ad_coin_v2.adc2_paid_bookings') IS NOT NULL AS paid_bookings, to_regclass('ad_coin_v2.adc2_paid_plans') IS NOT NULL AS paid_plans"` → `t|f`
- 네 역할 확인(11-16 15:5x): frontend·jobs·execution `d8359782`(day-*-20261116-r9), admin `ff765a36`(day-admin-20261116-r2). 둘 다 `paid_plans.py`, 계획 SQL 14개가 든 sql_registry, `migrate-paid-plans`를 갖는다. AD Coin 저장소는 표 목록을 검사하지 않아 새 표가 생겨도 붙는 데 영향이 없다. jobs·admin·execution은 이 표를 읽지 않는다.
- **적용 시점 주의:** 표가 생기는 순간 frontend가 계획 판매를 연다("Plan by budget" 버튼, 견적). r9에는 오늘 고친 계획 운영자 경로·환율 재시도·계획 최종성 감시(e1407de6)가 없다. 그래서 **적용은 r10이 운영에 올라간 뒤**에 한다.
- 적용 뒤 확인: 선행 조건 쿼리가 `t|t`, 데몬 로그 오류 없음, `/ad-coin/v2` 작업 공간의 "Book a Sponsored day"에 "Plan by budget" 버튼이 보임(로그인 필요).

## 3. 첫 실제 결제 1건이 들어왔을 때 사람이 볼 것 (한 장)

| 볼 것 | 어디서 | 정상일 때 |
|---|---|---|
| 들어왔다는 사실 | `deploy/ops/adcoin-payments-today.sql`(건수·금액만) | `bookings_today` 1 |
| 운영자가 할 일이 있는지 | 운영자 화면 "USDC 결제 검토·환불"(예약과 계획 함께, r11부터 계획 포함) · 감시 줄 [adcoin_review]·환불 대기 | 확정된 결제는 목록에 나오지 않음(review·refund_due만 나옴) |
| 영수 확인 | 결제 행 `state='confirmed'`(Base 3블록, 공개 노드 2개 일치), 감사 `adc2_paid_booking_events`의 receipt, 이후 finality 행이 `finalized`가 될 때까지 | receipt 1행, 7일 안에 finalized |
| 금액 | 감사 receipt의 `received_units` = 견적 `amount_units` | 같음(다르면 붙지 않고 대사에 나옴) |
| 원화 환산 기록 | 결제 행 `krw_rate`, 월별 내보내기 `/admin/paid-bookings/export?month=YYYY-MM`(`kind` 열, 원화는 Decimal 반올림) | 비어 있지 않음. 비면 작업자가 다시 시도해 채움(e1407de6) |
| 거래 해시 | 결제 행 `tx_hash`, 내보내기 같은 줄 | 한 결제에 하나, 다른 예약·계획·환불에 다시 쓰이지 않음(공용 검사) |
| 제재 주소 대조 | `gateway-data/ofac/eth_addresses.txt`(11-16 06:20 갱신, 매일), 결과는 receipt 감사의 `sanctions` | `clear`. 맞으면 review로 감 |
| 매일 대사 | `logs/ops/payment-reconcile/<날짜>.json`(11-16 14:48 실행, 11-15 결과 ok) | `ok: true`, findings 없음 |
| 광고가 실제로 나갔는지 | 다음 날 정산 뒤 `state='served'`, 공개 `/ads/library` | 그날 줄이 보임 |

### 빠진 것과 조치
1. **운영자 화면에 맞춤 계획이 없었다.** 계획의 review·refund_due는 API로만 처리할 수 있었다. → 운영자 화면 "USDC 결제 검토·환불"에 계획을 함께 보이고 같은 버튼(확정·환불 필요·환불함)으로 처리하게 했다. r11용으로 별도 ref에 둔다.
2. **결제가 확정돼도 PM에게 바로 알리는 줄이 없었다**(대기열·환불 대기만 알림). → 읽기 전용 `deploy/ops/adcoin-payments-today.sql`을 만들었다. 운영·SRE 10분 감시에 "USDC 결제 확정 N건(오늘)" 줄을 요청한다. 계획 표가 생기면 계획 건수 줄을 같은 파일에 더한다.
3. 대사·제재 목록·원장 점검은 돌고 있다(11-16 확인). 원장 점검은 읽기 전용 세션이다(6e6ab0f5).
