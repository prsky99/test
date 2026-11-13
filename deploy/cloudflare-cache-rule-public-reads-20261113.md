# Cloudflare 캐시 규칙 경로 추가: /api/agents/{id}, /api/feed/verified.json (2026-11-13, 운영·SRE)

- 근거: 검색과 RAG의 11-13 22:26 측정에서 두 경로의 서버 처리 시간은 80~190ms였다. 그런데 공개 주소에서는 1.3~9.8초가 걸렸다. 응답이 `no-store`라 엣지가 `DYNAMIC`으로 처리해 매번 한국 → 미국 엣지 → 터널 → 원서버를 거쳤다.
- 요청: PM 11-13 22:3x. 사용자 승인은 PM이 고지 화면·sitemap 건과 묶어 받는다. 이 문서는 변경안이다.
- 비용: 0. 새 규칙을 만들지 않고 `Public insights (11-13)` 규칙의 경로 조건만 넓힌다(무료 플랜 Cache Rules 10개 안).
- 적용: 대시보드 변경은 사용자가 한다. Claude 세션은 Cloudflare 설정을 바꾸지 않는다.
- 원서버 쪽: `public_http_contract`가 두 경로에 공개 캐시 헤더를 준다(이 문서와 같은 커밋). 이 헤더가 배포되기 전에 규칙을 넓혀도 원서버가 `no-store`를 보내므로 엣지에 남지 않는다. 순서는 상관없다.

## 1. 원서버 헤더 (쿠키·Authorization 없는 GET/HEAD, 200·304만)
| 경로 | Cache-Control | 근거 |
|---|---|---|
| `/api/agents/{숫자 id}` | `public, max-age=300, stale-while-revalidate=300` | 요청을 읽지 않고 누구에게나 같은 기록이다. 같은 내용의 `/agent/{id}` 화면은 엣지가 이미 1시간 보관한다(GROWTH_CACHE). 헬스·등급은 몇 시간 간격의 점검으로 바뀌므로, 5분(+stale 5분)이면 그보다 훨씬 짧다. |
| `/api/feed/verified.json` (질의 문자열 포함) | `public, max-age=60, stale-while-revalidate=60` | 읽는 쪽이 ETag로 주기적으로 묻는 이벤트 목록이다. 새 이벤트는 최대 2분 늦게 보인다. 응답 속 서명된 `_next_cursor`는 1시간 유효하다. |

- 쿠키나 `Authorization`이 있으면 `no-store`다(`_credentials`, insights와 같음).
- 404·오류 응답은 공개 캐시 헤더를 받지 않는다.
- `/api/agents/` 아래의 숫자가 아닌 경로(예: `/api/agents/42/reported`)는 원서버가 계속 `no-store`를 보낸다.
- `s-maxage`는 쓰지 않는다. Cloudflare가 s-maxage를 proxy-revalidate로 읽어 stale 사본을 주지 않기 때문이다(11-12 실측).

## 2. 규칙 변경 (Caching → Cache Rules → `Public insights (11-13)` → Edit)
조건(식 편집기)을 다음으로 바꾼다. 바뀌는 곳은 경로 줄 하나다.

```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"}
 and (http.request.uri.path in {"/api/insights" "/api/feed/verified.json"}
      or starts_with(http.request.uri.path, "/api/agents/"))
 and http.cookie eq ""
 and not any(lower(http.request.headers.names[*])[*] eq "authorization"))
```

- `/api/agents/{숫자}`만 고르는 정규식(`matches`)은 무료 플랜에서 쓸 수 없어 `starts_with`를 쓴다.
  - 숫자가 아닌 하위 경로는 원서버가 `no-store`를 보낸다. 동작이 "원서버 헤더를 따름"이라 엣지에 남지 않는다.
- insights 규칙을 아직 만들지 않았다면, 처음 만들 때 이 식으로 만든다. 이름은 그대로 `Public insights (11-13)`로 한다. 동작은 `deploy/cloudflare-cache-rule-insights-20261113.md` 2절과 같다.
  - Eligible for cache
  - Edge TTL: Use cache-control header if present
  - Browser TTL: 원서버를 따름
  - 캐시 키 기본값
- 마지막 줄(Authorization 조건)에서 식 편집기가 오류를 내면 그 줄만 빼고 저장한다. 원서버가 그런 요청에 `no-store`를 보내므로 안전성은 같다.

## 3. 적용 뒤 확인 (운영·SRE, 공개 주소·새 연결, 한국 측정 표시)
1. 쿠키 없이 같은 주소를 연달아 두 번 받는다. 두 번째가 `cf-cache-status: HIT`여야 한다(갱신 중이면 `UPDATING`·`REVALIDATED`).
   - 에이전트 상세 `/api/agents/61464`
   - 피드 `/api/feed/verified.json`
2. `Cookie` 요청과 `Authorization` 요청은 `DYNAMIC`이고 `no-store`여야 한다.
3. `/api/agents/999999999`(404)는 HIT가 되지 않아야 한다.
4. 첫 요청 시간을 새 연결로 잰다. 표본은 빼지 않는다.
   - 캐시 키에는 질의 문자열이 들어간다.
   - 측정 때 질의 문자열을 매번 바꾸면 항상 MISS다.

## 4. 되돌리기
- 식의 경로 줄을 `http.request.uri.path eq "/api/insights"`로 되돌리면 두 경로는 바로 엣지 캐시에서 빠진다.
- 남은 사본은 에이전트 상세가 최대 10분, 피드가 최대 2분 안에 만료된다. 급하면 Custom Purge로 해당 URL을 지운다.
- 원서버 헤더를 되돌리려면 `public_http_contract`의 `agent_detail_path`·`FEED_READS` 추가를 되돌린 버전을 배포한다. 정책 해시 파일이 아니라 frontend만 배포하면 된다.
