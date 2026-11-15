# USDC 이용권 설계 (AI AD Coin, 2026-11-15 초안, PM 검토용)

PM 과제(11-15): USDC로 사는 "이용권"을 설계한다. 이 문서는 설계만 하고 구현은 하지 않는다.
**11-15 사용자 결정(PM 11:3x 전달):** 결제 단위를 풀어 매출 증대에 맞게 판다. 제공자용 **10 USDC**, 개발자용 **20 USDC**, 30일, 이용권 1건 = 결제 1건. 표는 운영 DB 변경 절차(리허설 → 사용자 승인)로 간다. 약관·환불 문구는 PM 재량이다.
`docs/AD_FREE_SUBSCRIPTION_DESIGN.md`(광고 제거 구독 메모, 11-15)는 이 문서의 개발자 이용권에 합쳤다.

## 0. 한 줄 요약
- 이용권 1장 = USDC on Base 결제 1건 = 30일. 자동 갱신, 선충전, 잔액, 보관은 없다. 서버는 받기만 하고 개인키를 두지 않는다.
- 두 종류다.
  - 제공자 이용권 10 USDC: 자기 에이전트의 다운·지문 변경·등급 변화 알림, 추천 노출 분석, 시험 기록 내보내기
  - 개발자 이용권 20 USDC: API 키, 높은 호출 한도, 광고 없는 결과(광고 제거 구독), 서명 피드 대량 접근
- 결제는 지금 운영 중인 USDC 광고 예약(`paid_bookings.py`)의 견적·확인 경로를 그대로 쓴다.
  - 견적: 고유 끝자리 금액
  - 확인: 체인 확정, 제재 주소 대조
  - 기록: 원화 환산, 거래 해시, 월별 내보내기
- 기능 스위치는 기본 꺼짐이다. 표가 없으면 켜도 꺼진 채(409, 빈 목록)로 둔다.

## 1. 지켜야 할 원칙 (기존 사용자 결정에서)
| 원칙 | 이용권에서의 뜻 |
|---|---|
| 결제 1건 = 상품 1건 (11-11) | 결제 1건이 이용권 1장이다. 여러 달을 한 번에 사는 묶음은 없다(선충전처럼 됨). |
| 선충전·잔액·보관·환전·자동 송금 없음 | 남은 기간을 돈이나 코인으로 돌려주거나 옮기지 않는다. 자동 인출(구독 결제 승인)도 없다. |
| 서버는 받기만 한다, 개인키 없음 | 받는 주소는 광고 예약과 같은 주소 하나다. 서명 검증(공개키 복원)만 하고 서명은 하지 않는다. |
| 환불 송금은 사용자가 직접 | 운영자가 환불 tx를 기록하면 그 이용권은 끝난다. |
| AD Coin과 섞지 않음 (헌장 1절) | AD Coin으로 이용권을 살 수 없고, 이용권을 AD Coin으로 바꿀 수 없다. 장부도 따로 둔다. |
| 법정화폐 거래 없음 | 가격은 USDC로만 표시한다. 원화 환산은 기록용이다. |
| 광고는 항상 나감 (11-15) | 광고 없는 결과는 개발자 이용권으로만 준다. 무료로 끄는 길은 없다. |
| 돈으로 품질을 사지 못함 (PM 11-15 결정 4) | 이용권은 등급·순위·점수·재시험 순서·추천 결과에 영향을 주지 않는다. |
| 응답 시간 정책 | 요청 경로에 실시간 DB 조회를 새로 넣지 않는다. 키 확인은 메모리에서 한다(6절). |

