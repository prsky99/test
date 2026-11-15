# 목걸이 외부 멤버 약관 확인 1차 (에이전트 팀, 2026-11-15)

PM 12:28 지시를 따랐습니다. 11-17 관문 후보 3개(quakes-near-address, book-author-brief, website-trust-brief)와 company-due-diligence의 외부 멤버 8개를 먼저 봤습니다.

## 확인 방법

- 제공자 홈페이지에서 약관 링크를 찾고 그 페이지를 읽었습니다. 링크가 없으면 `/terms`와 공개 문서 페이지를 읽었습니다.
- 모두 읽기 전용 GET이고, 공용 장부 'adhoc' 몫 안(도메인당 2번)입니다. 제공자에게 문의나 연락은 하지 않았습니다.
- 남의 약관 문장은 옮기지 않고, 근거 위치(조항·문단 이름)만 `basis`에 적었습니다. 읽은 원문은 팀 scratchpad에만 두었습니다.
- 판정 기준(PM)
  - `allowed`: 자동 호출이나 재사용을 허용하거나, 공개 API라고 밝힘
  - `silent`: 약관에 그에 대한 말이 없거나, 약관 페이지가 없음을 확인함
  - `prohibits`: 자동 호출, 상업적 재사용, 중계를 금지함. 애매하면 이쪽으로 둡니다.

## 결과

| 멤버 | 목걸이·자리 | 판정 | 근거 |
|---|---|---|---|
| 37322 Datakoot 날씨·지리 | quakes-near-address location·quakes | allowed | datakoot.com/terms 3절 Acceptable use: 요금제 한도 안의 에이전트 자동 접근을 환영함, 경쟁 데이터셋으로 재판매 금지 |
| 264482 DMV Transit | quakes-near-address location | allowed | dmvtransit.com/mcp-server Limits: 모든 MCP 앱용 키 없는 공개 서버, 망당 분당 120·하루 3,000 |
| 52559 Presend | website-trust-brief registration, company-due-diligence domain | allowed | presend.pages.dev/api: 키·가입 없는 무료 공개 엔드포인트, 공정 사용, 과도한 자동 호출은 속도가 제한될 수 있음 |
| 38608 Invokera Book Search | book-author-brief book | silent | 홈페이지에 약관 링크가 없고 /terms는 404(11-15). Open Library API를 가져다 올린 것이라 데이터에는 Open Library 조건이 적용됨 |
| 178542 A.U.G.U.R Foresight | quakes-near-address quakes | silent | 홈페이지에 약관 링크가 없고 /terms는 404(11-15). 지진 자료는 USGS 공공 영역 |
| 241601 web2mcp | book-author-brief author, company-due-diligence background | silent | 개인 workers.dev 주소의 시연 서버라 약관 페이지가 없음. 코드는 MIT. 돌려주는 Wikipedia 글은 CC BY-SA 4.0이라 출처 표시가 필요 |
| 58997 filings.tools | company-due-diligence filings | **prohibits** | filings.tools/terms의 무료 사용 문단: 무료 도구·키 없는 API·무료 키는 운영 환경, 팀, 사업에 쓸 수 없고 유료 플랜이 필요함(지출 0이라 불가) |
| 132732 xfix | website-trust-brief crawlers | **prohibits** | xfix.ai/terms의 What you may not do: 이 서비스로 경쟁하는 감사 제품을 만들거나 보고서를 재게시하는 것을 금지. 사이트 신뢰 목걸이가 여기에 걸린다고 봄(애매하면 prohibits) |

allowed와 silent 6개는 정의 파일의 멤버 `terms`에 넣었습니다(같은 커밋).

## 워크플로우가 정할 것(prohibits 2건)

prohibits 2건은 정의에 넣지 않았습니다. 넣으면 그 멤버가 모든 사슬에서 빠집니다(watch.runtime_chain). 그 결과가 아래처럼 정의 구조를 바꾸기 때문에 워크플로우가 정하고 반영합니다.

