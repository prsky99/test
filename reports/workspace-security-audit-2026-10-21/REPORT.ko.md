# 워크스페이스 시큐어코딩 및 동적 보안 점검

검증일: 2026-10-21 KST. 실제 Google 계정의 소유자 워크스페이스와 격리된 합성 계정·데이터를 구분하여 점검했다.

## 결과

- 보안·기능 회귀 419개, 25개 모듈 통과. 최종 JUnit의 실패·오류는 0개다. 세션 만료 관련 추가 표적 회귀도 통과했다.
- 운영 서비스에 인증 정보를 보내지 않은 경계 요청 10개가 모두 예상대로 응답했다. 비인증 조회 401, 외부 Origin/Sec-Fetch-Site 및 CSRF 없는 변경 요청 403. 어떤 조직도 생성되지 않았다.
- Python 관련 소스 21개, 5,756줄을 Bandit으로 검사했다. 경고 6개를 모두 검토했다. HTML/JavaScript 문자열의 SQL 오인 3개, 공급자 URL·공개 Bearer 유형 문자열의 자격 증명 오인 3개였으며 실제 취약한 SQL 실행이나 하드코딩 비밀은 확인하지 않았다. 경고는 억제하지 않았다.
- JavaScript 문법 검사 통과. 공개 콘텐츠 237개 파일에서 정책 위반 0개.
- 설치 패키지 77개 중 알려진 취약 의존성 1건을 발견하여 수정했다. 수정 후 재조회 결과 77개, 알려진 취약점 0건, 조회 제외 0개. `pip check`도 통과했다.

## WS-SEC-01: 인증서 신뢰 저장소 갱신

프로젝트 `.venv`의 certifi 2026.7.22에서 GHSA-6q48-6c7w-9gw2 / PYSEC-2026-4320이 검출됐다. 공식 보안 권고는 손상된 CA 중간 인증서 키와 관련한 중간자 공격 위험을 Critical로 분류한다. 프로젝트에서 실제 도청이나 계정 침해가 일어났다는 증거는 확인하지 않았다.

certifi만 2026.10.19로 갱신했고 `requirements.txt`에 `certifi>=2026.10.19`를 추가했다. 갱신한 120개 루트 중 문제가 된 `emSign ECC Root CA - G3`가 없음을 확인했다. TLS 검증은 활성 상태이며, 새 Python 클라이언트로 Google OIDC 공개 설정과 GitHub 공개 API에 검증된 HTTPS 연결이 성공했다. 다른 패키지는 갱신하지 않았다.

사용자가 서버를 재시작했고 공개 포트의 프로세스가 PID 4763에서 PID 58322으로 교체된 것을 확인했다. 새 프로세스는 프로젝트 .venv 인터프리터를 사용한다. 재시작 후 운영 로그인 페이지 200, 비인증 고객 API 401 및 no-store, 새 세션 만료 안내와 화면 숨김 코드 반영을 확인했다. 이전 프로세스의 TLS 컨텍스트는 프로세스 교체로 종료됐다. 상세 확인 결과는 post-restart-checks.json과 rollout.json에 보존했다.

