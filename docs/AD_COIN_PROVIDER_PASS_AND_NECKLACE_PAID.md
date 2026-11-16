# 제공자 이용권 입구와 목걸이 유료 전환 설계 (AI AD Coin, 2026-11-16, PM 21:13 배정 ②③)

설계만 한다. 이 문서의 기능은 켜지 않는다.
- 이용권 표: 운영 DB 변경 절차(사본 리허설, 복구 SQL, 실행 직전 check 0)를 거쳐 PM이 만든다.
- 목걸이 유료 전환: 조건을 채운 목걸이에만, PM이 켠다.

기존 결정은 그대로 따른다.
- USDC on Base 건별 결제이고, 서버는 받기만 한다.
- 선충전·잔액·보관·자동 갱신이 없다.
- 연락처를 받지 않는다(11-10, 11-15).
- 돈으로 순위·등급·시험 결과를 살 수 없다.

## 1. 제공자 소유 확인 → 제공자 이용권 (11-30, 성장·유통과)

### 지금 있는 것
- 소유 확인: `agent_market/concierge/owner_proof.py`, `GET /api/agent/v1/owner/token`, `POST /api/agent/v1/owner/verify`
  - 계정·메일·비밀번호 없이 호스트를 제어하는지로 확인한다(well-known 파일 또는 DNS TXT).
  - 결과는 저장하지 않는다(`OWNER_PROOF_STORE`가 꺼져 있고 `agentcon_owner` 표가 없다).
- 이용권 설계: `docs/USDC_PASS_DESIGN.md`
  - 2.1절은 로그인한 고객을 전제로 한다.
  - 이번 배정은 "연락처 없이 상태 주소로"이므로 아래처럼 계정 없는 입구를 더한다.
- 상태 주소 방식: 목걸이 주문(`agent_market/concierge/necklace_orders.py`)
  - 무작위 번호를 주고 `status_url`에서 결과를 보여 준다.

### 흐름 (계정·연락처 없음)
1. 제공자가 `owner/verify`로 호스트 확인을 통과한다. 응답에 다음 단계가 붙는다.
   - `next.pass_quote = POST /api/agent/v1/owner/pass`
   - 문구: "Provider pass, 10 USDC for 30 days"
2. `POST /api/agent/v1/owner/pass {host}`
   - 서버가 그 자리에서 호스트 확인을 한 번 더 한다(저장된 확인이 없으므로). 실패하면 `claim_required`.
   - 통과하면 견적을 만든다.
     - 금액: 10 USDC + 고유 끝자리
     - 받는 주소, 체인 ID, 토큰
     - 만료: 견적 30분
   - 함께 주는 것:
     - 무작위 `pass_id`
     - `status_url`(`/provider-pass#<pass_id>`)
     - 읽기 키(32바이트 무작위, 이때 한 번만 보여 주고 서버는 해시만 둔다)
3. 제공자가 USDC를 보내고 `POST .../pass/{pass_id}/payment {tx_hash}`로 알린다.
   - 확인은 광고 예약과 같은 공용 결제 엔진으로 한다(`paid_payments.py`, 11-18 배포 예정).
     - Base 3블록, 공개 노드 2개 일치
     - 제재 주소 대조
     - 원화 환산·거래 해시 기록
     - 다른 결제에 쓴 tx는 거부
4. 확정되면 30일이 시작된다.
   - `status_url`과 읽기 키로 다음을 가져간다(가져가는 방식만 쓴다. 메일·웹후크 없음).
     - 알림 피드: 다운, 지문 변경, 등급 변화
     - 노출 집계
     - 시험 기록 내보내기
5. 갱신은 새 견적·새 결제 1건이다. 자동 갱신은 없다.
   - 남은 기간은 돈이나 코인으로 바꾸지 않는다.
   - 환불 송금은 사용자가 직접 한다.

### 필요한 것과 순서
- 표 `ad_coin_v2.adc2_paid_passes`: id, kind, host, read_key_hash, quote 열, tx_hash, state, starts_ms, ends_ms, krw_rate
  - 공용 결제 엔진의 세 번째 어댑터로 붙인다. 리허설·복구 SQL은 표를 만들 때 함께 준비한다.
