# AgentValCon 자체 대체 에이전트 1차 — cve-incident-brief·package-risk-audit (에이전트 팀, 2026-11-14)

목걸이 자리의 사슬 맨 뒤(`kind: agentcon`)에 둘 자체 대체 에이전트 6개를 만들었습니다(1차 4개 04:5x, package.health 2개 05:0x). 모두 키 없는 공개 원천을 읽기만 하고, 응답마다 출처·라이선스·받은 시각·캐시 상태를 붙입니다. 아직 운영에 넣지 않았습니다(운영·SRE 관문 10절 전).

## 1. 결과 요약 (정답 세트 tuning 30건, 11-14 04:4x~05:3x 맥에서 실제 원천으로, 고정 과제는 role_tasks.score)

| agent_id (도구) | 자리·계약 | 원천 | 통과 | 지연 p50 / p95 | 판단 |
|---|---|---|---|---|---|
| `nvd-cve` (`get_cve_record`) | cve-incident-brief 기록 자리, `cve.record.v1` | NVD 공개 피드 스냅샷(2시간 갱신) | **30/30** | 0 ms / 2 ms | 관문 신청 |
| `cisa-kev` (`check_kev`) | cve-incident-brief 악용 자리, `cve.exploited.v1` | CISA KEV 목록 + FIRST EPSS | **30/30** (EPSS 구간 일치 30/30) | 506 ms / 900 ms | 관문 신청 |
| `cve-org` (`get_cve_org_record`) | 기록 자리 두 번째 대체, `cve.record.v1` | CVE Services API(cveawg.mitre.org) | NVD 기준 24/30 → **PM 승인 기준(표기한 CNA·ADP 값과 같은지) 28/30** | 1,008 ms / 1,066 ms | 남은 2건은 고르는 규칙 차이(3절 ③), 맞춘 뒤 신청 |
| `package-registry` (`get_package_release`) | package-risk-audit health 자리, `package.health.v1` | npm 레지스트리 `/latest`·PyPI JSON | **30/30**, 고정 과제 2/2 | 204 ms / 331 ms | 관문 신청 |
| `depsdev-package` (`get_package_scorecard`) | 같은 자리 두 번째, `package.health.v1` | deps.dev(OpenSSF Scorecard 포함) | **30/30**, 고정 과제 2/2 | 739 ms / 1,045 ms | 관문 신청 |
| `gleif-lei` (`find_lei_record`) | company-due-diligence 등기 자리, `company.registry.v1` | GLEIF LEI API | 정답 세트 없음 → 고정 과제 2/2, 계약 입력 2/2, 자체 점검(미국 상장사 30곳) 28/30 | 945 ms / 1,718 ms | 정답 세트 요청 |
| `sec-edgar` (`find_sec_company`) | 같은 자리 두 번째, `company.registry.v1` | SEC EDGAR(ticker 목록 + submissions) | 고정 과제 2/2, 계약 입력 2/2, 자체 점검 29/30(둘 중 하나로는 30/30) | 40 ms / 136 ms | 정답 세트 요청 |
| `wikipedia-summary` (`get_wikipedia_summary`) | topic-evidence-brief 백과 자리, `encyclopedia.summary.v1` | 영어 Wikipedia action API | 고정 과제 2/2, 계약 입력 3/3, 자체 점검 30개 제목 30/30 | 474 ms / 503 ms | 정답 세트 요청 |
| `arxiv-search` (`search_arxiv_papers`) | paper-cross-search·topic-evidence-brief 논문 자리, `papers.search.v1` | arXiv API | 고정 과제 3/3, 자체 점검 유명 논문 30편 제목 질의 1위 25/30 | 3초 간격 대기 포함 p50 3.0초 | 한계 있음(2-6) |
| `worldbank-indicator` (`get_country_indicator`) | country-economy-snapshot 지표 자리, `country.indicator.v1` | World Bank WDI | 고정 과제 3/3, 자체 점검 10개국×3지표 30/30 | 204 ms / 215 ms | 정답 세트 요청 |
| `met-weather` (`get_weather_forecast`) | trip-brief 날씨 자리, `weather.forecast.v1` | MET Norway Locationforecast 2.0 | 고정 과제 2/2(온도 실측 비교는 안 함, 2-8), 세계 30개 도시 30/30 | 1,191 ms / 1,199 ms | 정답 세트 요청 |
| `public-holidays` (`list_public_holidays`) | trip-brief 행사 자리(공휴일 한정), `events.search.v1` | holidays 0.108 라이브러리(네트워크 없음) | 고정 과제 0/2(둘 다 범위 밖, 설계대로), 30개국 30/30 | 최대 88 ms | 운영 lock 반영 대기(2-9) |
| `holiday-calendar` (`get_holidays`) | 공휴일 역할, `holiday.calendar.v1` | holidays 0.108(같은 계산) | 고정 과제(검색과 RAG) 1/1, 계약 입력 1/1 | 수 ms | 관문 신청(운영 lock 반영 뒤 운영 동작) |
| `sec-filings` (`list_sec_filings`) | 회사 목걸이 보조, `sec.filings.v1` | SEC EDGAR submissions | 고정 과제 1/1, 계약 입력 1/1 | 캐시 0 ms(목록 공유) | 정답 세트 요청 |
| `software-incident` (`find_fix_guidance`) | cve-incident-brief 수정 안내 자리, `software.incident.v1` | GitHub Advisory + NVD 스냅샷 | 계약 입력 2/3(lodash·CVE-2021-44228), 고정 과제 0/2(xz-utils·log4j 같은 프로그램 이름은 범위 밖) | 0.9~1.2 s | 목걸이는 CVE id로 물어 지장 없음 |
| `scorecard` (`get_scorecard`) | 패키지 위험, `package.risk.v1` | OpenSSF Scorecard 원 API | 고정 과제 1/1(실측 비교는 허용 목록 밖이라 not checked), 계약 입력 1/1 | 0.1 s | 정답 세트 요청 |
| `github-advisory` (`list_package_advisories`) | package-risk-audit 취약점 자리, `package.advisories.v1` | GitHub Advisory Database(reviewed) | 1차 27/30 → 범위 직접 판정으로 고친 뒤 **30/30**(05:36 재측정), 고정 과제 3/3 | 1,010 ms / 1,412 ms | 관문 신청 가능 |

