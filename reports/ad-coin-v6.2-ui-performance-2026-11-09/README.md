# AI AD Coin v6.2 화면·성능 구현 검증

2026-11-09 한국 시간. 범위는 PostgreSQL 전용 모델 앱과 localhost Chromium이다. 보안·정합성을 유지하며 별도 사용자/광고주 화면과 DB 접근 성능을 개선했다. 운영 서버·배포·운영 DB·실자금·체인은 변경하지 않았다.

## 구현과 수정

- `/ad-coin/v2` 정적 영어 화면: Rewards, Your choices, Advertising, Reports. 기존 Pearl 테마와 로컬 Lucide SVG, 390px 모바일·light/dark·reduced motion·focus/skip link를 적용했다. 새 화면은 `router_for(..., include_workspace=True)`일 때만 등록되며 기본값은 false다. 실제 앱에는 아직 등록하지 않았다.
- 처음 진입 시 API 조회 0, shell의 DB 접근 0. 계정 정보는 사용자가 여는 동작 이후 조회한다. 지갑/권한 캐시를 만들지 않고 서버 값을 다시 읽는다. fingerprint/ETag/immutable 정적 자산만 캐시하며 개인 응답은 no-store다. 전면 로딩/팝업 없이 inline 검토와 작은 비차단 진행 표시를 쓴다.
- 수신 선택과 세 가지 맥락 공유는 독립적이며 기본 해제다. 조건·정확한 보상 배분을 검토한 후 건별 승인한다. 승인 전 소재를 요청하지 않는다. P1은 클릭·구매·퀴즈 없이 검증된 노출로 보상한다. 화면 진행은 추정치이며 서버 검증이 최종 판단한다. 시험 코인에 현금 가치·실제 AI 결제가 있다고 표시하지 않는다.
- 광고주 draft→심사 요청→예산 검토/승인→활성화→중지→재개와 보고 조회를 기존 API에 연결했다. 심사자는 별도 인증 경계를 유지한다. 예산 승인/활성화의 역할과 버전은 서버가 재검사하며 재개 시 예산을 다시 차감하지 않는다. 캠페인 목록은 keyset 10개, 고정 쿼리다.
- CSP와 정적 자산 allowlist, cookie/CSRF 전송, DOM textContent, BigInt 금액, 재시도 시 동일 멱등 키, scope/owner/최신 guard를 적용했다. 인증 철회 시 개인 상태를 지우고 늦은 응답은 epoch로 차단한다. 화면에 principal/token/raw JSON을 표시하지 않는다.
- 검토 과정에서 승인 대기 중 메뉴 이동 경합을 수정했다. 숨겨진 부모 아래 높이 0인 카드가 가시 판정을 통과하지 못하게 했고, 네 승인 단계의 지연 응답을 각각 취소 의도와 대조한다. start 직후부터 세션을 추적해 취소하며 소재 조회 실패도 취소한다. 중지는 네트워크 응답 이전에 DOM을 숨긴다. 철회 저장은 취소 검증 완료를 기다리지 않는다.
- 명시적 schema 4 migration은 38개 표를 유지하고 여섯 인덱스를 추가한다. 미완료 journal/명령·활성 campaign, advertiser별 campaign·owner별 wallet·활성 membership이다. 원장 전역 미완료 검사·balance·잠금·nonce·권한 검사를 없애지 않았다. 3→4 및 반복 실행 후 잔액 불변을 시험했다.

## 검증 결과

- `final.xml` / `final.log`: **169 passed, 실패 0, 오류 0, skip 0**. 기존 SQLite 이전 시험 1개는 선택에서 제외했고 실행하지 않았다. v2 저장/DB 시험은 PostgreSQL만 사용한다. 151개 기존 기반 회귀와 새 workspace API 9개·Chromium 9개다. 기존 httpx TestClient deprecation 경고 1개는 남아 있으며 이번 기능 실패는 아니다.
- 브라우저: 실제 18초 전경 시청 후 사용자 0.5 test coins 지급, 조기 중지 무보상, 승인 전 소재 요청 없음, editor/approver 분리와 단회 예산 배정/재개, 모바일 overflow 없음, light/dark/reduced motion, keyboard skip link, 일부 텍스트 대비 ≥4.5, XSS 문자열 비실행, 권한 철회/늦은 조회 차단, challenge/consent/start/creative 지연 중 이동 모두 무시청 기록. 전체 접근성 인증이나 실제 사람 집중의 완전 증명을 주장하지 않는다.
- `secure-coding.json`: Ruff S 규칙 위반 0(v2와 기존 v1 api.py). 일반 Ruff·Node 구문 검사도 통과했다. `content-final.log`: 공개 frontend **335개 파일, 위반 0**. 동적 보안 회귀는 위 브라우저와 격리 PG/API 테스트 범위다. 독립 침투 테스트가 아니다.
- 두 P1 계약 파일은 동일하고 operation 29개를 유지한다. SQL registry 412개 중 기존 174개를 보존했다. `verify.py`는 최종 XML·성능 원장 보존·계약·SQL 및 소스/증거 SHA-256을 재확인해 `verification.json`을 만든다.

