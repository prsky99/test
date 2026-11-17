# 진주 발굴 W1 검토 (검색과 RAG, 2026-11-17)

- 검토 대상: 안티그래비티 W1 결과(`../A2A_Discovery-ag/reports/pearl-scout-2026-11-17/W1.md`, `w1_diagnosis.json`, `w1_role_catalog.diff`, 10:27)
- 대조 자료
  - `reports/pearls-2026-11-14/role_groups.json`(09:16 생성): 최종 진주가 없는 역할은 19개다. W1이 쓴 19개와 같다.
  - 저장된 시험 버전 전체(`exports/pearls/reports`)
  - 시험 때 남긴 전체 답(`answers/`)
- 검증 방법: 고친 규칙으로 저장된 답을 **메모리 안에서만** 다시 채점했다. 점수 파일은 쓰지 않았다.

## 1. 받아들인 것 (이번 커밋)

### (1) TLS·DNS 역할에 필수 출력 칸이 없어 정확한 답이 80점에 묶임

W1 공통 결함 1의 일부다.

- **원자료 확인**: `tls.certificate.v1`과 `dns.mail_auth.v1`이 `data_quality.REQUIRED_OUTPUT`에 없다. 그래서 정확도 25점을 받은 답도 완전성이 "no required output for this role (unconfirmed)" 0점이다.
  - TLS는 4개 멤버가 해당한다(37468, 39368, 114379, 45519, 모두 80.0점).
  - DNS는 124629가 80.0점이다.
- **고침**: 아래 두 줄을 추가했다.
  - `'tls.certificate.v1': ('issuer', 'expires')`
  - `'dns.mail_auth.v1': ('mail_auth',)`
  - 칸 이름 규칙: issuer는 `issuer|issued_by`이다. expires는 `expir|not_after|valid_to/until|days_left/remaining`이다. mail_auth는 `mx|txt|spf|dmarc|dkim|checks|records`이다.
- **다시 채점한 결과(메모리)**:
  - TLS: 37468 90.0, 39368 89.3, 114379 89.1, 45519 88.3. 넷 다 85점 이상이다.
  - DNS: 124629 89.7, 39800 94.8(85.0에서 올라감).

### (2) 이벤트 과제가 미래 공연을 과거 발행일로 검사함

W1 공통 결함 4다.

- **원자료 확인**: `events-san-francisco`의 `published_within_days: 60`은 'published' 라벨이 붙은 과거 날짜만 통과시킨다. 그래서 8개 멤버가 "no item published within 60 days"로 정확도 0점을 받았다(83372, 32887, 33892, 115024, 40556, 241887, 34238, 46779).
- **고침**
  - 이 과제의 조건을 `upcoming_within_days: 120`으로 바꿨다.
  - `data_quality.upcoming_within`을 추가했다. 어제부터 120일 안의 날짜가 붙은 항목이 하나라도 있으면 통과한다. 장소 단어("San Francisco")는 입력과 같아 사실 확인으로 세지 않으므로, 날짜 확인이 사실 확인 1개가 된다.
- **다시 채점한 결과(메모리)**: 83372 84.6, 32887 83.0, 33892 82.5, 115024 82.3, 40556 79.4, 241887 71.7.
  - 85점은 아직 못 넘는다. 2일째 성공으로 일관성 점수가 붙어야 넘는다.
  - 46779는 60.0에서 50.0으로 내려갔다. 날짜가 붙은 항목이 없는 글 답이다.

### (3) MCP 레지스트리 과제가 정답을 입력에 이미 줌

W1 공통 결함 3이다.

- **원자료 확인**: `mcp-registry-agent-concierge`의 `input.name`과 `must_include_all`이 둘 다 `biz.agentconcierge/agent-concierge`다. 그래서 `fact_checks` 0, "not checkable"로 모든 후보가 정확도 0점이다.
- **고침**: 입력에서 `name`을 빼고 `query: "agent concierge"`만 남겼다. 이제 이름을 찾아내야 정답이다(`fact_checks` 1).
- **다시 채점한 결과**: 저장된 답 3건(86261, 47683, 45964)에 정답 이름이 없어 점수는 그대로다. 다음 회차부터 새 입력으로 시험한다.

### (4) 과제가 직접 정한 선택 인자를 버림

W1 공통 결함 2다.

