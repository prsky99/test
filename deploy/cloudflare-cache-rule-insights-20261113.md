# Cloudflare 캐시 규칙: /api/insights (2026-11-13, 운영·SRE)

- 근거: 11-13 09:35 배포 뒤 원서버 안 시간은 0.01초(내부 수치)인데, 공개 첫 요청은 1초 안에 든 것이 6표본 중 1개뿐이었다. 응답에는 `public, max-age=30`이 붙어 있지만 엣지는 `DYNAMIC`으로 처리해 매번 원서버까지 간다(한국→미국 엣지→터널→원서버).
- 사용자 승인: 11-13 15:18 "둘 다 진행"(PM 경유). 이 규칙 한 건에만 해당한다.
- 비용: 0. 무료 플랜 Cache Rules 10개 안이다. 이미 있는 규칙: 에이전트 문서, 성장 페이지, 공개 HTML.
- 적용: 대시보드 설정 변경은 사용자가 한다. Claude 세션은 Cloudflare 설정을 바꾸지 않는다.

## 1. 사용자별로 달라지지 않는지 확인 (11-13 15:2x, 공개 주소)
- 처리기 `front.py`의 `api_insights()`는 요청을 받지 않는다. jobs가 5분마다 쓰는 스냅샷 파일(`insights_snapshot.served`)만 돌려준다.
- 본문 해시가 세 경우 모두 `4b1d8b66e2f6`으로 같았다.
  - 쿠키 없음
  - `Cookie: sid=zzz`
  - `Authorization: Bearer x`
- 쿠키나 인증 헤더가 있으면 원서버가 `Cache-Control: no-store`를 보낸다(`public_http_contract._credentials`). 쿠키가 없으면 `public, max-age=30, stale-while-revalidate=30`이다.
- `Set-Cookie`는 없고, `Vary`는 `Accept-Encoding`뿐이다.

## 2. 규칙 (Caching → Cache Rules → Create rule)
- 이름: `Public insights (11-13)`
- 조건(식 편집기):

```
(http.host eq "agentconcierge.biz" and http.request.method in {"GET" "HEAD"}
 and http.request.uri.path eq "/api/insights"
 and http.cookie eq ""
 and not any(lower(http.request.headers.names[*])[*] eq "authorization"))
```

- 저장할 때 식 편집기가 문법 오류를 알려 주면, 마지막 줄(인증 조건)만 빼고 저장한다. 원서버가 인증 헤더가 있는 요청에 `no-store`를 보내고 본문도 같으므로 안전성은 그대로다. 뺐다면 3절 확인 때 알려 준다.

- 동작
  - Cache eligibility: **Eligible for cache**
  - Edge TTL: **Use cache-control header if present**(원서버 값을 따른다). 무료 플랜에서 Edge TTL을 직접 정하면 최소 2시간이라, 5분마다 바뀌는 insights에는 쓰지 않는다.
  - Browser TTL: 원서버를 따른다.
  - 캐시 키: 기본값

### 왜 이렇게 좁히는가
- **쿠키·인증 조건**: 본문은 같지만, 자격 증명이 있는 요청은 처음부터 캐시를 보지 않게 한다(공개 HTML 규칙과 같은 방식). 처음 방문자는 쿠키가 없으니 효과는 그대로다.
- **경로 하나만**: `/api/` 아래 다른 주소는 들어가지 않는다.

## 3. 적용 직후 확인 (운영·SRE, 공개 주소·새 연결)
1. 쿠키 없이 `/api/insights`를 연달아 두 번 받는다. 두 번째가 `cf-cache-status: HIT`여야 한다. 30~60초 안에는 `UPDATING`·`REVALIDATED`일 수 있다.
2. `Cookie`가 있는 요청과 `Authorization`이 있는 요청은 `DYNAMIC`이어야 하고, `Cache-Control: no-store`가 그대로여야 한다.
3. 첫 요청 시간을 새 연결로 잰다(표본 제외 없음, 한국 측정으로 표시). 판정에는 공개 주소 수치만 쓴다.

### 원서버 헤더 (PM 11-13 15:2x 결정, 같은 날 frontend 배포)
- 쿠키·인증 없는 `/api/insights` 응답은 `public, max-age=300, stale-while-revalidate=300`이다. 스냅샷 주기(5분)와 같다(`public_http_contract.SNAPSHOT_CACHE`).
- `s-maxage`는 쓰지 않는다. Cloudflare가 s-maxage를 proxy-revalidate로 읽어 stale 사본을 주지 않기 때문이다(11-12 실측, `max-age`로 엣지 시간을 정한다).
- 쿠키·Authorization 요청은 `no-store` 그대로다(`_credentials`).
- 이 헤더가 배포되기 전에는 원서버가 `max-age=30`만 보내므로, 엣지 사본은 30초(+stale-while-revalidate 30초)만 쓰인다.
- 캐시 키에는 질의 문자열이 들어간다. 측정 때 질의 문자열을 매번 바꾸면 항상 `MISS`가 된다. 실제 화면(`learn` 탭)은 질의 문자열 없이 부른다.

## 4. 되돌리기
- 대시보드 Caching → Cache Rules에서 `Public insights (11-13)` 규칙을 끄거나(Disable) 지우면 바로 원래대로 돌아간다. 데이터 변경은 없다.
- 엣지에 남은 사본은 길어야 10분(max-age 300 + stale 300) 안에 만료된다. 급하면 Caching → Configuration → Custom Purge로 `https://agentconcierge.biz/api/insights`를 지운다.
- 문제가 생기면 규칙을 끄고 PM에 보고한다.