- **company-due-diligence filings 자리**: 멤버가 58997 하나뿐이라 자리가 비게 됩니다.
  - 정할 것: 다른 멤버로 바꿀지, 자리를 선택으로 돌릴지, 이 자리를 뺄지.
  - 참고: 자체 대체 sec-edgar는 registry 자리에서 회사 식별자만 돌려주고, 공시 목록은 주지 않습니다.
- **website-trust-brief crawlers 자리**: 132732가 빠지면 자체 대체 site-readiness가 선두가 됩니다.
- 영향받는 시험(그대로 두면 실패): tests/test_necklace_gate_check.py 3개, tests/test_necklace_website_trust_brief.py::test_run_sends_the_url_and_the_domain. 둘 다 이 두 멤버가 실행된다고 가정합니다.
- 넣을 값

```json
{"58997": {"status": "prohibits", "source": "https://filings.tools/terms", "checked_at": "2026-11-15",
           "basis": "paragraph on free use: the free tool, the API without a key and a free key may not be used in production, for a team or for a business; that needs a paid plan"},
 "132732": {"status": "prohibits", "source": "https://xfix.ai/terms/", "checked_at": "2026-11-15",
            "basis": "section What you may not do: using the service to build a competing audit product and republishing reports; a site-trust necklace is close enough to count (PM rule: unclear means prohibits)"}}
```

## PM 12:46 결정 반영

- prohibits 2건은 멤버에서 뺍니다(정의 반영은 워크플로우). 유료 플랜이 있어야 사업용으로 쓸 수 있는 곳은 지출 0이라 모두 prohibits입니다.
- website-trust-brief의 crawlers 자리는 자체 site-readiness가 선두입니다.
- company-due-diligence의 filings 자리는 필수로 둡니다. 멤버는 SEC EDGAR를 직접 읽는 자체 대체 `sec-filings`(list_sec_filings, 계약 sec.filings.v1)로 채웁니다.

### SEC EDGAR 판정: allowed (11-15 확인)

| 읽은 페이지 | 근거 위치 | 내용 |
|---|---|---|
| https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data (`/os/accessing-edgar-data`가 이 주소로 넘어감) | "Fair access" 문단 | 최대 초당 10회, 필요한 것만 받기, User-Agent에 회사 이름과 연락 메일을 밝히기. 밝히지 않은 봇이나 정책 밖의 자동 도구는 제한함 |
| https://www.sec.gov/about/privacy-information | 사이트 보안 문단과 배포 문단 | 초당 10회를 넘으면 그 IP를 잠시 제한함. sec.gov의 정보는 공개 정보라 SEC 허가 없이 복사·재배포할 수 있음(SEC 출처 표시를 권함) |

- 우리 쪽 준수
  - User-Agent `AgentValCon-FallbackAgents/1.0 (+https://agentconcierge.biz; contact@agentconcierge.biz)`(catalog.USER_AGENT)
  - 호스트당 초당 5회 이하(HostLimiter, 프로세스 사이 공용)
  - 회사 하나에 2번 요청(submissions, companyfacts), 1시간 캐시
  - 시험·보고서 호출은 장부의 sec.gov 600 안(substitute_tests 30)에서 씁니다.
  - 응답의 source에 SEC EDGAR를 적고, 카탈로그 고지에 "Not endorsed by the SEC"를 둡니다.
- 출력: 최근 공시 목록(형식·날짜·접수 번호), 그리고 최신 연차 보고서(10-K·20-F·40-F)의 매출·순이익·총자산입니다. 이 값은 XBRL companyfacts에서 제출자가 보고한 값 그대로 가져옵니다.
- EDGAR 전문 검색(efts)은 쓰지 않습니다. 회사 하나의 공시 목록과 연차 사실이면 실사 자리에 충분하고, 요청 수를 늘리지 않기 위해서입니다.

### sec-filings 확장과 실제 호출 (11-15 13:4x)

