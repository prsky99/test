# Cloudflare 캐시 규칙: 공개 HTML 60초 (2026-11-11, 성장·유통)

- 근거: PM 결정 A. 첫 방문 FCP의 대부분이 HTML 첫 바이트 1.0~1.5초(한국→LAX→터널→원서버)였다. 원서버 안 HTML 응답은 0.02~0.25초(내부 수치)다.
- 사용자 승인: 11-11 "캐시 규칙 승인"(PM 경유). 이 규칙 한 건에만 해당한다.
- 비용: 0(무료 플랜 Cache Rules 10개 안).

## 1. 먼저 나가 있어야 하는 코드
공개 페이지가 방문자마다 같은 바이트여야 한다.
- 커밋: 성장·유통 "public HTML hashes" 커밋.
- 시험: `tests/test_public_page_cache.py`

| 항목 | 내용 |
|---|---|
| CSP | 응답마다 바뀌던 nonce 대신 인라인 스크립트의 sha256 해시를 쓰고, 파일은 'self'로 허용한다 |
| 공개 페이지 헤더 | `/`, `index`·`explore`·`chat`·`test`·`learn`·`workflows`·`list-agent`·`about`·`agent-status`: `Cache-Control: public, max-age=0, s-maxage=60` |
| 그 밖의 `/new/en/*.html` | 정책·디자인 예시·로그인·계정 화면: `no-store` 그대로. 원서버 헤더를 따르므로 엣지에 저장되지 않는다 |
| Set-Cookie | 이 헤더가 붙은 응답은 `public`이 될 수 없다(`SharedCacheCookieGuard` + 보안 헤더 단계) |
| 사용자별 값 | 로그인·쿠키 동의 상태·방문자 토큰이 HTML에 없다. 쿠키·토큰이 다른 4가지 방문자가 같은 바이트를 받는다 |

## 2. 규칙 (Caching → Cache Rules → Create rule, 3번)
- 이름: `Public HTML 60s (11-11)`
- 조건(식 편집기):

```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"}
 and (http.request.uri.path eq "/"
      or http.request.uri.path in {"/new/en/index.html" "/new/en/explore.html" "/new/en/chat.html" "/new/en/test.html"
                                   "/new/en/learn.html" "/new/en/workflows.html" "/new/en/list-agent.html"
                                   "/new/en/about.html" "/new/en/agent-status.html"})
 and http.cookie eq ""
 and any(lower(http.request.headers["accept"][*])[*] contains "text/html")
 and not any(lower(http.request.headers["accept"][*])[*] contains "text/markdown")
 and not any(lower(http.request.headers["accept"][*])[*] contains "application/json"))
```

- 동작
  - Eligible for cache
  - Edge TTL: "Use cache-control header if present"(원서버 s-maxage=60을 따름)
  - Browser TTL: 원서버를 따름(max-age=0, 브라우저는 매번 다시 확인)
  - 캐시 키: 기본값

### 왜 이렇게 좁히는가
- **Accept 조건**: `/`는 같은 주소로 HTML·Markdown·JSON(에이전트용)을 돌려준다(`Vary: Accept`). 무료 플랜은 Vary를 캐시 키에 쓰지 않는다. 그래서 HTML을 원하는 요청만 규칙 대상으로 한다. 대상이 아닌 요청은 캐시를 보지도 않고 원서버로 간다.
- **JSON 조건**: Accept에 application/json이 하나라도 있으면 뺀다. 브라우저 HTML 요청에는 없고, 에이전트는 JSON을 받아야 한다.
- **쿠키 조건**: 쿠키가 하나라도 있으면 우회한다. PM 조건(세션·로그인 쿠키 우회)보다 넓다. 처음 방문자(측정 기준)는 쿠키가 없으니 효과는 그대로다.
- **경로를 하나씩 적음**: `/api/*`, `/mcp`, `/a2a`, `/customer/*`, `/admin*`, 로그인·계정·작업 공간 화면은 처음부터 들어가지 않는다.