## 2. 두 종류의 이용권
### 2.1 제공자 이용권 (provider)
- 대상: 제공자 소유 확인(`docs/PROVIDER_SELF_CLAIM.md`)이 `verified`인 고객만 살 수 있다. 확인이 없으면 견적을 내지 않는다(`claim_required`).
- 가격: 10 USDC / 30일(사용자 결정 11-15).
- 주는 것(읽기 전용, 자기 자원만):
  - 알림(사용자 결정의 세 가지): **다운**(헬스 up→down, 다시 up), **지문 변경**(도구 목록·스키마 지문이 바뀜), **등급 변화**.
    - PM 11:4x 결정 5: 1차에는 메일을 보내지 않고 메일 주소도 모으지 않는다. 알림은 로그인한 제공자 화면과, 제공자별 알림 피드(제공자가 가져가는 방식, 이용권 키로 읽는 `GET /api/customer/passes/alerts?since=`)로만 준다.
    - 메일과 웹후크는 수요를 본 뒤 따로 정한다. 웹후크는 외부 주소 호출이라 `check_public_url`과 호출 예산이 필요하다.
  - 추천 노출 분석: 자기 자원이 탐색·추천·Chat·MCP/A2A 응답에 나온 횟수(일별 집계), 상세 페이지 열람 수, "연결" 버튼 수.
  - 시험 기록 내보내기: 자기 자원의 헬스·시험 호출·시험 보고서 v2 기록을 CSV/JSON으로(공개 시험 결과 범위만).
- 주지 않는 것: 다른 고객의 질의 원문과 실행 기록, 이용자 개인정보, 다른 제공자의 수치. 공개 "확인됨"·"후원" 표시도 없다(PM 결정 3).
- 확인이 중간에 `lapsed`되면 이용권 기간은 계속 흐르되 알림·분석 화면은 "확인 다시 하기"만 보인다. 기간을 늘려 주지 않는다. 환불은 6절을 따른다.

### 2.2 개발자 이용권 (developer)
- 가격: 20 USDC / 30일(사용자 결정 11-15).
- 대상: 계정이 있는 누구나(에이전트를 만드는 개발자, 우리 MCP·A2A·REST를 많이 부르는 쪽)
- 주는 것
  - API 키 1개(재발급 가능, 한 번에 유효한 키는 1개)
  - 높은 호출 한도
    - 지금 공개 한도: Chat 60/분, 방문자 토큰 규칙
    - 이용권 한도: **무료 한도의 배수**로 둔다(PM 11:4x 결정 3). 배수는 PM이 운영·SRE와 검색과 RAG의 제안(엣지 실행 칸 4개·추천 지연 목표 안에서 몇 배까지 되는지)을 받아 정한다. 설정 키 `developer_limit_multiple`.
  - 광고 없는 결과(= 광고 제거 구독): MCP·A2A·REST 응답의 `sponsored` 칸을 비운다. 유기 결과는 이용권 여부와 상관없이 같다(중립). 민감 주제는 지금도 광고가 없다.
  - 서명 피드 대량 접근: 공개 서명 피드(시험 보고서·등급 스냅샷)를 페이지 한도 없이 내려받는다. 무료 쪽은 지금 한도를 그대로 둔다. 피드 내용은 무료와 같고, 양과 속도만 다르다.
- 키를 보내지 않거나 기간이 끝난 키면 지금과 똑같이 공개 한도와 광고가 적용된다. 오류를 내지 않고 조용히 일반 요청으로 처리하고, 응답 헤더 `X-Pass: expired`만 붙인다.
- 키 공유: 약관에서 한 조직 안의 공유만 허용한다. 한도가 키 단위라 공유해도 한도는 늘지 않는다.

## 3. 결제 흐름 (광고 예약과 같은 엔진)
1. 고객이 종류를 고르고 "Pay in USDC"를 누른다. 서버가 견적을 만든다.
   - 금액: 가격 + 고유 끝자리(0.000001~0.009999)
   - 받는 주소, Base 체인 ID, USDC 토큰 주소
   - 기한: 30분
2. 고객이 자기 지갑에서 그 금액을 보내고 tx 해시를 붙여 넣는다.
3. 서버가 확인한다. 기존 `PaidBookings._check`와 같은 규칙이다.
   - 영수증 status 1인지, 체인·토큰·받는 주소가 맞는지
   - Transfer 금액이 견적과 정확히 같은지
   - 확정 3블록이 지났는지