- PM 12:55 조건 반영
  - 회사는 CIK → ticker → 정확히 일치하는 이름 순서로 찾습니다. 비슷한 이름은 추측하지 않습니다.
  - 답 첫머리에 "Matched SEC filer: 정식 이름 (SEC CIK n), by …"를 적습니다. 합성 단계가 registry 답과 대조할 수 있습니다.
  - SEC 등록이 없는 회사에는 "No SEC EDGAR registration matches …"를 정상 답으로 돌려줍니다. 오류로 세지 않습니다.
  - XBRL 값마다 회계 기준(US GAAP/IFRS)과 개념 이름, 통화를 적습니다. 연차 보고서 형식, 회계연도 끝, 제출일, companyfacts 주소도 적습니다. 그 해에 없는 값은 "not reported for that year"로 두고 지어내지 않습니다.
- 실제 호출: 공용 장부 sec.gov의 substitute_tests 몫에 예약하고 8번 불렀습니다.
  - MSFT: 10-K, FY 2026-06-30, 매출 USD 331.8 billion, 순이익 133.7 billion, 총자산 758.4 billion, 0.8초
  - SAP: 20-F IFRS, FY 2025-12-31, 매출 EUR 36.8 billion, 순이익 7.3 billion, 총자산 70.4 billion, 0.8초
  - Allianz SE: SEC 등록 없음(정상 답)
  - 첫 실행에서 MSFT 매출이 비었습니다. 쓰지 않게 된 개념(Revenues)의 옛 연도에서 멈췄기 때문입니다. 개념 전체에서 최신 연도를 고르도록 고친 뒤 다시 확인했습니다.
- 워크플로우가 filings 자리에 넣을 멤버(58997 자리 대신)

```json
{"kind": "agentcon", "agent_id": "sec-filings", "resource_id": null, "tool": "list_sec_filings",
 "registrable_domain": "agentconcierge.biz", "upstream": ["sec-edgar"], "read_only_hint": true,
 "destructive_hint": false, "idempotent_hint": true, "resend_safe": true, "state": "planned",
 "input_map": {"cik": "{{slot.registry.cik}}", "ticker": "{{slot.registry.ticker}}",
               "company": "{{slot.registry.legal_name}}"},
 "coverage": {"country": ["US"]}}
```

## PM 13:42 과제 세 가지의 원천 판정 (11-15)

| 과제 | 원천 | 판정 | 근거 위치 | 조건 |
|---|---|---|---|---|
| 1 좌표 → 시간대 | timezone-boundary-builder 경계 자료(github.com/evansiroky/timezone-boundary-builder README "Licenses") | allowed | 코드는 MIT, 내보낸 자료는 ODbL 1.0 | 답에 "time zone boundaries © timezone-boundary-builder / OpenStreetMap contributors, ODbL" 표시 |
| 1 계산 라이브러리 | timezonefinder(pypi.org/project/timezonefinder) | allowed | MIT | 의존성 추가는 PM 승인 대상(아래) |
| 2 ip.lookup | DB-IP IP to City Lite(db-ip.com/db/lite.php, /db/download/ip-to-city-lite) | allowed | "licensed under a Creative Commons Attribution 4.0 International License", 앱에서 쓸 수 있고 DB-IP.com 출처 표시가 조건 | 출처 표시. Lite에는 시간대 칸이 없어 시간대는 과제 1에 기댐. 월 1회 갱신. 내려받기 약관(db-ip.com/tos.php)은 11-16에 읽음(오늘 도메인 몫 다 씀) |
| 3 일반 뉴스 | GDELT(gdeltproject.org/about.html "Terms of use", "Redistributing GDELT") | allowed | 모든 데이터셋은 학술·상업·정부 용도에 제한 없이 쓸 수 있고, 재배포·재게시할 수 있음 | 쓸 때마다 GDELT Project 인용과 gdeltproject.org 링크. 기사 본문은 각 언론사 것이라 제목·매체·날짜·URL만 냄 |

### 과제 1의 막힌 점(PM 결정 필요)