## 3. 적용 직후 확인 (공개 주소)
1. `/`와 `/new/en/explore.html`을 쿠키 없이 두 번 받는다. 두 번째가 `cf-cache-status: HIT`여야 한다.
2. `Accept: text/markdown`, `Accept: application/json`으로 `/`를 받는다. `DYNAMIC`이어야 하고, 본문이 각각 Markdown·JSON이어야 한다.
3. 쿠키가 있는 요청(로그인한 브라우저)은 `DYNAMIC`이어야 한다. 로그인 표시는 JS(`/customer/*` API)로 따로 불러온다.
4. 로그인한 브라우저와 하지 않은 브라우저에서 다른 사람의 상태가 보이지 않는지 본다.
5. 첫 바이트와 FCP를 전후로 비교한다(화면당 3회, 표본 제외 없음). 콘솔 CSP 오류가 0인지 본다.

## 4. 되돌리기
- 대시보드에서 3번 규칙을 끄면 바로 원래대로 돌아간다(데이터 변경 없음). 엣지에 남은 사본은 길어야 60초 안에 만료된다.
- 급하면 Caching → Configuration → Purge Everything으로 지운다.
- 코드는 그대로 둬도 된다. 규칙이 없으면 무료 플랜은 확장자 없는 `/`를 캐시하지 않는다. `.html`도 규칙 없이는 기본 캐시 대상이 아니다.
- 문제가 생기면 규칙을 끄고 PM에 보고한다.

## 5. 알려진 영향
- 홈 방문 집계(`record_hit`)와 익명 일일 집계(traffic)는 엣지 HIT 요청을 세지 못한다. 방문 수는 Cloudflare Analytics로 본다.
- 일일 통계 문구는 길어야 60초 늦게 바뀐다.

## 6. 적용 결과 (11-11 오후, 사용자 승인 "캐시 규칙 승인"·PM 경유, 사용자 Chrome)
- 3번 규칙 `Public HTML 60s (11-11)`을 2절의 식 그대로(610자) Eligible for cache, Edge TTL 기본값(원서버 s-maxage=60)으로 추가했다. 1·2번 규칙은 바꾸지 않았다.
- 적용 전 공개 확인(usdc-frontend-20261111-r1): 공개 화면 10개 × 1280·375에서 콘솔·CSP 오류 0, live 화면 `public, max-age=0, s-maxage=60`, privacy `no-store`.

| 확인 | 결과 |
|---|---|
| `/`, explore, chat HTML(쿠키 없음) | 첫 요청 MISS 1.9~4.6초 → 다음 요청 HIT, 첫 바이트 0.74~1.17초(curl, 새 연결) |
| `Accept: text/markdown`·`application/json`으로 `/` | DYNAMIC, 본문 각각 Markdown·JSON(섞이지 않음) |
| 쿠키가 있는 요청 | DYNAMIC(우회). 로그인한 방문자는 캐시본을 받지 않는다. 캐시본에는 사용자 상태가 없다(시험 고정) |

- 첫 방문 전후(화면당 3회, 홈·탐색·Chat·Test·Learn, 표본 제외 없음, 한국→LAX)

| 폭 | 첫 바이트 중앙값 | FCP 중앙값 | FCP 2초 안 |
|---|---|---|---|
| 1280 | 1.17 → 1.30초 | 2.82 → 3.00초 | 5/15 → 3/15 |
| 375 | 1.28 → 0.99초 | 2.02 → 1.98초 | 7/15 → 7/15 |

- 이번 표본에서는 나아지지 않았다. 측정 중 경로 편차가 컸다(첫 바이트 15.9초·7.4초 1회씩).
- HIT여도 새 연결 비용(약 0.46초)과 묶음 CSS 57KB의 꼬리 지연이 남는다. 다음은 PM 결정 B(CSS 줄이기)다.
