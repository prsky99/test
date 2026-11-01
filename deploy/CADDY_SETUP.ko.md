# Caddy 설정과 배포 전환 가이드

**현재 사용 환경은 Mac 터미널에서 실행하는 native 서버다.** 2026-10-19 Cloudflare 브라우저에서 서비스 호스트 전용 HTTPS 전환 규칙을 배포하고 확인했다. 현재 필요한 메뉴와 적용 결과는 [Mac + Cloudflare 실제 설정 안내](CLOUDFLARE_NATIVE_SETUP.ko.md)를 따른다. 아래 Docker/Caddy 전환 절차는 향후 별도 배포를 위한 참고 자료다.

기준일: 2026-10-19. 이 문서는 운영자가 직접 실행할 절차를 설명한다. 문서를 작성하면서 서버·컨테이너를 실행하거나 재시작하지 않았고, DNS·Cloudflare 설정도 변경하지 않았다.

현재 서비스는 **방문자 → Cloudflare → Cloudflare Tunnel → macOS의 native HTTP frontend** 구조이며 Caddy를 사용하지 않는다. HTTP→HTTPS 전환은 위의 Mac + Cloudflare 안내에 기록한 호스트 전용 규칙으로 해결했다. 아래 A는 zone 전체 적용을 선택할 때의 대안이며 현재 추가로 수행할 단계가 아니다. 저장소의 Compose+Caddy를 사용하려면 B 경로를 별도 배포 전환으로 진행한다.

## A. 현재 macOS + Cloudflare Tunnel 유지

### 1. Cloudflare에서 HTTPS 전환 설정

1. Cloudflare에서 해당 도메인의 활성 edge 인증서와 HTTPS 접속을 확인한다.
2. **SSL/TLS → Edge Certificates → Always Use HTTPS**를 켠다. 이 옵션은 zone의 다른 호스트·하위 도메인에도 영향을 주므로, 해당 서비스 호스트만 대상으로 해야 한다면 호스트 조건을 가진 **Single Redirect Rule**을 사용한다.
3. 서비스의 공개 hostname과 현재 터널 origin 매핑을 그대로 유지한다. macOS에서 새 Caddy를 띄우거나 라우터 80/443을 열 필요가 없다.

HSTS 헤더가 있어도 최초 HTTP 방문이 서버에서 redirect된다는 뜻은 아니다. 앞선 검증에서는 HTTP GET이 200이고 `Location`이 없었다. Cloudflare는 origin의 무조건적인 redirect보다 edge에서의 전환을 권고한다. [Always Use HTTPS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/)

### 2. 설정 적용 후 GET으로 확인

다음은 운영자가 설정을 변경한 뒤 실행하는 읽기 전용 확인이다. HEAD는 앱에서 405일 수 있어 GET을 사용하고, `-L`을 넣지 않아 첫 응답을 확인한다.

```sh
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code} redirect=%{redirect_url}\n' http://agentconcierge.biz/
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://agentconcierge.biz/
```

HTTP는 HTTPS 주소를 가리키는 3xx, HTTPS는 정상 응답이어야 한다. 인증서 오류를 숨기는 `-k`는 사용하지 않는다. 이 절차는 Cloudflare 설정 변경이며 앱 재시작 없이 적용할 수 있다.

### 3. native 서버 설정은 별도로 관리

native 구성에서 앱이 신뢰할 대상은 같은 호스트의 터널 접속이다. Compose 전용 `CADDY_PROXY_IP`를 native 서버의 신뢰 주소로 복사하지 않는다. 운영 모드·TLS 종단·loopback 바인딩 등의 환경변수 변경은 실행 중인 프로세스에 소급 적용되지 않으므로, 준비한 설정은 운영자가 정상 재시작할 때 적용·검증한다. 기존 터널 origin이 사용하는 포트와 frontend 포트는 함께 유지해야 한다.