- **원자료 확인**: `role_tool_test.OPTION_NAME`(`mode|type|sort|...`)는 선택 인자를 채우지 않는다. 그래서 과제 입력이 `type: "TXT"`라고 정해도 버려졌다.
- **고침**: 과제 입력에 같은 이름(`type`, `record_type`처럼 문자만 비교)이 있으면 그 선택 인자를 넘긴다. 과제가 정하지 않은 선택 인자(`search_mode` 등)는 지금처럼 비운다.
- **효과**: 다음 회차부터 116903·46220이 TXT 레코드를 조회한다(W1 근거). 저장된 답은 바꿀 수 없다.

### 시험

- 새 시험 `tests/test_pearl_scout_w1_review.py` 4건
  - TLS·DNS 필수 출력과 글 답
  - 앞으로의 날짜·지난 날짜·400일 뒤 날짜
  - 레지스트리 이름 찾기
  - 정한 선택 인자만 넘기기
- 결과
  - `test_role_tool_test`, `test_necklaces_role_tasks`와 함께 29 passed
  - `data_quality`를 쓰는 시험 10개 파일 56+64 passed

## 2. 뺀 것과 이유

### 주인 팀이 따로 있음

- **company.profile 'encyclopedia' 조건 제거**: 실수가 아니다. aee5e2c0(11-16, 워크플로우 팀)에서 `sec-company-profile` 계약의 "not an encyclopedia" 문장을 확인하려고 넣었다. 다만 외부 범용 회사 도구가 이 문장을 말할 수는 없다는 지적은 맞다. 워크플로우 팀에 넘긴다. 진주 시험용 과제와 계약 확인용 과제를 나누는 안이다.

### 남의 약관이라 바꿀 수 없음

- **crypto.price·stock.quote 실시간 참조 켜기**: Coinbase와 Yahoo 참조는 상업 재사용 약관을 확인하지 못해 `terms_ok=False`로 꺼 두었다(role_catalog 76·82행). 약관이 확인된 다른 공개 출처가 생기기 전에는 켜지 않는다.

### 우리가 정한 원칙이라 바꾸지 않음

- **weather SAME_SOURCE 규칙 완화**: 답이 기준 출처(MET Norway) 자체에서 온 경우 독립 확인이 아니어서 점수를 주지 않는 것은 의도한 규칙이다. 다른 기상청과의 교차 확인은 새 참조 출처가 필요하다. 다음 과제로 둔다.

### 결함이 아님

- **package.health "live reference unavailable"**: 시험 결함이 아니라 그날 npm 참조 몫을 다 쓴 일이다. 거절은 저장되지 않으므로(R08) 다음 회차에 다시 시험한다.

### 미룸

- **이름 규칙 좁히기와 넓히기**: `get_quote`, `get_package\w*`, `scorecard`, `list_releases`, `answer_question`, `get_incidents`, `get_company\w*` 등이다.
  - 잘못 잡힌 도구를 빼는 것은 진주를 만들지 않는다. 그 도구들은 어차피 실패한다.
  - 새 이름을 더하면 스냅샷에서 후보가 크게 늘어난다(예: company.profile 36→357). W2(이름 규칙 밖 후보) 검토와 함께 후보 수·도메인 수를 대조해 다음 묶음으로 낸다.
- **과제 입력 보강**: github-react-license에 owner·name·url, place-eiffel-tower에 위도·경도, company와 advisories 입력 추가 등이다. 인자 대응 문제는 맞지만 과제 입력을 바꾸면 정답 세트 지문(answer_set)이 바뀐다. 정답 출처를 다시 확인한 뒤 다음 묶음으로 낸다.

## 3. 평가기 버전

`data_quality` 채점이 바뀌므로 `EVALUATOR_VERSION`(gate_rules)을 올려야 한다. 그리고 다시 채점(rescore)해야 저장된 답에 새 점수가 붙는다. 올리는 시점은 PM이 정한다. 배포된 목걸이 판정기는 자기 버전과 다른 스냅샷을 믿지 않기 때문에, jobs 배포와 짝을 맞춰야 한다.

## 4. W2 검토: 이름 규칙 밖 후보 (11-17 11:4x)

