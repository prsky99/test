# Cloudflare 캐시 규칙 제안 (2026-11-10, 성장·유통)

PM 요청: 정적 자원·고정 HTML에 무료 Cloudflare Cache Rules를 쓸 수 있는지 조사(캐시 적중률 1.39%).
Cloudflare 설정 변경이라 PM 결정이 필요합니다. 비용은 0입니다(무료 플랜 Cache Rules 10개 안).

## 1. 측정 (11-10 18:1x, 공개 주소, 같은 주소 두 번씩)

| 대상 | 원서버 Cache-Control | cf-cache-status | 판단 |
|---|---|---|---|
| `/new/en/assets/*.js?v=…`, `*.css?v=…` | public, max-age=31536000, immutable | HIT / HIT | 이미 캐시됨 |
| `/new/en/assets/pearl.png`, `?v=` 없는 js | public, max-age=300, swr=86400 | MISS→HIT | 이미 캐시됨 |
| `/llms.txt`, `/robots.txt`, `/sitemap.xml`, `/.well-known/agent-card.json` | public, s-maxage=600 | HIT | 이미 캐시됨 |
| `/`, `/new/en/*.html` | no-store | DYNAMIC | 바꿀 수 없음: 응답마다 CSP nonce가 다름 |
| `/agents/tasks`, `/agents/best`, `/connect`, `/agent/{id}` 등 성장 페이지 | public, max-age=300, swr=600 | **DYNAMIC / DYNAMIC** | **원서버는 허용하는데 Cloudflare가 확장자 없는 HTML이라 캐시하지 않음** (1.0~3.5초) |
| `/api/explore?q=…` | public, max-age=30 | DYNAMIC | 처음 보는 질의가 기준이라 캐시해도 목표 측정에 도움 없음 |

결론: 정적 자원과 텍스트 문서는 이미 캐시되고 있습니다. 1.39%가 낮은 이유는 요청 대부분이 no-store HTML·API·봇의 동적 경로이기 때문입니다.
무료로 바로 늘릴 수 있는 곳은 성장 페이지 하나입니다.

## 2. 제안 규칙 (Caching → Cache Rules → Create rule)

- 이름: `growth pages eligible (11-10)`
- 조건(식 편집기):

```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"}
 and (http.request.uri.path in {"/connect" "/agents/tasks" "/agents/best" "/badges" "/reports/state-of-ai-agents"}
      or starts_with(http.request.uri.path, "/agents/task/")
      or starts_with(http.request.uri.path, "/agents/best/")
      or starts_with(http.request.uri.path, "/agent/")
      or starts_with(http.request.uri.path, "/agents/compare/")
      or starts_with(http.request.uri.path, "/reports/state-of-ai-agents/"))
 and not ends_with(http.request.uri.path, "/reported")
 and not any(lower(http.request.headers["accept"][*])[*] contains "text/markdown"))
```

- 동작: Eligible for cache. Edge TTL은 "Use cache-control header if present"(원서버 300초를 따름). Browser TTL은 원서버를 따름. 캐시 키는 기본값.

### 왜 Markdown 요청을 빼는가
같은 주소가 `Accept: text/markdown`이면 Markdown을 돌려줍니다. 원서버는 `Vary: Accept`를 보내지만, Cloudflare 무료 플랜은 Vary를 캐시 키에 쓰지 않습니다.
그래서 Markdown 요청은 규칙에서 빼서 지금처럼 원서버로 가게 합니다. 이 규칙이 없으면 브라우저에 Markdown이, 에이전트에 HTML이 섞여 나갈 수 있습니다.

### 확인할 것 (적용 뒤 5분)
1. `/agents/tasks`를 두 번 받아 두 번째가 `cf-cache-status: HIT`인지 봅니다.
2. `Accept: text/markdown`으로 같은 주소를 받아 `DYNAMIC`이고 본문이 Markdown인지 봅니다.
3. `/agent/{id}/reported`가 `no-store`, `DYNAMIC`인지 봅니다.

- 되돌리기: 규칙을 끄면 바로 원래대로 돌아갑니다(데이터 변경 없음).
- 위험: 식 편집기가 `starts_with`·`ends_with`·헤더 필드를 무료 플랜에서 받지 않으면 저장 단계에서 거절됩니다(운영 영향 없음).
  그때는 경로 조건을 `http.request.uri.path wildcard "/agent/*"` 형태로 바꿉니다.

## 3. 같이 결정할 것: 엣지 Worker의 `/a2a/` 404

- 공개 `POST /a2a/`(끝에 `/`)는 Cloudflare Worker(`cloudflare/edge-gateway/worker.mjs`)가 직접 404로 답합니다.
- 원인은 Worker가 `/mcp`는 `startsWith`로 원서버에 넘기지만, `/a2a`는 정확히 같은 경로만 넘기기 때문입니다. 원서버(슬롯·Caddy)는 `/a2a/`에 200을 줍니다.
- 수정은 커밋 6c0b0c5c입니다. Worker 시험 89개가 통과했습니다.
- 적용하려면 Worker를 다시 배포해야 합니다(`wrangler deploy`, Cloudflare 변경).

## 4. 적용 결과 (11-11 01시, 사용자 승인 "진행")

