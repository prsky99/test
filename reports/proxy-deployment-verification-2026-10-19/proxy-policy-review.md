# 재시작 후 프록시 정책 독립 검토

검토일: 2026-10-19 KST. 코드·설치된 라이브러리·Cloudflare 공식 문서를 읽기 전용으로 검토했다. 이 검토에서는 서비스 요청, 프로세스 실행·종료·재시작, 운영 DB 변경, 외부 설정 변경을 하지 않았다. 아래 실제 응답 및 실행 환경은 루트 담당자가 전달한 관측이며, 이 검토자가 독립 재요청한 결과가 아니다. 토큰, 방문자 IP, 터널 식별자는 수록하지 않았다.

## 결론

Cloudflare Tunnel이 같은 호스트의 HTTP origin으로 연결하는 현재 구조에서는 기본 loopback 신뢰와 `Uvicorn proxy_headers=False` 및 바깥쪽 `TrustedIngressMiddleware` 조합이 합리적이다. 코드는 실제 socket peer를 확인한 후 IP와 프로토콜을 한 번 해석한다. 다만 실제 origin 수신 헤더를 관측하지 않았으므로, 운영 방문자의 IP가 올바르게 구분되고 앱이 HTTPS로 인식한다는 종단 간 검증까지 완료된 것은 아니다.

실제 HTTP GET이 `200`이고 `Location`이 없다는 관측은 HTTPS 강제 전환이 해당 요청에서 동작하지 않았음을 보여준다. HTTPS 접속 성공 및 HSTS 응답만으로 이 문제를 해소할 수 없다. 우선순위는 Cloudflare edge의 HTTPS 전환 설정 확인·보완이다.

## 제공받은 실제 관측

- 마지막 터널 ingress: 공개 서비스 호스트 → 같은 호스트의 HTTP frontend origin. 최종 미일치 규칙은 `http_status:404`.
- 관리 리스너는 loopback, 공개 frontend 리스너는 전체 IPv4 인터페이스에 바인딩되어 있다.
- `FORWARDED_ALLOW_IPS`, `DEPLOYMENT_MODE`, `PUBLIC_TLS_TERMINATION` 환경변수가 없다.
- 공개 HTTPS 루트는 `200`, 최신 script 일치, CSP/HSTS/no-store 및 동적 응답 확인.
- 공개 `/admin`, `/admin/ui`, `/admin/api/overview`는 `404`; 로컬 관리 경로의 미인증 요청은 `403`.
- 공개 HTTP 루트 GET은 `200`이며 `Location`이 없다. HEAD는 `405`이고 `Location`이 없다. 리다이렉트 판정 근거는 GET 결과다.

## IP와 XFF 신뢰 경계

`agent_market/gateway/deployment_security.py:9`의 기본 신뢰 대상은 IPv4/IPv6 loopback이다. 임의 호스트명, wildcard 및 전체 주소 공간 CIDR은 거부된다. `:37`의 `forwarded_client`는 실제 socket peer가 신뢰 대상일 때만 XFF를 사용한다. XFF 전체에 대해 IP literal 유효성, 길이와 hop 수를 검사하고 오른쪽부터 첫 비신뢰 주소를 선택한다. 유효하지 않거나 너무 긴 체인은 socket peer로 되돌린다. 직접 접속한 비신뢰 peer가 보낸 XFF는 사용하지 않는다. `CF-Connecting-IP` 및 `X-Real-IP`도 이 정책에서 사용하지 않는다. 테스트 전용 `testclient` 예외는 실제 TCP 주소가 아니다.

Cloudflare는 기존 XFF가 있으면 접속한 upstream 주소를 뒤에 추가하고, 없으면 방문자 주소를 넣는다고 설명한다. 그러므로 일반적인 Cloudflare→로컬 터널 경로에서는 왼쪽의 사용자 삽입값을 선택하지 않는 현재 방식이 타당하다. Cloudflare 자체는 원본 IP 복원 시 단일 값인 `CF-Connecting-IP` 등을 권장하지만, 현재 코드를 바로 그 헤더로 바꿀 필요가 입증된 것은 아니다. Workers, 다중 CDN, IP 제거 Transform, Pseudo IPv4 설정에 따라 표현되는 주소가 달라질 수 있다. [Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)

여기서 loopback 신뢰는 **cloudflared 프로세스의 신원을 앱이 인증한다는 뜻이 아니다**. 같은 호스트에서 loopback으로 접속할 수 있는 다른 프로세스도 이 네트워크 신뢰에 포함된다. 또한 전체 IPv4 바인딩은 네트워크에서 origin 포트 접근이 가능하면 Cloudflare edge 정책을 우회하는 통로가 될 수 있다. 실제 외부 접근 가능 여부는 방화벽·NAT를 확인하지 않아 미확인이다. 후속 배포에서는 터널 전용 loopback 바인딩 또는 origin inbound 차단을 검토한다. Cloudflare Tunnel 자체는 origin에서 시작하는 outbound 연결을 사용하며, 방화벽으로 직접 inbound를 차단할 수 있다. [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)

