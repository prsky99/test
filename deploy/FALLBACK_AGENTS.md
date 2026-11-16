# 자체 대체 에이전트 (fallback_agents)

목걸이 자리의 마지막 고리로 쓰는 AgentValCon 자체 대체 에이전트의 목록과 운영 규칙이다. 소스 기준으로 2026-11-16에 썼다(개발 브랜치 9a56b929). 표는 코드에서 뽑은 것이므로, 바뀌면 아래 "목록 다시 뽑기"로 다시 만든다.

- 코드: `agent_market/fallback_agents/`
  - `catalog.py`: 정의 `SPECS`, 도구 정의 `tool_spec`
  - `agents.py`: 실행 `FallbackAgents`, `run`, `slot_output`
  - `net.py`: 바깥 호출, 장부와 공개 주소 검사
  - `limits.py`: host 간격
  - `watch.py`: 매시 점검
  - `gold_check.py`: 관문 채점
- 관문과 승인: `deploy/NECKLACE_GATE.md` 10절
- 호출 장부: `deploy/PROVIDER_BUDGET.md`

## 1. 무엇을 하나

- 키 없는 공개 원천을 읽기만 한다. 계정·결제·쓰기가 없다.
- 목걸이 자리는 진주 → 외부 대체 → 자체 대체 순서로 부른다(헌장 0절 대체 원칙).
- runner는 `fallback_agents.run(agent_id, arguments)`로 같은 프로세스 안에서 부르고, 운영의 실행 스위치(`workflow`, `invoke`)가 꺼져 있으면 부르지 않는다(`necklaces/runner.engine_caller`).
- 답(envelope)에 담는 것
  - `result`: 계약의 출력 스키마에 맞는 답
  - `sources`: 원천 이름, 라이선스, 필요한 고지
  - `retrieved_at`
  - `cache`: live, cache, snapshot 중 무엇에서 왔는지와 나이
  - `partial`
  - `freshness`: 원천 자료 시각, 나이, 최대 나이
- 우리 사본이 표의 "최대 나이"보다 오래되면 답하지 않고 `stale` 오류를 낸다. 그러면 자리는 다음 멤버로 넘어간다.
- 입력과 출력은 계약 스키마(`agent_market/necklaces/contracts/<계약>.json`)로 검사한다. 일부 계약은 `CONTRACT_CHECKS`로 의미까지 본다. cve 계열은 같은 CVE인지 확인한다.

## 2. 목록 (36개, 2026-11-16)

승인 상태는 `gateway-data/necklaces/approvals.json`의 `substitutes`에서 에이전트별 마지막 기록이다. "없음"은 승인 기록이 없다는 뜻이다. 승인되지 않은 대체는 목걸이 정의에서 `planned`로 남고 실제 자리에서는 불리지 않는다.

