# 32개 역할의 정답 출처 (2026-11-14, 검색과 RAG)

PM 데이터 품질 결정: 정답 출처가 "없음"인 역할은 정확성 0점이라 검증 진주(85점)가 될 수 없습니다.

| 역할 | 정답 출처 |
|---|---|
| airport.lookup.v1 | 없음 |
| book.search.v1 | 없음 |
| company.registry.v1 | 워크플로우 정답 2건 |
| country.indicator.v1 | 워크플로우 정답 3건 |
| crypto.price.v1 | 공개 기준값(같은 시각, ±2%) |
| cve.exploited.v1 | 워크플로우 정답 3건 |
| cve.record.v1 | 워크플로우 정답 3건 |
| dictionary.define.v1 | 없음 |
| domain.lookup.v1 | 없음 |
| earthquake.feed.v1 | 없음 |
| encyclopedia.summary.v1 | 워크플로우 정답 2건 |
| events.search.v1 | 워크플로우 정답 2건 |
| fx.rate.v1 | 워크플로우 정답 2건 + 실시간 기준값(rate) |
| geocode.address.v1 | 없음 |
| github.repo.v1 | 없음 |
| holiday.calendar.v1 | 없음 |
| ip.lookup.v1 | 없음 |
| news.search.v1 | 워크플로우 정답 2건 |
| package.advisories.v1 | 워크플로우 정답 3건 |
| package.health.v1 | 워크플로우 정답 2건 + 실시간 기준값(latest_version) |
| package.risk.v1 | 없음 |
| papers.search.v1 | 워크플로우 정답 3건 |
| place.search.v1 | 없음 |
| sec.filings.v1 | 없음 |
| software.incident.v1 | 워크플로우 정답 2건 |
| stock.quote.v1 | 공개 기준값(같은 시각, ±2%) |
| timezone.time.v1 | 없음 |
| translate.text.v1 | 없음 |
| unit.convert.v1 | 없음 |
| weather.forecast.v1 | 워크플로우 정답 2건 + 실시간 기준값(temperature_c) |
| web.grounding.v1 | 워크플로우 정답 2건 |
| website.ai_readiness.v1 | 워크플로우 정답 2건 |

- 정답 있음 17개, 없음 15개
- "없음" 역할은 워크플로우와 정답 확보 순서를 정합니다. 모두 공개 원천으로 확인할 수 있는 고정 입력을 골라 두었습니다(scripts/role_catalog.py의 input).