- 계약 시험 입력(`test_inputs`) 3건씩: nvd-cve·cve-org·cisa-kev 9/9 통과(`contract-test-inputs.json`). 고정 과제(role-tasks-v1): nvd-cve 3/3, cisa-kev 3/3, cve-org 3/3, package-registry 2/2, depsdev-package 2/2.
- cve 정답 세트는 20:01Z에 다시 만들어졌습니다(tuning sha256 fd476464…, `cvss_record` 추가). nvd-cve·cisa-kev는 새 세트에서도 30/30입니다(`gold-package-health-tuning.json`과 같은 회차).
- package.health 정답은 package 정답 세트의 `latest_version`(만든 시각의 레지스트리 값)입니다. 그 뒤 새 버전이 나오면 실패로 그대로 보입니다(이번에는 0건).
- 원자료: `gold-nvd-cveorg-tuning.json`, `gold-cve-org-kev-tuning.json`, `gold-github-advisory-tuning.json`(1차). 정답 세트는 워크플로우 팀 `agent_market/necklaces/gold.py` 결과(cve 2026-11-13T19:46:41Z, tuning sha256 4678bce6…; package 19:43:00Z, 7ae34e9d…). **보류(holdout) 세트는 읽지 않았습니다.** 관문 판정은 운영·SRE가 보류 세트로 합니다.
- 지연은 내부 수치입니다(맥 안에서 에이전트 호출 시간, 공개 주소 경유 아님).

## 2. 설계

코드: `agent_market/fallback_agents/` (새 패키지, 다른 팀 파일 변경 없음)

| 파일 | 내용 |
|---|---|
| `catalog.py` | 에이전트 6개, 원천별 이름·URL·라이선스·고지 문구, 도구 명세. 입력·출력 스키마는 목걸이 계약 파일 그대로(대응표 없이 자리에 들어감) |
| `agents.py` | `FallbackAgents.execute(agent_id, arguments)`와 목걸이 실행기 진입점 `run()`, `slot_output()`. 입력·출력을 계약으로 검사(안 맞으면 `invalid_output` 오류, 추측 없음). 캐시: 새것 → 실시간 → 기한 안 묵은 캐시 → 오류. 호출마다 사용 기록 1줄(입력 값 없음) |
| `limits.py` | 원천별 최소 간격·창 한도. 429면 Retry-After(30초~1시간, 없으면 5분) 동안 그 호스트를 쉼, 503이면 60초. 숨은 재시도 없음 |
| `net.py` | 허용 호스트 9개, HTTPS만, 자격 증명·리다이렉트 거부. 사설 주소는 DNS 사전 검사(`validate_public_url`, `check_public_url` 규칙)와 공개 전용 연결(`bounded_client`)로 두 번 막음. User-Agent `AgentValCon-FallbackAgents/1.0 (+https://agentconcierge.biz; contact@agentconcierge.biz)` |
| `nvd_store.py`, `nvd_sync.py` | NVD 스냅샷(SQLite, 행마다 계약 필드만 압축 저장). 피드를 하나씩 흘려 읽어 메모리를 적게 씀. 피드가 게시한 SHA-256이 맞을 때만 반영, 오래된 lastModified는 새 행을 덮지 않음 |
| `versions.py` | GitHub 권고 범위 판정용 버전 순서(npm semver, PyPI PEP 440). 읽을 수 없는 범위는 "안전"이 아니라 남기고 `partial` 표시 |
| `gold_check.py` | 정답 세트 채점기(기본 tuning만 읽음) |

