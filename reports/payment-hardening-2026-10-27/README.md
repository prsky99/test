# 결제 검증·게이트웨이 개선 결과

**운영 반영 확인 완료: `payment-hardening-20261027-r2` — 사용자 배포 후 frontend/admin/execution 정상, 운영 점검 36건 통과. 배포 전 패키지 548건과 별도로 기록한다. [배포·복귀 기록](DEPLOYMENT.md).**

2026-10-27. 사용자가 전달한 결제 개선 요약을 현재 소스 및 x402 공식 규격과 대조해 필요한 보완을 구현했다. 원래 `docs/qa/payment-improvement-plan.md`와 원본 15개 입력 결과는 로컬에 없었으므로, 요약을 바탕으로 [수정 계획서](../../docs/qa/payment-improvement-plan.md)를 새로 작성했다. 원본 테스트를 재현했다고 주장하지 않는다.

## 적용한 개선

1. **오류 분류:** 관리자 오프라인 EIP-3009 검사에 안전한 `error_code`와 `validation_stage`를 추가했다. 형식·버전·허용 네트워크/방식·수신자·금액·유효 기간·서명 오류를 구분하며 기존 HTTP 400과 내부 예외 코드는 보존했다. 잔액·온체인 nonce 소비·실제 정산을 검사한 것처럼 표시하지 않는다. 레거시 송금 영수증 검증에도 별도의 안정된 오류 코드를 적용했다.
2. **헤더·본문 경계:** 공개 x402 게이트웨이에 결제 증명을 보내면 `501 PAYMENT_EXECUTION_DISABLED`와 `payment_processed: false`로 명시적으로 거절한다. 기존 요구사항 조회 전용 정책을 유지한다. 비공개 프록시는 허용된 결제 증명 헤더 하나의 방식만 받으며 Host/Authorization/Cookie 등 임의 헤더와 혼합 증명을 차단한다. 중복 JSON 키·비정규 base64·NaN/무한대·과도한 중첩/크기도 거절한다. 레거시 판매자 요청 본문은 1MiB로 제한했다.
3. **정산 불확실성:** 영수증 누락·변조·네트워크/금액/지불자 불일치, pending, 응답 유실, 정산 후 서비스 실패는 성공으로 확정하지 않는다. 가상 예치금을 보류하고 자동 환불·재요청을 차단한다. 레거시 판매자의 예기치 않은 작업 실패도 기존 결제 claim을 유지해 재사용을 막는다. 제공자 영수증은 `settlement_verified: false`로 표시한다. 가상 예치금 반환이나 로컬 claim 해제는 실제 토큰 환불이 아니다.
4. **준비 상태·한도:** 공개 에이전트 응답의 `gateway_ready`를 현재 실행 검증과 지원 프로필에서 계산한다. 제공자 값은 신뢰하지 않는다. 일시적인 수용량 부족 503과 실제 제공자 실패는 기존 증거 체계로 구분한다. 429에 `Retry-After`, `RateLimit`, `RateLimit-Policy`를 제공한다. 검증되지 않은 결제 헤더로 한도를 우회시키지 않는다.
5. **credit·OpenAPI:** credit의 잔액 조회·본인 세션 경계를 유지하고 미지원 충전 인자와 저장소 예외를 구조화해 처리한다. 충전·구독은 준비 중으로 설명한다. 공개 OpenAPI는 명시한 공개 경로와 참조되는 스키마만 포함한다. 내부·워크스페이스·고객 인증·어드민 경로 및 불필요한 정의는 제외한다. 경로 비노출이 인증을 대신하지는 않는다.

## 제안에서 수정한 부분

