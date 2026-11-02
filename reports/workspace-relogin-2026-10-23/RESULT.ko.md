# 워크스페이스 세션 만료 후 재로그인 수정

## 원인과 수정

OAuth 제공자에서 돌아오는 브라우저의 리다이렉트 체인은 후속 `/customer/workspaces` 문서 요청에도 `Sec-Fetch-Site: cross-site`를 유지한다. 기존 `customer_actor`는 HTML 문서 진입과 API 호출에 동일한 same-origin 검사를 적용해 로그인에 성공한 세션까지 HTTP 403과 `Use the customer service origin.`으로 거부했다.

읽기 전용 HTML 진입점 `/customer/workspaces`, `/customer/organizations`에 한해서, GET + Fetch Mode navigate + Destination document + Origin 헤더 없음 조건을 충족하는 최상위 화면 이동을 허용했다. 세션 검증은 그대로 수행한다. 만료된 세션은 로그인 페이지로 이동하며, 로그인 후 유효한 세션은 정상 HTML을 받는다.

API 조회와 저장·실행·로그아웃에는 이 예외를 적용하지 않는다. 교차 출처 API 요청, iframe, cors 요청과 명시적인 다른 Origin 요청은 계속 거부한다. 로그인 상태나 CSRF 검사를 생략하지 않았다. OAuth state/PKCE/cookie 처리는 변경하지 않았다.

## 재현 및 검증

수정 전 회귀 재현에서 Google/GitHub 모두 만료된 워크스페이스 진입이 303 대신 403을 반환했다. 수정 후 전체 고객 인증 API 시험 52개가 통과했다.

최종 영향 범위 검사(인증·조직·워크플로우 작성·진입/로딩·브라우저·공통 보안) 125개가 모두 통과했다. 위 52개를 포함한 수치다. 공개 콘텐츠 검사도 245파일에서 위반 0개로 통과했다.

새 브라우저 시험은 운영 서버 대신 임시 루프백 HTTPS 포트의 실제 FastAPI/Uvicorn 서버와 Chromium을 사용한다. 외부 제공자 화면과 제공자 API만 합성 데이터로 대체했다. 콜백과 그 다음 303 리다이렉트는 실제 HTTPS로 처리하여 브라우저의 Fetch Metadata가 보존되도록 했다. 기존 오프라인 로그인 시험은 303을 테스트용 스크립트 이동으로 바꾸어 이 문제를 포착하지 못했다.

각 제공자에서 최초 로그인, Workflows 메뉴 진입, 테스트 세션 만료, 로그인 화면 이동, 재로그인, 정상 워크스페이스 표시를 확인했다. 두 번의 문서 진입 모두 실제 `cross-site / navigate / document` 헤더로 HTTP 200을 받았다.

- `google-relogin-fixed.png`, `github-relogin-fixed.png`: 수정된 재로그인 완료 화면.
- `google-redirect-metadata.json`, `github-redirect-metadata.json`: 쿼리·쿠키·토큰 없이 기록한 문서 요청 메타데이터.
- 변경: `agent_market/customer_identity_service.py`, `agent_market/customer_organization_service.py`.
- 회귀: `tests/test_customer_identity.py`, `tests/test_customer_relogin_redirect_browser.py`.

## 운영 반영

2026-10-23 사용자가 다음 명령으로 프론트엔드를 교체했다. 새 배포본은 `web-20261023-095902-4063`, 활성 슬롯은 A다.

```bash
./agentcon restart frontend
```

배포본 manifest 검증과 수정 파일 2개의 일치를 확인했다. 실제 공개 주소에서도 교차 사이트 최상위 문서 이동은 로그인 페이지로 정상 303 이동하고, 로그인 화면은 200으로 응답했다. API 교차 출처 요청과 iframe 접근은 계속 403, 미로그인 세션 API는 401이다. 홈페이지도 200이며 jobs/execution heartbeat가 정상이다. 공개 확인 7개가 모두 통과했다. `production-verification.json`에 증적을 보존했다.

운영 교체는 사용자가 실행했고 추가 재시작은 필요 없다. 실제 개인 계정으로 제공자에 로그인하지 않았으며, 제공자별 로그인·만료·재로그인 검증은 격리 테스트 계정으로 수행했다.