loopback 신뢰는 cloudflared의 프로세스 신원을 앱이 인증한다는 뜻이 아니라, 같은 호스트의 loopback 접속을 신뢰한다는 뜻이다. 실제 수신 XFF/XFP와 최종 client/scheme은 개인정보를 노출하지 않는 방식으로 별도 확인한다. 현재 구조의 검토와 한계는 [프록시 검토 기록](../reports/proxy-deployment-verification-2026-10-19/proxy-policy-review.md)을 참고한다.

## B. 저장소 Compose + Caddy로 전환

이 경로는 **공개 DNS → Caddy의 80/443 → Compose의 gateway** 구성을 기준으로 한다. 먼저 별도 Linux VM과 테스트 hostname에서 검증하는 편이 안전하다. 현재 macOS에서 그대로 실행하면 native 관리 포트 8200과 충돌한다. 같은 호스트에서 전환하려면 운영자가 기존 서버를 정상 종료하는 유지보수 시간이 필요하다.

### 1. 저장소 구성을 이해하고 DB를 구분

- `deploy/Caddyfile`은 `/admin`과 `/admin/*`에 404를 반환한다. 지정된 gateway API 경로는 `gateway:8200`, 나머지는 `gateway:8400`으로 전달한다. **`gateway`는 Compose 네트워크의 서비스 DNS 이름**이다. macOS에서 `caddy run --config deploy/Caddyfile`만 실행하면 native 서버에 연결되지 않는다.
- `deploy/docker-compose.yml`은 Caddy만 80/443에 공개하고, 관리 포트는 호스트 loopback의 8200으로만 publish한다. 8400은 호스트에 publish하지 않는다. 현재 파일은 TCP 443을 publish하며 UDP 443을 추가한 HTTP/3 배포 절차는 포함하지 않는다.
- `Dockerfile`의 DB 기본 경로는 컨테이너의 `/data/gateway.sqlite3`이다. Compose의 `gateway-data`는 **Docker named volume**이며 저장소의 `gateway-data/` 디렉터리와 별개다. 현재 운영 중인 `collector.sqlite3` 등의 이력이 자동으로 들어가지 않는다.
- 아래 예시는 project name을 `agentcon-caddy`로 고정한다. 보통 `agentcon-caddy_gateway-data`, `agentcon-caddy_caddy-data` 볼륨이 생성된다. 프로젝트 이름을 바꾸면 다른 새 DB로 보일 수 있으므로 같은 이름을 계속 사용한다. 같은 이름의 기존 볼륨이 있다면 fresh DB라고 가정하지 않는다. [Compose project name](https://docs.docker.com/compose/how-tos/project-name/)
- Caddy의 `/data`에는 인증서와 개인 키가 저장된다. 앱 DB와 Caddy 데이터 모두 영속 보관한다. **`docker compose down -v`, `docker volume prune`을 운영 복구 명령으로 사용하지 않는다.** [Caddy official image](https://hub.docker.com/_/caddy)

현재 데이터와 계정·작업 이력을 유지해야 한다면 fresh DB로의 공개 전환을 진행하지 말고 8단계의 데이터 이전 계획을 먼저 완료한다.

### 2. Docker와 서버 네트워크 준비

대상 서버의 Docker Engine과 Compose v2를 공식 절차로 설치한다. macOS 검증용은 Docker Desktop을 사용하지만, 그것만으로 인터넷에서 80/443에 접근할 수 있게 되는 것은 아니다. [Ubuntu 설치](https://docs.docker.com/engine/install/ubuntu/), [macOS 설치](https://docs.docker.com/desktop/setup/install/mac-install/)

```sh
docker version
docker compose version
```

기존 서버·리버스 프록시가 80/443/8200을 사용하는지 확인한다. Linux에서는 `ss -ltn`, macOS에서는 `lsof -nP -iTCP -sTCP:LISTEN`을 사용할 수 있다. 충돌하는 프로세스를 임의로 종료하지 않는다. `PROXY_SUBNET`이 기존 Docker/VPN/사설망과 충돌하지 않는지도 확인한다.

직접 Caddy를 공개하는 기본 경로에는 다음 조건이 필요하다.

1. 테스트 hostname의 A 레코드가 대상 서버의 공개 IPv4를 가리킨다. AAAA를 설정한다면 IPv6도 실제로 같은 Caddy에 도달해야 한다.
2. 서버·클라우드 방화벽 및 필요한 NAT에서 TCP 80/443이 Caddy로 도달한다. 8200/8400은 외부에 열지 않는다.
3. Caddy가 해당 포트를 바인딩할 수 있고 `/data`를 지속해서 쓸 수 있다.

이 조건에서 도메인이 지정된 Caddy는 인증서 발급·갱신과 HTTP→HTTPS redirect를 자동 처리한다. CGNAT 환경처럼 inbound가 불가능하면 현재 터널 경로를 유지한다. DNS challenge는 별도 DNS provider 모듈·자격 증명 설정이 필요하며, 저장소의 기본 `caddy:2` 이미지에 Cloudflare DNS 모듈이 포함되어 있다고 가정하지 않는다. [Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https), [Caddy 설치·모듈](https://caddyserver.com/docs/install)

### 3. Compose 전용 비공개 환경 파일 생성

저장소 루트에서 `deploy`로 이동한다. 아래 코드는 **기존 파일을 덮어쓰지 않고** 새 Compose 환경 파일을 만든다. 관리자 로그인 비밀번호를 두 번 입력하며 입력값과 생성된 API 관리 토큰을 출력하지 않는다. 비밀번호는 비밀번호 관리자에 보관한다. 이 파일을 native용 환경 파일 대신 사용하지 않는다.

```sh
cd deploy
umask 077
python3 - <<'PY'
from pathlib import Path
import getpass
import re
import secrets
import warnings

target = Path('gateway.env')
if target.exists():
    raise SystemExit('gateway.env exists; edit it privately instead of replacing it.')
warnings.simplefilter('error', getpass.GetPassWarning)
password = getpass.getpass('New bootstrap admin password (16+ characters): ')
confirmation = getpass.getpass('Confirm password: ')
if password != confirmation or not 16 <= len(password) <= 128:
    raise SystemExit('Passwords must match and contain 16 to 128 characters.')
if any(c in password for c in "'\\\r\n"):
    raise SystemExit('Use a password without single quotes, backslashes or line breaks.')
text = Path('gateway.env.example').read_text()
text = re.sub(r'(?m)^ADMIN_TOKEN=.*$', 'ADMIN_TOKEN=' + secrets.token_hex(32), text)
text = re.sub(r'(?m)^ADMIN_BOOTSTRAP_PASSWORD=.*$', lambda _: "ADMIN_BOOTSTRAP_PASSWORD='" + password + "'", text)
with target.open('x', encoding='utf-8') as handle:
    handle.write(text)
target.chmod(0o600)
print('Created gateway.env with private permissions; no secret values printed.')
PY
nano gateway.env
```

편집기에서 다음 항목을 확인한다. 테스트 hostname은 소유한 실제 도메인으로 바꾼다.

```dotenv
DOMAIN=stage.example.net
AGENT_FRONT_URL=https://stage.example.net
AGENT_FRONT=1
AGENT_FRONT_PORT=8400
AGENT_FRONT_HOST=0.0.0.0
GATEWAY_DB=/data/gateway.sqlite3
SSL_ENABLED=0
ALLOW_PRIVATE_AGENT_URLS=0
CONCIERGE_LLM=off
LOG_DIR=/data/logs
LOG_ARCHIVE_DIR=/data/logs/archives
CADDY_PROXY_IP=172.30.90.2
PROXY_SUBNET=172.30.90.0/24
CADDY_TRUSTED_UPSTREAMS="127.0.0.1/32 ::1/128"
```

이는 해당 키를 확인·추가할 값의 예시이지 파일 전체를 대체할 내용이 아니다. `ADMIN_TOKEN` 및 `ADMIN_BOOTSTRAP_PASSWORD`를 비우지 않는다. `CADDY_PROXY_IP`를 바꾼다면 같은 주소를 포함하는 `PROXY_SUBNET`과 함께 변경한다. gateway는 Caddy의 고정 주소만 신뢰한다. 외부 프록시가 없는 이 경로에서 `CADDY_TRUSTED_UPSTREAMS`에 Cloudflare 주소나 `private_ranges`, wildcard를 추가하지 않는다.

새 SQLite DB에서는 앱 시작 시 schema와 `sadmin` 계정이 생성되고, 로그인 비밀번호는 위에서 지정한 bootstrap 비밀번호다. `ADMIN_TOKEN`은 별도의 관리 API 자격 증명이며 로그인 비밀번호와 다르다. 기존 DB에서는 bootstrap 값이 기존 계정의 비밀번호를 덮어쓰지 않는다. production 모드는 기본 관리자 비밀번호가 남아 있거나 관리 토큰이 너무 짧으면 시작을 거부한다. 앱이 초기화 과정에서 schema를 생성·변경하므로, 기존 운영 DB를 단순 검증용으로 연결하지 않는다.

OAuth를 사용할 경우 staging과 운영의 callback URL·provider 등록을 각각 맞춘다. 비활성 provider의 자격 증명을 다른 배포에서 복사할 필요는 없다.

### 4. 환경 치환·이미지·Caddy 문법 검증

이후 모든 명령은 `deploy` 디렉터리에서 동일한 `--env-file`과 `-p`를 사용한다. Compose의 서비스 `env_file:`은 컨테이너 환경용이며 `${CADDY_PROXY_IP}` 등의 Compose 치환과 별개이므로 `--env-file gateway.env`를 생략하지 않는다. 동일한 이름의 shell 변수가 있으면 파일보다 우선하므로 의도하지 않은 shell override도 제거한다. `source gateway.env`로 shell 코드를 실행하지 않는다. [Docker 환경변수 치환](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

```sh
docker compose --env-file gateway.env -p agentcon-caddy config --quiet
docker compose --env-file gateway.env -p agentcon-caddy pull caddy
docker compose --env-file gateway.env -p agentcon-caddy build gateway
docker compose --env-file gateway.env -p agentcon-caddy run --rm --no-deps --entrypoint caddy caddy version
docker compose --env-file gateway.env -p agentcon-caddy run --rm --no-deps --entrypoint caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

`config --quiet`는 전체 자격 증명을 출력하지 않고 Compose 문법을 검증한다. `config`, `config --environment`, `docker inspect`의 전체 결과, `caddy environ` 또는 컨테이너 `env`를 공유하지 않는다. Caddy에는 도메인과 신뢰 upstream 설정만 전달하며 앱 관리자 자격 증명은 전달하지 않는다. gateway에는 비공개 환경 파일이 전달되므로 Docker 접근 권한은 비밀값 접근 권한으로 취급한다.

`run --no-deps` 검증 명령은 gateway 서버를 시작하거나 서비스 포트를 publish하지 않는다. 다만 검증용 컨테이너·네트워크·볼륨을 생성할 수 있다. `caddy validate` 통과는 DNS·ACME 발급·실제 upstream 연결 성공까지 증명하지 않는다. 저장소 Caddyfile의 strict proxy 해석에는 Caddy 2.8 이상이 필요하다. `caddy:2`는 고정 버전이 아니므로 검증한 버전·image digest를 운영 기록에 남기고 이후 배포는 같은 image를 기준으로 관리한다. [Caddy validate](https://caddyserver.com/docs/command-line#caddy-validate), [strict trusted proxies](https://caddyserver.com/docs/caddyfile/options#trusted-proxies-strict)

Docker build에 필요한 `scripts/audit_stored_tokens.py`만 `.dockerignore` 예외로 포함되어 있어야 한다. 전체 `scripts`나 `gateway-data`를 build context에 다시 포함시키는 방식으로 해결하지 않는다. 이번 설정 작업의 해당 예외처리를 포함한 checkout에서 위 build 명령의 성공을 확인한다. Dockerfile은 UID 10001의 앱 계정과 `/data`를 사용하므로 수동 데이터 이전 시에도 쓰기 권한을 맞춰야 한다.

### 5. DNS·터널 충돌 없이 새 배포 시작

먼저 별도 테스트 hostname으로 검증한다. 이 기본 절차에서는 Cloudflare DNS를 쓰더라도 테스트 레코드는 **DNS only**로 두어 브라우저가 Caddy에 직접 HTTPS로 연결되게 한다. 공개 서버 주소가 노출되는 경로임을 고려한다. Cloudflare 프록시를 앞에 추가하는 경우는 아래 9단계의 별도 설계가 필요하다.

기존 운영 hostname이 Tunnel CNAME으로 연결되어 있다면 같은 이름에 A/AAAA를 추가할 수 없다. 기존 CNAME·터널 hostname 설정을 비공개로 기록하고, 전환 시점에 두 경로 중 하나를 선택한다. **운영 CNAME을 먼저 삭제한 뒤 서버를 준비하는 순서로 진행하지 않는다.** [Cloudflare 동일 이름 DNS 충돌](https://developers.cloudflare.com/dns/manage-dns-records/troubleshooting/records-with-same-name/)

테스트 서버의 포트·DNS 조건과 fresh DB 사용을 확인한 뒤 운영자가 실행한다.

```sh
docker compose --env-file gateway.env -p agentcon-caddy up -d --no-build
docker compose --env-file gateway.env -p agentcon-caddy ps
```

`depends_on`은 gateway가 준비될 때까지 기다리는 readiness 보장이 아니다. 초기에는 Caddy가 502를 반환할 수 있다. 필요하면 서버 내에서 로그를 살펴보되 토큰·요청 본문·방문자 IP가 포함될 수 있으므로 원문을 외부에 공유하지 않는다. fresh DB는 수집을 새로 시작하므로 기존 운영 DB와 같은 검색 결과가 바로 나오지 않는다.

### 6. 공개 경로와 관리자 접근 확인

아래 `stage.example.net`을 실제 테스트 hostname으로 바꾼다.

```sh
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code} redirect=%{redirect_url}\n' http://stage.example.net/
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://stage.example.net/
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://stage.example.net/health
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://stage.example.net/admin/ui
```

HTTP→HTTPS 전환, HTTPS 루트와 health 정상, 공개 admin 404를 확인한다. 저장소 루트의 Python 환경에서는 `python -m scripts.check_front_deployment --url https://stage.example.net/`로 인증서와 주요 보안 응답 헤더를 확인할 수 있다. 8200/8400이 외부에 열리지 않았는지도 별도 확인한다.

관리 화면은 서버 자체에서 `http://127.0.0.1:8200/admin/ui`를 열거나, 다른 PC에서 SSH 터널을 사용한다. 다음 명령의 `user@server`는 본인의 SSH 대상으로 바꾼다. 로컬의 다른 8200 서비스와 충돌하지 않도록 로컬 포트는 18200으로 예시를 들었다.

```sh
ssh -N -L 127.0.0.1:18200:127.0.0.1:8200 user@server
```

브라우저에서 `http://127.0.0.1:18200/admin/ui`를 열고 `sadmin`과 bootstrap 비밀번호로 로그인한다. 필요한 관리 토큰은 비공개로 보관하고 공유 채팅·URL·shell 인자에 넣지 않는다. 기존 DB라면 기존 계정 비밀번호를 사용한다.

### 7. 운영 hostname 전환과 롤백

1. 테스트 결과, 선택한 DB, 관리자 로그인, 백업, 유지보수 시간과 DNS 롤백 값을 확정한다. 새 DB라면 과거 방문·추천·작업 이력이 없다는 점을 명시적으로 수용한 뒤 공개 전환한다.
2. 같은 호스트라면 운영자가 native 서버를 정상 종료한 뒤 Compose를 시작한다. 다른 호스트라도 원본과 복제 DB의 자동 작업을 동시에 활성 executor로 운영하지 않는다.
3. Caddy의 `DOMAIN`, 앱의 `AGENT_FRONT_URL`, OAuth callback을 운영 hostname에 맞추고 4단계 검증을 반복한다. 환경변수 변경은 컨테이너 재생성이 필요하다.
4. Cloudflare에서 기존 터널 hostname/DNS 연결과 충돌하지 않게 운영 DNS를 Caddy 경로로 전환한다. 이 기본 경로는 DNS only이며 새 hostname 인증서 발급 및 실제 접속을 즉시 확인한다. DNS 전파·발급 중 짧은 공백 가능성을 반영한다. 터널 자격 증명은 삭제하거나 노출하지 않는다.
5. 6단계의 확인을 운영 hostname에서 반복한다. 잘못된 경로나 인증서·DB 문제가 보이면 전환을 확대하지 않는다.

롤백은 먼저 새 배포에서 발생한 쓰기·자동 작업을 확인하고, 운영자가 새 gateway를 정상 종료한 뒤 기존 터널 hostname/DNS를 기록한 값으로 복원한다. 같은 호스트였다면 기존 native 서버를 이전 설정·DB로 정상 시작한다. 새 DB의 쓰기는 이전 DB로 자동 합쳐지지 않는다. `docker compose --env-file gateway.env -p agentcon-caddy down`은 선택한 새 프로젝트를 내리는 명령이며, **`-v`를 붙이지 않는다**. 이전 DB와 새 볼륨을 모두 보존한다.

### 8. 기존 운영 이력 이전과 백업

이 문서의 fresh volume 절차는 운영 DB 이전을 수행하지 않는다. 이력 이전이 필요하면 [SQLite 운영 안내](DATABASE_OPERATIONS.md) 및 workflow 백업·복구 계약을 먼저 따른다.

- 실행 중인 SQLite 파일을 `cp`하거나 WAL만 삭제하지 않는다. 온라인 백업 API로 일관된 snapshot을 만들고, 최종 전환 시 모든 writer를 정상 종료한 뒤 마지막 변경분과 백업을 확정한다.
- backup 디렉터리는 700, 파일은 600으로 보관하고 snapshot의 `quick_check`·`integrity_check`, 주요 row 수와 앱 조회를 확인한다. 원본 DB와 일치하는 WAL·키·artifact 파일도 이전 범위를 검토한다.
- 컨테이너 DB는 `/data/gateway.sqlite3`이며 앱 UID는 10001이다. 원본을 직접 mount하여 예행연습하지 않고 새 볼륨의 복사본에 대해 schema 초기화·변경과 조회를 검증한다. 원본과 복제본이 같은 작업·알림을 중복 실행하지 않게 한다.
- workflow 복구 CLI는 미완료 작업·기존 승인·세션·전달 권한을 보수적으로 비활성화할 수 있다. 단순 파일 복사와 서비스 연속성 복구가 같은 의미라고 가정하지 않는다. 새 환경에서 필요한 재승인·재인증을 확인한다.
- 앱 DB 볼륨뿐 아니라 Caddy 인증서/키 볼륨과 비공개 환경 파일의 복구 계획도 마련한다. 백업 완료만으로 복원이 검증된 것은 아니다.

## 9. Cloudflare 앞뒤에 Caddy를 추가할 때의 주의

**현재 터널에 Caddy만 끼우는 작업은 위 B 경로와 다르다.** 저장소 Caddyfile은 `X-Forwarded-Proto`를 `{scheme}`으로 명시적으로 덮어쓴다. `Cloudflare HTTPS → cloudflared HTTP → Caddy HTTP → gateway`로 추가하면 Caddy가 본 scheme이 HTTP여서 원래 HTTPS 정보가 사라질 수 있고, 기본 자동 redirect와 결합하면 반복 redirect도 생길 수 있다. `CADDY_TRUSTED_UPSTREAMS`만 바꾸어 해결되었다고 가정하지 않는다.

Cloudflare의 일반 proxied DNS를 Caddy 앞에 둘 때도 실제 TLS 종단·SSL 모드, Caddy까지의 프로토콜, origin 직접 접근 차단, 정확한 신뢰 upstream CIDR, XFF/XFP 전달을 함께 검증한다. 현재 기본값은 외부 Cloudflare peer를 신뢰하지 않으므로 client IP가 edge 주소로 보일 수 있다. 표준 Caddy의 trusted proxy 처리와 달리 이 저장소에는 명시적인 `header_up`가 있으므로 이 설정까지 검토해야 한다. 검증 없이 사용자 제공 XFP를 그대로 복사하거나 모든 private 주소를 신뢰하지 않는다. [Caddy reverse proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#defaults), [Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)

별도 검증된 설계가 없다면 A의 현재 터널 구성을 유지하거나, B의 Caddy 직접 공개 경로 중 하나를 선택한다.

## setup.sh와 검토 근거

`deploy/setup.sh`는 Ubuntu·DuckDNS 전용 자동 설치 스크립트다. root 권한으로 패키지 설치, iptables 변경, 토큰을 포함한 DuckDNS cron 등록, Compose 시작을 수행한다. 현재 macOS+Cloudflare 환경의 Caddy 설정 방법으로 `sudo bash deploy/setup.sh`를 실행하지 않는다. 이 가이드는 해당 스크립트를 사용하지 않는다.

2026-10-19 실제 소스에서 확인한 기준점:

- `deploy/Caddyfile:3,9,16,19,22` — 신뢰 upstream, 전달 헤더, 도메인, admin 차단, 분기 경로.
- `deploy/docker-compose.yml:6,8,17,19,21,24,27,29,33,39` — 환경변수, production/TLS 종단, 볼륨·포트·고정 IP·Caddyfile mount.
- `Dockerfile:7,9,10,11` — UID 10001, audit script 포함, 비root 실행, 컨테이너 DB 경로.
- `agent_market/gateway/admin_auth.py:90` — schema/초기 관리자 생성과 bootstrap 조건.
- `agent_market/gateway/store.py:550` — Store 시작 시 schema와 admin 초기화.
- `agent_market/gateway/deployment_security.py:91` — production 시작 검증.
- `agent_market/config.py:160` — DB와 frontend 환경변수 해석.
- `deploy/setup.sh:9,18,23,31,37` — shell sourcing, 설치·방화벽·cron·서비스 시작.

현재 Compose는 Caddyfile **단일 파일**을 bind mount한다. 편집기가 파일 inode를 교체하면 컨테이너가 이전 파일을 계속 볼 수 있으므로, 유지보수 때 파일이 실제 반영됐는지 확인한다. Caddy 설정만 바뀐 경우 검증 후 Caddy 컨테이너 재생성으로 mount·환경을 갱신할 수 있다. 전체 gateway를 필요 없이 재시작하지 않는다. 공식 이미지는 디렉터리 mount 방식과 reload 절차도 설명한다. [Caddy official image](https://hub.docker.com/_/caddy)

```sh
docker compose --env-file gateway.env -p agentcon-caddy run --rm --no-deps --entrypoint caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose --env-file gateway.env -p agentcon-caddy up -d --no-deps --force-recreate caddy
```

이 문서는 소스와 공식 문서를 대조한 운영 절차다. 실제 Docker image build, 컨테이너 시작, ACME 발급, DNS 전환 및 기존 DB 이전은 문서 작성 과정에서 수행하지 않았다.