공식 출처: [Certifi 보안 권고](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2), [수정 패키지](https://pypi.org/project/certifi/2026.10.19/).

## WS-SEC-02: 세션 만료 후 사적 화면 잔존

어제의 기존 탭에서 현재 이력을 조회했을 때 서버는 401로 접근을 차단했지만, 워크플로우 이름·입력·결과가 계속 표시됐다. 이는 서버 인증 우회나 새로운 데이터 유출은 아니며, 공유 기기의 화면 노출 위험으로 분류했다.

공통 요청 처리에서 조직·워크플로우·단일 작업·플랜 페이지의 고객 API 401이 확인되면 기존 main을 즉시 숨기고 inert 처리하며 열린 dialog를 닫고 로그인 문서로 이동하도록 수정했다. 로그인 진입 페이지와 자체적으로 계정 상태를 지우는 workspaces 페이지는 중복 이동하지 않는다. 403 에이전트 실행 거부를 세션 만료로 오인하지 않으며, 주기적 새로고침도 추가하지 않았다.

격리 브라우저로 조직·단일 작업·다단계 결과·플랜 잔액의 비공개 화면 제거와 거부된 작업의 상태 불변을 확인했다. 운영 Chrome에서도 임시 탭에서 정식 로그아웃한 뒤 기존 워크플로우 탭의 이력 조회가 로그인 화면으로 전환되는 것을 확인했다. 임시 탭은 닫았다.

증적: 수정 전 `screenshots/02-expired-session-retained-data.png`, 격리 수정 후 `screenshots/session-expiry-fixed-isolated.png`, 운영 수정 후 `screenshots/12-session-revoked-fixed-live.png`.

## 실제 로그인 후 확인한 범위

Google 정식 로그인, 조직 개요, 멤버·초대, 플랜·크레딧, 워크플로우, 입력 검토, 실행 동의, 다운로드·릴리스 만료, 고급 A2A 화면을 확인했다. 새 워크플로우 저장·크레딧 사용·앱 실행 권한 발급·외부 에이전트 신규 실행은 하지 않았다. 입력 검토 한 건만 준비했으며 실행 동의는 체크하지 않았다. 화면에 남아 있는 succeeded 결과는 어제의 이력이고 이번 실행 결과로 집계하지 않았다. 잔액 99983과 저장 항목 32개를 확인했다.

공개 로그인 및 조직 페이지에서 no-store, nosniff, HSTS, nonce 기반 script CSP, frame-ancestors 차단을 확인했다. 거부 응답도 no-store였고 외부 CORS 허용 및 traceback은 보이지 않았다. 단순 헤더 검증을 인증 공격 전체 검증과 혼동하지 않았다.

## 격리 동적 검증 범위

실제 API 핸들러와 네트워크 차단 Chromium 및 합성 공급자 응답을 사용했다. Google/GitHub OAuth의 state·PKCE·nonce·발급자·서명·키 선택·재사용 차단, Secure/HttpOnly/SameSite 세션, CSRF·외부 출처, 테넌트 간 접근·역할 상승·철회, JSON 크기·형식·중복 필드, XSS 안전 렌더링, 검토 동의와 일회 실행·중복 방지·unknown 결과, 릴리스·앱 origin·토큰 scope·철회, A2A 통신과 비공개 결과 경계를 관련 회귀로 확인했다. 상세 테스트 이름과 결과는 `final-regressions.xml`에 있다.

## 남은 제한

실제 계정은 Google 소유자 한 개다. GitHub 실계정, 다른 실제 고객의 계정·역할은 사용하지 않았으며 해당 공격은 합성 데이터로 확인했다. 승인된 운영 A2A 연결이 없어 실제 A2A 외부 전송을 하지 않았다. 다운로드 앱의 신규 호스팅·권한 발급도 하지 않았다. 비밀번호 대입, 과부하·서비스 거부, 실제 회원·권한 삭제, 네트워크 침투, Cloudflare·OS·PostgreSQL 전체 구성 감사는 이번 범위가 아니다. 알려진 취약점 0건은 시스템에 취약점이 없다는 보장이 아니다.

## 증적 파일

`summary.json`, `live-boundaries.json`, `bandit-final.json`, `static-review.json`, `dependency-audit.json`, `dependency-audit-after.json`, `certificate-verification.json`, `tls-smoke.json`, `final-regressions.xml`, `expiry-credit-regressions.xml`, `screenshots/`.

## 재시작 후 실제 로그인 확인

새 서버에서 정식 로그아웃 후 Google로 다시 로그인하여 소유자 워크스페이스 접근을 확인했다. 인증서 갱신 후 서버의 새 OAuth 인증 통신도 정상 완료됐다. 증적: `screenshots/14-post-restart-google-login.png`. 신규 저장·크레딧 사용·외부 에이전트 실행은 하지 않았다.