### 2-0. 데이터 시각과 나이 (PM 11-14, 사용자 강조)
- 모든 응답에 `freshness = {data_as_of: {원천: 원천 갱신 시각}, age_seconds, max_age_seconds}`를 붙입니다.
  - NVD: modified 피드의 lastModifiedDate. CVE Program: 기록의 dateUpdated. CISA KEV: 목록의 dateReleased, EPSS: 점수 날짜. deps.dev: 받은 시각 + Scorecard 날짜. GitHub·npm·PyPI: 한 개의 발행 시각이 없어 받은 시각.
- 나이 상한을 넘은 사본으로는 답하지 않고 `stale` 실패를 내 다음 순위로 넘깁니다: NVD 6시간, CVE Program 24시간, KEV 24시간, GitHub 6시간, 레지스트리 6시간, deps.dev 24시간. EPSS는 48시간이 넘으면 빼고 `partial`로 표시합니다.
- 그래서 NVD 갱신 작업(2시간마다)이 6시간 넘게 멈추면 nvd-cve는 실패하고 사슬이 다음 멤버로 갑니다.

### 2-1. NVD를 스냅샷으로 답하는 이유
- 11-14 04:3x 키 없는 NVD CVE API 실측 5회: 13.0초, 23.0초, 26.7초, 503, 503. 목걸이 자리 예산 3.5초 안에 실시간으로는 답할 수 없습니다.
- NVD가 안내하는 공개 피드(연도별 + 2시간마다 갱신되는 modified)로 로컬 사본을 둡니다. 첫 빌드 5분, 425,596건, 파일 244MB(`gateway-data/fallback-agents/nvd-cve.sqlite3`, git 제외).
- 응답의 `cache.status`는 `snapshot`, `age_seconds`는 마지막 동기화 뒤 경과 초입니다. 스냅샷에 없는 새 CVE만 NVD API를 한 번 부르고(남은 예산 2.5초 이상일 때, 30초에 5회 한도), 안 되면 `rate_limited`로 실패합니다.
- 점수 고르는 규칙은 정답 세트와 같습니다: CVSS 4.0 → 3.1 → 3.0 → 2.0 순, NVD Primary가 있으면 그것, 없으면 첫 값.

### 2-2. GitHub Advisory를 패키지 단위로 받는 이유
- 1차 측정 실패 3건을 직접 확인: API의 `affects=이름@버전` 필터가 이름 대소문자가 다른 권고("Scrapy")를 놓치고(scrapy@1.1.1에서 13개 중 5개 누락), 사전 출시 버전(`18.7.0rc1`, `0.8.0b2`)에서 권고를 못 찾았습니다.
- 고친 방식: 패키지 전체 권고를 한 번 받고(1시간 캐시) 범위를 직접 판정합니다. PEP 440 순서는 시험에서 `packaging` 라이브러리와 대조했습니다(운영 의존성은 늘리지 않음).

### 2-3. 출처·라이선스 표기 (응답 `sources`에 그대로 들어감)
| 원천 | 라이선스·이용 조건 | 고지 |
|---|---|---|
| NVD | 미국 정부 저작물(미국 내 저작권 없음) | "This product uses data from the NVD API but is not endorsed or certified by the NVD." (NVD 이용 약관 요구 문구) |
| CVE Program | CVE Program Terms of Use | CVE는 MITRE 등록 상표, 내용은 CNA·ADP 제공 |
| CISA KEV | 미국 정부 저작물(CISA) | 목록에 없음 ≠ 안전 |
| FIRST EPSS | FIRST 표기 조건으로 무료 사용 | 30일 안 악용 확률이지 심각도 아님 |
| GitHub Advisory Database | CC BY 4.0 | reviewed만, 빈 목록 ≠ 안전 |
| npm 레지스트리 | npm Open-Source Terms, 저자가 올린 메타데이터 | 스크립트·관리자·메일은 내보내지 않음 |
| PyPI JSON API | PyPI Terms of Use, 저자가 올린 메타데이터 | PyPI에는 deprecated 표시가 없어 yanked·Inactive일 때만 true |
| deps.dev | 생성 데이터 CC BY 4.0, API는 Google APIs 약관, 캐시 명시 허용 — **11-14 하위 조사에서 상업 조건 "불분명"으로 판정, Scorecard 원 API(CDLA-Permissive-2.0)로 바꿀지 PM 결정 대기** | Scorecard 값은 deps.dev가 주는 OpenSSF 총점과 날짜 |