4. 보낸 주소를 제재 목록과 대조한다. 목록이 맞거나, 없거나, 낡았으면(2일) `review`로 보낸다.
5. 확정되면 `active`가 되고 원화 환율을 적는다.
   - 시작 시각: 확정 시각
   - 끝 시각: 시작 + 30일
   - 개발자 이용권이면 이때 키를 한 번만 보여 준다.
- 가격은 코드 상수가 아니라 모듈 설정 파일 `agent_market/ad_coin/usdc_passes_config.json`(`{"provider_units": 10000000, "developer_units": 20000000, "days": 30, "developer_limit_multiple": null}`)에 둔다. PM이 바꾸고, 바뀐 값은 다음 견적부터 적용된다(이미 낸 견적은 그 금액 그대로). `agentcon.env` 허용 목록에는 새 키를 넣지 않는다(PM 11:4x 결정 2, 11-14 04:34 사고).
- 대기 이용권: 같은 종류는 만료 전에 다음 30일을 1장까지 미리 살 수 있다. 2장째 견적은 `pass_already_queued`로 거부한다(PM 11:4x 결정 6).
- 끝자리 겹침 방지
  - 받는 주소가 광고 예약과 같으므로, 끝자리는 두 표를 합쳐 7일 안에 쓰이지 않은 값으로 고른다(지금 R32 규칙을 두 표로 넓힘).
  - 같은 tx 해시는 두 표를 통틀어 한 번만 쓸 수 있다. 제출 때 두 표를 다 확인하고, 각 표의 UNIQUE 제약으로도 막는다.
- 금액이 다르거나 늦게 온 결제는 붙이지 않는다. 지금처럼 매일 대사(`scripts/ad_coin_paid_reconcile.py`)에 나오고, 운영자가 환불을 정한다.
- 미리 사기(갱신): 기간이 남았을 때 새로 사면, 새 이용권은 지금 것이 끝나는 시각에 시작한다. 대기 중인 이용권은 종류별로 1장까지만 허용한다(선충전처럼 쌓이지 않게). 2장째 견적은 `pass_already_queued`로 거부한다.

## 4. 무엇에 묶이나
| 묶는 대상 | 제공자 | 개발자 | 이유 |
|---|---|---|---|
| 계정(`customer_id`) | 필수 | 필수 | 화면·재발급·환불 기록의 주인 |
| 소유 확인(`claim_id`) | 필수 | - | 자기 자원만 보게 함 |
| 결제 지갑 주소(`payer`) | 기록 | 기록 + 키 복구 수단 | 환불 받을 곳, 계정을 잃었을 때 본인 증명 |
| API 키 | - | 필수(해시만 저장) | 에이전트가 쓰기 쉬움. MCP·A2A·REST에 같은 헤더를 씀 |

- 키
  - 생성: 32바이트 난수. 형식은 `avc_pass_` + base32이고, 저장값은 `sha256(key)`와 마지막 4자다.
  - 원문은 확정 응답에서 한 번만 보여 준다.
  - 요청 헤더: `Authorization: Bearer avc_pass_…`. A2A·MCP 클라이언트가 이 헤더를 못 넣으면 `X-Pass-Key`도 받는다.
  - 쿼리 문자열로는 받지 않는다(로그·캐시에 남음).
- 재발급
  - 로그인한 계정 주인이 하면 옛 키는 바로 끊긴다(메모리 반영까지 최대 60초).
  - 계정을 잃었을 때: 결제 지갑으로 서명한 문장(EIP-191, 이용권 ID와 10분짜리 nonce 포함)을 내면 운영자 검토 뒤 새 키를 준다. 1단계에서는 운영자 수동 처리로 둔다.
- 서명 주소만으로 쓰는 방식(요청마다 서명)은 에이전트 구현 부담과 서명 검증 비용 때문에 1단계에 넣지 않는다.

