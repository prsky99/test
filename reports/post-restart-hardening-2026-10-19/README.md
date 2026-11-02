# 운영 설정 재시작 후 확인 — 2026-10-19

사용자가 재시작한 뒤 13:02 KST에 실제 실행 프로세스와 공개 연결을 읽기 전용으로 확인했다. 설정 파일 검사에 더해 새 PID 3327의 환경과 리스너를 직접 확인했다.

## 반영 확인

- 새 프로세스 환경: `DEPLOYMENT_MODE=production`, `PUBLIC_TLS_TERMINATION=proxy`.
- 실제 8200·8400 리스너: 모두 `127.0.0.1`. 이전 프론트엔드의 모든 인터페이스 바인딩이 loopback으로 제한됐다.
- 명시적 신뢰 프록시: `127.0.0.1,::1`. 내부 프론트엔드는 HTTP이며 SSL 자체 종료는 꺼져 있다.
- private 목적지 차단 및 관리 API 토큰이 반영됐다. 토큰은 길이 조건 및 비공개 파일과의 일치 여부만 검사했으며 값을 출력하거나 저장하지 않았다.
- 비공개 프로필의 모든 필드가 실행 프로세스 환경과 일치했다.
- 실행 프로세스의 실제 환경과 기존 DB의 읽기 전용 facade로 production guard를 다시 실행해 통과했다. 앱 Store 초기화나 DB 업무 데이터 변경은 수행하지 않았다.

[실행 환경 검증](<저장소>/reports/post-restart-hardening-2026-10-19/runtime-verification.json).

## 재시작 후 연결

리다이렉트를 따라가지 않는 GET 5건으로 확인했다.

- 로컬 Home: **200**.
- 공개 HTTP `/api/overview?proxy_check=restart20261019`: **308**, 동일한 경로·쿼리를 유지한 HTTPS Location.
- 공개 HTTPS Home: **200**, 인증서 검증 성공. CSP·HSTS·nosniff·frame 차단·no-store 유지.
- 공개 `/admin/ui`: **404**.
- 로컬 관리자 API 무인증 요청: **403**.

[공개·로컬 응답](<저장소>/reports/post-restart-hardening-2026-10-19/public-checks.json).

현재 Mac 터미널 + Cloudflare Tunnel 구성이 유지된다. 이번 확인에서 서버·Tunnel·Cloudflare 규칙·DNS를 변경하거나 재시작하지 않았다. 검증 결과는 해당 시점과 경로에 한정하며 장시간 가용성, 외부 원본 접근, 실제 사용자별 주소 귀속, 과거 운영 기록 누락의 복구까지 증명하지 않는다.

재시작 직후 13:01:18–13:01:56 KST의 38초 로그 13건은 모두 INFO였으며, 새 WARNING/ERROR·운영 기록 경고·자동 차단·개발용 자체 인증서 스케줄러 시작 표시는 없었다. 이 짧은 구간에는 HTTP 접근 기록도 없어 업무 실행 성공이나 과거 누락 복구의 근거로 해석하지 않는다. 이후 13:02의 공개 GET 결과와 구분한다. [로그 확인](log-check.md)에 시각 범위를 기록했다.

