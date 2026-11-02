# Cloudflare HTTPS 전환 적용 — 2026-10-19

사용자 요청에 따라 Mac Computer Use로 로그인된 Chrome의 Cloudflare 대시보드를 조작했다. 현재 Mac 터미널의 native 서버 실행과 Tunnel 원본 연결을 유지했다. Docker/Caddy 설치·실행, 서버 재시작, DNS·터널·SSL 암호화 모드 변경은 수행하지 않았다.

## 실제 UI 작업

1. Cloudflare 계정 홈에서 `agentconcierge.biz`를 선택했다.
2. SSL/TLS → Edge Certificates에서 유효한 edge 인증서와 `Always Use HTTPS: off`를 확인했다. 해당 토글은 zone 전체에 적용되므로 그대로 두었다.
3. Rules → Redirect Rules에서 기존 Single Redirect가 0개임을 확인했다.
4. 아래 단일 호스트 규칙을 작성하고 Deploy했다.
5. 목록의 활성 상태 및 `1 rule active`를 확인했다. 편집 화면을 다시 열어 저장된 조건·대상·응답코드·쿼리 보존 값을 확인하고 규칙 목록으로 돌아왔다.

- 이름: `Enforce HTTPS for agentconcierge.biz`
- 조건: `(http.host eq "agentconcierge.biz" and not ssl)`
- 대상 유형: Dynamic
- 대상 식: `concat("https://agentconcierge.biz", http.request.uri.path)`
- 응답: 308 Permanent Redirect, HTTP method preserved
- Preserve query string: On
- 상태: Enabled
- 적용 대상: apex 호스트의 HTTP 요청. 다른 호스트 및 HTTPS 요청에는 이 규칙이 매칭되지 않는다.

## 공개 검증

12:57 KST에 리다이렉트를 따라가지 않는 GET 4건을 수행했다.

- HTTP Home: **308**, `Location: https://agentconcierge.biz/`
- HTTP `/api/overview?proxy_check=20261019`: **308**, 같은 경로·쿼리를 보존한 HTTPS Location
- HTTPS Home: **200**, 인증서 검증 성공 및 HSTS 확인
- HTTPS `/admin/ui`: **404**

원시 검증: [verification.json](<저장소>/reports/cloudflare-https-2026-10-19/verification.json).
사용자용 클릭 안내: [CLOUDFLARE_NATIVE_SETUP.ko.md](<저장소>/deploy/CLOUDFLARE_NATIVE_SETUP.ko.md).

방문자 식별 정보, 응답 본문·쿠키, Cloudflare 계정·zone·rule ID, 계정 이메일과 인증 값은 이 기록에 보관하지 않았다. API 실행이나 알림을 호출하지 않았으며 POST 실행 자체는 검증하지 않았다. 308 메서드 보존은 저장된 규칙 설정을 확인한 범위다.