| 에이전트 | 도구 | 계약 | 원천 | 최대 나이 | 승인 상태(승인 기록) |
|---|---|---|---|---|---|
| nvd-cve | `get_cve_record` | cve.record.v1 | NVD (National Vulnerability Database), NIST | 6시간 | provisional |
| cve-org | `get_cve_org_record` | cve.record.v1 | CVE Program (CVE Services API) | 1일 | 없음 |
| cisa-kev | `check_kev` | cve.exploited.v1 | CISA Known Exploited Vulnerabilities Catalog, FIRST EPSS | 1일 | provisional |
| github-advisory | `list_package_advisories` | package.advisories.v1 | GitHub Advisory Database | 6시간 | provisional |
| package-registry | `get_package_release` | package.health.v1 | npm public registry, PyPI JSON API | 6시간 | provisional |
| package-releases | `get_package_releases` | package.releases.v1 | npm public registry, PyPI JSON API | 1일 | 없음 |
| depsdev-package | `get_package_scorecard` | package.health.v1 | Open Source Insights (deps.dev), Google, OpenSSF Scorecard API | 1일 | provisional |
| gleif-lei | `find_lei_record` | company.registry.v1 | GLEIF LEI records (Global Legal Entity Identifier Foundation), Wikidata, Wikimedia Foundation (LEI links, property P1278) | 1일 | 없음 |
| sec-edgar | `find_sec_company` | company.registry.v1 | SEC EDGAR (U.S. Securities and Exchange Commission) | 1일 | approved |
| sec-company-profile | `get_sec_company_profile` | company.profile.v1 | SEC EDGAR (U.S. Securities and Exchange Commission) | 1일 | 없음 |
| wikipedia-summary | `get_wikipedia_summary` | encyclopedia.summary.v1 | Wikipedia (English), Wikimedia Foundation | 1일 | revoked |
| arxiv-search | `search_arxiv_papers` | papers.search.v1 | arXiv API (Cornell University) | 2일 | 없음 |
| worldbank-indicator | `get_country_indicator` | country.indicator.v1 | World Bank Open Data (World Development Indicators) | 1일 | 없음 |
| met-weather | `get_weather_forecast` | weather.forecast.v1 | MET Norway Locationforecast 2.0 (Norwegian Meteorological Institute) | 3시간 | 없음 |
| public-holidays | `list_public_holidays` | events.search.v1 | holidays (Python library, Vacanza team) | 400일 | 없음 |
| holiday-calendar | `get_holidays` | holiday.calendar.v1 | holidays (Python library, Vacanza team), Natural Earth 1:10m Admin 0 countries and disputed areas | 400일 | 없음 |
| sec-filings | `list_sec_filings` | sec.filings.v1 | SEC EDGAR (U.S. Securities and Exchange Commission) | 1일 | approved |
| software-incident | `find_fix_guidance` | software.incident.v1 | GitHub Advisory Database, NVD (National Vulnerability Database), NIST | 6시간 | 없음 |
| scorecard | `get_scorecard` | package.risk.v1 | OpenSSF Scorecard API | 1일 | 없음 |
| site-readiness | `check_site_files` | website.ai_readiness.v1 | The website's own public files (robots.txt, llms.txt, sitemap.xml) | 1일 | 없음 |
| wiki-grounding | `answer_from_wikipedia` | web.grounding.v1 | Wikipedia (English), Wikimedia Foundation | 1일 | provisional |
| ecb-fx | `get_reference_rate` | fx.rate.v1 | European Central Bank euro foreign exchange reference rates | 26시간 | 없음 |
| usgs-quakes | `list_recent_earthquakes` | earthquake.feed.v1 | USGS Earthquake Hazards Program real-time feeds | 1시간 | 없음 |
| tz-time | `get_local_time` | timezone.time.v1 | IANA Time Zone Database (system zoneinfo), timezone-boundary-builder time zone boundaries (via timezonefinder) | 400일 | 없음 |
| airport-lookup | `lookup_airport` | airport.lookup.v1 | OurAirports, timezone-boundary-builder time zone boundaries (via timezonefinder) | 8일 | approved |
| tls-certificate | `check_tls_certificate` | tls.certificate.v1 | The website's own TLS certificate (read in the TLS handshake) | 1일 | 없음 |
| mcp-registry | `lookup_mcp_registry` | mcp.registry.lookup.v1 | Official MCP Registry (Model Context Protocol) | 1일 | 없음 |
| census-geocode | `geocode_us_address` | geocode.address.v1 | U.S. Census Bureau Geocoder | 30일 | 없음 |
| gdelt-news | `search_news_gdelt` | news.search.v1 | The GDELT Project, DOC 2.0 API | 6시간 | 없음 |
| wiktionary-define | `define_word` | dictionary.define.v1 | Wiktionary (English), Wikimedia Foundation | 7일 | 없음 |
| github-repo | `get_repo_facts` | github.repo.v1 | GitHub REST API (public repositories) | 1일 | 없음 |
| github-releases | `list_github_releases` | github.releases.v1 | GitHub REST API (public repositories) | 1일 | 없음 |
| rdap-domain | `lookup_domain` | domain.lookup.v1 | RDAP (registry servers from the IANA bootstrap) | 7일 | provisional |
| unit-convert | `convert_units` | unit.convert.v1 | NIST Special Publication 811 conversion factors | 3650일 | 없음 |
| wikidata-place | `find_place` | place.search.v1 | Wikidata, Wikimedia Foundation | 7일 | 없음 |
| wikidata-book | `find_written_work` | book.search.v1 | Wikidata, Wikimedia Foundation | 7일 | 없음 |

