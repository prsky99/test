# AI AD Coin 문서 색인 (2026-11-10 기준)

AD Coin 문서가 많아 무엇이 지금 기준인지 찾기 어려워서 만든 색인이다. 문서를 새로 쓰거나 기준이 바뀌면 이 표를 함께 고친다.

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

## 2. v2 설계 기준 (v6.2)

| 문서 | 내용 |
|---|---|
| `docs/AD_COIN_PLATFORM_ARCHITECTURE.md` | v6.2 설계 결정 DEC-01~13 |
| `docs/AD_COIN_PLATFORM_DESIGN_UPGRADE.md` | v6.2 보강 |
| `docs/AD_COIN_V6_2_DETAILED_DESIGN.md`, `docs/ad_coin_v6_2_detail/` | 상세 설계(도메인·저장·API·작업자·화면) |
| `docs/AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md` | 작업 묶음 WP-01~12와 진행 |
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