## 5. 표와 등록 SQL
- 자기 스키마 `usdc_passes`에 둔다(제공자 확인 `provider_claims`와 같은 방식).
  - 공용 카탈로그(`application_store_sql.json`)에 새 표를 먼저 올리면, 표를 만들기 전까지 frontend가 시작하지 못한다.
  - 그래서 모듈 자체 SQL 목록(`agent_market/ad_coin/usdc_passes_sql.json`)에 있는 문장만 보낸다.
  - 이 목록을 카탈로그 밖에 두는 것은 provider_claims와 같은 PM 결정 사항이다.
- 트리거·함수는 만들지 않는다(public 트리거 5개 불변식).
- 앱은 표를 만들지 않는다. 표가 없으면 기능이 꺼진 채로 5분마다 다시 본다.

```sql
CREATE SCHEMA IF NOT EXISTS usdc_passes;
CREATE TABLE IF NOT EXISTS usdc_passes.passes(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('provider','developer')),
  customer_id TEXT NOT NULL, claim_id TEXT,                      -- provider면 필수(앱에서 검사)
  state TEXT NOT NULL CHECK (state IN ('quoted','confirming','queued','active','expired','review','refund_due','refunded','cancelled')),
  amount_units BIGINT NOT NULL CHECK (amount_units > 0), pay_to TEXT NOT NULL, chain_id BIGINT NOT NULL, token TEXT NOT NULL,
  tx_hash TEXT UNIQUE, payer TEXT, krw_rate TEXT, note TEXT,
  quoted_ms BIGINT NOT NULL, quote_expires_ms BIGINT NOT NULL, confirmed_ms BIGINT,
  starts_ms BIGINT, ends_ms BIGINT, refund_tx_hash TEXT UNIQUE);
CREATE INDEX IF NOT EXISTS passes_customer ON usdc_passes.passes(customer_id, kind, state);
CREATE INDEX IF NOT EXISTS passes_state ON usdc_passes.passes(state, quote_expires_ms);
CREATE INDEX IF NOT EXISTS passes_amount ON usdc_passes.passes(amount_units, quoted_ms);   -- 끝자리 겹침 검사

CREATE TABLE IF NOT EXISTS usdc_passes.pass_keys(
  key_hash TEXT PRIMARY KEY, pass_id TEXT NOT NULL REFERENCES usdc_passes.passes(id),
  last4 TEXT NOT NULL, created_ms BIGINT NOT NULL, revoked_ms BIGINT);
CREATE UNIQUE INDEX IF NOT EXISTS pass_keys_live ON usdc_passes.pass_keys(pass_id) WHERE revoked_ms IS NULL;

CREATE TABLE IF NOT EXISTS usdc_passes.pass_events(               -- 추가만 하는 감사 기록, 5년 보존(지우지 않음)
  id TEXT PRIMARY KEY, pass_id TEXT NOT NULL, at_ms BIGINT NOT NULL, kind TEXT NOT NULL,
  from_state TEXT, to_state TEXT, actor TEXT NOT NULL, reason TEXT, tx_hash TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS pass_events_pass ON usdc_passes.pass_events(pass_id, at_ms);
```

- 이름 붙은 SQL(초안)
  - 견적: `pass_insert`, `pass_get`, `pass_open_for_customer`, `pass_tail_used`
    - `pass_tail_used`는 `ad_coin_v2.adc2_paid_bookings`와 `usdc_passes.passes`를 UNION으로 함께 본다.
  - 제출: `pass_tx_used`(두 표 확인), `pass_set_state`, `pass_set_confirmed`
  - 키: `key_insert`, `key_revoke`, `keys_active`(메모리 갱신용, `ends_ms > now`인 active 이용권의 살아 있는 키)
  - 작업자: `passes_expire_quotes`, `passes_confirming`, `passes_activate_queued`, `passes_expire_ended`
  - 운영: `passes_review`, `pass_decide`, `passes_export_month`
  - 감사: `pass_event_insert`, `pass_events_of`
