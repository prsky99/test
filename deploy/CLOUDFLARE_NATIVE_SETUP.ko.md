# Mac의 native agentcon과 Cloudflare HTTPS 규칙

현재 서비스는 **MacBook 터미널에서 `agentcon`으로 실행하는 서버**다. 연결은 `방문자 → Cloudflare → Tunnel → Mac의 HTTP 서버(localhost:8400)`이며, 이 구성을 유지한다.

2026-10-19 브라우저에서 Cloudflare 규칙을 배포하고 저장값을 다시 확인했다. **설정 배포·활성화 및 12:57 KST 공개 GET 검증을 완료**했다. 아래는 실제 설정과 추후 확인할 메뉴다. [검증 JSON](../reports/cloudflare-https-2026-10-19/verification.json)에 공개 응답을 기록했다.

## 1. 이미 만들어진 규칙 확인

1. [Cloudflare 대시보드](https://dash.cloudflare.com/)에 접속한다. 로그인·MFA·보안 확인은 계정 소유자가 직접 완료한다. 비밀번호나 인증 코드를 채팅에 전달하지 않는다.
2. 계정 홈에서 해당 계정을 선택하고 **Domains/Websites → agentconcierge.biz**로 들어간다. 공식 문서의 현재 도메인 목록 명칭은 Domains다. [도메인 선택 안내](https://developers.cloudflare.com/fundamentals/account/find-account-and-zone-ids/)
3. 실제로 확인한 메뉴 경로인 **Rules → Redirect Rules**를 연다.
4. **Enforce HTTPS for agentconcierge.biz** 규칙을 찾는다. 배포 후 목록은 `1/10`, `1 rule active`였으며 해당 규칙이 활성화되어 있었다.
5. 해당 규칙의 편집 화면을 열어 아래 저장값을 확인한다. **Create rule로 같은 규칙을 다시 만들지 않는다.**

저장된 규칙값:

- **When incoming requests match**: Custom filter expression
- **조건**: `(http.host eq "agentconcierge.biz" and not ssl)`
- **URL redirect Type**: Dynamic
- **Expression**: `concat("https://agentconcierge.biz", http.request.uri.path)`
- **Status code**: `308 — Permanent, HTTP method preserved`
- **Preserve query string**: On

조건은 `agentconcierge.biz`의 HTTP 요청만 대상으로 하며 `www`나 다른 하위 도메인은 포함하지 않는다. `ssl`은 방문자와 Cloudflare 사이의 암호화 여부를 뜻하며, `not ssl`은 비암호화 요청 조건이다. Mac의 로컬 HTTP 연결은 그대로 유지된다. [ssl 필드](https://developers.cloudflare.com/ruleset-engine/rules-language/fields/reference/ssl/), [boolean 문법](https://developers.cloudflare.com/ruleset-engine/rules-language/values/#boolean-values)

Dynamic 대상은 경로만 조합하고 query는 보존 옵션으로 한 번 추가한다. 308은 redirect를 따르는 클라이언트가 POST 등 원래 HTTP 메서드를 유지하도록 한다. [경로·query 보존 공식 예제](https://developers.cloudflare.com/fundamentals/manage-domains/redirect-domain/), [308 등 Redirect 설정](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/)

## 2. 기존 규칙 수정·비활성화

수정할 때는 **Rules → Redirect Rules → 해당 규칙의 편집 화면**을 사용한다. 변경할 항목만 고친 뒤 화면의 저장·배포 동작으로 반영하고, 목록과 편집 화면을 다시 열어 실제 저장값을 확인한다. 확인만 할 때는 값을 바꾸거나 다시 배포하지 않는다.

이 규칙을 중단하려면 목록의 **해당 규칙 활성화 컨트롤**을 꺼서 비활성 상태와 활성 규칙 수를 확인한다. 삭제하거나 다른 규칙을 만들 필요는 없다. 비활성화하면 해당 호스트의 HTTP 전환이 다시 없어질 수 있으므로, 변경 의도와 검증 결과를 함께 기록한다.

zone 전체 스위치인 **SSL/TLS → Edge Certificates → Always Use HTTPS**는 이번 작업에서 **Off로 유지**했다. 이 옵션은 다른 호스트·하위 도메인에도 영향을 주므로, 이번처럼 apex만 전환하려는 범위에는 별도의 Redirect Rule을 사용한다. 추가로 켜야 하는 단계가 아니다. [Always Use HTTPS 적용 범위](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/)

## 3. 공개 GET 검증 완료

2026-10-19 **12:57 KST**, redirect를 따라가지 않는 공개 GET 4회에서 다음을 확인했다.

- `http://agentconcierge.biz/` → **308**, `Location: https://agentconcierge.biz/`.
- `http://agentconcierge.biz/api/overview?proxy_check=20261019` → **308**, 동일한 경로·query가 중복 없이 유지된 HTTPS 주소.
- `https://agentconcierge.biz/` → **200**, TLS 인증서 검증 성공, HSTS 헤더 있음.
- `https://agentconcierge.biz/admin/ui` → **404**, 공개 관리 화면 분리 유지.

검증은 GET 응답 범위다. POST 재전송 동작은 이번에 실행하지 않았으며 메서드 보존은 선택한 308의 정책이다. 브라우저는 `Rules → Redirect Rules` 목록을 열어 둔 상태이고 `1 rule active`가 확인됐다.

추후 Mac 터미널에서 다시 확인하려면 다음 명령을 사용한다.

```sh
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code} redirect=%{redirect_url}\n' http://agentconcierge.biz/
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code} redirect=%{redirect_url}\n' 'http://agentconcierge.biz/api/overview?proxy_check=20261019'
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://agentconcierge.biz/
curl --silent --show-error --output /dev/null --write-out 'status=%{http_code}\n' https://agentconcierge.biz/admin/ui
```

- HTTP 루트의 기대값: `308`, `redirect=https://agentconcierge.biz/`.
- HTTP 경로·query의 기대값: `308`, 같은 경로와 query가 중복 없이 유지된 HTTPS 주소.
- HTTPS 루트의 기대값: `200`이며 인증서 검증 성공.
- HTTPS 관리 화면의 기대값: `404`.

HEAD 대신 GET을 사용하고 `-L`을 넣지 않아 첫 응답을 확인한다. 인증서 검증을 끄는 `-k`도 사용하지 않는다. 본문·쿠키·자격 증명은 출력하지 않는다. 설정 전 HTTP GET 200·redirect 없음 상태에서, 이번 규칙 배포 후 308 전환으로 바뀌었다.

## 4. 터널·서버 설정과 분리

터널 origin은 **`http://localhost:8400`으로 유지**한다. 이번 HTTPS 전환을 위해 origin URL을 `https://`로 바꾸거나, origin 인증서·TLS 검증 설정·DNS 레코드를 임의로 변경하지 않는다. 이번 설정은 **native 서버 재시작 없이** 적용·검증했다.

저장소 루트의 `./agentcon check`는 준비된 native 환경 설정을 검사하는 별도 명령이며 Cloudflare 규칙이나 실행 중인 프로세스 설정을 바꾸지 않는다. `agentcon restart`는 native 설정을 실제 적용하는 별도 운영 작업으로, 이번 브라우저 설정과 분리한다. 이 문서 갱신 과정에서는 서버를 실행·종료·재시작하지 않았다.