- 운영 venv는 Python 3.11.18입니다.
- timezonefinder 최신판 9.2.0은 Python 3.12 이상을 요구합니다.
- 3.11에서 쓸 수 있는 8.1.0은 새 의존성 3개(numpy, h3, flatbuffers)가 필요합니다. 배포 파일도 소스(28MB)뿐이라 설치 때 C 확장을 빌드합니다.
- 선택지
  - (가) 8.1.0과 의존성 3개 추가: 경계에서도 정확합니다. 운영·SRE 잠금 파일 반영이 필요합니다(holidays 때와 같은 절차).
  - (나) 의존성 없이 미리 만든 격자표: 개발 때만 timezonefinder로 0.05° 격자를 만들어 gateway-data에 둡니다(수 MB 예상). 실행 때는 표만 읽습니다. 시간대 경계 근처 수 km는 틀릴 수 있습니다.
  - (다) Python 3.12 전환 뒤 9.2.0: 운영 전체 영향이 커서 이 과제만으로는 권하지 않습니다.
- 권장은 (가)입니다. 승인 전에는 구현을 시작하지 않고 과제 2를 먼저 진행합니다.
- 연결 방식(새 계약 없음): 기존 자체 대체 tz-time(timezone.time.v1)이 `location`에 "위도,경도"를 받으면 시간대를 계산합니다. 그러면 주소·공항 허브의 `{{slot.location.point}}`를 local-time 자리에 그대로 넘길 수 있습니다. airport-lookup 답에도 timezone을 넣어 norm_location이 허브 칸으로 올리게 합니다.

### 과제 1 결과: 좌표 → 시간대 격자표 (PM 13:52 결정 (나), 11-15)

- 만드는 법(운영 밖)
  - 별도 Python 3.12 venv에 timezonefinder 9.2.0(경계 자료 timezonefinder-data 4.2026.6)을 설치합니다.
  - `scripts/build_tz_grid.py build`로 만듭니다(일꾼 4개, 무거운 작업 칸, 103초).
  - 운영 코드는 timezonefinder를 import하지 않고, 결과 파일만 읽습니다(`agent_market/fallback_agents/tz_grid.py`, 의존성 없음).
- 결과 파일: `gateway-data/fallback-agents/tz-grid.bin`(git 밖), **0.8MB**(목표 30MB 이하)
  - 0.02° 격자(약 2km), 1억 6,200만 칸, 시간대 443개
  - 경계 칸 760,506개(**0.47%**), 후보 묶음 2,040개
  - 출처 표기(ODbL, timezone-boundary-builder, OpenStreetMap 기여자, timezonefinder MIT)는 파일 머리와 답의 source에 들어갑니다.
- 정확도(timezonefinder와 대조, `build_tz_grid.py check`)
  - 무작위 10만 점: 정답 99,577, 경계 표시 421(모두 후보에 정답 있음), **단정 오류 2(0.002%)**
    - 30.82,-105.31: Denver를 Ciudad_Juarez로 답함(미국·멕시코 강 국경)
    - 40.05,68.86: Dushanbe를 Tashkent로 답함
    - 둘 다 국경 바로 옆이고, 같은 UTC 차이의 이웃 시간대입니다.
  - OurAirports 대형·중형 공항 5,066곳: 정답 5,043, 경계 표시 23, **단정 오류 0**
    - 공항 나라 코드로 좁히면 23곳 중 17곳이 단정 답이 되고 모두 정답입니다. 6곳은 후보로 남습니다.
- 연결(새 계약 없음)
  - tz-time(timezone.time.v1)이 "위도,경도" 또는 "위도,경도,나라코드"를 받습니다.
  - 경계 칸에서는 후보마다 현지 시각을 담아 답하고 "near a time zone boundary"라고 적습니다. 외부 호출은 없습니다.
  - airport-lookup 답에 `country code XX`와 `time zone Region/City`(경계면 `time zone near a boundary: A or B`)를 고정 표현으로 넣습니다. 워크플로우가 norm_location에서 읽습니다.
