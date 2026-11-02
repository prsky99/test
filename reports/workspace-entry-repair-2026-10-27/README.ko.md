# Workspace 로그인·접근 통제 개선 — 2026-10-27

수정과 격리 검증을 완료하고 **사용자 승인 후 Frontend A/B 교체와 운영 확인까지 완료했다.** Admin·Jobs·Execution·Cloudflare Worker·DB 구조·Secret은 이 작업에서 변경하지 않았다. 실제 고객 로그인·폼 제출·Provider 호출도 수행하지 않았다.

## 핵심 개선

1. **인증과 권한 오류 구분:** 같은 출처의 고객 요청에서 로그인 정보가 없거나 유효하지 않으면 401을 반환한다. 유효한 세션의 CSRF 실패, 권한 부족, 다른 출처의 요청은 403으로 구분한다. 기존 Workspace별 권한 검사를 유지한다.
2. **인증 우선 검사:** 공개 서버의 고객 Router에 인증 관문을 추가했다. 로그인 없이 잘못된 경로 인자·쿼리·본문을 보내도 업무 검증과 실행에 앞서 차단한다. 앞단의 본문 크기·압축·요청량·출처 방어는 유지한다. 공개 OAuth 시작·가용성·콜백·Provider 클라이언트 메타데이터는 각자의 기존 계약을 따른다. 다운로드 웹앱의 목적 제한 토큰 계약도 유지한다.
3. **첫 방문 안내:** 첫 방문은 일반 로그인 안내로 연결한다. 페이지가 유효한 세션을 확인한 뒤 401을 받은 경우에만 세션 만료를 안내한다. 로그인 화면은 상태 확인 API의 `200 / authenticated:false` 응답을 사용하므로 정상적인 첫 방문에서 예상된 401 요청이 사라진다. 실제 인증 실패의 401 응답은 유지한다.
4. **로그인 후 원래 화면 복귀:** Workspace 선택 쿼리와 알려진 화면 구역을 보존한다. 복귀 주소는 `/customer/`의 지정된 화면만 허용하고 외부 주소·중복 쿼리·인코딩 우회·임의 API 경로를 차단한다. 검증된 목적지는 기존 OAuth의 암호화된 일회성 상태에 연결한다. 로그인 성공 및 취소 후 재시도에서 유지하며, 새 Secret이나 테이블을 추가하지 않는다. 브라우저가 리디렉션에 계승한 fragment도 처리한다.
5. **OAuth 이후 깊은 링크:** Workflow·개별 작업·Provider 연결의 읽기 전용 문서는 OAuth 이동 직후의 top-level navigation을 허용한다. API 읽기와 모든 변경 요청은 기존 같은 출처·CSRF 검사를 계속 적용한다.
6. **지원 화면:** 현재 소스에는 이미 로그인 확인 전 폼을 숨기는 처리가 있다. 추가한 진입 관문으로 비로그인 고객은 폼을 받기 전에 로그인으로 이동한다. 세션 만료 시에는 지원 내용이 없는 로그인 문서로 전환하고 복귀 목적지를 `/customer/support`로 보존한다. 로그인 후 문의 작성·초안 공유·공유 철회를 합성 계정으로 검증했다.
7. **OpenAPI 노출:** 현재 공개 서버는 이미 명시적으로 허용한 공개 API만 스키마에 게시한다. 실제 구성된 고객 Router를 대상으로 고객·Workspace 앱 경로가 공개 스키마에서 제외되는 것을 검사했다. 경로 은닉과 별도로 인증·권한 검사도 검증했다.
8. **오류 추적:** 처리하지 못한 내부 예외에는 `X-Request-ID` 참조 번호를 반환한다. 서버에는 참조 번호·HTTP method·고정 Route 패턴·예외 종류만 기록한다. 입력·쿠키·개인정보·예외 문자열을 로그에 추가하지 않으며, 변경 요청을 자동 재실행하지 않는다.

## 연결 끊김에 대한 확인 범위

제공된 요약의 원본 `reports/워크스페이스 기능 테스트.md`와 요청 시각·참조 번호는 이 작업 폴더에 없다. 로컬 Frontend 로그에서는 고객 요청의 5xx 기록이나 `ClientDisconnect`, `ConnectionResetError`, `BrokenPipeError`, `EndOfStream` 표식을 찾지 못했다. 과거 `ApplicationStoreError` 기록은 있으나 보고된 세 번의 연결 끊김과 연결할 근거는 부족하다. 원인 확정에는 해당 시각의 요청·프록시 로그가 필요하다.

최신 운영 버전의 DB 재연결 및 등록 보안 변경을 배포 후보에 보존했고, 이번에는 오류 추적과 안전한 오류 응답을 추가했다. **세 번의 연결 끊김 원인이 해결됐다는 판정은 보류한다.** 근거: `local-log-review.json`.

## 검증 결과