- 이날 집계: approved 3, provisional 7, revoked 1(wikipedia-summary), 없음 25
- provisional은 30건 관문만 통과한 임시 멤버다. 정식 승인에는 시험 보고서 v2 85점 이상이 더 필요하다.

목록 다시 뽑기:

```bash
.venv/bin/python -c "from agent_market.fallback_agents.catalog import SPECS; print(len(SPECS), list(SPECS))"
```

## 3. 실패 코드

| 코드 | 뜻 | 누구의 문제 |
|---|---|---|
| invalid_input | 인자가 계약 입력 스키마에 맞지 않음, 모르는 에이전트 | 부른 쪽 |
| not_found | 원천에 그런 것이 없음(정답이 "없음"인 경우도 포함) | 답 |
| rate_limited | 원천이 쉬어 달라고 함, 또는 우리 장부·간격이 거절함 | 원천 또는 우리 몫 |
| source_unavailable | 원천이 실패했거나 쓸 수 없는 답을 줌 | 원천 |
| invalid_output | 원천 답이 계약 출력에 맞지 않음 | 원천 답 |
| stale | 우리 사본이 최대 나이를 넘음 | 우리 사본 |
| internal_error | 우리 코드가 처리하지 못한 경우(KeyError 등) | 우리 코드 |

- `failure_code`(agents.py)가 예외를 위 코드로 나눈다(11-16).
  - SourceBusy는 rate_limited
  - SourceError와 ValueError는 source_unavailable
  - 그 밖의 예외는 internal_error
- 사용 기록에는 예외의 종류 이름만 남긴다.
- internal_error는 첫 건에 바로 경보한다(`internal_error:<agent>`).

## 4. 호출 장부와 간격

- 우리가 시작한 실행은 `net.budget(system)` 안에서 부른다. 이 안의 바깥 호출은 `provider_budget.reserve(url, system)`로 도메인별 하루 몫을 먼저 잡는다.
  - 관문: `gate`
  - 녹화: `cassettes`
  - 매시 점검: `fallback_watch`
  - 대체 시험: `substitute_tests`
- 실서비스 목걸이 호출은 이 장부를 쓰지 않는다. runner의 `live_quota_caller`가 제공자 공개 한도의 80%를 따로 센다.
- api.github.com은 시간당 GitHub 몫(`github_reserve`)도 함께 잡는다.
- host마다 간격과 창이 있다(`limits.py`). 원천이 429·503을 보내면 그 host를 쉬게 한다.
- 알려진 누수와 수정
  - 지금 코드는 장부를 잡은 뒤 간격 거절이 나면 그 몫을 돌려주지 않는다.
  - 보내기 전 거절의 몫을 `release`로 돌려주는 수정은 c98dc871(브랜치 `agent-team/split-1116`)이다. 11-17 topic 판정 뒤 반영 예정이다.
  - 시간당 GitHub 몫을 돌려주는 `github_release`는 운영·SRE가 r11 뒤에 만든다.

## 5. 매시 점검 (watch.py)

- jobs의 정비 칸에서 매시 돈다. 결과는 `gateway-data/fallback-agents/watch/state.json`과 날짜별 jsonl에 남는다.
- 바깥 호출 없이 보는 것
  - 원천 상태: 지난 한 시간의 사용 기록
  - 로컬 사본 나이: NVD 6시간, 공항 8일, KEV 24시간
  - GitHub 남은 몫
- 목걸이 자리에서 유일한 멤버인 대체는 매시 직접 한 번 불러 본다(`sole_members`, `probe`, 장부 `fallback_watch`).
- 경보는 키마다 하루 한 번이다.
  - `source_failing`: 연속 3회 실패
  - `sole_member_failing`, `sole_member_unprobed`
  - `internal_error`
  - `snapshot_stale`
  - GitHub 몫 부족

## 6. 승인과 지문