## HTTPS 인식과 강제 전환

`deployment_security.py:59`는 신뢰된 실제 peer의 단일 `X-Forwarded-Proto`가 허용된 정확한 값일 때만 ASGI scheme에 반영한다. 중복·복합·비정상 값은 무시한다. `gateway/server.py:553` 이후의 두 Uvicorn 실행 경로는 바깥쪽 ingress middleware와 `proxy_headers=False`를 사용하므로, Uvicorn이 먼저 헤더를 소비하여 원래 socket peer를 잃는 것을 막는다. Cloudflare는 XFP를 방문자가 연결한 HTTP/HTTPS 프로토콜로 설정하고, 사용자가 보낸 다른 값은 덮어쓴다고 설명한다. [Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)

따라서 정상 HTTPS 방문은 HTTP 로컬 origin을 사용하더라도 앱에서 HTTPS로 해석할 수 있다. 반대로 공개 HTTP 요청이 허용되면 XFP도 HTTP일 수 있다. 로컬 origin의 `http://` 자체와 방문자↔edge의 HTTP 허용은 서로 다른 문제다. 현재 공개 HTTP GET 결과는 후자가 남아 있음을 보여준다. Caddy 설정 파일의 리다이렉트나 헤더 정책은 실제 터널→frontend 직접 경로에 적용되었다는 증거가 아니다.

권고: 활성 edge 인증서와 영향 범위를 확인한 뒤 Cloudflare **Always Use HTTPS**를 사용한다. 이 옵션은 전체 호스트·하위 도메인에 영향을 주므로 특정 호스트만 대상으로 해야 한다면 해당 호스트의 Redirect Rule을 사용한다. origin 자체 리다이렉트는 프록시 설정에 따라 루프가 생길 수 있어 Cloudflare가 edge 전환을 권고한다. 이 검토에서는 변경하지 않았다. [Always Use HTTPS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/)

HSTS는 HTTPS로 전달되어 브라우저가 수락한 뒤의 연결에 영향을 주며, 사전 상태가 없는 클라이언트의 HTTP 요청을 서버가 redirect한다는 증거가 아니다. HTTPS HSTS 헤더와 이번 HTTP GET `200`은 함께 발생할 수 있다. [Cloudflare HSTS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/http-strict-transport-security/)

`deployment_security.py:91` 이후의 운영 환경 검증은 `DEPLOYMENT_MODE=production`일 때만 실행된다. 제공된 환경에서는 이 검증이 활성화되지 않는다. 이것이 ingress 신뢰 검사를 끄는 것은 아니지만, 운영 URL/TLS 종단/관리 자격 증명 관련 시작 시 검증이 적용된 상태라고 주장할 수 없다. 추후 설정을 명시할 때는 관련 검증을 사전에 확인한다.

## access log 해석 주의

`TrustedIngressMiddleware`는 `scope = dict(scope)`로 사본을 만든 뒤 앱이 보는 client와 scheme을 수정한다. 설치된 Uvicorn의 `h11_impl.py:409`는 원본 `self.scope`를 앱에 전달하고, `:479`의 기본 access logger는 같은 원본 scope의 client를 읽는다. 따라서 **기본 access log에 loopback이 찍혀도 앱 내부의 IP 분리가 실패했다는 뜻은 아니다**. 이는 현재 코드 구조에서 도출한 판단이며 운영 요청별 로그·보안 집계를 대조하여 입증한 결과는 아니다. `concierge/security.py`의 `resolve_ip`는 ingress가 설정한 `agent_market.client_ip`를 우선 사용한다.

## 추가 확인 범위

- 운영 origin에 실제 도착한 socket peer, XFF hop 수·형식, XFP 및 앱의 최종 scheme/IP 분리 여부. 원시 방문자 IP·헤더를 공개 로그나 응답에 추가하지 않고 격리된 검증 또는 익명화 집계로 확인할 필요가 있다.
- Cloudflare Workers, Transform, Pseudo IPv4, Redirect Rules, Always Use HTTPS의 실제 설정. HTTP 응답은 전환 미동작을 증명하지만 어떤 설정이 꺼져 있거나 우회되었는지까지 단정하지 못한다.
- origin의 방화벽·NAT와 직접 접근 가능 여부. 전체 인터페이스 바인딩만으로 인터넷 노출을 단정하지 않는다.
- 관리 경로의 관측된 404/403은 확인된 해당 경로·요청 범위의 결과다. 모든 관리 라우트·모든 프록시 우회 경로의 부재를 증명하지 않는다.
- 기존 `tests/test_front_ingress_observability.py`에 신뢰 경계, 중복/비정상 헤더, 방문자별 보안 격리 회귀가 있으나 이번 읽기 전용 검토에서는 테스트를 새로 실행하지 않았다.