- 실제 배포본의 관련 검사 **181개 통과·실패 0개**: `rebased-candidate-tests.log`. 최신 결제 보안 운영본에 승인된 Workspace 수정만 옮긴 뒤 전체 관련 항목을 다시 검사했다. 이전 후보의 `candidate-tests.log`와 `candidate-support-final.log`는 이력으로 보존하며 중복 합산하지 않았다.
- 현재 등록된 고객 전용 API **90개 method/path 조합: GET 41개·POST 49개**를 격리 환경에서 순회했다. 모두 401이며 이 순회에서 DB 변경이 없었다. 로그인 전 고객 화면 6종의 복귀 주소도 확인했다. `anonymous-route-matrix.json`.
- OAuth Google/GitHub 모의 로그인, 일회성 상태 재사용 거부, 안전한 복귀, 취소, 새로고침, 정상 첫 방문, 만료, 같은 출처 제한, CSRF, Workspace 권한, Provider 연결, 기존 웹앱 계약을 확인했다. 실제 OAuth 승인이나 외부 Provider 실행을 대체하는 운영 실증으로 해석하지 않는다.
- 추가 호환성 검사: `compatibility-security.log`에 145개 통과·기존 문구 기대값 실패 2개를 보존했다. `Organization` → `Workspace`, AI 사용 불가 안내 문구를 현재 화면에 맞췄고 해당 두 여정은 최종 후보 검사에서 통과했다. 지원 만료 후 문서를 바꾸는 새 동작도 별도로 검증했다.
- 공개 콘텐츠: 작업 폴더 309개, 배포 후보의 게시 파일 308개에서 정책 위반 0개. 양쪽 릴리스에 배포되지 않는 `AGENT_FRONT.md`는 작업 폴더에서 검사했다. 새 navigation 모듈의 영문 소스·Python 컴파일 및 JS 구문도 확인했다.
- Secure coding: Ruff S 검사에서 기존 2건·현재 2건·신규 0건. 기존 S105는 공식 OAuth token endpoint URL을 비밀번호로 간주한 탐지다. 격리 브라우저/API 보안 회귀도 포함했다.
- 이전 검증 로그는 실패 원인과 재검사 근거를 보존한다. 초기 Chromium sandbox 실행 제한은 허용된 오프라인 브라우저 검증으로 해소했다.

전달받은 과거 138개 호출 목록과 현재 소스의 Route 구성은 범위가 다르다. 이 결과는 **현재 고객 API 90개와 명시한 합성 사용자·웹앱 테스트 범위**를 의미한다. 운영 고객 계정의 실제 로그인·수금·외부 실행은 별도 운영 검증 영역이다.

## 운영 반영 완료

- 운영 Frontend: `workspace-entry-20261027-r3`, 활성 슬롯 `b`, PID `13740`.
- 기반: `payment-hardening-20261027-r2`.
- 승인 시점의 `workspace-entry-20261027-r2`는 이전 등록 보안 운영본을 기반으로 준비됐다. 배포 전 결제 보안 버전 갱신을 발견해 대조한 결과, 최신 변경 9개와 Workspace 수정 9개 사이의 겹침은 0개였다. 최신 운영본에 승인된 9개 파일을 그대로 옮겨 r3를 준비하고 재검증했다. `deployment-rebase.json`, `staged-release-approved-r2.json`에 근거를 보존했다.
- 변경: `customer_navigation.py`, `customer_identity.py`, `customer_identity_service.py`, `customer_identity_view.py`, `workspace_platform.py`, `workspace_service.py`, `customer_authoring_service.py`, `customer_provider_connections_service.py`, `workspace-interactions.js` — 런타임 파일 9개.
- 나머지 **1,303개 파일**과 최신 `front.py`·동기화된 embedded HTML·등록 보안·DB 재연결·결제 보안 코드를 보존했다. 배포 전후 manifest를 검증했다.
- Frontend만 A/B 교체했다. Admin·Jobs·Execution의 PID·버전과 프록시 PID가 배포 직전과 동일한 것을 확인했다. 이전 Frontend는 A/B 복구를 위해 유지했다. Cloudflare Worker·DB 구조·Secret 변경 작업은 수행하지 않았다.
- 운영 HTTP 점검 **25개 통과·실패 0개**: 공개 Home, 익명 상태 200, 로그인 옵션, 고객 API 401, 입력 검사 전 인증, 고객 문서 303 및 복귀 주소, 외부 복귀 주소 차단, 공개 OpenAPI의 비공개 경로 제외, readiness와 다른 서비스 상태 유지. `live-after.json`.
- 실제 운영 Chromium 점검 **9개 통과·실패 0개**: 첫 방문 로그인 안내, Workflow 깊은 링크 및 fragment 보존, 지원 화면 복귀, 비로그인 지원 폼 제외, 모바일 가로 넘침 방지, 정상 첫 방문의 불필요한 API 401 제거, JavaScript 오류 없음. `live-browser-after.json`.
- 운영 확인에서는 같은 호스트 GET/HEAD만 전달했다. 실제 고객 OAuth 로그인·폼 제출·Provider 실행은 제외했으며, 관련 인증·실행 동작은 앞서 명시한 격리 테스트 범위로 검증했다.

실행 완료한 명령(다시 실행할 필요 없음):

```sh
agentcon deploy frontend workspace-entry-20261027-r3
```

기록: `staged-release.json`, `deployment-rebase.json`, `deploy-frontend.log`, `services-before-deploy.json`, `verify-deployment.py`, `live-browser-after.py`, `checkpoint.md`.

## 기준 자료

인증 누락과 권한 거절은 [RFC 9110의 401·403 정의](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.2)를 기준으로 구분했다. 로그인 복귀 주소는 [OWASP의 Redirect 허용 목록 원칙](https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html)에 따라 제한하고, OAuth의 일회성 암호화 상태에 연결했다.