- `PAYMENT-REQUIRED.error`는 선택적인 설명 문자열이다. 모든 제공자가 이를 표준 오류 enum으로 반환한다고 가정하지 않는다. `VerifyResponse.invalidReason`·`SettleResponse.errorReason`과 자체 API의 `error_code`를 구분한다.
- v1 제공자 서명을 v2라고 바꾸지 않는다. native v1/v2 증명을 그대로 전달하고 버전 불일치는 거절한다.
- 모든 503을 즉시 영구 추천 제외로 처리하지 않는다. 검증 결과의 현재성·관련성·기존 철회 경계를 유지한다.
- 일일 실제 0.001 USDC 결제는 실행·예약하지 않았다. 승인된 지갑·지출 상한·수수료 예산·정산기·중복 방지·수동 조정 절차가 필요하다. 현재 공개 프로브나 오프라인 검사를 실제 결제 기능으로 전환하지 않았다.

근거: [x402 core](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md), [HTTP transport](https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/http.md), [exact EVM](https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact_evm.md). `authorization`과 `upfront` 흐름은 실행·정산 순서가 다르므로 일률적인 10단계 완료를 주장하지 않는다.

## 검증 증빙

**최종 고유 546건 통과·실패 0·skip 0**이다. 통합 검사 520건(환경 문제였던 PostgreSQL 1건의 별도 통과 포함)과 Chromium 26건을 중복 제거했다. 동시 화면 변경 후 API 147건·브라우저 26건을 재확인했으며 이를 추가 합산하지 않았다. 공개 콘텐츠 309개 파일 위반 0건, 신규 정적 경고 0건이다. 실제 이체·운영 배포는 0이다. `validation-summary.json`, `test-inventory.json`.

- 결제 회귀: `tests/test_payment_improvements.py`. 고정 공개 서명 fixture와 가상 제공자만 사용했다. 임의 헤더·중복 증명·오류 우선순위·정산 pending/유실/불일치·보류 예치금·레거시 재사용·공개 프로브·한도·credit 장애·공개 스키마를 검사했다.
- 통합 실행: `integration-final.xml` / `integration-final.log`. 단위·ASGI·격리 저장소 검증 519건 통과, native PostgreSQL 리허설 1건은 처음에 환경 문제로 중단됐다.
- 해당 PostgreSQL 검사는 의존성을 갖춘 임시 인터프리터에서 별도로 **1건 통과**했다: `postgres-isolated-final.xml`, `postgres-isolated-final.log`. 사설 Unix 소켓의 일회용 DB만 사용하고 종료·삭제, 외부 제공자 호출 0, 운영 변경 0을 테스트가 확인한다. 제품 코드나 운영 의존성을 바꾸지 않았다. 초기 실패 로그도 보존한다.
- 실제 Chromium의 공개 화면·게이트웨이·관리자 보안 회귀: `browser-latest.xml` / `browser-latest.log`. CSP와 TLS를 완화하지 않고 ASGI 격리 앱으로 연결했으며 외부 호출을 차단했다. 기존 HTTP 400 기대값과의 차이를 발견해 제품 API 호환성을 보존하도록 수정했다. 샌드박스의 Chromium 실행 권한 문제와 수정 전 실패 로그는 별도 보존한다.
- 통합 도중 다른 작업의 공개 화면 파일 6개가 변경되어, 결제 구현 보존과 최신 API·브라우저 계약을 추가 확인했다: `concurrent-frontend-change.json`, `latest-contracts.xml`. 중간 실행 건수를 더해 통과 수를 부풀리지 않는다. 최종 중복 제거 결과는 `validation-summary.json`을 참조한다.
- 공개 콘텐츠 검사: `public-content-latest.log`. 영어·Chat 표시·메타데이터·embedded HTML 동기화 검사를 포함한다.
- 정적 검사: 12개 결제/게이트웨이 모듈의 기존 경고 **8건**, 신규 **0건**, 파싱 오류 0. 기존 릴리스와 같은 B104 Medium 3건·B110 Low 5건이다. `bandit-comparison.json`. 별도 front.py 검사도 기존 기준 27건에서 19건이며 신규 경고 0이다: `bandit-front-comparison.json`. 다른 작업의 기존 감소분을 이번 결제 개선 실적으로 계산하지 않는다. 경고를 숨기는 예외는 추가하지 않았다.
- PostgreSQL SQL 카탈로그의 SQL 3,806개와 스키마 232개는 기존 운영 릴리스와 동일하다. 소스 해시·위치 이름만 갱신했다: `catalog-comparison.json`, `sql-catalog-latest.log`. DB 마이그레이션은 없다.