- 대체 관문 기준은 `gate_rules.py`에 있다. 보지 않은 사례 30건 중 29건 이상 통과(`SUBSTITUTE_CASES`, `SUBSTITUTE_PASS`)에 더해, 품질 검사 전부, 계약 입력 전부, 역할 과제 전부를 통과해야 한다.
- 실행은 `scripts/substitute_gate.py`가 하고, 세는 방식은 `deploy/NECKLACE_GATE.md` 10절에 있다.
- 승인 기록 `{agent_id, slot_role, version, definition_digest, state, at}`
  - `definition_digest`는 도구 정의 지문이다. `agent_market/tool_fingerprint.tool_fp`가 `tool_spec`의 {name, description, inputSchema}로 계산하고, `gateway-data/fingerprints/substitutes.json`의 `fp`와 같다.
  - `version`은 승인 때의 git 커밋이다.
- catalog의 설명이나 입력 스키마를 바꾸면 지문이 바뀐다. 이때는 관문을 다시 지나야 하고, 바꾸기 전에 운영·SRE에 알린다.
- 코드 파일의 위치와 내용은 지문에 들어가지 않는다. 동작을 바꾼 코드는 PM이 새 세트로 다시 판정할지 정한다.

## 7. 녹화와 재생 (scripts/fallback_cassettes.py)

agents.py를 원천별 모듈로 나누면서 답이 바뀌지 않았음을 보이는 도구다(PM 11-16, 11-24까지). 관문을 다시 돌리는 대신, 같은 녹화 답에 옛 코드와 새 코드를 돌려 envelope 전체를 바이트 단위로 비교한다.

```bash
.venv/bin/python -m scripts.fallback_cassettes inputs <agent>...     # 녹화할 입력 수(관문 입력, 계약 입력, 역할 과제)
.venv/bin/python -m scripts.fallback_cassettes record <agent>...     # 실제 원천 호출, 장부 'cassettes'
.venv/bin/python -m scripts.fallback_cassettes baseline <agent>...   # 지금 코드로 재생해 기준 저장
.venv/bin/python -m scripts.fallback_cassettes check <agent>...      # 지금 코드로 재생해 기준과 비교
```

- 저장 위치는 `gateway-data/fallback-agents/cassettes/`이며 커밋하지 않는다.
  - `<agent>.jsonl`: 사례마다 인자, 주고받은 HTTP, 녹화 시각
  - `data/`: 녹화 때의 로컬 파일(NVD, 공항, KEV, 격자) 사본
- 녹화 규칙
  - 모든 주소를 공개 주소 검사로 확인한 뒤 보낸다.
  - 우리 쪽 간격 거절이면 기다렸다 다시 시도한다.
  - 장부나 GitHub 몫이 거절하면 그 에이전트는 그날 멈춘다.
  - 거절로 중간에 끊긴 사례는 남기지 않는다.
  - 녹화 직후 그 사례를 바로 재생한다. 녹화되지 않은 요청이 있으면(예: EPSS를 빼고 부분 답으로 넘어간 경우) 버린다.
- 재생 규칙
  - 바깥 호출이 없고, 녹화 시각으로 시계를 맞춰 돌린다.
  - 녹화한 사례에 더해 오류 경로 4개(404, 429, 시간 초과, 빈 본문)를 고정 가짜 응답으로 돌린다.
  - 결과가 다른 에이전트만 새 세트로 다시 판정한다.
- 몫: 장부 `cassettes`의 기본값은 20(60 기준)이고, 도메인 합계에 비례한다. sec.gov는 하루 40, wikipedia.org는 66이다(`CASSETTE_OVERRIDE`). 2026-11-24 뒤에는 0이다(`provider_budget.CASSETTES_UNTIL`). 자세한 것은 `deploy/PROVIDER_BUDGET.md`에 있다.
- 진행(2026-11-16): 녹화가 끝나 40/40 일치를 보인 것은 airport-lookup, nvd-cve, package-registry다. 아직 덜 된 것은 다음과 같다.
  - wiki-grounding 28/36, cisa-kev 17/37, depsdev-package 12/36, rdap-domain 3/35, github-advisory 2/37
  - 뒤의 둘은 4절의 누수로 몫이 먼저 바닥났다.

## 8. 시험

```bash
.venv/bin/python -m scripts.pytest_slot tests/test_fallback_agents.py tests/test_fallback_cassettes.py tests/test_substitute_gate.py
```
