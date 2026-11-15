# 자체 대체가 없는 자리와 자료 신선도 (에이전트 팀, 2026-11-15)

PM 14:57 지시에 따른 두 가지입니다. 하나는 자체 대체가 없는 필수 자리와 만드는 순서, 다른 하나는 대체마다 원천 갱신 주기와 "자료가 오래됨"을 스스로 알리는 방법입니다. 사용자 지시(11-15)는 모든 목걸이에 폴백과 자체 대체를 붙이고 정기·상시 점검을 빼먹지 않는 것입니다.

## 1. 자체 대체가 없는 자리

- 지금 정의 9개의 필수 자리 20개는 모두 자체 대체가 하나 이상 있습니다(11-15 15시 `necklaces.model` 기준).
- 역할 32개 전체를 기준으로 보면 자체 대체가 없는 역할은 4개입니다.

| 역할 | 쓸 수 있는 공개 원천 | 판정 | 순서 | 원천이 없을 때 |
|---|---|---|---|---|
| ip.lookup.v1 | DB-IP City Lite(CC BY 4.0) + 시간대 격자 | allowed(d6f07f6e). 내려받기 약관 tos.php는 11-16에 확인 | 1(11-16) | 해당 없음 |
| translate.text.v1 | MyMemory(익명 하루 5,000자, 이메일을 주면 50,000자), Apertium 공개 APy(apertium.org/apy, 공개된 언어 쌍만) | **판정 전**: MyMemory의 별도 약관과 Apertium 공개 인스턴스의 이용 정책을 아직 못 읽음(11-16) | 2 | 약관이 막으면 외부 대체 2개 이상 |
| crypto.price.v1 | 상업 재배포를 허용하는 무료 원천 없음(11-14 조사 roles-32-survey) | 만들지 않음(PM 결정 ③, model.NO_FALLBACK_ROLES) | — | **외부 대체 2개 이상**(워크플로우·검색과 RAG) |
| stock.quote.v1 | 같은 이유로 없음 | 만들지 않음(같은 결정) | — | **외부 대체 2개 이상** |

- crypto.price와 stock.quote는 선택 자리로만 쓰고, 외부 진주를 2개 이상 사슬에 두는 것으로 워크플로우와 검색과 RAG에 넘깁니다(현황판).

## 2. 자료 신선도: 스스로 알리는 방법

- **응답마다**: 자체 대체 답 봉투에 `freshness {data_as_of, age_seconds, max_age_seconds}`가 있습니다.
  - 나이가 상한(MAX_AGE)을 넘으면 답 대신 `stale` 오류를 내고, 목걸이는 다음 멤버로 넘어갑니다.
  - 미리 만든 자료(격자 등)는 이제 **만든 날짜를 나이로 씁니다**. 그래서 오래된 격자도 나이 0으로 숨지 않습니다(이 커밋).
    - tz-time: data_as_of에 "time zone grid built"
    - airport-lookup: 시간대가 붙으면 같은 키
    - holiday-calendar: 좌표 입력이면 "country grid built"를 넣고, 나이도 그 날짜 기준입니다.
- **파일마다**: 미리 받거나 만든 자료는 아무도 묻지 않으면 조용히 낡습니다. 그래서 다음 명령이 파일마다 자기 날짜·나이·상한·갱신 방법을 JSON 한 줄씩 냅니다. 하나라도 상한을 넘거나 파일이 없으면 종료 코드가 1입니다. 운영·SRE의 점검 누락 경보가 이것을 읽습니다.

```bash
.venv/bin/python -m agent_market.fallback_agents.freshness
```

| 파일 | 읽는 대체 | 날짜 근거 | 상한 | 갱신 |
|---|---|---|---|---|
| airports.json | airport-lookup | fetched_at | 8일 | jobs `fallback_agents.airports --sync` 매일 |
| kev-catalog.json | cisa-kev | 파일 시각 | 1일 | cisa-kev가 스스로(1시간 캐시) |
| nvd-cve.sqlite3 | nvd-cve, software-incident | 파일 시각 | 2일 | jobs NVD 갱신 |
| tz-grid.bin | tz-time, airport-lookup | 머리의 built | 400일 | 운영 밖 `scripts/build_tz_grid.py`(경계 자료·tzdata 새 판) |
| country-grid.bin | holiday-calendar | 머리의 built | 400일 | 운영 밖 `scripts/build_country_grid.py`(Natural Earth 새 판) |

- 11-15 15시 실행: 다섯 파일 모두 상한 안(airports 0.19일, kev 0.21일, nvd 0.02일, 두 격자 0.04일 이하), 종료 코드 0

### 원천별 갱신 주기와 우리 상한(MAX_AGE, 답의 나이)

| 원천 묶음 | 대체 | 원천 갱신 | 우리 캐시 | 상한 |
|---|---|---|---|---|
| NVD, GitHub Advisory, npm | nvd-cve, software-incident, github-advisory, package-registry | 수시 | 1~6시간 | 6시간 |
| CVE.org, CISA KEV, deps.dev, GLEIF, SEC, Wikipedia, World Bank, Scorecard, GitHub, 사이트 파일 | cve-org, cisa-kev, depsdev-package, gleif-lei, sec-edgar, sec-filings, wikipedia-summary, wiki-grounding, worldbank-indicator, scorecard, github-repo, site-readiness | 매일 또는 수시 | 1~6시간 | 1일 |
| arXiv | arxiv-search | 매일 | 24시간 | 2일 |
| MET Norway | met-weather | 1시간 | — | 3시간 |
| USGS 실시간 피드 | usgs-quakes | 1분 | 5분 | 1시간 |
| ECB 기준 환율 | ecb-fx | 영업일 하루 1번 | 1시간 | 26시간(+ 5일 넘은 날짜면 stale) |
| GDELT | gdelt-news | 15분 | 1시간 | 6시간 |
| Wikidata, Wiktionary, RDAP | wikidata-place, wikidata-book, wiktionary-define, rdap-domain | 수시 | 6~24시간 | 7일 |
| OurAirports | airport-lookup | 매일 | 매일 동기화 | 8일 |
| 인구조사국 지오코더 | census-geocode | 분기(benchmark) | 7일 | 30일 |
| python-holidays, IANA tz, NIST 단위 | holiday-calendar, public-holidays, tz-time, unit-convert | 라이브러리·데이터 판 | 판 고정 | 400일(단위는 10년) |
| 시간대·나라 격자 | tz-time, airport-lookup, holiday-calendar | 경계 자료 연 몇 번 | 미리 만든 파일 | 400일 |

- 라이브러리·데이터 판 묶음(holidays, tzdata)은 운영 잠금 파일의 판을 올릴 때 바뀝니다. 400일 상한은 "적어도 1년에 한 번은 판을 올린다"는 뜻입니다.