## 변경 위치

- `agent_market/concierge/payment_wire.py`, `public_api_schema.py`: 제한된 결제 wire·공개 스키마 경계.
- `agent_market/concierge/proxy.py`, `managed_gateway.py`, `connections.py`, `mcp_contract.py`, `front.py`: 프록시·공개 API·credit·표시 상태.
- `agent_market/capability_registry.py`: 현재 검증에 근거한 준비 상태.
- `agent_market/workspace_x402_eip3009.py`, `workspace_protocol_conformance_service.py`: 오프라인 오류 분류·관리자 응답.
- `agent_market/payments.py`, `server.py`, `gateway/server.py`: 레거시 검증·오류·불확실한 작업 결과.
- `agent_market/application_store_sql.json`: SQL 변경 없는 소스 증빙 갱신.
- 관련 신규 결제 회귀 및 capability registry·관리자 API 회귀, 수정 계획서.

## 완료 경계와 운영 반영

이번 범위는 **기존 결제 경계 보존, 실패 진단·보안·호환성 보완과 격리 검증**이다. 실제 체인 이체, 정산기, 환불, mainnet canary, 결제 후 한도 면제는 구현 완료나 검증 완료로 표시하지 않는다. 현재 영수증 검사는 EVM 형식 범위이며 다른 체인 전체의 결제 검증기가 아니다. 토큰 잔액·nonce·최종성 검증은 별도의 승인된 실제 연동 단계가 필요하다.

서버·워커·운영 DB를 재시작하거나 배포하지 않았다. 운영 반영에는 사용자 터미널의 배포 절차로 frontend/admin/execution에 해당 변경을 포함한 검증 릴리스를 반영해야 한다. 현재 진행 중인 다른 수정과 함께 패키징할 경우 해당 변경분도 배포 검토에 포함해야 한다. 이 보고서의 검증을 운영 반영 확인으로 해석하지 않는다.

## 배포 준비 요청 후 최종 패키지 검증

운영 frontend/admin의 비공개 준비 상태가 정상임을 확인했다. 결제 소스는 이전 검증 이후 그대로였으며, 별도 브라우저 테스트 9개 파일의 변경만 확인됐다. 현재 운영 `registration-hardening-20261027-r1`을 기준으로 결제 개선만 반영한 불변 릴리스를 만들었다. 미배포 워크스페이스·로그인 변경은 포함하지 않았으며 운영 HTML·발행 자산은 모두 보존했다.

첫 패키지의 전체 검사에서 Redis 사용 시 정확한 잔여량이 없는 분기를 발견했다. 허용 결과의 잔여량은 추측하지 않고, 차단 결과에만 확실한 잔여량 0을 제공하도록 보완했다. 공유 security.py의 기존 상태를 먼저 대조하고 이 분기만 수정했다. 로컬·Redis 허용·Redis 차단 회귀와 한 번의 카운터 판정만 사용하는지 추가 검사했다. 초기 r1은 사용하지 않는다. 상세 경위는 배포 문서를 참조한다.

최종 **`payment-hardening-20261027-r2`**:

- 실제 패키지의 검증 복사본에서 **548 passed / 실패 0 / skip 0**, Chromium 26건·일회용 PostgreSQL 리허설 포함. `package-integration.xml`, `package-integration.log`.
- 공개 콘텐츠 309개 파일 위반 0, 발행 JavaScript 구문 통과, SQL 카탈로그 재생성 일치. SQL 3,806개·스키마 232개는 기준 릴리스와 동일하다.
- 런타임 lock·Python·OpenSSL·libpq·CA 번들 검증 통과. 테스트 의존성 경로가 운영 검사에 섞이지 않도록 분리했다. lock과 운영 가상환경을 수정하거나 검사를 우회하지 않았다.
- manifest의 **1,311개 파일**과 검증 복사본 해시 모두 일치. 기준 릴리스 대비 결제 관련 9개 파일만 변경됐으며 신규 파일은 없다. SQL 카탈로그 소스 증빙 갱신 포함이다. 새로 보완한 security.py 정적 검사는 기존 3건·신규 0·파싱 오류 0이다.
- 운영 서비스 상태 파일 변경 0, 실제 이체 0, 배포 실행 0. 최종 준비 판정 `ready_to_deploy: true`: `package-validation.json`, `deployment-package.json`.

사용자 터미널에서 **frontend → admin → execution** 순서로 해당 r2를 반영한다. **jobs·DB 재시작과 마이그레이션은 필요 없다.** 이미 생성한 릴리스를 다시 package/restart하지 않는다. 실제 운영 반영 확인은 사용자가 명령을 실행한 이후의 별도 단계다.

## 사용자 실행 후 운영 확인 — 2026-10-27 12:03 KST

사용자의 실행 완료 통보 후 확인한 결과, frontend/admin의 활성 A 슬롯과 execution 워커가 모두 **`payment-hardening-20261027-r2`**였다. 서명된 비공개 준비 상태, 실행 워커의 launch 설정·실제 프로세스·최근 heartbeat를 대조했다. jobs는 계획대로 기존 `registration-hardening-20261027-r1`을 유지하며 heartbeat가 정상이었다. 릴리스 manifest 1,311개 파일 검증도 통과했다.

**운영 점검 36건 통과·실패 0**: `rollout-verification.json`, `rollout-verification.log`, 재실행 가능한 `verify_rollout.py`.

- 로컬·공개 도메인의 홈 HTML/CSP, 운영 JavaScript 해시, 공개 OpenAPI 및 비공개 경로/정의 제외를 확인했다.
- 공개 진입점의 `/admin/ui`, `/internal/service/ready`는 404였다. 관리자 진입점 UI는 200, 개별 세션 없는 규격 검사 API는 401이었다.
- 테스트 예제 4개 조회와 연결된 MCP의 로컬 `ping`이 정상이고 게이트웨이 한도 정책 헤더가 있었다. ping은 외부 제공자 도구를 실행하지 않는다.
- 명시적 x402 카탈로그 조회가 200이며, 결제 증명이 아닌 검사 표식을 보낸 로컬 게이트웨이는 **501 `PAYMENT_EXECUTION_DISABLED`**, `payment_processed: false`, `probe-only`, `no-store`로 거절했다. 실제 결제와 외부 제공자 호출은 0이다.
- 운영 서비스 상태 파일은 점검 전후 동일했다. 서버·워커·DB 교체나 고객 데이터 변경을 수행하지 않았다.

첫 검사 도구는 HTML Accept 없이 홈에 접속해 정상적인 머신용 JSON 200을 HTML 오류로 분류했다. 브라우저용 `Accept: text/html`을 명시해 검사 도구를 수정했고 로컬·공개 홈 모두 정상 HTML 200을 확인했다. 제품 코드는 바꾸지 않았으며 첫 결과는 `rollout-content-negotiation-initial.json`에 보존했다.

현재 확인 범위의 운영 반영은 정상이다. 인증된 관리자 변경 작업, 실제 토큰 이체·체인 정산·환불·실제 에이전트 도구 실행을 운영에서 재시험한 것은 아니다. 해당 기능의 격리 회귀 548건과 운영의 읽기·무정산 smoke 확인을 구분한다.