- **한계(PM 13:58: 숫자 그대로)**
  - 무작위 10만 점 중 단정 오류는 2건(0.002%)입니다. 둘 다 국경 바로 옆이고 같은 UTC 차이의 이웃 시간대입니다.
  - 경계 칸(0.47%)에서는 시간대를 하나로 정하지 않습니다. 나라 코드가 없으면 후보만 냅니다.
  - 칸 크기는 약 2km입니다. 그보다 작은 섬이나 고립 영토는 놓칠 수 있습니다.
- **다시 만드는 주기**
  - timezonefinder-data(경계 자료)나 tzdata의 새 판이 나올 때 다시 만듭니다. 대개 연 몇 번입니다.
  - 운영 밖 3.12 venv에서 build와 check 두 명령을 돌리고(약 2분, 무거운 작업 칸), 대조 숫자를 이 절에 새로 적습니다.
  - 운영 배포에는 이 파일 하나만 필요합니다. 경로는 FallbackAgents의 data_dir, 즉 `gateway-data/fallback-agents/tz-grid.bin`입니다. 파일이 없으면 tz-time의 좌표 질문은 source_unavailable(목걸이는 다음 멤버로 넘어감)이 되고, airport-lookup은 시간대만 빼고 답합니다.

## 약관 2차 (PM 13:53 ③, 11-15 14:1x): 7곳, member_terms.json에 set-terms로 기록(이력 포함)

| 멤버 | 판정 | 근거 |
|---|---|---|
| 367249 Fixlane | allowed | fixlane.poparecon.com/terms: 무료·공개·읽기 전용 서비스라고 밝힘 |
| 50972 Pipeworx(Brave Search 중계) | **prohibits** | pipeworx.io/terms 허용 사용 조항: 허가 없이 서비스 접근을 재판매·재배포하는 것을 금지함. 라이선스가 걸린 원천은 그 조건이 이용자에게 넘어오고, 계정과 과금이 있음(애매하면 prohibits) |
| 39577 NobleBlocks | silent | 약관은 이용자 글과 연구 윤리만 다루고, 자동 호출이나 답 재사용에 대한 말은 없음 |
| 37259 cve-security.com | silent | 약관 링크 없음, /terms 404. 자료는 공개 CVE·NVD |
| 241082 IPIPAI | silent | 약관 링크 없음, /terms 404. IP 자료의 출처·라이선스를 밝히지 않음 |
| 86011 TidyData | silent | 약관 링크 없음, /terms 404. 공항 자료는 OurAirports(공공 영역) |
| 47189 Wikipedia MCP(caseyjhand) | silent | 호스팅 서버 약관 없음(/terms 404). Wikipedia 글은 CC BY-SA 4.0이라 출처 표시가 필요 |

- 50972는 topic-evidence-brief의 web·news 자리 멤버입니다. 빠지면 그 자리는 자체 대체(wiki-grounding)나 다른 멤버가 선두가 됩니다. 정의 반영은 워크플로우가 합니다.
- 241082(ip 허브 선두)는 silent입니다. 다만 IP 자료의 원천 라이선스를 알 수 없으므로, 자체 ip.lookup(DB-IP Lite, CC BY 4.0)이 생기면 그쪽을 선두로 두기를 권합니다.

## PM 13:53 ④ 판정: 좌표 지진과 geocode (11-15 14:2x)

