# Cloudflare 캐시 규칙 경로 추가: R78 고정 문서·상태 경로 11개 (2026-11-15 12:40, PM 실행)

- 근거: 11-15 pm16-frontend r2부터 원서버가 아래 경로에 공개 캐시 헤더를 준다(R78, `public_http_contract`). 그런데 엣지 규칙에 경로가 없어 `cf-cache-status: DYNAMIC`이었다. 요청마다 한국 → 미국 엣지 → 터널 → 원서버를 거쳤다(`/api/pearl/status` 한 번 7.07초, 11-15 10:45).
- 실행: 사용자 결정 11-15 "모두 맡김"(Cloudflare 설정은 PM이 크롬 로그인으로 실행). 대시보드 화면에서 저장했다.
- 비용: 0. 새 규칙을 만들지 않고 `Public insights (11-13)` 규칙의 경로 집합만 넓혔다(규칙 4개 그대로, 무료 플랜 10개 안).

## 1. 바꾼 것
`Caching → Cache Rules → Public insights (11-13)`의 조건식. 경로 집합에 11개를 더했다. 다른 줄과 동작(Eligible for cache, 원서버 헤더를 따름)·순서는 그대로다.

바꾼 뒤(761자):
```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"} and (http.request.uri.path in {"/api/insights" "/api/feed/verified.json" "/advertise" "/methodology" "/methodology.json" "/methodology/changelog" "/api/necklaces" "/api/feed/necklaces.json" "/api/verify" "/api/roles" "/.well-known/glama.json" "/.well-known/skill.md" "/.well-known/agent-entry.json" "/skill.md" "/status.json" "/api/pearl/status" "/api/pearl/access" "/ads/library" "/ads/library.json" "/api/agent/v1/openapi.json" "/security.txt" "/claude-plugins/marketplace.json"} or starts_with(http.request.uri.path, "/api/agents/") or starts_with(http.request.uri.path, "/api/roles/")) and http.cookie eq "" and not any(lower(http.request.headers.names[*])[*] eq "authorization"))
```

바꾸기 전(523자, 되돌릴 때 이 식을 넣는다):
```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"} and (http.request.uri.path in {"/api/insights" "/api/feed/verified.json" "/advertise" "/methodology" "/methodology.json" "/methodology/changelog" "/api/necklaces" "/api/feed/necklaces.json" "/api/verify" "/api/roles" "/.well-known/glama.json"} or starts_with(http.request.uri.path, "/api/agents/") or starts_with(http.request.uri.path, "/api/roles/")) and http.cookie eq "" and not any(lower(http.request.headers.names[*])[*] eq "authorization"))
```

더한 경로와 원서버 헤더:
| 경로 | Cache-Control |
|---|---|
| `/.well-known/skill.md`, `/.well-known/agent-entry.json`, `/skill.md`, `/api/agent/v1/openapi.json` | `public, max-age=3600, stale-while-revalidate=3600` |
| `/status.json`, `/api/pearl/status`, `/api/pearl/access` | `public, max-age=60, stale-while-revalidate=60` |
| `/ads/library`, `/ads/library.json`, `/security.txt` | `public, max-age=600, stale-while-revalidate=3600` |
| `/claude-plugins/marketplace.json` | `public, max-age=21600, stale-while-revalidate=86400` |

- `/skill.md`, `/security.txt`, `/claude-plugins/marketplace.json`은 R78 목록에는 없었지만 같은 상태(공개 헤더인데 DYNAMIC)라 함께 넣었다.
- `/logo.svg`는 확장자 기본 캐시로 이미 HIT라 넣지 않았다.

