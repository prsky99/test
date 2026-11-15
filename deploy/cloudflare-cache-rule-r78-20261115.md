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

## 2. 넣지 않은 것 (뒤에 할 일)
- `/necklaces/*`: 지금 공개 목걸이가 없어 404·`no-store`다. 넣어도 효과가 없다. 화면이 `Accept` 헤더에 따라 다른 형식을 주는지 확인한 뒤, 첫 공개(11-21) 전에 맞는 규칙에 넣는다. Cloudflare 무료 플랜은 `Vary: Accept`를 캐시 키에 넣지 않는다.
- `/privacy`, `/terms`, `/registry`, `/registry/verified/v0.1/*`: 아직 운영에 없다(404). 배포 뒤 같은 확인을 하고 넣는다.

## 3. 적용 뒤 확인 (11-15 12:41, 공개 주소·새 연결, 한국에서 측정)
- 11개 경로 모두 두 번째 요청이 `cf-cache-status: HIT`. 응답 시간 0.71~0.83초(`/claude-plugins/marketplace.json`만 2.27초).
- `Cookie` 요청과 `Authorization` 요청은 `DYNAMIC`이고 `no-store`다(`/api/pearl/status`로 확인).
- 대시보드 API로 다시 읽은 값: 규칙 4개 모두 enabled, 네 번째 규칙 식 761자.

## 4. 되돌리기
- 같은 화면에서 조건식을 1절의 "바꾸기 전" 식으로 바꾸고 저장한다. 바로 엣지 캐시에서 빠진다.
- 남은 사본은 원서버 헤더의 max-age + stale 시간 안에 만료된다(가장 긴 것은 marketplace.json). 급하면 Custom Purge로 해당 URL을 지운다.