- DB 변경 절차(CLAUDE.md, `deploy/DATABASE_OPERATIONS.md`)
  - `deploy/db-changes/usdc-passes-v1.sql`과 복구 SQL `usdc-passes-v1-rollback.sql`(행이 0일 때만 DROP SCHEMA)을 준비한다.
  - `scripts.db_change_rehearsal run`으로 네 역할(frontend·admin·jobs·execution)의 운영 커밋이 붙는지 확인한다.
  - 사용자 승인을 받고, 실행 직전 `check`가 0인지 확인한다. 애플리케이션 DB 역할로 실행해 앱이 표를 소유하게 한다.
- 연결: 기능 전용 연결을 프로세스당 1개 쓰고 문장마다 2초 제한을 둔다. 운영 max_connections 48 예산 안에서 provider_claims와 같은 몫으로 잡는다.

## 6. 요청 경로, 만료, 환불
- 요청 경로(개발자 이용권)
  - front 프로세스가 60초마다 `keys_active`로 `{key_hash: (pass_id, ends_ms, limits)}`를 메모리에 다시 읽는다. 요청 때는 `sha256` 한 번과 사전 조회만 한다(DB·DNS 없음, R39와 같은 원칙).
  - 키가 끊기거나 만료가 반영되기까지 최대 60초 걸린다. 이 지연은 약관과 화면에 적는다.
  - 한도는 키 단위 토큰 버킷(프로세스 메모리)이다. 프로세스가 여러 개면 프로세스 수로 나눈 값을 쓴다(지금 공개 한도와 같은 방식).
  - 광고 칸: `ad_slot.fill(ctx)`에 `pass_active`를 넘겨 비운다. `/ads/library`와 광고 집계에는 "이용권으로 비운 횟수"만 따로 센다.
- 만료
  - 작업자(jobs)가 5분마다 `ends_ms`가 지난 active를 expired로 바꾸고, 같은 종류의 queued 이용권을 active로 올린다.
  - 7일 전과 1일 전에 계정 화면에 안내를 띄운다(메일 없음, 결정 5).
- 환불
  - 원칙: 환불은 운영자 판단과 사용자의 직접 송금으로만 한다. 운영자가 "환불 필요"(refund_due)를 적으면 이용권은 바로 멈춘다.
  - 사용자가 지갑에서 보낸 뒤 환불 tx를 기록하면 refunded가 된다. 기록할 때 기존 `_verify_refund`처럼 체인에서 금액과 받는 사람을 확인한다.
  - 원칙(PM 11:4x 결정 4): **쓰기 시작한 이용권은 환불하지 않는다.** 우리 쪽 사유로 쓰지 못한 날은 그 날짜만큼 `ends_ms`를 늘린다(연장 기록은 `pass_events`에 `kind='extended'`, 사유와 일수). 송금 환불은 사용자가 직접 해야 하므로 예외로만 한다(예: 확정됐지만 한 번도 쓰지 못한 채 우리 쪽 사유로 서비스를 닫는 경우).
  - 금액이 틀린 결제, 늦은 결제, 제재 대조에 걸린 결제는 이용권을 열지 않고 review로 보낸다. 판단은 운영자가 한다.

## 7. 원화 환산과 거래 기록
- 확정 때 환율(지금 `upbit_krw_rate`, 실패하면 `krw_rate_unavailable`로 적고 운영자가 채움)과 tx 해시, 보낸 주소를 적는다.
- 월별 내보내기(`/admin/paid-bookings/export`)에 `kind` 열(booking·provider_pass·developer_pass)을 더해 한 파일로 낸다. 정기 세금 신고용 기록은 처음부터 남긴다(사용자 결정 11-11).
- 감사 기록 `pass_events`는 5년 보존하고 지우지 않는다(광고 예약 `adc2_paid_booking_events`와 같음).

