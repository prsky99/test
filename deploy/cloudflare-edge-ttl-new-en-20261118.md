# /new/en 페이지와 로그인 페이지의 엣지 보관 6시간 (성장·유통, PM 11-18 06:40 승인)

## 왜
- 11-17 새벽 이후 전수 점검(2시간마다)의 느린 페이지 46건 중 24건이 엣지 만료 사본의 동기 재검증(EXPIRED·REVALIDATED, 1.0~5.0초)이었다.
- 점검이 늘 같은 `/new/en/*.html`을 보는데, 이 페이지들은 엣지 전용 머리글이 없어 Cache-Control의 300초만 엣지에 남았다. `/customer/sign-in`은 1시간이었다.

## 바뀐 것 (코드 2곳, 정책 해시 파일 아님)
| 곳 | 전 | 후 |
|---|---|---|
| `pearl_view.py` 공개 페이지(live 9개 + 안내 7개)에 `Cloudflare-CDN-Cache-Control` | 없음(엣지 300초) | `public, max-age=21600, stale-while-revalidate=86400` |
| `customer_sign_in_cache.py` `EDGE_CACHE` | 3600 | 21600 |
- 브라우저는 그대로 5분(`Cache-Control`). 쿠키·인증이 있는 안내 페이지 요청은 전처럼 no-store이고 엣지 머리글도 없다.
- 시험: `tests/test_public_page_edge_cache.py`(새), `test_notice_page_cache`·`test_public_html_long_swr`·`test_customer_sign_in_cache`·`test_public_page_cache` 포함 관련 시험 통과.

## 옛 HTML과 새 자원이 섞이면 깨지나
- 엣지 사본 최대 나이는 6시간 + 낡은 사본 허용 1일이다(전에도 SWR이 1일이라 낡은 사본 허용 시간은 같고, 신선 시간만 5분→6시간).
- 옛 HTML이 부르는 `?v=<해시>` 자원은 이미 보관 장치가 있다(`pearl_view.earlier_asset`, 이전 릴리스 8개의 번들·panels.js·정적 파일을 찾아 옛 해시 그대로 준다. `tests/test_earlier_asset_urls.py`). 로그인 페이지는 `gateway-data/services/sign-in-css`에 최근 CSS 16개를 보관한다.
- 한계: 이전 릴리스 8개를 넘겨 배포가 쌓이면(약 30시간 안에 9번 넘는 배포) 가장 오래된 해시는 못 찾고, 그때는 R07대로 오늘 파일을 주되 저장하지 않는다(화면이 깨지는 것은 아니고 옛 HTML에 새 CSS·JS가 붙는다). 이 맥에서는 하루 배포가 서너 번이라 여유가 있다.
- 그래서 배포 때 퍼지가 필수는 아니지만, 화면을 바로 바꿔야 하면(문구·가격 정정 등) 아래 URL을 퍼지한다.

## 퍼지 (무료 플랜은 URL 단위, 실행은 PM)
- 목록: `deploy/cloudflare-purge-urls-new-en.txt`(18개: live 9, 안내 7, 옛 로그인 주소 1, `/customer/sign-in` 1). 한 번에 30개까지 가능하다.
- 배포 절차에 퍼지 단계를 넣는 것은 운영·SRE. 이번 변경이 처음 나가는 배포 직후에는 퍼지가 필요 없다(옛 사본은 300초 규칙으로 만료되고 새 머리글을 받는다).
- `/`(홈)은 이 변경 대상이 아니다.
