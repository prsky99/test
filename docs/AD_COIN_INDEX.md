# AI AD Coin 문서 색인 (2026-11-16 기준, 처음 11-10)

AD Coin 문서가 많아 무엇이 지금 기준인지 찾기 어려워서 만든 색인이다. 문서를 새로 쓰거나 기준이 바뀌면 이 표를 함께 고친다.

## 0. 지금 켜진 것과 꺼진 것 (11-16, 코드 기본값과 운영 설정 기준)

| 스위치 | 코드 기본값 | 운영 | 어디서 | 뜻 |
|---|---|---|---|---|
| `AD_COIN_V2_ENABLED` | 0 | **1** | `gateway-data/agentcon.env` (`scripts/agentcon_config.ALLOWED_KEYS`) | v2 포인트 모드와 `/ad-coin/v2` 작업 공간 |
| `MAIN_SPONSORED` | 0 | **1** | `gateway-data/sponsored.env` (`SPONSORED_KEYS`) | 메인 탐색·Chat의 Sponsored 칸 |
| `AD_COIN_PAID_BOOKING_ENABLED` | 0 | **1** (11-14 사용자 결정) | `sponsored.env` | USDC on Base 건별 결제 예약. 작업자 데몬도 같은 파일을 따른다(`scripts/adcoin_worker_env.py`) |
| 맞춤 광고 계획 | 표가 있으면 열림 | 표 적용 전(11-17 오후 PM) | `ad_coin_v2.adc2_paid_plans` 존재 여부 | 표가 없으면 계획은 제안만 하고 팔지 않는다 |
| `AD_COIN_AUTO_REVIEW_ENABLED` | 0 | 꺼짐(키 없음) | 데몬이 `sponsored.env`에서 받음 | 캠페인·에이전트 제안 자동 심사. **11-16 현재 `SPONSORED_KEYS`에 없어, 이 키를 `sponsored.env`에 쓰면 frontend 설정 읽기가 실패한다.** 키 추가 코드가 네 역할에 나간 뒤에만 켠다. 차단 목록 출처는 없음(11-16 PM 결정): 에이전트 제안은 사람이 심사 |
| `AD_COIN_REAL_VALUE_ENABLED` | 0 | 켤 수 없음 | 허용 목록에서 일부러 뺌 | 판매·현금화·체인 출고 없음(헌장 1절) |
| v1 `AD_COIN_ENABLED` | 0 | 설정 없음 | `agent_market/ad_coin/config.py` | v1은 시험 전용 동결(`AD_COIN_V1_FREEZE.md`) |
| 이용권(USDC 30일) | — | 구현 안 됨 | `USDC_PASS_DESIGN.md` | 설계만 |

운영에 등록하지 않은 v2 경로: `ad_relay`, `advertiser_platform`, `agent_payment`(`include_unused_routes=False`).

**켜고 끄는 순서(PM 11-16):**
- USDC 결제 스위치는 `docs/AD_COIN_USDC_SWITCH_RUNBOOK.md`를 따른다.
- 자동 심사(`AD_COIN_AUTO_REVIEW_ENABLED`):
  1. `scripts/agentcon_config.SPONSORED_KEYS`에 키를 더한 코드가 배포된다.
  2. frontend·admin·jobs·execution 네 역할이 모두 그 키를 아는 버전인지 `./agentcon status`로 확인한다.
  3. 확인한 **뒤에만** `sponsored.env`에 키를 쓴다. 그 전에 쓰면 그 파일을 읽는 역할의 설정 읽기가 실패한다.
- 켜는 것은 PM 결정이다. 끄려면 키 줄을 지우거나 0으로 둔다. 데몬은 파일이 바뀌면 다시 읽는다.

## 1. 지금 기준 (먼저 읽을 것)