## 8. 켜고 끄기
- 스위치: 모듈 설정 파일의 `"enabled_kinds": []`(기본 꺼짐). `["developer"]`처럼 종류별로 켠다. `agentcon.env`에는 새 키를 넣지 않는다.
  - 켜는 것은 PM이다(PM 11:4x 결정 1). 제공자 이용권은 소유 확인 표(11-18 승인 요청) 뒤, 개발자 이용권은 API 키·한도 적용이 되는 대로 연다. 이용률·고객 수 문턱은 두지 않는다.
- 꺼지면 새 견적만 막는다. 이미 산 이용권은 끝까지 효력이 있고, 확인 중인 결제도 계속 확인한다. 돈을 받은 뒤 혜택을 끊지 않는다.
- 표가 없으면 스위치가 켜져 있어도 꺼진 것과 같다(견적 409, 목록 빈 값).

## 9. 나눌 경계 (구현할 때)
| 팀 | 맡을 것 |
|---|---|
| AI AD Coin | **결제·만료·기록**: `agent_market/ad_coin/usdc_passes.py`(견적·확인·작업자·감사, `PaidBookings`의 확인 함수 공유), SQL 목록, 고객 API `/api/customer/passes`, 운영 API, 대사·월별 내보내기 확장, 키 발급·해시 저장, 활성 키 목록을 내주는 읽기 함수, 시험 |
| 에이전트 팀 + 성장·유통 | **제공자 혜택 화면**: 알림(다운·지문 변경·등급 변화)과 노출 분석·시험 기록 내보내기 데이터는 에이전트 팀, 계정 화면 "Passes"와 혜택 화면(영어, 디자인 시스템·화면 정책)은 성장·유통 |
| 검색과 RAG + 운영·SRE | **개발자 한도·키 적용**: front 요청 경로의 키 확인(60초 메모리 갱신)·한도·광고 칸 비우기·서명 피드 한도는 검색과 RAG(front.py는 공유 파일이라 자기 hunk만), DB 변경 리허설·실행 준비, `agentcon.env` 허용 목록, 작업자 일정(jobs), 연결 예산, 깔때기 줄에 이용권 수는 운영·SRE |

## 10. 결정된 것과 남은 것
- 결정(사용자 11-15): 판매한다. 제공자 10 USDC, 개발자 20 USDC, 30일, 이용권 1건 = 결제 1건, 자동 갱신·선충전·보관 없음. 약관·환불 문구는 PM 재량.
- PM 결정(11:4x): 판매 시점은 문턱 없이 만들어지는 대로, 가격은 설정 파일, 개발자 한도는 무료의 배수(배수는 제안을 받아 PM이 정함), 환불은 쓰기 시작하면 없음·못 쓴 날은 연장, 메일 없이 화면과 피드, 대기 이용권 1장 허용, 모듈 SQL 목록은 카탈로그 밖(provider_claims와 같은 조건: 문장마다 해시 대조, 한 줄씩 추가만), 운영 DB에 닿는 코드는 운영·SRE 검토 뒤 PM 접수.
- 남은 것: 개발자 한도 배수(PM), 약관 문구 확정(PM, `docs/REVENUE_TERMS_DRAFT_2026-11-15.md`), 표 생성(사용자 승인, 11-17 밤 리허설에 provider_claims·adc2_paid_plans와 묶음, 승인 요청은 PM이 11-18에 한 번에).

## 11. 열린 문제
- 목걸이 호출당 결제는 보류다(사용자 결정 11-15, 무료 이벤트). 아래 부록 참고.
- 이용권 결제와 광고 예약이 한 주소를 쓰므로, 매일 대사 보고서에 두 표를 함께 보여 준다.

## 부록. 목걸이 호출당 과금 (닫음)
**사용자 결정(11-15, PM 11:3x 전달): 만들지 않는다.** 처음엔 무료 이벤트로 열고, 지금은 사용자 수를 늘리는 것이 먼저다. 아래 판단과 워크플로우 설계 메모(`reports/necklace-billing-design-2026-11-15/README.md`)만 남기고 이 과제를 닫는다. 다시 열 때는 아래 6가지부터 본다.

