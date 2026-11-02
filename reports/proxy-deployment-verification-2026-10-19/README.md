# 재시작 후 배포 프록시 확인

검증일: 2026-10-19, Asia/Seoul. 서버 재시작은 12:15:31, 공개 경로 확인은 약 12:18–12:19에 수행했다.

공개 HTTPS 연결, 최신 프론트엔드 반영, 관리자 경로 격리는 확인됐다. **HTTP → HTTPS 강제 전환은 확인되지 않았으며 실제 HTTP GET이 200을 반환했다.** 배포 전체를 정상으로 판정하지 않는다.

## 실제 배포 경로

- 실행 중인 외부 연결 프로세스는 Cloudflare Tunnel의 `cloudflared`다. Caddy 프로세스는 관측되지 않았다.
- 터널 데몬 로그에 마지막으로 남은 원격 구성은 `agentconcierge.biz` → `http://localhost:8400`, 나머지 호스트는 `http_status:404`다. 해당 구성 갱신 기록은 10월 15일이며, 10월 19일 연결 재등록 기록도 존재한다. 원격 제어판의 현재 구성을 직접 조회한 결과와는 구분한다.
- 현재 앱은 관리자 포트 8200을 loopback, 프론트엔드 포트 8400을 모든 IPv4 인터페이스에 바인딩한다.
- 저장소의 `deploy/Caddyfile` 및 Compose 설정은 현재 관측된 배포 경로에 적용되고 있지 않다. 해당 파일 검증만으로 현재 서비스의 프록시 설정을 확인했다고 볼 수 없다.

## 공개 및 로컬 응답

- 로컬 프론트엔드 및 공개 HTTPS Home: 200. 두 응답의 메인 스크립트가 현재 소스와 일치한다. 새 캐시 버전이 있으며 고정 `99.4%` 문구는 없다.
- 공개 `/api/overview`: 200. 새 `verification` 집계가 반환된다.
- 공개 `/admin`, `/admin/ui`, `/admin/api/overview`: 모두 404.
- 로컬 관리자 API의 무인증 요청: 403.
- 공개 HTTPS 응답: 인증서 검증 성공, CSP, HSTS, `nosniff`, `DENY`, `no-referrer`, `no-store` 확인. Cloudflare 캐시 상태는 `DYNAMIC`이다. CSP nonce 값과 쿠키는 보관하지 않았다.
- 공개 HTTP Home: 리다이렉트 추적을 비활성화한 GET에서 **200, Location 없음**. 추가 HEAD는 **405, Location 없음**이었다. 두 경우 모두 HTTPS 전환 응답이 아니다. HTTP 응답에 HSTS 헤더가 있어도 최초 HTTP 요청의 강제 전환을 대신하지 않는다.

원시 결과: [live-checks.json](<저장소>/reports/proxy-deployment-verification-2026-10-19/live-checks.json), [HTTP 재확인](<저장소>/reports/proxy-deployment-verification-2026-10-19/http-redirect-recheck.json).

## 신뢰 프록시 설정

현재 프로세스 환경에는 `FORWARDED_ALLOW_IPS`가 없으며, 구현 기본값은 `127.0.0.1,::1`이다. 관측된 로컬 터널 원본 연결과 맞는 범위다. Cloudflare의 전체 공인 IP 대역을 앱의 신뢰 프록시로 추가할 근거는 없다.

소스에서는 Uvicorn의 자동 프록시 처리를 끄고 `TrustedIngressMiddleware`가 원래 소켓 상대를 기준으로 전달 헤더를 한 번만 해석한다. 신뢰하는 상대에서 온 XFF만 제한된 길이와 홉 수 안에서 오른쪽부터 검사한다. 벤더별 클라이언트 IP 헤더를 무조건 신뢰하지 않는다.

Cloudflare는 기존 XFF 뒤에 연결 상대의 IP를 추가하며, `X-Forwarded-Proto`에는 방문자의 원래 프로토콜을 설정한다고 설명한다. 이 동작과 현재 파서의 방향은 부합한다. Workers, 헤더 변환, Pseudo IPv4 설정은 별도로 관측하지 않았다. [Cloudflare 공식 헤더 문서](https://developers.cloudflare.com/fundamentals/reference/http-headers/).

다만 이번 실서비스 검증은 일반 GET/HEAD로 한정했다. 전달 헤더 위조, 악성 경로 요청, 패킷 캡처, 개인 IP 수집을 수행하지 않았으며, 실제 사용자의 앱 내부 식별 결과를 직접 증명하지는 않는다. Uvicorn 접근 로그는 원래 전송 연결의 loopback 상대를 기록할 수 있으므로 그 값만으로 앱의 클라이언트 구분 성공·실패를 판단할 수 없다.

## 보완 우선순위

1. **HTTPS 강제 전환**: Cloudflare에서 해당 호스트의 HTTP 요청이 HTTPS로 301/308 전환되도록 `Always Use HTTPS` 또는 동등한 명시적 리다이렉트 규칙을 적용한다. 이후 리다이렉트를 따르지 않는 HTTP GET으로 다시 확인해야 한다. 현재 관측된 구성에서는 Caddy 설정을 수정해도 이 경로에 적용되지 않는다.
2. **원본 포트 바인딩 제한**: 로컬 Tunnel만 사용할 목적이라면 다음 서버 시작부터 `AGENT_FRONT_HOST=127.0.0.1`로 제한한다. 현재 8400이 모든 인터페이스에서 수신하는 것은 확인했지만, 방화벽/NAT를 넘어 인터넷에서 직접 접근 가능한지는 검사하지 않았다.
3. **운영 모드 명시**: 프로세스 환경에 `DEPLOYMENT_MODE`, `PUBLIC_TLS_TERMINATION`이 없다. 다음 배포에서 실제 TLS 종료 방식과 운영 사전 검사를 명시하는 것이 좋다. `DEPLOYMENT_MODE=production`은 관리자 인증 및 목적지 정책도 검사하므로, 나머지 조건을 검토한 뒤 적용해야 한다. 확인 없이 실행 환경에 추가하지 않았다.

HTTPS 전환 설정의 공식 안내: [Cloudflare Always Use HTTPS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/).

## 재시작 로그 및 범위

새 시각 포함 접근 로그와 DEBUG 억제가 적용됐다. 재시작 이후 제한된 관측 구간에 새 자동 차단은 없었다. 12:16:03에 운영 기록 경고 및 `AUTH_REQUIRED`가 별도로 관측됐으며, 이를 프록시 오류라고 단정하지 않았다. 자세한 집계와 시각 범위는 [로그 확인](<저장소>/reports/proxy-deployment-verification-2026-10-19/log-findings.md)을 따른다.

실행한 요청은 GET 8건과 보완 확인 HEAD 1건이다. 사용자 서버, Tunnel 설정, DB 업무 데이터, 관리자 인증 정보를 수정하지 않았다. 원격 설정의 모든 경로, 외부 원본 우회 접근, WAF 전체 규칙, 브라우저 Push/WebSocket 장시간 연결은 이번 검증 범위에 포함되지 않는다. 단일 응답 시간은 가용성이나 SLA의 근거로 사용하지 않았다.

재현 도구: [verify_proxy.py](<저장소>/reports/proxy-deployment-verification-2026-10-19/verify_proxy.py). 실행 환경 요약: [runtime-topology.json](<저장소>/reports/proxy-deployment-verification-2026-10-19/runtime-topology.json).