### 2-4. 호출 간격 (원천 공개 제한 대비)
| 호스트 | 우리 간격 | 원천 제한 |
|---|---|---|
| services.nvd.nist.gov (API) | 6.5초, 30초에 5회 | 키 없으면 30초에 5회 |
| nvd.nist.gov (피드) | 6.5초 | 피드는 2시간마다 갱신, 우리는 2시간에 meta 1회 + 바뀌었을 때만 내려받기 |
| cveawg.mitre.org | 1초, 분당 60회 | 공개 제한 문서 없음(보수적으로 잡음) |
| www.cisa.gov (KEV) | 1시간 캐시, 60초 간격, 디스크 사본 72시간까지 | — |
| api.first.org (EPSS) | 0.5초, 분당 60회, 6시간 캐시 | — |
| registry.npmjs.org·pypi.org·api.deps.dev | 0.2초, 분당 300회, 1~6시간 캐시 | 공개 상한 문서 없음(보수적으로 잡음). npm 전체 문서는 최대 16MB라 `/latest`(약 4KB)만 씀 |
| api.github.com | 시간당 50회, 1시간 캐시, `x-ratelimit-remaining: 0`이면 reset까지 쉼 | 키 없으면 IP당 시간당 60회(이 맥 전체 공유) |

### 2-5. 회사 자리(GLEIF·SEC EDGAR, PM ④)
- 정확한 법인명만 돌려줍니다. 대소문자·문장부호·접미사 표기(Inc.=Incorporated, Corp=Corporation, AG=Aktiengesellschaft)는 같은 것으로 보고, 같은 이름이 여럿이면 추측하지 않고 `not_found`("several ... add the country")로 실패합니다.
- GLEIF: 법인명과 등록된 다른 이름(영문 표기 등)을 모두 대조합니다. 원어 법인명이면 영문 이름을 괄호로 붙입니다(예: `トヨタ自動車株式会社 (Toyota Motor Corporation)`). 검색은 핵심 이름(접미사 뺀 것) → 없으면 전체 이름, 한 페이지 100건. GLEIF 상한(분당 60회)에 맞춰 1초 간격.
- SEC: `company_tickers.json`(ticker가 있는 회사 약 1만 곳, 하루 캐시)으로 CIK를 찾고 submissions에서 법인명·CIK·ticker·거래소·신고자 구분·사업장 도시를 읽습니다. 전화·EIN 같은 연락·세금 항목은 내보내지 않습니다. EDGAR 이름의 주(州) 꼬리표("QUALCOMM INC/DE")는 무시합니다. User-Agent에 contact@agentconcierge.biz, 0.2초 간격(SEC 상한 초당 10회).
- 자체 점검 실패 3건(`company-check.json`): Exxon(SEC 등록명이 "ExxonMobil Holdings Corp"로 바뀜), Chevron(GLEIF에서 정확히 같은 이름을 못 찾음), Oracle(GLEIF 미국에 같은 법인명 여러 개 → 추측 안 함). 사슬로 두 개를 함께 두면 30/30.
- 관문용 정답 세트(보류 60건)는 워크플로우 팀 몫이라 요청했습니다(정답 = SEC CIK·GLEIF LEI 고정).

### 2-6. 백과·논문 자리(Wikipedia·arXiv, PM ⑤)
- Wikipedia: action API로 리다이렉트 제목을 서버에서 풀고(`redirects=1`), 동음이의 문서는 답하지 않습니다(`not_found`). 첫 문단을 문장 끝에서 1,500자 안으로 자릅니다. 응답 `source`와 `sources.license`에 CC BY-SA 4.0과 "Wikipedia contributors"를, `url`에 문서 링크를 넣어 재사용 조건(출처·라이선스 표기)을 지킵니다. `maxlag=5`로 Wikimedia 서버가 바쁠 때는 물러납니다. 데이터 시각 = 문서 `touched`.
- arXiv: API 이용 약관대로 3초에 1회, 감사 문구를 고지에 넣었습니다. 메타데이터는 CC0. XML은 DTD·ENTITY가 든 응답을 거부한 뒤 읽습니다(defusedxml이 설치돼 있지 않음).
- arXiv 한계: API 검색 순서가 제목 일치를 우선하지 않아, 50건을 받아 "제목에 든 질의 단어 수 → 군더더기 단어가 적은 순"으로 다시 줄 세웁니다. 그래도 "Attention Is All You Need"·"Generative Adversarial Networks"처럼 같은 말이 든 제목이 수백 개인 경우는 50건 안에 원 논문이 없습니다(제목 한정 질의면 36위). 3초 규칙 때문에 한 번에 두 번 물을 수 없어 고치지 않았습니다. 이 자리에는 외부 멤버 4개와 자체 Crossref(133019)가 있으니 arXiv는 뒤 순위가 맞습니다.
- 자체 점검(`reference-check.json`, 정답 세트 아님): 시험 30회를 이어 보내 3초 간격 대기가 지연에 들어갔고, 마지막 3회는 arXiv가 상한 응답을 줘 쉬는 동안 `rate_limited`로 실패했습니다(쉬기 규칙대로 동작).

