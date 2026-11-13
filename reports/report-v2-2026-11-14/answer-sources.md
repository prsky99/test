# 32개 역할의 정답 출처 (2026-11-14 05:0x 갱신, 검색과 RAG)

PM 데이터 품질 결정: 정답 출처가 없는 역할은 정확성 0점이라 검증 진주(85점)가 될 수 없습니다.

| 역할 | 정답 출처 |
|---|---|
| airport.lookup.v1 | 검색과 RAG 정답 2건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| book.search.v1 | 검색과 RAG 정답 2건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| company.registry.v1 | 워크플로우 정답 2건 |
| country.indicator.v1 | 워크플로우 정답 3건 |
| crypto.price.v1 | 같은 시각 공개 기준값(±2%) |
| cve.exploited.v1 | 워크플로우 정답 3건 |
| cve.record.v1 | 워크플로우 정답 3건 |
| dictionary.define.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| domain.lookup.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| earthquake.feed.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) + 같은 시각 기준값(usgs_places) |
| encyclopedia.summary.v1 | 워크플로우 정답 2건 |
| events.search.v1 | 워크플로우 정답 2건 |
| fx.rate.v1 | 워크플로우 정답 2건 + 실시간 기준값(rate) |
| geocode.address.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| github.repo.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| holiday.calendar.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| ip.lookup.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| news.search.v1 | 워크플로우 정답 2건 |
| package.advisories.v1 | 워크플로우 정답 3건 |
| package.health.v1 | 워크플로우 정답 2건 + 실시간 기준값(latest_version) |
| package.risk.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) + 같은 시각 기준값(scorecard) |
| papers.search.v1 | 워크플로우 정답 3건 |
| place.search.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| sec.filings.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| software.incident.v1 | 워크플로우 정답 2건 |
| stock.quote.v1 | 같은 시각 공개 기준값(±2%) |
| timezone.time.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) + 같은 시각 기준값(clock_tz) |
| translate.text.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| unit.convert.v1 | 검색과 RAG 정답 1건(공개 원천 자동 대조, 워크플로우 표본 검토 20%) |
| weather.forecast.v1 | 워크플로우 정답 2건 + 실시간 기준값(temperature_c) |
| web.grounding.v1 | 워크플로우 정답 2건 |
| website.ai_readiness.v1 | 워크플로우 정답 2건 |

- 정답 출처 없음: 0개
- 검색과 RAG 정답은 scripts/build_rag_role_tasks.py가 만들 때 공개 원천에서 정답을 다시 받아 대조하고, 대조에 실패한 과제는 쓰지 않습니다.

## 기준값 원천의 이용 조건 (11-14 05:5x, PM 지시)

PM 지시에 따라 상업 이용이 허용되는 원천만 판정에 씁니다. 확인되지 않은 원천은 판정을 멈춥니다(정확성 0점).

**시험할 때 쓰는 원천(같은 시각 기준값)**

| 원천 | 쓰는 역할 | 이용 조건 | 판정 |
|---|---|---|---|
| ~~Open-Meteo~~ | weather.forecast | 무료판은 비상업 전용 | **뺌.** MET Norway로 바꿈 |
| MET Norway Locationforecast | weather.forecast | CC BY 4.0과 NLOD, 상업 이용 가능(PM 확인) | 사용 |
| Frankfurter(ECB 기준 환율) | fx.rate | 공식 FAQ에 "상업 이용 가능"이라고 명시, MIT 코드 | 사용 |
| npm 레지스트리 `/latest` | package.health | 공개 레지스트리 읽기. 약관의 상업 이용 문구는 미확인 | 사용 |
| USGS 지진 피드 | earthquake.feed | 미국 정부 공공 영역 | 사용 |
| IANA tz(zoneinfo) | timezone.time | 공공 영역. 외부 호출 없음 | 사용 |
| OpenSSF Scorecard API | package.risk | 데이터 CDLA-Permissive-2.0 | 사용 |
| ~~Coinbase 현물가~~ | crypto.price | Coinbase App API 약관의 상업 재사용 문구 미확인 | **중지**(확인 전 정확성 0) |
| ~~Yahoo 차트~~ | stock.quote | 비공식 주소, 개인 용도로 안내됨 | **중지**(대체 원천을 찾을 때까지 정확성 0) |

- MET Norway 조건
  - User-Agent에 연락처(`contact@agentconcierge.biz`)를 넣습니다.
  - 좌표는 소수 4자리로 맞추고, 같은 지점은 10분 캐시로 Expires 전에 다시 받지 않습니다.
  - 역할 시험은 하루 120건 이하라 초당 20회와는 거리가 멉니다.
- 자기 채점 방지: 답에 MET Norway(api.met.no) 출처가 보이면 MET Norway로 채점하지 않습니다. "not checked"로 남기고, 정확성 점수는 주지 않습니다.
- 서울·베를린은 미국 밖이라 NWS로 대신 채점할 수 없습니다.

**과제를 만들 때 한 번만 쓰는 원천(정답 확인용, 원천마다 1회 호출)**
- 정답은 사실 값(공항 이름, 저자, 날짜 등)이라 원천의 글을 옮기지 않습니다.
- 원천과 이용 조건
  - Wikipedia·Wiktionary: CC BY-SA
  - Open Library: Internet Archive 공개 API
  - Free Dictionary API: Wiktionary 기반
  - rdap.org·ARIN RDAP: 공개 등록 정보 조회, 대량 조회 금지 조항 있음. 1회만 호출
  - OpenStreetMap Nominatim: ODbL. 사용 정책상 초당 1회, 대량 금지. 1회만 호출
  - GitHub REST: GitHub 약관상 API 사용 허용
  - Nager.Date: 공개 API
  - SEC EDGAR: 미국 정부 공개 자료, 연락처 User-Agent