| 주제 | 문서 | 요약 |
|---|---|---|
| 운영 원칙 | `docs/OPERATIONS_CHARTER.md` 1절 | 지출 0, 수익·지출은 코인으로만, 법정화폐 거래 없음, 규제 영역 회피 |
| 코인 경제 | `docs/AD_COIN_COIN_ECONOMY.md` | 플랫폼↔사용자만 오가는 닫힌 고리, 광고주 코인 획득 경로, 성장 지출, 발행 상한(설계안) |
| 포인트 모드 | `docs/AD_COIN_POINTS_MODE.md` | 구매·현금화·사람 간 이전 불가, 플랫폼 혜택에만 사용, 365일 만료(구현됨) |
| Sponsored 영역 | `docs/AD_COIN_SPONSORED_SLOT.md` | 추천과 분리된 공개 광고 영역, 속도 측정(구현됨) |
| 운영 연결 | `docs/AD_COIN_V2_PROD_CONNECT.md` | 운영 DB 표·설정·연결 예산, 승인 목록 A1~A3 |
| v1 동결 | `docs/AD_COIN_V1_FREEZE.md` | v1은 시험 전용, 보안 수정만 |
| 개인정보 | `docs/AD_COIN_PRIVACY_FLOW.md` | 실제 표 기준 처리 흐름, 감사 로그 최소화·보존 기간 |
| 화면 문구 | `docs/AD_COIN_SCREEN_COPY.md` | 공개 화면 문구와 내부 용어 정리 목록 |
| 토큰 계약 | `docs/AD_COIN_TOKEN_CONTRACT.md` | 감사 전 초안, 결함 C1~C8과 Foundry 동작 시험. 배포하지 않음 |
| 판매 정책(v1) | `docs/AD_COIN_SALES_POLICY.md` | v1 광고 판매 정책과 11-05 결정(15초, Chat 분리, 5년 보존) |
| 목표·관문(v1) | `docs/AD_COIN_TARGETS.md` | 리허설 목표와 보안 관문 |
| 개요(v1) | `docs/AD_COIN.md` | v1 구조와 운영 방법 |
| USDC 결제 켜기·끄기 | `docs/AD_COIN_USDC_SWITCH_RUNBOOK.md` | 스위치 한 장, 검토 사례(11-14) |
| 첫 실제 결제 점검 | `docs/AD_COIN_FIRST_PAYMENT_CHECKLIST.md` | r10 뒤 확인, 계획 표 리허설, 첫 결제 때 볼 것(11-16) |
| Sponsored 계약 | `docs/AD_COIN_SPONSORED_CONTRACT.md` | 탐색·Chat 공용 Sponsored API 계약(11-11) |
| 지역 판매 | `docs/AD_COIN_GLOBAL_REGION_DESIGN.md` | '기타 모든 나라(GLOBAL)' 판매(11-12) |
| 자사 광고 | `docs/AD_COIN_HOUSE_AD_DAILY.md` | 자사 광고 매일 예약(11-12 설계) |
| 포인트 혜택 | `docs/AD_COIN_BENEFITS.md` | 혜택 후보와 비용 0 근거(11-10) |
| 매출 약관 | `docs/REVENUE_TERMS_DRAFT_2026-11-15.md` | 이용권·맞춤 계획·광고주 제한 없음(11-15 결정 반영 초안) |
| 이용권 | `docs/USDC_PASS_DESIGN.md` | 제공자 10·개발자 20 USDC/30일 설계(구현 전). 광고 제거 구독 메모(`AD_FREE_SUBSCRIPTION_DESIGN.md`)는 여기에 합쳐졌다 |
| 광고 문구 규칙 | `agent_market/ad_coin/v2/ad_rules.py` | 금지(HARD)·사람 판단(REVIEW) 규칙 한 곳(5b0b8b9d). 사람이 승인할 때마다 다시 검사 |
| 결제 코드 | `agent_market/ad_coin/v2/paid_bookings.py`, `paid_plans.py`, `paid_audit.py`, `scripts/ad_coin_worker_daemon.py` | 견적·확인·확정·환불 검증·대사·영수 최종성. 매일 대사 `scripts/ad_coin_paid_reconcile.py`, 제재 목록 `scripts/ad_coin_ofac_refresh.py` |

## 2. v2 설계 기준 (v6.2)

| 문서 | 내용 |
|---|---|
| `docs/AD_COIN_PLATFORM_ARCHITECTURE.md` | v6.2 설계 결정 DEC-01~13 |
| `docs/AD_COIN_PLATFORM_DESIGN_UPGRADE.md` | v6.2 보강 |
| `docs/AD_COIN_V6_2_DETAILED_DESIGN.md`, `docs/ad_coin_v6_2_detail/` | 상세 설계(도메인·저장·API·작업자·화면) |
| `docs/AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md` | 작업 묶음 WP-01~12(11-07 계획, 모듈 이름은 실제와 다름. 문서 머리 표 참고) |
| `docs/ad_coin_platform_p1_v6_2.openapi.json`, `docs/ad_coin_platform_v6_2_spec.json` | API 계약 |
| `docs/AD_COIN_PLATFORM_DATA_API.md`, `docs/AD_COIN_PLATFORM_POLICY.md`, `docs/AD_COIN_PLATFORM_ROADMAP.md` | 데이터 API, 정책, 로드맵 |

**주의:** v6.2 문서에는 실제 가치 모드(준비금, 상환, 체인)가 있다. 11-09·11-10 결정으로 그 부분은 **잠근 채로 둔다**. 지금 기준은 1절이다.

## 3. 역사본 (참고만)

| 문서 | 상태 |
|---|---|
| `docs/AD_COIN_ARCHITECTURE.md`, `docs/AD_COIN_POLICY.md` | v6.1 이전 설계 |
| `docs/AD_COIN_V5_IMPLEMENTATION_PLAN.md`, `docs/ad_coin_v5_spec.json`, `docs/ad_coin_platform_v6_1_spec.json`, `docs/ad_coin_platform_p1.openapi.json` | v5·v6.1 계약 |
| `docs/AD_COIN_TERMS_DRAFT.md` | 시험 이용 조건 초안. 포인트 모드에 맞게 다시 써야 함 |
| `docs/AD_COIN_LAW_FIRM_CANDIDATES.md`, `reports/AI-AD-Coin-법률검토-쟁점초안-2026-11-09.md` | 법률 작업 보관(11-09 중단). 법령 원문 확인 결과 포함 |

## 4. 보고서 (`reports/`)

| 보고서 | 내용 |
|---|---|
| `AI-AD-Coin-소스분석-2026-11-09.md` | v1·v2 소스 분석과 개선사항 17개 |
| `AI-AD-Coin-v2-현황과-법률검토자료-2026-11-09.md` | v2 진행 상황(11-09) |
| `AI-AD-Coin-보안점검-2026-11-05.md`, `ad-coin-security-2026-11-05/` | v1 시큐어코딩·동적 점검 219개 |
| `AI-AD-Coin-운영-리허설-2026-11-05.md`, `ad-coin-rehearsal-2026-11-05/` | v1 부하 리허설 |
| `ad-coin-v6.2-*` | v2 개발·검증 증거(WP-01~04, 화면·성능) |
| `AI-AD-Coin-business-plan-v3-2026-11-04.md` 등 | 사업계획(실가치 부분은 지금 기준이 아님) |