- 순서:
  1. 결제 클래스 배포(11-18)
  2. 이용권 어댑터와 시험
  3. 사본 리허설
  4. PM 적용
  5. 성장·유통의 입구 화면 문구(영어)
- 막힌 것 없음. `agentcon_owner` 표(소유자 기록)는 없어도 된다. 견적 때마다 호스트 확인을 다시 하기 때문이다.

## 2. 목걸이 유료 전환 (PM 결정: 목걸이별 30일 외부 성공 300+ 그리고 호출자 20+)

### 공개 문구 (영어, 조건 충족 전에는 게시하지 않음)
> Necklace runs are free during the launch event. A necklace becomes paid only after it has proven itself: at least 300 successful outside runs and 20 different callers in the last 30 days. Even then, every caller keeps a free daily allowance; runs beyond it are paid one by one in USDC on Base. There is no prepaid balance, no subscription and no stored funds. Paying never changes a necklace's answers, tests or ranking.

### 계량 (워크플로우와 맞춤)
- 셀 것: 목걸이별 하루 외부 실행 성공 수, 서로 다른 호출자 수
  - 호출자 = 방문자 토큰 또는 IP 해시. 원문은 남기지 않는다.
- 뺄 것: 우리 시험, 관문 회차, 자동 반복, QA 헤더, Early-Data 요청
- 같은 기준을 운영·SRE 지표판에도 쓴다. AI AD Coin은 이 수를 읽기만 하고 문턱 판단만 한다.
- 도구: `scripts/necklace_meter.py`(워크플로우, 5bcab9de). `.venv/bin/python -m scripts.necklace_meter [--end YYYYMMDD] [--days 30]`
  - 목걸이별로 `external_runs`, `succeeded`, `days_with_success`, `success_bar_met`을 낸다. north_star.count와 같은 기준이다(run_id 중복 제거, 우리 시험·감시 0, 캐시 답은 실행이 아님).
  - `callers`는 r12까지 null이다. 호출자는 PM 규칙(a715268b)대로 센다: 30일 동안 서로 다른 방문자 토큰, 토큰 없는 호출은 하루 소금 지문의 합계.
  - 유료 전환 판단은 `success_bar_met`과 `callers >= 20`을 함께 본다. `callers`가 null이면 조건 미충족으로 본다.

### 결제 경로 (건별, 선충전 없음)
1. 하루 무료 몫(호출자당)을 넘은 실행 요청에는 `402`와 견적을 돌려준다.
   - 금액: 건당 가격 + 고유 끝자리
   - 받는 주소, 만료 10분, `quote_id`
2. 호출자가 USDC를 보내고 같은 요청에 `X-Payment-Quote: <quote_id>`, `X-Payment-Tx: <hash>`를 붙여 다시 부른다.
3. 서버가 공용 결제 엔진으로 확인한다(3블록, 제재 대조, tx 1회 사용). 확인되면 그 1건만 실행한다.
   - 실행이 실패하면 운영자 환불 대기열에 넣는다(환불 송금은 사용자가 직접).
- 지연: 3블록 확인에 약 6초가 더 든다. 목걸이 실행은 "복잡한 답변 5초" 목표 밖으로 나간다. 그래서 유료 실행은 응답에 그 시간을 따로 표시한다(`payment_wait_ms`).
  - 대안 1: 확인을 1블록으로 줄이고 금액 상한을 둔다. PM이 정한다.
  - 대안 2: x402 표준 서명 결제는 퍼실리테이터 계정이 필요해 쓰지 않는다(계정 생성·남의 서버 결제 금지).
- 가격과 하루 무료 몫은 조건을 채운 목걸이가 생길 때 PM이 정한다. 설정 키로 두고 코드에 박지 않는다.
- 켜는 조건: 그 목걸이가 문턱을 채우고 PM이 켠다. 문턱 아래로 내려가면 다시 무료로 돌아간다(가격 문구도 사라짐).

## 3. 멈춘 것
- AD Coin v3를 비롯해 결제·목걸이에 닿지 않는 새 하위 체계는 확장하지 않는다(PM 11-16 21:13).
- v3 코드 삭제는 원래대로 11-24에 한다(코드만, v1 표는 지우지 않음).