| 원천 | 판정 | 근거 위치 | 비고 |
|---|---|---|---|
| USGS 지진(earthquake.usgs.gov) | allowed | 미국 정부 자료(usgs.gov/policies-and-notices). FDSN 이벤트 API 안내 머리에 "자동 애플리케이션은 실시간 GeoJSON 피드를 쓰라"고 함 | 기존 usgs-quakes가 이미 피드를 씁니다. 좌표·반경·기간은 받은 피드를 우리 쪽에서 거르면 되므로 호출이 늘지 않습니다. **계약 earthquake.feed.v1 입력에 lat·lon·radius_km·days가 없어(additionalProperties false) 워크플로우의 계약 변경이 먼저입니다** |
| 미국 인구조사국 지오코더(geocoding.geo.census.gov) | allowed | 지오코더 첫 페이지: 대화형과 프로그램(REST) 접근을 제공한다고 밝힘. 정부 공개 자료 | 미국 주소만. 키 없음. 37322 Datakoot의 geocode도 이 원천입니다 |
| OSM Nominatim(operations.osmfoundation.org/policies/nominatim) | **prohibits** | 사용 정책: 플랫폼이 범용 지오코딩·주소 찾기로 제공하는 것 금지, 지오코딩이 주 기능인 서비스의 결과 재판매 금지, 앱의 주기적 요청은 대량 지오코딩으로 보고 강하게 말림, 상업 앱은 다른 제공자를 쓰라고 함 | 만들지 않습니다 |

- 결론: geocode 자체 대체는 미국 주소에 한해 인구조사국 지오코더로 만들 수 있습니다. 미국 밖 주소를 키 없이 허용하는 원천은 찾지 못했습니다. 구현 여부는 PM이 정합니다.

### 나라 경계 격자 (PM 13:58, 11-15 14:4x)

- 원천: Natural Earth 1:10m Admin 0 countries와 disputed areas(공공 영역, naciscdn.org에서 받음, 장부 adhoc 2회). 판정은 allowed입니다(Natural Earth 이용 조건: 공공 영역, 출처 표시는 권장).
- 만드는 법: 운영 밖 3.12 venv(shapely, pyshp)에서 `scripts/build_country_grid.py build`(무거운 작업 칸, 329초)
- 결과: `gateway-data/fallback-agents/country-grid.bin` 0.86MB(git 밖), 나라 240개, 국경 칸 0.54%, 분쟁 칸 0.17%
- 단정하지 않는 곳
  - 분쟁 지역 층의 모든 영역과, ISO 코드가 없는 나라 다각형 13곳(Somaliland, N. Cyprus, Siachen 등)은 관리국과 주장국을 후보로만 둡니다.
  - 국경 2km 안도 후보로만 둡니다.
  - 해안 칸(나라 하나와 바다)은 그 나라로 답합니다. 바다 칸이어도 약 6km 안에 나라가 하나뿐이면 그 나라로 답합니다(Natural Earth 해안선이 거칠어서).
- 대조(`build_country_grid.py check`)
  - 무작위 육지 2만 점(Natural Earth 기준): 정답 19,783, 후보 75(모두 후보에 정답 있음), 분쟁 미단정 142, **단정 오류 0**
  - 대형·중형 공항 5,066곳(OurAirports 나라 코드 기준): 정답 4,948(97.7%), 후보 84, 후보에 없음 20(대부분 프랑스령 폴리네시아·몰디브의 작은 환초), **단정 차이 14**
- 단정 차이 14건은 모두 영토 표기 방식입니다.
  - Natural Earth가 해외 영토를 본국으로 적음: RE·GF·GP·MQ→FR(9건), BQ→NL(3건), CC·CX→AU(2건)
  - Åland는 Natural Earth가 AX로 따로 적음
  - 서사하라 표기의 공항 1곳(MA-0003)은 Natural Earth상 모로코 영역 안에 있음
- **한계**: 해외 영토의 지점은 본국 나라 코드로 답합니다. 그래서 공휴일 목걸이는 본국 공휴일을 냅니다(예: Réunion → 프랑스 공휴일). 더 나누려면 Natural Earth map units 층으로 다시 만들어야 합니다.
- 연결: holiday-calendar가 `country`에 "위도,경도"를 받습니다. 국경·분쟁·바다면 not_found에 후보를 담고, 파일이 없으면 source_unavailable입니다.
- 다시 만들기: Natural Earth 새 판(연 1회 안팎)이 나오면 build와 check를 다시 돌리고 이 절의 숫자를 새로 적습니다.

## PM 16:07 새 목걸이 원천 판정 (11-15 16시)