### 2-7. 국가 지표 자리(World Bank; IMF는 만들지 않음)
- 지표 이름(population, gdp, gdp per capita, gdp growth, inflation, unemployment, life expectancy, population growth, area, internet users, capital)이나 World Bank 코드를 받습니다. 계약 규칙대로 population = SP.POP.TOTL, gdp = NY.GDP.MKTP.CD. 응답에 연도·단위·원천 갱신일(`lastupdated`)을 적습니다. 연도를 안 주면 가장 최근 발표값이고, 올해 측정값이 아니라고 고지에 적었습니다.
- World Bank API는 보통 0.03~0.3초인데 가끔 한 URL이 15초 넘게 멈춥니다(11-14 실측). 그래서 첫 요청을 1.4초에서 끊고, 시간 초과일 때만 캐시 키가 다른 형식(`mrnev`·`date`)으로 한 번 더 묻습니다. 429 같은 거절 뒤에는 다시 묻지 않습니다. 고치기 전 자체 점검 27/30 → 고친 뒤 30/30.
- **IMF는 만들지 않았습니다(PM 결정 필요).** IMF 저작권·이용 조건(https://www.imf.org/en/About/copyright-and-terms)은 데이터를 출처 표기로 쓰게 하지만, "상업적 재사용은 copyright@imf.org에 허락 요청", "콘텐츠의 체계적인 내려받기는 서면 허락 필요", "LLM 학습 사용 금지"를 적고 있습니다. 하루 1회 전체 지표 스냅샷은 체계적 내려받기에 해당할 수 있어, 허락 없이 만들지 않았습니다. 허락 요청은 외부 연락이라 사용자 승인 대상입니다.

### 2-8. 날씨 자리(MET Norway)
- 이용 조건(https://api.met.no/doc/TermsOfService, /doc/License, 11-14 확인): 연락처가 든 User-Agent 필수, 전체 초당 20회 미만, 좌표는 소수 넷째 자리까지, Expires 전에는 같은 요청을 되풀이하지 않기, If-Modified-Since 사용, 라이선스 CC BY 4.0·NLOD 2.0("Data from MET Norway"). 상업적 이용 가능.
- 구현: 좌표를 0.01도(약 1km)로 반올림해 같은 칸은 Expires(최대 1시간)까지 캐시로 답하고, 그 뒤에는 If-Modified-Since로 다시 확인합니다(304면 내용 재사용). 지금 시각에 가장 가까운 시간대의 기온과 다음 1·6시간 날씨·강수·바람·습도를 영어 문장으로 냅니다. 데이터 시각 = 예보 `updated_at`, 나이 상한 3시간.
- 고정 과제 weather-*의 온도 기준값은 Open-Meteo 주소입니다. Open-Meteo 무료판은 비상업 전용이라 부르지 않았고, 채점 기록에 "not checked"로 남깁니다(통과로 치지 않음). 워크플로우에 기준 원천을 바꿀지 물었습니다.

### 2-9. 행사 자리(국가 공휴일 한정, PM 승인 (가))
- Nager.Date는 약관(https://date.nager.at/TermsOfService)이 "개인·비영리만, 상업적 이용은 후원 필요"라 쓰지 않았습니다(지출 0).
- 대신 오픈소스 holidays 라이브러리로 네트워크 없이 계산합니다. 확인 내용:
  - 버전 0.108(PyPI 2026-11-02 출시), 라이선스 MIT(저장소 LICENSE 원문 확인), 관리자 3명(Vacanza team), 개발 단계 Beta, 최근 개발판이 매일 올라오는 활발한 프로젝트.
  - 의존성: python-dateutil 2.9.0.post0(Apache-2.0·BSD-3), six 1.17.0(MIT). 셋 다 운영 lock에 새로 들어갑니다.
  - lock 변경안(`deps/holidays-0.108.patch`): 기존 lock 명령(pip-compile --generate-hashes, 같은 pip 인자)으로 다시 만들었고, runtime·dev 두 lock 모두 이 세 패키지만 늘고 다른 버전 변화는 없습니다.
  - pip-audit(runtime·dev): 새 세 패키지 취약점 0. 다만 기존 `opentelemetry-api 1.45.1`에 CVE-2026-126360(1.45.2 수정)이 있어 운영·SRE에 알렸습니다(이번 변경과 무관).
  - 설치: 시험 환경 `.venv-tests`에만 해시 고정(`--require-hashes --no-deps`)으로 넣었습니다. 운영 `.venv`와 lock 반영은 릴리스 패키징이 lock과 환경을 대조하므로 운영·SRE가 네 역할 릴리스와 함께 맞춥니다. 그 전까지 운영에서 이 에이전트는 `source_unavailable`로 실패합니다(라이브러리 없음).
- 응답: 국가(이름 또는 ISO 코드)·연도·월·이름 검색어로 국가 공휴일을 돌려줍니다. 제목마다 "(national public holiday)", 출처에 "holidays 0.108 (MIT): national public holidays only", 데이터 기준일 = 라이브러리 출시일(2026-11-02), 나이 상한 400일(최소 1년에 한 번 버전 갱신). 축제·공연·지역 행사는 다루지 않는다고 고지에 적고, 그런 질문에는 범위 밖이라고 실패합니다.
- 영어 이름이 있는 나라는 영어로(고유명사 악센트는 그대로, 예: Atatürk), 영어가 없는 나라는 "Public holiday (local name: …)"로 표기합니다.

### 2-10. 수정 안내·SEC 신고·Scorecard (PM 조사 뒤 착수, 조건 명확한 셋)
- software-incident: CVE id면 GitHub Advisory `cve_id`로 첫 수정 버전·링크를 주고, 오픈소스 패키지 권고가 없으면(상용 제품 CVE) NVD 스냅샷의 참고 링크를 줍니다. 패키지 이름은 GHSA의 정확한 패키지명만 됩니다("log4j"는 실제 이름이 `org.apache.logging.log4j:log4j-core`라 못 찾음). 수정 버전은 데이터로만 보여 주고 실행하지 않습니다(계약 규칙).
- sec-filings: ticker·CIK·정확한 회사명으로 CIK를 찾고(sec-edgar와 같은 하루 캐시), submissions의 최근 신고와 정기·수시 보고서(10-K·10-Q·8-K 등)를 접수번호와 함께 답합니다. 데이터 시각 = 가장 최근 신고일.
- scorecard: Scorecard 원 API(CDLA-Permissive-2.0). 같은 React 점수가 원 API는 11-09 기준, deps.dev는 08-24 기준이라 원 API가 더 새롭습니다. 패키지만 주면 package-registry로 저장소를 찾아 묻습니다.

## 3. 관문 신청 묶음 (deploy/NECKLACE_GATE.md 10절 대비)

| 조건 | 상태 | 근거 |
|---|---|---|
| 읽기 전용 | 준비됨 | 도구 4개 모두 `readOnlyHint: true`, `is_relay_safe_tool` 통과, 위험 단어 없음(시험). 원천 호출은 GET뿐(`net.get`) |
| 출처·라이선스 표기 | 응답은 준비됨, 카드·상세 페이지는 없음 | 응답 `sources`(2-3). 공개 카드·페이지는 아래 결정 ① 뒤 |
| 정답 세트 통과 | tuning 기준 nvd-cve·cisa-kev·package-registry·depsdev-package 30/30 | 보류 60건은 운영·SRE가 판정. 재현: `python -m agent_market.fallback_agents.gold_check nvd-cve cisa-kev package-registry depsdev-package --split holdout-r1 --role-tasks --out <파일>` |
| 호출 간격 준수 | 준비됨 | 2-4. 사용 기록 `gateway-data/fallback-agents/usage/<날짜>.jsonl`(agent·ok·code·ms·cache) |
| 시험 보고서 v2 85점 | 없음 | 아래 결정 ① 뒤 검색과 RAG 보고서 생성기로 |
| 보안·지문 | 지문 기준값 없음 | 결정 ① 뒤 |

**PM 결정(11-14 05시대)과 반영**
1. **공개 경로 = 안 A**: 목걸이 실행기(ab86ffa7) 프로세스 안에서 `fallback_agents.run()`을 부릅니다. 안 B(MCP 등록·resource_id)는 지금 하지 않습니다. 워크플로우 정의 검증기는 활성 agentcon 멤버에 resource_id를 요구하므로, agent_id로 받도록 맞춰 달라고 워크플로우에 요청했습니다. 그래서 관문 10절의 "공개 경로 재현"은 운영 맥에서 `gold_check --split holdout-*`로, 카드·상세 페이지·시험 보고서 v2·지문은 안 B를 할 때로 미룹니다(운영·SRE 판단).
2. **NVD 갱신 jobs**: 운영·SRE가 등록. `python -m agent_market.fallback_agents.nvd_sync --update`를 2시간마다, 측정 시간(:55~:10)을 피해서. 7일 넘게 멈추면 `--full`(5분, 약 350MB 내려받기). 데이터 경로 `FALLBACK_AGENTS_DATA`(기본 `gateway-data/fallback-agents`), 디스크 약 245MB.
3. **cve-org 별도 기준 승인**: "응답 값이 표기한 원천(CNA·ADP)의 값과 같은지". 응답 `source`에 점수 원천을 적습니다(예: `CVE Program (score from CNA cisco)`). 워크플로우가 정답에 `cvss_record`를 이미 넣어 28/30입니다. 남은 2건(CVE-2026-48587·CVE-2026-15830)은 한 CNA가 3.1과 4.0 점수를 둘 다 낸 경우로, 에이전트는 최신 버전(4.0, NVD와 같은 순서)을, 정답은 첫 항목(3.1)을 골랐습니다. 정답 세트 쪽 규칙을 최신 버전 우선으로 맞춰 달라고 워크플로우에 요청했습니다. 맞춘 뒤 관문에 신청합니다.

## 4. 다음 자리 조사 (외부 멤버 1개 역할·패키지 상태 자리, 키 없는 공개 원천)

11-14 04:5x 한 번씩 호출해 본 결과입니다(지연은 맥에서 잰 내부 수치). 라이선스는 보안·준법 확인이 필요합니다.

| 역할 | 후보 원천 | 실측 | 판단 |
|---|---|---|---|
| package.health (package-risk-audit 공급망 자리, 외부 0) | ① npm 레지스트리·PyPI JSON ② deps.dev(OpenSSF Scorecard 포함) | npm 0.03초, PyPI 0.02초, deps.dev 0.18~0.32초 | **만듦(PM 승인, 05:0x)**: package-registry·depsdev-package 30/30 |
| package.metadata (성공 멤버 0) | 위 ①(기존 자체 133021은 npm만) | 위와 같음 | **해결**: package-registry가 npm·PyPI 둘 다(계약은 package.health.v1) |
| country.indicator (외부 1) | World Bank(기존 자체 133020·133022), IMF DataMapper | World Bank 0.04초, IMF 0.96~6.65초에 전 국가 응답 | **World Bank로 만듦(worldbank-indicator)**. IMF는 이용 조건상 상업적 재사용·체계적 내려받기에 허락이 필요해 보류(2-7) |
| news.search (외부 1) | GDELT DOC 2.0(키 없음, 5초에 1회), 기존 자체 133018(HN, 기술 뉴스만) | GDELT 첫 호출이 13.7초 뒤 429("5초에 1회") | **실시간 대체로는 불안정**. 캐시·범위 표시를 붙여도 성공률이 낮을 것. 보류 권장 |
| weather.forecast (대체 1개) | MET Norway Locationforecast. Open-Meteo 무료판은 비상업 전용이라 제외 | 1.2초 | **만듦(met-weather, 2-8)**, 이용 조건 문서로 확인함 |
| events.search (범용 멤버 없음) | Nager.Date는 약관상 상업 이용에 후원 필요 → 제외 | — | **만듦(public-holidays, 국가 공휴일 한정, 2-9)**. 운영 lock 반영 대기 |

## 5. GitHub Advisory 재측정과 공용 호출 예산, 시험 보고서 v2

- GitHub Advisory: 1차(`affects=이름@버전` 필터) 27/30 → 패키지 단위로 받아 범위를 직접 판정하도록 고친 뒤 **30/30**(`gold-github-advisory-tuning-v2.json`, 11-14 05:36, 시간당 한도 리셋 뒤).
- 공용 호출 예산(운영·SRE 요청, `agent_market/provider_budget.py`): 우리가 시작하는 시험 실행에서만 바깥 호출마다 `reserve()`를 먼저, 응답 뒤 `note()`를 부릅니다(429면 그 도메인을 그날 모든 시스템이 멈춤). 보류 세트(`--split holdout-*`)는 `gate`, 조정 세트·보고서 입력 실행은 `substitute_tests`(도메인당 하루 5회). 목걸이 실시간 호출은 세지 않습니다. 몫을 넘으면 그 호출은 보내지 않고 `rate_limited`로 실패합니다.
- 시험 보고서 v2(PM 11-14): 자체 대체는 resource_id가 없어(안 A) `avc:<agent_id>` 이름공간으로 판·점수·서명 사슬을 쌓습니다. `agent_market/fallback_agents/report_input.py`가 workflow 고정 과제를 실제로 돌려 `scripts.report_v2 import` 입력을 만듭니다(응답 envelope 전체를 본문으로 넘겨 데이터 품질 60점 규칙을 그대로 적용). 첫 파일 `exports/pearls/avc-results-2026-11-14.json`(git 제외): nvd-cve 3/3, cisa-kev 3/3, package-registry 2/2, depsdev-package 2/2(lodash는 예산 몫 소진으로 Scorecard 없이 partial), github-advisory 3/3, cve-org 3/3. 문자열 id 처리와 진주 순위 제외는 검색과 RAG의 report_v2 쪽에 요청했습니다.

### 5-0. 시험 보고서 v2 결과 (검색과 RAG가 05:39에 avc: 판을 쌓음, `exports/pearls/reports/avc:*`)

| 판 | 결과 | 점수(통과 85) | 데이터 60 중 | 증거 30 중 | 글 10 |
|---|---|---|---|---|---|
| avc:nvd-cve / cve.record.v1 | accurate | 90 | 정확 25·최신 10·완전 10·깨끗 10·일관 0 | 인자 10·반복 5·지연 10 | 10 |
| avc:cisa-kev / cve.exploited.v1 | accurate | 90 | 같음 | 인자 10·반복 5·지연 10 | 10 |
| avc:package-registry / package.health.v1 | accurate | 90 | 같음 | 인자 10·반복 5·지연 10 | 10 |
| avc:depsdev-package / package.health.v1 | accurate | 90 | 같음 | 인자 10·반복 5·지연 10 | 10 |
| avc:github-advisory / package.advisories.v1 | accurate | 88 | 같음 | 인자 10·반복 5·지연 8 | 10 |
| avc:cve-org / cve.record.v1 | accurate | 88 | 같음 | 인자 10·반복 5·지연 8 | 10 |

- 반복 증거는 하루치라 5/10, 일관성은 이전 판이 없어 0입니다. 내일 다시 쌓으면 오릅니다.
- 판의 서명(`signed_report`)이 비어 있습니다. 서명 열쇠는 운영·SRE 문서(deploy/EVIDENCE_SIGNING.md) 몫이라 확인을 요청합니다.

## 5-1. 운영 연결 점검과 stale 실제 시험 (11-14 05:4x, PM 지시)

- 운영 중인 버전(frontend `brand-frontend-20261114-r2`, jobs `retention-jobs-20261114-r2`, execution `align-execution-20261113-r2`)에는 `fallback_agents`, NVD 갱신 단계(운영·SRE c6893817 `nvd_snapshot_schedule.py`), 목걸이 실행기의 agentcon 경로가 **아직 없습니다**. 다음 jobs·frontend 묶음에 함께 실려야 합니다.
- NVD 갱신: jobs 스케줄러가 2시간마다 :15~:50에 `Snapshot.sync('update')`를 배경 스레드로 돌립니다(운영·SRE). 스냅샷 파일이 없으면 아무것도 안 하므로, 운영 데이터 폴더(`FALLBACK_AGENTS_DATA`, 기본 `gateway-data/fallback-agents`)에 지금 있는 사본(04:57 동기화)을 씁니다. 묶음 배포가 늦어지면 첫 배포 직후 한 번 갱신이 돌아야 6시간 상한 안에 듭니다.
- KEV: 별도 작업이 필요 없습니다. 요청 때 1시간이 지난 목록이면 다시 받고(0.08초, 60초 간격), 실패하면 디스크 사본을 24시간까지 쓰고, 그보다 오래되면 실패합니다. EPSS는 질의마다 받고 48시간 넘은 값은 빼고 partial입니다.
- stale 실제 시험(`stale-check.json`, 운영 스냅샷의 sqlite 백업 사본에서, 원본 무변경): 동기화 시각을 6시간 1분 전으로 바꾸자 nvd-cve는 `stale`("21660 s old, over the 21600 s limit")로 답하지 않았고, 갱신 작업(meta 1회, 0.6초) 뒤에는 나이 0으로 다시 답했습니다. 사용 기록에도 `code=stale`이 남았습니다. 실행기는 이 실패를 다음 순위로 넘깁니다(워크플로우 cc96f227).

## 5-2. 32개 역할 원천 조사

`roles-32-survey.md`: 외부 대체 현황, 원천별 상업 이용 조건(약관 원문 확인), 만들 수 있는 역할과 원천이 없는 역할(crypto.price·ip.lookup·stock.quote).

## 6. 시험·재현

```bash
nice -n 10 .venv-tests/bin/python -m pytest -q tests/test_fallback_agents.py     # 85 passed (네트워크 없음)
.venv/bin/python -m agent_market.fallback_agents.nvd_sync --full                  # 스냅샷 첫 빌드
.venv/bin/python -m agent_market.fallback_agents.gold_check nvd-cve cisa-kev --out /tmp/x.json
```
