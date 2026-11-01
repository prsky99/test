# 현재 macOS + Cloudflare Tunnel 서버 설정

2026-10-19 사용자 재시작 후 새 프로세스에서 production/proxy TLS 및 실제 8200·8400 loopback 바인딩을 확인했다. 공개 HTTPS 200, HTTP→HTTPS 308, 공개 관리자 404도 유지된다. [재시작 후 검증 결과](../reports/post-restart-hardening-2026-10-19/README.md).

현재 경로는 방문자 → Cloudflare → cloudflared → 로컬 HTTP frontend다. 이 문서의 설정은 native `agentcon`용이며, Docker/Compose에는 [별도 Caddy 가이드](CADDY_SETUP.ko.md)의 값을 사용한다.

## 저장된 설정

2026-10-19에 `gateway-data/agentcon.env`를 생성했다. 파일 권한은 600이며 Git에서 제외된다. 기존 운영 DB를 유지하며 관리자 계정 비밀번호는 변경하지 않는다. 새 관리 API 토큰은 파일 안에서만 보관하며 화면·로그·이 문서에 표시하지 않는다.

다음 항목을 저장했으며, 위 재시작 후 실제 실행 프로세스에 반영된 것을 확인했다.

```dotenv
DEPLOYMENT_MODE=production
PUBLIC_TLS_TERMINATION=proxy
HOST=127.0.0.1
AGENT_FRONT_HOST=127.0.0.1
AGENT_FRONT_URL=https://agentconcierge.biz
PORT=8200
AGENT_FRONT_PORT=8400
GATEWAY_DB=gateway-data/collector.sqlite3
FORWARDED_ALLOW_IPS=127.0.0.1,::1
SSL_ENABLED=0
ALLOW_PRIVATE_AGENT_URLS=0
```

이 예시는 비밀값을 생략한 일부 항목이다. 파일 전체를 위 내용으로 덮어쓰면 관리 토큰이 사라진다. 필요한 편집은 로컬 편집기에서 하고 비공개 파일 원문을 공유하지 않는다.

## 1. 시작 전 읽기 전용 확인

저장소 루트에서 실행한다.

```sh
./agentcon check
```

이 명령은 서버나 스케줄러를 시작하지 않는다. 기존 SQLite DB는 읽기 전용으로 열어 기본 관리자 비밀번호 사용 여부 등 운영 조건을 검사한다. DB를 생성하거나 앱의 Store 초기화를 실행하지 않는다. 공개 HTTPS 주소, 관리 토큰 길이, 목적지 정책, TLS 종료 방식, 프록시 신뢰 목록과 포트 등도 확인한다. 결과에는 비밀값을 출력하지 않는다.

환경변수의 우선순위는 **사용자가 이미 설정한 환경변수 → 비공개 파일 → 런처 기본값**이다. 따라서 shell에 예전 설정이 남아 있다면 파일보다 우선한다. 의도하지 않은 override는 확인 후 해당 shell 변수만 제거한다. 비공개 파일을 `source`하거나 `eval`로 실행하지 않는다.

파일은 unquoted literal `KEY=value` 형식이며 빈 줄과 `#` 주석을 지원한다. 따옴표·변수 확장·명령 실행 기능은 지원하지 않는다. 허용한 서버 설정 키만 사용하며, 중복 키·잘못된 행·다른 사용자 소유·과도한 파일 권한·symlink는 거부한다.

`AGENTCON_ENV_FILE`을 다른 경로로 명시할 수도 있다. 고립된 개발·테스트에서 기본 비공개 파일을 완전히 건너뛰려면 `AGENTCON_ENV_FILE=`을 사용한다. 해당 파일은 현재 기존 DB를 대상으로 준비했으며, 새 DB를 선택하면 별도의 초기 관리자 비밀번호 조건도 충족해야 한다.

## 2. 운영자가 정상 재시작

환경변수와 바인딩은 실행 중인 프로세스에 소급 적용되지 않는다. `check`가 성공하면 운영자가 평소 재시작 명령을 실행한다.

```sh
./agentcon restart
```

`restart`는 기존 서버를 중지하기 전에 사전 검사를 실행한다. 제안 설정이 잘못됐다면 현재 서버를 계속 실행한 채 실패한다. 사전 검사 성공이 새 앱의 완전한 readiness나 공개 연결 성공을 보장하는 것은 아니므로 아래 확인을 이어서 수행한다.

설정 작업 중 실행 중인 서버를 재시작하지 않았다. 로컬 Tunnel의 원본 `http://localhost:8400`은 포트를 유지하므로 변경할 필요가 없다. loopback 신뢰는 같은 호스트에서 오는 접속 전체를 신뢰하는 경계다.

## 3. 적용 후 바인딩과 공개 경로 확인

```sh
lsof -nP -iTCP:8200 -iTCP:8400 -sTCP:LISTEN
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' http://127.0.0.1:8400/
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://agentconcierge.biz/
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://agentconcierge.biz/admin/ui
```

8200과 8400이 loopback으로 수신하는지 확인한다. 로컬·공개 Home은 200, 공개 관리자 화면은 404를 기대한다. `agentcon status`의 주소는 해당 호출에서 읽은 설정이므로 실제 소켓 확인을 대신하지 않는다. 공개 인증서/보안 헤더는 다음 명령으로 추가 확인한다.

```sh
.venv/bin/python -m scripts.check_front_deployment --url https://agentconcierge.biz/
```

HTTP→HTTPS 강제 전환은 Cloudflare의 별도 설정이다. 2026-10-19 브라우저에서 서비스 호스트 전용 308 규칙을 배포하고 공개 GET으로 확인했다. [Cloudflare 실제 설정 안내](CLOUDFLARE_NATIVE_SETUP.ko.md)에서 기존 규칙과 메뉴를 확인한다. 앱의 운영 모드가 이를 자동 활성화하는 것은 아니며, 같은 목적의 규칙이나 zone 전체 스위치를 중복으로 추가할 필요가 없다.

## 변경 범위와 복구

계정 비밀번호, 현재 DB 업무 데이터, 터널 자격 증명, DNS, 실행 중인 서버는 이번 설정 저장으로 변경하지 않는다. 새 운영 모드는 로그의 과거 누락을 소급 복구하지 않는다.

사전 검사에 실패하면 기존 서버는 그대로 유지되므로 로컬에서 해당 조건을 수정한 뒤 `check`를 다시 실행한다. 잘못된 파일 때문에 `check/start/restart`가 거부되어도 `stop/logs/help`는 파일을 읽지 않아 사용할 수 있다. 운영 보안 조건을 해제하거나 원본 포트를 전체 공개하여 우회하지 않는다. 재시작 후 예상과 다르면 기존 비공개 설정과 DB를 보존한 채 바인딩·Tunnel·앱 응답을 각각 확인한다.

