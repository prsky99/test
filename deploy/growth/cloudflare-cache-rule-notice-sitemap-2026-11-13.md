# Cloudflare 캐시 규칙 변경: 고지 화면 7개와 sitemap 자식 (2026-11-13, 성장·유통)

- 근거: PM 11-13 20:5x 지시 ②③, 보고서 `reports/page-body-time-2026-11-13/README.md`.
  - 고지 화면은 no-store라서 방문마다 LAX→터널→이 맥을 다녀왔다(disclosures 18:31에 6.68초, DYNAMIC).
  - sitemap.xml은 압축 뒤 39KB여서, 엣지 HIT에서도 5~6초가 걸렸다(본문 손실 대기).
- 비용: 0. 새 규칙을 만들지 않고, 있는 규칙 두 개의 경로 목록에 주소를 더한다.
- **승인 필요**: Cloudflare 설정 변경이다. 사용자 승인 뒤에만 사용자 Chrome에서 바꾼다. 이 두 규칙 말고는 건드리지 않는다.

## 1. 먼저 나가 있어야 하는 코드 (frontend 배포)

| 항목 | 내용 | 시험 |
|---|---|---|
| 고지 화면 7개 | accessibility, contact, cookies, disclosures, privacy, service-disclosures, terms. 쿠키·Authorization이 없는 요청에 `public, max-age=300, stale-while-revalidate=86400`(live 화면과 같음, s-maxage 없음). 쿠키나 인증 헤더가 있으면 `no-store`. noindex는 그대로 | `tests/test_notice_page_cache.py` |
| sitemap | `/sitemap.xml`은 색인(sitemapindex, 0.2KB)이다. 자식은 `/sitemaps/pages.xml`과 `/sitemaps/agents-N.xml`(N=1~5, 각 2,000개)이고, 압축 뒤 4.4~7.1KB다. 자식도 `/sitemap.xml`과 같은 `public, max-age=600, stale-while-revalidate=3600`을 쓴다. 쿠키·인증이 있으면 공유 캐시를 쓰지 않는다 | `tests/test_sitemap_parts.py` |

코드만 나가도 /sitemap.xml은 작아져서 바로 빨라진다(이미 1번 규칙 대상). 규칙 변경은 고지 화면과 sitemap 자식을 엣지에 두기 위한 것이다.

## 2. 바꿀 것

### 3번 규칙 `Public HTML 60s (11-11)` (이름은 그대로)
- 경로 목록 `in {...}`에 다음 7개를 더한다. 쿠키·Accept 조건은 그대로 둔다.

```
"/new/en/accessibility.html" "/new/en/contact.html" "/new/en/cookies.html" "/new/en/disclosures.html"
"/new/en/privacy.html" "/new/en/service-disclosures.html" "/new/en/terms.html"
```

### 발견 문서 규칙(경로에 `/sitemap.xml`이 있는 규칙)
- 경로 목록 `in {...}`에 sitemap 자식을 더한다.
- 정규식·함수를 쓰지 않고 주소를 하나씩 적는다. 지금 5개이고, 늘어날 것을 생각해 8개까지 적는다.

```
"/sitemaps/pages.xml" "/sitemaps/agents-1.xml" "/sitemaps/agents-2.xml" "/sitemaps/agents-3.xml"
"/sitemaps/agents-4.xml" "/sitemaps/agents-5.xml" "/sitemaps/agents-6.xml" "/sitemaps/agents-7.xml" "/sitemaps/agents-8.xml"
```

- 바꾸기 전에 대시보드에서 지금 식을 읽어 이 문서에 그대로 붙여 둔다. 문서에 적어 둔 옛 식과 다를 수 있다.

## 3. 적용 직후 확인 (공개 주소, 새 연결)
1. 고지 화면 7개를 쿠키 없이 두 번씩 받는다. 두 번째가 HIT여야 한다. Cache-Control에 s-maxage가 없어야 한다.
2. 쿠키가 있는 요청으로 privacy를 받는다. DYNAMIC이고 `no-store`여야 한다.
3. `/sitemap.xml`과 자식 6개를 두 번씩 받는다. 두 번째가 HIT여야 하고, 색인의 주소 수 합계가 나누기 전과 같아야 한다.
4. 전후 시간은 user_slo와 같은 방식으로 잰다(새 연결, 1초 간격, 표본 제외 없음).

## 4. 되돌리기
- 더한 주소를 두 규칙의 목록에서 지우면 바로 돌아간다(데이터 변경 없음).
- 엣지에 남은 사본은 고지 화면이 길어야 5분, sitemap이 10분 뒤 만료된다. 급하면 해당 주소만 Purge한다.
- 코드는 그대로 둬도 된다. 규칙이 없으면 이 주소들은 엣지에 저장되지 않는다.
