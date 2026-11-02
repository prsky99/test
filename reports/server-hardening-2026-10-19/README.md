# 서버 설정 보완 결과 — 2026-10-19

현재 macOS + Cloudflare Tunnel용 설정을 저장하고 사전 검사를 완료했다. **운영 서버는 재시작하지 않았으며 기존 PID 84113과 리스너가 유지됐다.** 새 환경변수와 loopback 바인딩은 사용자가 다음 정상 재시작을 수행할 때 적용된다. 현재 8400은 여전히 모든 IPv4 인터페이스에서 수신한다.

## 저장 및 수정

- `gateway-data/agentcon.env`: 권한 600, Git 제외. production 모드, proxy TLS 종료, 관리자·프론트엔드 loopback 바인딩, 명시적 loopback 신뢰, 기존 DB 유지, private 목적지 차단을 지정했다. 누락된 운영 관리 API 토큰을 비공개로 생성했다. 기존 관리자 비밀번호는 이미 기본값이 아니므로 변경하지 않았다. 토큰은 보고서에 포함하지 않는다.
- `agentcon`: private literal 설정 파일 로드, 기존 환경 우선, 빈 `AGENTCON_ENV_FILE=`로 명시적 비활성화, loopback 기본값, 읽기 전용 `check`, restart 전 사전 검사. 설정 파일을 shell 코드로 실행하지 않는다. 상대 경로는 호출 시점의 절대 경로로 고정한다.
- `scripts/agentcon_config.py`: 파일 소유자·regular file·0400/0600·symlink·행 문법·키·중복·크기·제어문자 검사. `--check`는 값과 경로를 숨긴 결과만 출력하며, 순수 config와 최소 읽기 전용 SQLite facade로 운영 조건을 검사한다. 앱 Store나 서버·스케줄러를 생성하지 않는다.
- Compose: Caddy에는 도메인과 신뢰 upstream만 전달하고 앱 관리자 자격 증명을 전달하지 않는다. `.dockerignore`는 빌드에 필요한 audit 스크립트만 예외로 포함하며 private 환경 파일·로그·보고서를 제외한다. Compose의 환경 파일 치환을 실행 안내와 `setup.sh`에 명시했다. setup 스크립트는 실행하지 않았다.
- [Caddy 단계별 안내](<저장소>/deploy/CADDY_SETUP.ko.md), [현재 native 서버 적용 안내](<저장소>/deploy/NATIVE_RUNTIME.ko.md)를 작성했다.

## 실제 검증

기존 운영 DB를 대상으로 `./agentcon check`가 성공했다. `production_guards_checked`, `proxy_tls`, `private_destinations_disabled`가 모두 true다. 실제 설정 값과 비밀값은 출력하지 않았다.

- 고립된 프록시·운영 보안 API·Chromium 브라우저 회귀: **139 통과**.
- private 설정 파서·읽기 전용 DB·비밀값 미출력 회귀: **41 통과**.
- 운영 자격 증명을 상속하지 않는 임시 DB·임시 포트의 production 서버 시작/재시작/종료 및 실제 health/robots 응답: **1 통과**.
- 위 총 **181개**는 실패·오류·skip 없이 통과했다. 마지막 상대 경로 변경 후 CLI profile 4개를 추가 재확인했으며, 중복 실행을 총계에 더하지 않는다.
- 새 설정 검사 Python 파일의 Bandit: 발견 0, 검사 오류 0. shell 구문 검사도 통과했다. 전체 저장소 보안 무결성을 의미하지 않는다.
- public frontend content 검사: 81개 파일, 위반 0.
- 실제 Caddy 2.11.7 바이너리로 저장소 Caddyfile 문법 검증 성공. 리스너를 열거나 설정을 reload하지 않았다.
- 임시 예시 환경으로 Compose 문법 및 최종 모델을 확인했다. Caddy 관리자 토큰 미전달, gateway production/proxy TLS, loopback만 관리 포트 publish, 8400 미공개를 확인했다.

머신 판독 결과: [verification.json](<저장소>/reports/server-hardening-2026-10-19/verification.json). pytest XML/log 및 Bandit/Caddy 기록도 같은 디렉터리에 있다.

## 사용자 적용 순서

현재 Tunnel 구성을 유지한다면 저장소 루트에서 다음을 실행한다.

```sh
./agentcon check
./agentcon restart
```

이후 실제 8200/8400 loopback 바인딩, 공개 Home 200과 관리자 404를 확인한다. Cloudflare의 HTTP→HTTPS 강제 전환은 별도의 edge 설정이며 앱 재시작으로 자동 활성화되지 않는다. Caddy 가이드 A 절차에 따라 설정·확인한다.

저장소 Compose+Caddy 전환은 가이드 B의 별도 배포 절차다. 기존 DB 디렉터리와 Docker named volume이 자동으로 이어지지 않으므로 현재 운영 서버에서 즉시 `docker compose up`를 실행하지 않는다.

## 남은 검증 범위

Docker/Compose CLI는 있지만 Docker 데몬은 중지 상태였다. 이미지를 실제 빌드하거나 컨테이너·ACME·DNS 전환·원본 방화벽 검증을 수행하지 않았다. 새 설정을 적용한 운영 서버의 재시작 후 공개 검증도 남아 있다. 단위·브라우저 회귀는 실서비스의 사용자별 주소 귀속, 외부 원본 우회 접근 또는 장시간 연결의 성공을 대신 증명하지 않는다.

Cloudflare/DNS/Tunnel 자격 증명과 원격 설정, 관리자 계정 비밀번호, 기존 DB 업무 데이터는 변경하지 않았다. 운영 기록의 과거 누락은 이번 설정으로 소급 복구되지 않는다. 현재 릴리스의 별도 readiness 문제나 다른 환경 오류가 없다는 보장도 아니며, 사전 검사 성공 뒤 실제 HTTP 확인이 필요하다.

