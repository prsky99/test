# 32개 역할: 외부 대체 현황과 자체 대체 원천 조사 (에이전트 팀, 2026-11-14 05:5x)

- 외부 멤버 수: `reports/pearls-2026-11-14/role_groups.json`(05:38 생성)과 `exports/pearls/final-2026-11-14.json`을 기준으로 했습니다. 역할 목록은 `scripts/role_catalog.py`(32개)입니다.
- role_groups에는 10개 역할만 들어 있습니다. 나머지 22개 역할은 외부 멤버 시험 기록이 없어 "0"으로 셌습니다.
- 외부 대체 = 역할 1위(주 멤버)를 뺀, 시험에 성공한 외부 멤버 수입니다.
- 이용 조건은 하위 조사에서 각 원천의 약관·문서 페이지를 직접 받아 확인했습니다(11-14). 받지 못한 페이지는 "미확인"으로 적었습니다.
- 우리 서비스는 광고 수익이 있는 상업 서비스로 보고, 키·계정·후원·유료 플랜이 필요한 원천과 "비상업만" 원천은 제외했습니다.

## 1. 첫 목걸이 5개에 쓰이는 역할

| 역할 | 외부 멤버(성공) / 외부 대체 | 자체 대체 상태 | 원천과 상업 이용 | 판정·다음 |
|---|---|---|---|---|
| package.advisories.v1 | 4 / 3 | github-advisory(조정 30/30, 보고서 88) + 기존 133023(OSV) | GHSA: CC BY 4.0 가능. **OSV는 출처별 라이선스가 다르고 Chainguard는 CC-BY-NC-ND**. npm·PyPI 질의에는 Chainguard 기록이 나오지 않지만, 133023 응답에 NC 출처가 섞이지 않는지 점검 필요 | 충분 |
| package.health.v1 | 0 / 0 | package-registry(관문 30/30, 90), depsdev-package(관문 30/30, 90) | npm·PyPI 메타데이터는 가능. **deps.dev는 API가 Google API 약관을 따르고 생성 데이터만 CC BY 4.0이라 판정 "불분명"**. Scorecard 원 API(api.scorecard.dev)는 CDLA-Permissive-2.0으로 상업 이용 명확 | **결정 필요**: depsdev-package의 Scorecard 출처를 api.scorecard.dev로 바꿀지 |
| cve.record.v1 | 시험 기록 없음(정의 멤버 3) | nvd-cve(관문 30/30, 90), cve-org(28/30, 88) | NVD 공공 저작물, CVE 이용 약관 | 충분 |
| cve.exploited.v1 | 2 / 0 | cisa-kev(관문 30/30, 90) | CISA 공공 저작물, EPSS 표기 조건 | 충분. 두 번째 자체 대체는 불필요(원천이 하나뿐) |
| software.incident.v1 | 시험 기록 없음 | 없음 | GitHub Advisory DB(CC BY 4.0)의 패치 버전·참고 링크로 "수정 안내" 가능 | **만들 수 있음**(github-advisory 코드 재사용) |
| company.registry.v1 | 11-15 시험 예정 | gleif-lei, sec-edgar(고정 과제 2/2씩, 정답 세트 대기) | GLEIF CC0, SEC 공공 데이터 | 충분 |
| news.search.v1 | 2 / 0 | 없음(PM 보류) | **GDELT DOC 2.0: "unrestricted use for any academic, commercial…" 인용·링크 필수**. 11-14 실측으로는 첫 호출이 13.7초 뒤 429였음. HN Firebase API는 콘텐츠 약관 불분명 | 상업 조건은 통과. 속도·429 문제로 PM 보류 유지 여부 결정 필요 |
| web.grounding.v1 | 시험 기록 없음 | 없음 | Wikimedia 검색 API: 본문 CC BY-SA, 연락처 User-Agent 필수, 재허락·가용성 보장 불가. DuckDuckGo Instant Answer는 API 약관을 찾지 못함 | **제한적으로 만들 수 있음**(Wikipedia 근거만 인용하는 답, 범위 표기) |
| papers.search.v1 | 4 / 3 | arxiv-search(고정 과제 3/3) + 기존 133019(Crossref) | arXiv 메타데이터 CC0 | 충분 |
| encyclopedia.summary.v1 | 2 / 1 | wikipedia-summary(고정 과제 2/2) | CC BY-SA | 충분 |
| sec.filings.v1 (회사 목걸이 보조) | 시험 기록 없음 | 없음 | SEC EDGAR: 허락 없이 복제·재배포 가능, 초당 10회, User-Agent에 회사명·메일 | **만들 수 있음**(sec-edgar 코드 재사용) |
| package.risk.v1 (패키지 목걸이 보조) | 시험 기록 없음 | 없음 | Scorecard 원 API: CDLA-Permissive-2.0 | **만들 수 있음** |
| website.ai_readiness.v1 (예비 목걸이) | 시험 기록 없음 | 없음 | 사이트의 robots.txt·llms.txt·sitemap 직접 읽기(소량, robots 존중, 사설 주소 차단) | **만들 수 있음** |