## 2. 두 번째 변경 (11-15 12:48): 목걸이·레지스트리 경로
- 근거: 성장·유통의 확인(11-15, 로컬 앱에서 Accept 4가지·Origin 2가지로 같은 요청을 두 번씩 비교). `/necklaces/<slug>`, `/registry`, `/registry/verified/v0.1/*`는 Accept 협상이 없고 요청마다 달라지는 값(nonce·토큰·폼 값)이 없다. 레지스트리의 CORS는 Origin과 관계없이 `*`다. 목걸이 실행 폼의 제출은 POST라 규칙 대상이 아니다.
- 바꾼 것: 경로 집합에 `"/registry"`를 더하고, `starts_with(http.request.uri.path, "/necklaces/")`와 `starts_with(http.request.uri.path, "/registry/verified/v0.1/")`를 더했다. 식은 892자가 됐다.
- 지금 식(892자):
```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"} and (http.request.uri.path in {"/api/insights" "/api/feed/verified.json" "/advertise" "/methodology" "/methodology.json" "/methodology/changelog" "/api/necklaces" "/api/feed/necklaces.json" "/api/verify" "/api/roles" "/.well-known/glama.json" "/.well-known/skill.md" "/.well-known/agent-entry.json" "/skill.md" "/status.json" "/api/pearl/status" "/api/pearl/access" "/ads/library" "/ads/library.json" "/api/agent/v1/openapi.json" "/security.txt" "/claude-plugins/marketplace.json" "/registry"} or starts_with(http.request.uri.path, "/api/agents/") or starts_with(http.request.uri.path, "/api/roles/") or starts_with(http.request.uri.path, "/necklaces/") or starts_with(http.request.uri.path, "/registry/verified/v0.1/")) and http.cookie eq "" and not any(lower(http.request.headers.names[*])[*] eq "authorization"))
```
- 확인(12:49): 세 경로는 아직 운영에 없어 404·`no-store`이고 `cf-cache-status`가 DYNAMIC에서 BYPASS로 바뀌었다(규칙에 걸리지만 원서버가 `no-store`라 남지 않음). 기존 경로 `/ads/library` HIT, `/api/roles` REVALIDATED, `/api/pearl/status` EXPIRED 뒤 200.
- **남은 확인**: 목걸이 첫 공개와 레지스트리 배포 뒤, 200 응답이 두 번째 요청에서 HIT인지 본다(목걸이 5분, 레지스트리 5분 보관).
- 넣지 않은 것: `/privacy`, `/terms`는 전문 페이지로 보내는 301이라 넣지 않았다.
- 이 변경만 되돌리려면 1절의 "바꾼 뒤(761자)" 식을 넣는다.

## 3. 적용 뒤 확인 (11-15 12:41, 공개 주소·새 연결, 한국에서 측정)
- 11개 경로 모두 두 번째 요청이 `cf-cache-status: HIT`. 응답 시간 0.71~0.83초(`/claude-plugins/marketplace.json`만 2.27초).
- `Cookie` 요청과 `Authorization` 요청은 `DYNAMIC`이고 `no-store`다(`/api/pearl/status`로 확인).
- 대시보드 API로 다시 읽은 값: 규칙 4개 모두 enabled, 네 번째 규칙 식 761자.

## 4. 되돌리기
- 같은 화면에서 조건식을 1절의 "바꾸기 전" 식으로 바꾸고 저장한다. 바로 엣지 캐시에서 빠진다.
- 남은 사본은 원서버 헤더의 max-age + stale 시간 안에 만료된다(가장 긴 것은 marketplace.json). 급하면 Custom Purge로 해당 URL을 지운다.

## 5. 세 번째 변경 (2026-11-16 15:44, PM 실행): 고객 로그인 페이지
- 근거: 11-16 낮 배포(46aa1389 + 4507567f)부터 `/customer/sign-in`은 누구에게나 같은 바이트다(nonce 없음, 인라인 스크립트는 sha256 CSP, GET에 Set-Cookie 없음). 원서버는 `Cache-Control: public, max-age=300`을 주는데 엣지 규칙에 경로가 없어 `cf-cache-status: DYNAMIC`이었다.
- 바꾼 것: `Public insights (11-13)`의 경로 집합에 `"/customer/sign-in"` 하나를 더했다. 식은 892자에서 912자가 됐다. 규칙 수(4개)·동작·순서는 그대로다.
- 넣지 않은 것: `/customer/assets/sign-in.<해시>.css`는 확장자 기본 캐시로 이미 남는다(`immutable`, 확인 때 MISS 뒤 보관). 옛 주소 이동(`/new/en/sign-in.html` 등)의 엣지 리디렉션 규칙은 이번에 만들지 않았다.
- 확인(15:45, 공개 주소·새 연결, 한국에서 측정): 첫 요청 MISS 3.26초, 두 번째 HIT 0.80초(age 5). `Cookie`가 있는 요청은 DYNAMIC. `?next=`가 붙은 주소는 주소별로 따로 남는다(첫 요청 MISS, 200). 응답에 Set-Cookie 없음.
- 이 변경만 되돌리려면 2절의 "지금 식(892자)"을 넣는다.