| 원천 | 판정 | 근거 위치 | 조건과 비고 |
|---|---|---|---|
| npm 공개 레지스트리(registry.npmjs.org) | allowed | docs.npmjs.com/policies/open-source-terms "Use of npm Open Source": 공개 API로 패키지를 검색·내려받기 허용 | "Acceptable Use"와 복제·크롤러 정책 안에서. 자체 대체 package-registry가 이미 씀 |
| PyPI | **판정 전** | policies.python.org의 PyPI 이용 약관이 HTTP 429로 답함(11-15 16시, 장부에 기록) | 11-16에 다시 읽음 |
| GitHub 공개 API(릴리스·이슈, 비로그인) | **조건부 allowed** | docs.github.com GitHub Terms of Service H절 "API Terms": 남용·과도한 요청, 토큰 공유, 개인정보 판매 목적의 수집을 금지. 고처리량이나 GitHub 서비스를 재판매하는 결과가 되는 접근은 유료 구독 대상 | 목걸이 실행이 무료 이벤트인 지금은 허용. **목걸이 실행에 과금이 시작되면 "재판매" 여지가 있어 다시 판정**해야 함(PM 결정 필요). 비로그인 한도는 시간당 60회 |
| 공식 MCP Registry(registry.modelcontextprotocol.io) | allowed | modelcontextprotocol.io/registry/about: 클라이언트와 집계 서비스용 REST API를 공식으로 제공하는 메타데이터 저장소 | 데이터는 CC0. 미리보기 단계라 깨지는 변경이나 데이터 초기화가 있을 수 있음(같은 페이지). 검증 레지스트리(E7)가 이미 씀 |

## arxiv-search 채점 기준 눈 확인 (PM 16:12, 11-15 16시)

- 처음 기준은 "주제어 낱말이 제목에 모두 들어 있음"이었습니다. topic-evidence-brief holdout-r1의 8건을 실제로 돌렸습니다(arXiv, 시험 몫).
- 엉뚱한 통과 1건: "Population ageing"이 "Simulation for competition of languages with an **ageing** sexual **population**"(언어 경쟁 시뮬레이션)으로 통과했습니다. 낱말만 맞고 주제가 다릅니다.
- 억울한 실패 1건: "Income distribution"은 제목이 "The Gompertz-Pareto Income Distribution"처럼 맞는데 실패했습니다. 정답 세트의 paper_phrase가 "income inequality"였기 때문입니다.
- 바꾼 기준
  - 정답 구나 입력 주제가 제목에 **구로 붙어서** 나와야 합니다.
  - 두 낱말 구는 순서가 바뀐 것도 됩니다(ageing population). 하이픈과 복수형 s는 맞춰 줍니다.
  - 흩어진 낱말은 세지 않습니다.
- 바꾼 기준으로 다시 따지면 8건 중 7건 통과입니다. Population ageing은 이제 실패로 남고, Income distribution은 통과합니다. 나머지 6건(Entrepreneurship, Public transport, Populism, Universal basic income, Social capital, Subjective well-being)은 통과한 논문이 모두 주제에 맞습니다.

## 남은 것

- 카탈로그 밖 자체 에이전트 133018·133019·133023(topic-evidence-brief, package-risk-audit)
  - 지금 `model.terms_status`는 agentcon 종류를 자체 대체 카탈로그(SPECS)로만 판정해서, 멤버 `terms`를 넣어도 unknown으로 남습니다. 워크플로우가 이 경우에 멤버 `terms`를 읽도록 바꿔야 합니다.
  - 원천 약관은 R16과 같은 기준으로 공개 차례가 올 때 봅니다.
- 나머지 외부 멤버 23개(cve-incident-brief, package-risk-audit, topic-evidence-brief)도 공개 차례가 올 때 봅니다.
- silent 3개(38608·178542·241601)는 도메인당 하루 읽기 몫을 다 써서 /legal 같은 다른 주소는 아직 못 봤습니다. 다음 날 한 번 더 확인합니다.