- **대상**: `w2_candidates.json`의 후보 728개, 38개 역할. 안티그래비티 커밋 5e5a9580이다.
- **스냅샷 대조**
  - 등급 A 도구 스냅샷(09:11): 지금도 활성·등급 A·healthy·중계 안전인지 본다. 728개 모두 있었다.
  - 개인정보 인자: 인자 이름이 `_PII_PARAM`에 걸리면 뺀다. 0개였다.
  - 약관 prohibits: `member_terms.json`으로 본다. 0개였다.
  - 같은 역할·같은 도메인의 4번째 도구: 0개였다.
- **추가로 본 것**
  - 이미 그 역할로 시험한 후보: 69개를 뺐다.
  - 이미 시드에 있는 후보: 2개를 뺐다.
  - 역할 과제가 없는 역할: 64개를 뺐다.
  - 역할 과제 입력으로 필수 인자를 하나도 채울 수 없는 후보: 94개를 뺐다. `role_tool_test.case_arguments`로 확인했다. 시험해도 "missing_args"로 건너뛰어 자리만 쓴다.
  - 위를 거치고 499개가 남았다.
- **고르기**: 최종 진주가 없는 19개 역할에서만 역할마다 최대 6개를 골랐다. 약관이 allowed나 silent인 후보와 서로 다른 호스트를 먼저 골라 93개가 됐다.
  - crypto.price와 stock.quote는 맞는 후보가 없었다. 두 역할은 기준값 출처가 꺼져 있어 진주가 되어도 정확도를 잴 수 없다.
- **도구 설명을 읽고 뺀 것**: 42개. 역할과 다른 일을 하거나, 한 나라·한 서비스 전용이거나, 로그인이 필요한 도구다.
  - company.profile.v1 38450 search_filers: fund filer search, no profile fields
  - company.profile.v1 214979 get_company_news: company news
  - company.profile.v1 37077 get_bitcoin_company_calendar: bitcoin holders calendar
  - company.registry.v1 41381 screen_companies: screens by fundamentals, not a registry record
  - company.registry.v1 46210 find_korean_business: Korea only
  - company.registry.v1 142254 list_earnings_companies: saved earnings
  - company.registry.v1 159881 search_norwegian_companies: Norway only
  - country.indicator.v1 41381 get_economic_context: US treasury and BLS series
  - country.indicator.v1 228501 list_macro_indicators: lists indicator keys only
  - country.indicator.v1 45126 get_country_macro_indicators: Africa only
  - events.search.v1 73684 search_dance_events: dance events only
  - events.search.v1 125317 list_events: vanlife events only
  - events.search.v1 140983 search_shows: Australia/NZ tickets only
  - events.search.v1 145661 buffet_search_events: curated picks of one city
  - github.releases.v1 85397 get_tool_changelog: changelog by internal slug
  - github.releases.v1 228602 check_github_repo: reads pages for eight checks, no release list
  - github.repo.v1 38157 get_repository_diagram: architecture diagram
  - github.repo.v1 215747 check_repo: lockfile pins
  - github.repo.v1 228602 check_github_repo: reads pages for eight checks
  - mcp.registry.lookup.v1 33037 getV01Servers: lists every server, no query
  - package.health.v1 241601 npmstats_downloads: download counts only
  - package.health.v1 37259 query_package: vulnerabilities, not health
  - package.health.v1 275385 resolve_package: NEAR packages only
  - package.health.v1 34216 get_osv_advisory_for_package: vulnerabilities, not health
  - package.releases.v1 47161 osv_query_package: vulnerabilities, not releases
  - package.releases.v1 58234 package_status: one npm scope only
  - package.releases.v1 275385 resolve_package: NEAR packages only
  - place.search.v1 33719 drives_venue_search: delivery venues
  - place.search.v1 33902 list_venues: bike parks
  - place.search.v1 34435 search_venues: restaurants and bars
  - place.search.v1 35850 find_venues: Australian youth venues
  - place.search.v1 37774 list_placelists: curated place lists
  - software.incident.v1 155385 list_followed_project_cves: needs a signed-in account
  - tls.certificate.v1 47257 skuuy_check_security_headers: security headers
  - tls.certificate.v1 163728 check_tls_rpt: TLS-RPT record, not the certificate
  - tls.certificate.v1 290286 pqc_tls_scan: post-quantum handshake only
  - tls.certificate.v1 315662 check_security_headers: security headers
  - web.grounding.v1 247429 research_gtm_question: go-to-market tool questions
  - cve.record.v1 287974 cisoclub_get_vulnerability: Russian BDU numbers
  - fx.rate.v1 34660 fx: USDC sale price
  - papers.search.v1 40216 searchPapers: quantum computing papers only
  - papers.search.v1 47963 search_variant_literature: genetic variant literature