### 판단: `agent_market/payments.py`를 쓸 수 있나 (AI AD Coin, 11-15)
워크플로우 팀 설계(`reports/necklace-billing-design-2026-11-15/README.md`, 212549e8)를 읽고 판단했다.

**결론: 쓸 수 있다.** `PaymentVerifier.verify(tx, sig, body, price)`를 검증 핵심으로 쓰고, 아래 6가지를 바깥에 더한다.
- 그대로 맞는 점
  - 받기만 하고 상태가 없다(개인키 없음, 보관 없음).
  - 영수증 status·받는 주소·USDC 토큰·송금자 1명·금액 하한·확인 블록 수를 본다.
  - 송금 지갑의 서명을 요청 본문에 묶는다(EIP-712에 체인 ID와 토큰 포함). 남의 tx 해시를 가로채 쓰는 것을 막는다.
  - `eth_account`는 `requirements.txt`에 있다.

| # | 보탤 것 | 이유 |
|---|---|---|
| 1 | **tx 해시 한 번만: 모든 USDC 표를 통틀어 확인**(`adc2_paid_bookings`, `usdc_passes.passes`, `necklace_payments`) | 받는 주소가 같으면, 광고 예약에 쓴 5.00x USDC tx를 그 지갑 주인이 서명만 해서 목걸이 실행값으로 다시 쓸 수 있다(금액이 가격 이상이므로 통과함). 받는 주소를 따로 쓰는 방법도 있지만 지갑 관리가 사용자 몫이라 공용 확인 함수 하나(`tx_used_anywhere`)를 권장한다. |
| 2 | RPC는 `paid_bookings.default_rpc()`(두 공개 노드 일치, 호출당 4초)를 넘긴다 | `PaymentVerifier`가 받는 `chain.RPC`의 기본 제한 시간은 20초이고 노드 하나만 본다. 요청 경로에는 길고, 노드 하나의 말로 확정하게 된다(R36). 인터페이스(receipt·block_number·chain_id)가 같아 바로 넘길 수 있다. |
| 3 | 제재 주소 대조는 `paid_bookings.Sanctions`를 같이 쓴다 | verifier에는 없다. 목록이 없거나 낡았으면(2일) 실행하지 않고 `refund_candidate`로 적는다. |
| 4 | 오류 문장은 영어로 바꿔 내보낸다 | verifier의 일부 메시지가 한국어다. 에이전트가 읽는 응답은 영어 규칙이라, `error_code`에 영어 문장을 붙이는 표를 목걸이 쪽에 둔다(본문 문자열을 그대로 내보내지 않음). |
| 5 | MCP·A2A는 "본문 전체"가 아니라 정규화한 실행 인자에 서명하게 한다 | JSON-RPC는 다시 보낼 때 `id`가 바뀌어 본문 바이트가 달라진다. 그러면 서명이 깨져 재시도(설계 4절)가 안 된다. `{"necklace","version","input"}`을 정렬한 JSON으로 정해 세 표면에 같게 쓴다. |
| 6 | 원화 환율은 10분 캐시로 기록한다 | 실행마다 업비트를 부르면 응답 시간에 외부 호출이 하나 더 붙는다. 확정 시각과 캐시된 환율을 같이 적는다. |

- 금액이 가격보다 많으면 받은 금액을 그대로 기록한다. 가격의 2배를 넘으면 `refund_candidate`로 표시한다(잔액을 만들지 않으므로 남는 돈을 다음 실행에 쓰지 않는다).
- 확인 블록 수: 광고 예약은 3이다. 0.005 USDC 실행은 1로 두고, 재조직이 생기면 대사에서 잡는다(워크플로우 설계 9절과 같음).
- 같은 받는 주소를 쓰면, 매일 대사(`scripts/ad_coin_paid_reconcile.py`)가 세 표를 함께 보도록 넓힌다. 이것은 AI AD Coin이 맡는다.