- 엣지 Worker: `wrangler deploy`로 버전 b5d704ae를 100% 배포했습니다(6c0b0c5c, 메시지 a2a-trailing-slash-worker-20261111-r1).
  - 확인: 공개 `POST /a2a/` 404 → 200(message), `/a2a` 200, `/mcp/` 200, `POST /chat` 200. 홈·Chat·탐색·`/llms.txt` 200.
  - 되돌리기: `wrangler rollback 2d9e2799-8a5a-4319-b576-fa7aee0a2e1b`
- Cache Rule: 대시보드에 2번 규칙 `Growth pages HTML (11-11)`을 추가했습니다(위 2절의 식, Eligible for cache, Edge TTL은 기본값인 원서버 기준). 1번 규칙(Agent discovery documents)은 바꾸지 않았습니다.

| 확인 | 결과 |
|---|---|
| `/agents/tasks`, `/agents/best`, `/connect`, 실제 에이전트 페이지 | 첫 요청 MISS, 다음 요청부터 HIT |
| 시간(같은 주소 2·3번째 요청) | 전: 0.96~6.8초(DYNAMIC, 한 번 18.7초) → 후: HIT 0.48~1.7초(한 번 5.1초) |
| `Accept: text/markdown` | DYNAMIC, 본문 Markdown 그대로(섞이지 않음) |
| 쿠키가 있는 요청 | 캐시된 공개본(HIT), 로그인 표시 없음. 이 페이지들은 Set-Cookie를 보내지 않음 |
| `/agent/{id}/reported`, 없는 에이전트(404) | no-store, DYNAMIC·BYPASS(캐시 안 됨) |
| 홈 `/` | DYNAMIC(바뀌지 않음, CSP nonce) |

- user_slo의 pages 표본(`/`, chat.html, explore.html)은 이번 규칙 대상이 아닙니다. 그래서 성장 페이지 시간은 위처럼 따로 쟀습니다.
- 공개 측정은 한국→LAX 경유 값입니다.

## 5. 경로 추가 (11-11 01:4x, 사용자 "진행", 맥북 Chrome)

- 2번 규칙 식에 `(http.request.uri.path in {"/openapi.json" "/.well-known/mcp/server-card.json"})`를 OR로 더했습니다. 두 경로는 Markdown 제외 조건과 따로 둡니다.
- 1번 규칙(Agent discovery documents)은 Edge TTL 설정이 없어 기본값, 곧 원서버 Cache-Control을 따릅니다. 바꾸지 않았습니다.
- 확인 결과
  - `/openapi.json`: 200, MISS → HIT (1.01 → 0.48~0.76초), s-maxage=3600
  - `/.well-known/mcp/server-card.json`: 301, MISS → HIT (1.13 → 0.50~0.55초)
  - `/agents/tasks`: HTML은 HIT, Markdown은 DYNAMIC (변화 없음)
- `/skill.md`와 `/.well-known/llms.txt` 추가는 아직 사용자 확인을 받지 않아 넣지 않았습니다.

## 6. 경로 추가 계획: /agents/category/*, /reports/weekly/* (11-11 사용자 "추가 승인", PM 경유, 이번 한 건)
- 순서: 원서버 변경 d5fb6159가 먼저 운영에 나가야 한다. 이 변경으로 두 경로가 public, max-age=300, swr=600, Vary: Accept가 된다. 지금은 no-store라 규칙에 더해도 캐시되지 않는다. 11-12 08:00 이후 묶음 배포 뒤에 적용한다.
- 같은 주소가 Accept에 따라 Markdown을 돌려줄 수 있고, 무료 플랜은 Vary를 캐시 키에 쓰지 않는다. 그래서 공개 HTML 규칙(3번)처럼 "text/html, 쿠키 없음, Markdown·JSON 아님"에만 걸리는 별도 절로 2번 규칙 식에 OR로 더한다. 기존 절은 그대로 둔다.

```
or (http.request.method in {"GET" "HEAD"}
    and (starts_with(http.request.uri.path, "/agents/category/") or starts_with(http.request.uri.path, "/reports/weekly/")
         or http.request.uri.path eq "/reports/weekly")
    and http.cookie eq ""
    and any(lower(http.request.headers["accept"][*])[*] contains "text/html")
    and not any(lower(http.request.headers["accept"][*])[*] contains "text/markdown")
    and not any(lower(http.request.headers["accept"][*])[*] contains "application/json"))
```

- 11-12 08:3x PM: 주간 목록 `/reports/weekly`(끝 슬래시 없음)도 같은 절에 넣는다. 사용자 확인을 한 번에 받기 위해서다. 원서버 쪽 변경(65d9a599)은 다음 묶음에 나가므로, 그 전까지 이 주소는 no-store라 규칙에 걸려도 캐시되지 않는다(Edge TTL이 원서버를 따름).
- 11-12 08:1x 확인: 08시 묶음(414782c6) 배포 뒤 `/agents/category/web_search`·`/reports/weekly/2026-W45`가 public, max-age=300, swr=600을 보내지만 엣지는 DYNAMIC이다(규칙에 경로가 없음).
- 적용 직후 확인: 두 경로에서 처음 보는 주소로
  1. 브라우저형 Accept 두 번 → MISS 다음 HIT, 시간
  2. `Accept: text/markdown` → DYNAMIC, 본문 Markdown
  3. `Accept: application/json` → DYNAMIC
  4. 쿠키 있는 요청 → DYNAMIC
- 되돌리기: 2번 규칙 식에서 위 OR 절을 지운다(기존 절은 그대로). 급하면 Purge Everything. 원서버 헤더는 그대로 둬도 규칙이 없으면 캐시되지 않는다.
