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