- **받아들임**: 51개를 진주 시험 시드(`reports/pearls-2026-11-14/role_candidates_1115.json`)에 더했다. 106개에서 157개가 됐다.
  - `new_queue`로 미리 돌려 보니 51개 중 44개가 대기열에 들어간다. 나머지 7개는 같은 호스트가 여러 역할에 있어 회차당 호스트 3개 규칙에 걸린다. 다음 회차로 넘어간다.
  - 시드는 작업본에서 읽힌다. 그래서 15:12 회차부터 대기열에 들어간다.
  - company.profile.v1: 39451 lookup_company, 42425 verify_company_record, 34216 search_sec_edgar
  - company.registry.v1: 42425 verify_company_record, 47171 sanctions_resolve_entity
  - country.indicator.v1: 178542 country_info, 42768 get_historical_indicators, 58194 get_macro_indicators
  - cve.record.v1: 204621 search_vulnerabilities, 34216 get_cve_record, 166821 get_advisory
  - events.search.v1: 47989 get_upcoming_events, 107335 festival_and_vrat_dates
  - fx.rate.v1: 241601 currency_latest, 178542 fx_rates, 86011 exchange_rates, 37318 fx_rates, 45852 workflow.run_forex_currency_converter_live
  - github.releases.v1: 178541 github_repo, 45601 depwatch_preview
  - github.repo.v1: 52559 repo_health_check, 88731 check_repo
  - mcp.registry.lookup.v1: 33550 search_servers, 36749 list_mcp_servers, 42500 search_servers, 45870 list_mcp_servers, 56617 search_servers
  - package.advisories.v1: 52559 vulnerability_check, 267005 vulnerabilities, 37259 query_package, 34216 get_osv_advisory_for_package, 58944 find_package_advisories, 274848 check_package
  - package.health.v1: 35565 package_status, 43727 read_package_info
  - package.releases.v1: 241601 npm_package, 178541 package_info, 35565 list_versions
  - papers.search.v1: 178541 doi_lookup, 159640 researchpilot_search_literature, 325037 lookup_paper
  - place.search.v1: 38072 search_place
  - software.incident.v1: 46788 search_public_cve_records, 358790 cve_search
  - tls.certificate.v1: 267572 check_tls, 34409 check_https
  - web.grounding.v1: 47381 vc_web_search, 157022 web_search, 166688 web_search, 214656 serp_live_search, 56366 web_search

- **남은 일**: 남은 448개(진주 없는 역할의 7번째 이후 후보, 진주가 있는 역할의 후보)는 이번 51개의 시험 결과를 본 뒤 다음 묶음으로 낸다. 역할에 맞는 후보 비율을 보고 같은 방식으로 고른다.
- **15:12 대기열 미리 보기 (PM 11:5x)**: 오늘 등급 A 스냅샷으로 catalog_candidates를 대신해 `build_queue`를 돌렸다. 스냅샷은 같은 조건이고, 운영 DB는 읽지 않았다.
  - W2 시드 51개 중 27개가 대기열에 들어가고, 그중 24개가 새 후보 몫 80 안에 든다.
  - 나머지가 빠지는 이유는 두 가지다.
    - 그 도메인을 오늘 이미 시험해 하루 몫(role_tests 5)이 찼다. 예: augur-trade.com, presend.pages.dev, tidydata.workers.dev.
    - 한 회차에 같은 도메인은 한 멤버만 시험한다. 예: tensorfeed.ai·robotbase.cc가 두 역할에 걸려 있다.
  - 공정 사용 규칙이라 그대로 두고, 다음 회차에 넘어간다.
- **인자 대응이 모자란 94개**: `w2_arg_gaps.json`에 정리했다. 역할, 도구, 필수 인자, 못 채운 인자, 역할 과제 입력 키, W2의 arg_map을 담았다. 안티그래비티의 다음 과제(W1 방식의 인자 대응 안)로 넘긴다.
