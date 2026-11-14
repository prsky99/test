# Cloudflare Cache Rules — 변경 전 상태 (11-14 02:1x, PM이 대시보드에서 읽음)

1. **Agent discovery documents**
   - Hostname equals agentconcierge.biz
   - Request Method equals GET
   - URI Path is in /llms.txt, /llms-full.txt, /robots.txt, /sitemap.xml, /.well-known/agent-card.json, /.well-known/mcp.json, /.well-known/mcp/server.json, /.well-known/security.txt
   - 동작: Eligible for cache

2. **Growth pages HTML (11-11)**: 바꾸지 않음

3. **Public HTML 60s (11-11)**
```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"} and (http.request.uri.path eq "/" or http.request.uri.path in {"/new/en/index.html" "/new/en/explore.html" "/new/en/chat.html" "/new/en/test.html" "/new/en/learn.html" "/new/en/workflows.html" "/new/en/list-agent.html" "/new/en/about.html" "/new/en/agent-status.html"}) and http.cookie eq "" and any(lower(http.request.headers["accept"][*])[*] contains "text/html") and not any(lower(http.request.headers["accept"][*])[*] contains "text/markdown") and not any(lower(http.request.headers["accept"][*])[*] contains "application/json"))
```

되돌리기: 1번과 3번은 위 목록과 식으로 되돌린다. 새로 만든 `Public insights (11-13)`는 Disable 또는 Delete한다.

## 11-14 11:1x 변경 전 (PM, 사용자 "추가 승인")
4. **Public insights (11-13)** — Eligible for cache, Edge TTL 기본값(원서버 cache-control 따름)
```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"} and (http.request.uri.path in {"/api/insights" "/api/feed/verified.json"} or starts_with(http.request.uri.path, "/api/agents/")) and http.cookie eq "" and not any(lower(http.request.headers.names[*])[*] eq "authorization"))
```
변경: 경로 목록에 /advertise, /methodology, /methodology.json, /methodology/changelog, /api/necklaces, /api/feed/necklaces.json, /api/verify, /api/roles, /.well-known/glama.json과 starts_with "/api/roles/"를 더함(쿠키 없음·Authorization 없음 조건은 그대로).
되돌리기: 위 식으로 되돌린다.
