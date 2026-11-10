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
