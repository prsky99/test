# 검색 콘솔 등록 안내 (Google · Bing · Naver)

사용자 계정으로 진행하는 일입니다. 계정 만들기, 로그인, 약관 동의는 사용자가 합니다.
소유 확인 파일을 둘 자리와 사이트맵은 미리 준비해 두었습니다(11-10).

## 진행 상황 (11-10)
| 콘솔 | 상태 |
|---|---|
| Google Search Console | **등록 완료.** URL 접두어 `https://agentconcierge.biz/`, HTML 파일로 소유 확인, `sitemap.xml` 제출(제출 직후 "가져올 수 없음" 표시, Googlebot UA로 200 확인) |
| Bing Webmaster Tools | **등록 완료.** 수동 추가 + `BingSiteAuth.xml`로 소유 확인, 사이트맵 제출(Processing) |
| Naver 서치어드바이저 | 하지 않음(한국어 검색 노출이 적음, 필요하면 같은 방식) |

확인 파일 두 개(`google…html`, `BingSiteAuth.xml`)는 운영 맥 `logs/service-frontend/public-pages/site-verification/`에 있다. 지우지 않는다.

## 미리 준비된 것

| 항목 | 주소 또는 위치 | 상태 |
|---|---|---|
| 사이트맵 | `https://agentconcierge.biz/sitemap.xml` | 운영 중. 근거 있는 페이지만 들어 있습니다(약 1만 쪽). |
| robots.txt | `https://agentconcierge.biz/robots.txt` | 운영 중. 사이트맵 줄이 있습니다. |
| IndexNow 키 | `https://agentconcierge.biz/<키>.txt` | 운영 중. jobs가 매일 바뀐 페이지만 Bing·Naver 등에 알립니다. |
| 소유 확인 파일 자리 | 운영 맥의 `logs/service-frontend/public-pages/site-verification/` | 11-10 frontend 판부터 제공됩니다. 파일을 넣으면 배포나 재시작 없이 바로 사이트 루트에서 열립니다. |

확인 파일은 각 콘솔이 쓰는 형식과 내용이 정확히 맞을 때만 열립니다. 다른 파일은 그 폴더에 있어도 공개되지 않습니다.

| 콘솔 | 파일 이름 | 파일 내용(그대로) | 공개 주소 |
|---|---|---|---|
| Google | `google<코드>.html` | `google-site-verification: google<코드>.html` | `https://agentconcierge.biz/google<코드>.html` |
| Naver | `naver<코드>.html` | `naver-site-verification: naver<코드>.html` | `https://agentconcierge.biz/naver<코드>.html` |
| Bing | `BingSiteAuth.xml` | Bing이 내려 주는 XML 그대로 | `https://agentconcierge.biz/BingSiteAuth.xml` |

메타 태그 방식은 쓰지 않습니다. 홈 HTML을 고치고 배포해야 하기 때문입니다. 파일 방식이면 됩니다.

## 1. Google Search Console

1. https://search.google.com/search-console 에 사용자 Google 계정으로 로그인합니다.
2. 속성 추가에서 **URL 접두어**를 고르고 `https://agentconcierge.biz/` 를 넣습니다.
   - **도메인** 속성은 DNS TXT 레코드가 필요합니다. DNS 변경은 따로 승인할 일이라 이번에는 쓰지 않습니다.
3. 확인 방법에서 **HTML 파일**을 고르고 파일을 내려받습니다.
4. 받은 파일을 운영 맥의 `logs/service-frontend/public-pages/site-verification/` 에 그대로 넣습니다. 파일 이름과 내용을 바꾸지 않습니다.
5. 브라우저에서 공개 주소가 열리는지 본 뒤 콘솔에서 **확인**을 누릅니다.
6. 왼쪽 메뉴 **Sitemaps**에 `sitemap.xml` 을 넣고 제출합니다.
7. 확인 파일은 지우지 않습니다. Google은 소유권을 주기적으로 다시 확인합니다.

## 2. Bing Webmaster Tools

가장 쉬운 길은 Google Search Console에서 가져오기입니다. 1번을 먼저 끝낸 경우에 씁니다.

1. https://www.bing.com/webmasters 에 사용자 계정(Microsoft, Google, Facebook 중 하나)으로 로그인합니다.
2. **Import from Google Search Console**을 고르고 Google 계정 연결을 허락합니다. 사이트와 사이트맵이 함께 넘어옵니다.

가져오기를 쓰지 않을 때:

1. **Add your site manually**에 `https://agentconcierge.biz/` 를 넣습니다.
2. 확인 방법에서 **XML file**을 고르고 `BingSiteAuth.xml` 을 내려받습니다.
3. 파일을 위와 같은 폴더에 넣고, 공개 주소가 열리는지 본 뒤 **Verify**를 누릅니다.
4. **Sitemaps**에 `https://agentconcierge.biz/sitemap.xml` 을 제출합니다.

IndexNow로 이미 보낸 주소는 Bing 콘솔의 **IndexNow** 메뉴에서 볼 수 있습니다.

## 3. Naver 서치어드바이저

1. https://searchadvisor.naver.com 에 사용자 네이버 계정으로 로그인하고 **웹마스터 도구**로 갑니다.
2. 사이트 등록에 `https://agentconcierge.biz` 를 넣습니다.
3. 소유 확인에서 **HTML 파일 업로드**를 고르고 파일을 내려받습니다.
4. 파일을 위와 같은 폴더에 넣고, 공개 주소가 열리는지 본 뒤 **소유확인**을 누릅니다.
5. **요청 → 사이트맵 제출**에 `https://agentconcierge.biz/sitemap.xml` 을 넣습니다.
6. **검증 → robots.txt**에서 수집이 허용되는지 확인합니다. 지금 설정은 공개 페이지를 모두 허용합니다.

사이트 화면은 영어입니다. 네이버는 한국어 검색 노출이 적을 수 있으니, 처음에는 색인 수만 확인합니다.

## 파일을 넣은 뒤 확인

운영 맥에서 아래처럼 확인합니다. `<파일 이름>`을 실제 이름으로 바꿉니다.

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://agentconcierge.biz/<파일 이름>
```

200이 나오면 콘솔에서 확인 버튼을 누릅니다. 404이면 파일 이름과 내용이 받은 그대로인지, 폴더가 맞는지 확인합니다.

## 등록 뒤 지표 확인 (성장·유통 팀)

- 11-16, 11-23에 Google·Bing·Naver 색인 수, 노출 수, 클릭 수를 적습니다.
- 같은 날 traffic 요약의 AI 봇 요청 수, MCP clientInfo 이름 수, `logs/growth/directory-presence.jsonl` 기록을 함께 봅니다.
- 콘솔 화면 숫자는 사용자 계정에서만 보입니다. 숫자를 팀에 전해 주시면 보고서에 넣습니다.