## 2. 나머지 역할

| 역할 | 외부 대체 | 원천과 상업 이용 | 판정 |
|---|---|---|---|
| fx.rate.v1 | 4 / 3 | ECB 기준환율 XML: 무료, ECB 출처 표기, 정보 제공용 | 가능(급하지 않음) |
| weather.forecast.v1 | 3 / 1 | met-weather 있음(MET Norway, CC BY 4.0) | 완료 |
| country.indicator.v1 | 4 / 0 | worldbank-indicator 있음(CC BY 4.0). IMF는 PM 결정으로 제외 | 완료 |
| events.search.v1 | 3 / 0 | public-holidays(국가 공휴일 한정) | 완료(범위 한정) |
| holiday.calendar.v1 | 기록 없음 | holiday-calendar(holidays MIT) | 완료 |
| airport.lookup.v1 | 기록 없음 | OurAirports CSV: "All data is released to the Public Domain" | 가능(내려받은 사본으로) |
| dictionary.define.v1 | 기록 없음 | Wiktionary(CC BY-SA 4.0·GFDL). dictionaryapi.dev는 데이터 약관 불분명 | 가능(Wiktionary) |
| domain.lookup.v1 | 기록 없음 | rdap.org(10초에 10회). Verisign RDAP는 합법 목적만, 대량 자동 질의·광고 금지 | 가능(소량·캐시) |
| earthquake.feed.v1 | 기록 없음 | USGS GeoJSON: 미국 공공 저작물, 출처 표기 요청 | 가능 |
| github.repo.v1 | 기록 없음 | GitHub REST: 공개 저장소 합법 접근 허용, 비인증 시간당 60회 | 가능(캐시 필수, 이 맥의 시간당 한도 공유) |
| timezone.time.v1 | 기록 없음 | IANA tzdata(공공 저작물) + Python zoneinfo, 오프라인 | 가능 |
| unit.convert.v1 | 기록 없음 | 외부 원천 불필요(계산) | 가능 |
| book.search.v1 | 기록 없음 | Open Library: API는 "제3자 서비스의 데이터 백엔드용이 아님", 월간 덤프는 가능 | 불분명(덤프로만 가능, 용량 검토 필요) |
| geocode.address.v1, place.search.v1 | 기록 없음 | Nominatim 정책상 "주 기능이 지오코딩이면 자체 서버" → 불가. Photon은 "공정하게 써 달라"만 있음 | 불분명(OSM 데이터 자체 운영은 용량 큼) |
| translate.text.v1 | 기록 없음 | LibreTranslate 공개 서버는 키 필요. MyMemory는 재판매 금지. Argos 자체 실행은 모델 라이선스 미확인 | 불분명 |
| crypto.price.v1 | 기록 없음 | CoinGecko(상업은 유료), Coinbase(제3자 재배포에 서면 동의) 불가. Kraken 약관 미확인 | 원천 없음 |
| ip.lookup.v1 | 기록 없음 | ARIN(상업 서비스 금지), RIPE(재배포 금지), ip-api(비상업) | 원천 없음 |
| stock.quote.v1 | 기록 없음 | 키 없이 상업 이용이 확인되는 원천을 찾지 못함 | 원천 없음 |
| web.grounding 외 news 계열 | — | 위 1절 | — |

## 3. 제안 (PM 결정용)

1. **바로 만들 것(첫 목걸이 보조)**: software.incident(GitHub Advisory), sec.filings(SEC EDGAR), package.risk(Scorecard 원 API). 모두 기존 코드나 같은 원천을 다시 쓰고 상업 조건이 명확합니다.
2. **depsdev-package의 Scorecard 출처를 api.scorecard.dev(CDLA-Permissive-2.0)로 바꾸기**: deps.dev는 이용 조건이 "불분명"으로 나왔습니다. 버전·출시일은 이미 package-registry가 레지스트리에서 직접 줍니다.
3. **133023(기존 자체 OSV) 점검**: 응답에 비상업(NC) 라이선스 출처가 섞이지 않는지 확인하기(검색과 RAG 또는 owned 담당).
4. **news.search**: 상업 조건은 GDELT가 통과하지만 속도·429 문제로 보류 유지 여부를 결정해야 합니다.
5. **원천이 없는 역할(crypto.price, ip.lookup, stock.quote)**: 자체 대체를 만들지 않습니다. 목걸이 설계에서 이 역할을 필수 자리로 두지 않기를 권합니다.

## 4. 재조사 결과 (11-14 06:2x, README 2-16)

- place.search·book.search: Wikidata(CC0)로 만듦(wikidata-place, wikidata-book).
- geocode.address: 전 세계 키 없는 실시간 경로 없음(Nominatim 정책상 불가). 국가 한정 정부 API나 OSM 덤프 자체 설치(약 95GB)만 남음.
- translate.text: 상업 이용이 확인된 키 없는 공개 API 없음. Argos Translate 자체 실행은 모델별 라이선스 확인 뒤 PM 결정.