## 성능 측정과 한계

`scripts/ad_coin_v2_performance.py`는 사용자 DSN을 받지 않는다. PG 환경 변수를 격리하고 Unix socket 전용 임시 PG를 생성·제거한다. 6,000건 실제 balanced command 이력, 8개 미리 연 연결, 동일 guard와 21 DB calls(p50)를 유지한다. 소유한 임시 DB에서만 여섯 인덱스를 제거/복원한다. 최종 측정은 브라우저/회귀 종료 후 별도로 실행했다.

- `postgres-performance.json`: 각 단계 5초, 초당 200건 도착, **1,000/1,000 성공·실패 0**, 실측 처리량 200/s. 도착 지연 포함 p50 **3.951→3.149ms**, p95 **5.336→5.142ms**, p99 **6.649→5.777ms**. 서비스 시간 p50 2.417→1.495ms, p95 3.618→3.400ms. 정합성 검사 감소 0, beneficial 8,000,000 atoms 보존, 임시 DB 제거 확인.
- EXPLAIN ANALYZE의 미완료 journal/명령 검사는 0.749/0.854ms→각 0.009ms. 전체 plan을 JSON에 보존했다. 비교 후반은 전반의 1,000건이 추가된 이력이므로 정확히 같은 row 수는 아니다. 순서 고정 단일 로컬 비교로 반복 통계적 유의성을 증명하지 않는다.
- `browser-performance.json`: 로컬 Chromium 한 표본 FCP **36ms**, DOM ready 약 24.4ms, HTML 11,960 bytes·CSS 8,756 bytes·JS 27,474 bytes. long-task observer 활성, 해당 흐름의 관측 long task 0. 전체 방문자 p75/LCP/INP·저속 단말·WAN 측정이 아니다.
- 이 DB command는 HTTP·TLS·서명·AI 실행이 포함되지 않은 로컬 원장/멱등 작업이다. 200/s는 고정 도착 조건이며 최대 용량이 아니다. 글로벌 최고·운영 성능 달성을 주장하지 않는다. 초기 exploratory와 브라우저 동시 overlap 표본은 별도 JSON으로 보존했으며 최종 인수 수치에 사용하지 않는다.

## 실패 증거와 남은 범위

최초 `regression.xml`의 migration 보조 SQL 형식 실패와 `fixes.xml`의 보조 변수 오류를 수정하고 재검증했다. `navigation.xml`은 새 시험의 endpoint 오기와 route 해제 순서 문제로 실패했으며 `navigation-fixed.xml`에서 4개가 통과했다. 이후 제품 visibility/소재 오류 처리까지 포함해 전체 `final.xml`을 통과했다. 실패 로그를 삭제하지 않았다.

실제 IdP/쿠키 발급·mTLS/reviewer 증거 수집·조직 온보딩, 운영 DB role/RLS·복구/다지역 부하 인수, 실제 AI 사용 결제·발행/담보/체인·외부 지갑 이전은 남아 있다. 현재 model credential fixture를 운영 인증으로 사용하면 안 된다. 이번에 사용자 실행 서버를 시작·중지·재시작하거나 운영 플래그를 변경하지 않았다. 따라서 개발 화면은 격리 시험에서만 열리고 사용자 서버에는 자동 표시되지 않는다.

재현:

```sh
.venv-tests/bin/python -m pytest -q tests/test_ad_coin_v2_workspace.py tests/test_ad_coin_v2_workspace_browser.py tests/test_ad_coin_v2_review.py tests/test_ad_coin_v2_p1.py tests/test_ad_coin_v2_commercial.py tests/test_ad_coin_v2_persistence.py tests/test_ad_coin_v2_contracts.py tests/test_ad_coin_postgres.py -k 'not sqlite'
# Run after other tests stop; always creates its own disposable PostgreSQL cluster.
.venv-tests/bin/python -m scripts.ad_coin_v2_performance --duration 5 --out /tmp/aiac-v2-performance.json
.venv-tests/bin/python reports/ad-coin-v6.2-ui-performance-2026-11-09/verify.py
```

화면 증거: `desktop-offer.png`, `desktop-reward.png`, `advertiser-campaigns.png`, `mobile-choices-dark.png`.
