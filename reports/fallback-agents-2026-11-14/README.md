# AgentValCon 자체 대체 에이전트 1차 — cve-incident-brief·package-risk-audit (에이전트 팀, 2026-11-14)

목걸이 자리의 사슬 맨 뒤(`kind: agentcon`)에 둘 자체 대체 에이전트 4개를 만들었습니다. 모두 키 없는 공개 원천을 읽기만 하고, 응답마다 출처·라이선스·받은 시각·캐시 상태를 붙입니다. 아직 운영에 넣지 않았습니다(운영·SRE 관문 10절 전).

## 1. 결과 요약 (정답 세트 tuning 30건, 11-14 04:4x~05:3x 맥에서 실제 원천으로)

| agent_id (도구) | 자리·계약 | 원천 | 통과 | 지연 p50 / p95 | 판단 |
|---|---|---|---|---|---|
| `nvd-cve` (`get_cve_record`) | cve-incident-brief 기록 자리, `cve.record.v1` | NVD 공개 피드 스냅샷(2시간 갱신) | **30/30** | 0 ms / 2 ms | 관문 신청 |
| `cisa-kev` (`check_kev`) | cve-incident-brief 악용 자리, `cve.exploited.v1` | CISA KEV 목록 + FIRST EPSS | **30/30** (EPSS 구간 일치 30/30) | 506 ms / 900 ms | 관문 신청 |
| `cve-org` (`get_cve_org_record`) | 기록 자리 두 번째 대체, `cve.record.v1` | CVE Services API(cveawg.mitre.org) | 24/30 | 1,001 ms / 1,081 ms | 채점 기준 결정 필요(4절) |
| `github-advisory` (`list_package_advisories`) | package-risk-audit 취약점 자리, `package.advisories.v1` | GitHub Advisory Database(reviewed) | 1차 27/30 → 고친 뒤 재측정은 5절 | 987 ms / 1,301 ms | 재측정 뒤 결정 |

- 계약 시험 입력(`test_inputs`) 3건씩: nvd-cve·cve-org·cisa-kev 9/9 통과(`contract-test-inputs.json`).
- 원자료: `gold-nvd-cveorg-tuning.json`, `gold-cve-org-kev-tuning.json`, `gold-github-advisory-tuning.json`(1차). 정답 세트는 워크플로우 팀 `agent_market/necklaces/gold.py` 결과(cve 2026-11-13T19:46:41Z, tuning sha256 4678bce6…; package 19:43:00Z, 7ae34e9d…). **보류(holdout) 세트는 읽지 않았습니다.** 관문 판정은 운영·SRE가 보류 세트로 합니다.
- 지연은 내부 수치입니다(맥 안에서 에이전트 호출 시간, 공개 주소 경유 아님).

## 2. 설계

코드: `agent_market/fallback_agents/` (새 패키지, 다른 팀 파일 변경 없음)

| 파일 | 내용 |
|---|---|
| `catalog.py` | 에이전트 4개, 원천별 이름·URL·라이선스·고지 문구, 도구 명세. 입력·출력 스키마는 목걸이 계약 파일 그대로(대응표 없이 자리에 들어감) |
| `agents.py` | `FallbackAgents.execute(agent_id, arguments)`와 목걸이 실행기 진입점 `run()`, `slot_output()`. 입력·출력을 계약으로 검사(안 맞으면 `invalid_output` 오류, 추측 없음). 캐시: 새것 → 실시간 → 기한 안 묵은 캐시 → 오류. 호출마다 사용 기록 1줄(입력 값 없음) |
| `limits.py` | 원천별 최소 간격·창 한도. 429면 Retry-After(30초~1시간, 없으면 5분) 동안 그 호스트를 쉼, 503이면 60초. 숨은 재시도 없음 |
| `net.py` | 허용 호스트 6개, HTTPS만, 자격 증명·리다이렉트 거부. 사설 주소는 DNS 사전 검사(`validate_public_url`, `check_public_url` 규칙)와 공개 전용 연결(`bounded_client`)로 두 번 막음. User-Agent `AgentValCon-FallbackAgents/1.0 (+https://agentconcierge.biz; contact@agentconcierge.biz)` |
| `nvd_store.py`, `nvd_sync.py` | NVD 스냅샷(SQLite, 행마다 계약 필드만 압축 저장). 피드를 하나씩 흘려 읽어 메모리를 적게 씀. 피드가 게시한 SHA-256이 맞을 때만 반영, 오래된 lastModified는 새 행을 덮지 않음 |
| `versions.py` | GitHub 권고 범위 판정용 버전 순서(npm semver, PyPI PEP 440). 읽을 수 없는 범위는 "안전"이 아니라 남기고 `partial` 표시 |
| `gold_check.py` | 정답 세트 채점기(기본 tuning만 읽음) |

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

### 2-4. 호출 간격 (원천 공개 제한 대비)
| 호스트 | 우리 간격 | 원천 제한 |
|---|---|---|
| services.nvd.nist.gov (API) | 6.5초, 30초에 5회 | 키 없으면 30초에 5회 |
| nvd.nist.gov (피드) | 6.5초 | 피드는 2시간마다 갱신, 우리는 2시간에 meta 1회 + 바뀌었을 때만 내려받기 |
| cveawg.mitre.org | 1초, 분당 60회 | 공개 제한 문서 없음(보수적으로 잡음) |
| www.cisa.gov (KEV) | 1시간 캐시, 60초 간격, 디스크 사본 72시간까지 | — |
| api.first.org (EPSS) | 0.5초, 분당 60회, 6시간 캐시 | — |
| api.github.com | 시간당 50회, 1시간 캐시, `x-ratelimit-remaining: 0`이면 reset까지 쉼 | 키 없으면 IP당 시간당 60회(이 맥 전체 공유) |

## 3. 관문 신청 묶음 (deploy/NECKLACE_GATE.md 10절 대비)

| 조건 | 상태 | 근거 |
|---|---|---|
| 읽기 전용 | 준비됨 | 도구 4개 모두 `readOnlyHint: true`, `is_relay_safe_tool` 통과, 위험 단어 없음(시험). 원천 호출은 GET뿐(`net.get`) |
| 출처·라이선스 표기 | 응답은 준비됨, 카드·상세 페이지는 없음 | 응답 `sources`(2-3). 공개 카드·페이지는 아래 결정 ① 뒤 |
| 정답 세트 통과 | tuning 기준 nvd-cve·cisa-kev 30/30 | 보류 60건은 운영·SRE가 판정. 재현: `python -m agent_market.fallback_agents.gold_check nvd-cve cisa-kev --split holdout-r1 --out <파일>` |
| 호출 간격 준수 | 준비됨 | 2-4. 사용 기록 `gateway-data/fallback-agents/usage/<날짜>.jsonl`(agent·ok·code·ms·cache) |
| 시험 보고서 v2 85점 | 없음 | 아래 결정 ① 뒤 검색과 RAG 보고서 생성기로 |
| 보안·지문 | 지문 기준값 없음 | 결정 ① 뒤 |

**PM·운영·SRE 결정이 필요한 것**
1. **공개 경로 방식**: 관문은 "공개 경로로 다시 돌린 결과"와 resource_id를 전제합니다. 두 안이 있습니다.
   - 안 A: 목걸이 실행기가 프로세스 안에서 `fallback_agents.run()`을 부름(자체 에이전트 6개처럼 자기 HTTP 호출 없음). 관문은 운영 맥에서 `gold_check --split holdout-*`로 판정.
   - 안 B: `owned_data_agents`처럼 MCP 엔드포인트로 등록(목록 비공개, resource_id 생김) → 카드·보고서·지문 절차를 그대로 탐. frontend 배포와 카탈로그 행이 필요.
   - 에이전트 팀 의견: 목걸이 실행기가 아직 없으니 안 A로 먼저 관문을 보고, 공개 카드가 필요해지면 안 B.
2. **NVD 스냅샷 갱신 작업**: `python -m agent_market.fallback_agents.nvd_sync --update`를 2시간마다(바뀐 게 없으면 meta 1회만). 7일 넘게 못 돌면 `--full`이 필요합니다(5분, 약 350MB 내려받기). jobs 등록은 운영·SRE 몫. 데이터 경로는 `FALLBACK_AGENTS_DATA`(기본 `gateway-data/fallback-agents`), 디스크 약 245MB.
3. **cve-org 채점 기준**: 정답이 NVD 점수라 cve-org는 원천이 달라 95%가 구조적으로 어렵습니다. 실패 6건 = CNA와 NVD 점수가 실제로 다름 3건(CVE-2022-20708 CNA 10.0 vs NVD 8.0 등), CVE 기록에 점수가 없는 옛 CVE 3건(2012·2014·2019). 기록 자리 규칙("두 원천이 0.1 안이면 agreed")에는 다른 원천 값이 쓸모 있으니, 기록 자리 두 번째 대체로 두려면 "원천 표시가 맞는지·점수가 그 원천 값과 같은지"로 채점하는 기준이 따로 필요합니다(워크플로우 팀 정답 세트에 CNA 값 추가). 결정 전에는 관문 신청에서 뺍니다.

## 4. 다음 자리 조사 (외부 멤버 1개 역할·패키지 상태 자리, 키 없는 공개 원천)

11-14 04:5x 한 번씩 호출해 본 결과입니다(지연은 맥에서 잰 내부 수치). 라이선스는 보안·준법 확인이 필요합니다.

| 역할 | 후보 원천 | 실측 | 판단 |
|---|---|---|---|
| package.health (package-risk-audit 공급망 자리, 외부 0) | ① npm 레지스트리·PyPI JSON(최신 버전·출시일·deprecated/yanked·저장소) ② deps.dev v3 + OpenSSF Scorecard API(scorecard 총점) | npm 0.03초, PyPI 0.02초, deps.dev 0.18~0.32초, Scorecard 0.10초, 모두 200 | **만들 수 있음, 우선 권장**. 자체 대체 2개 = ①, ② |
| package.metadata (외부 1) | 위 ①과 같음(기존 자체 133021은 npm만) | 위와 같음 | 만들 수 있음(① 하나로 PyPI까지) |
| country.indicator (외부 1) | World Bank(기존 자체 133020·133022), IMF DataMapper | World Bank 0.04초, IMF 6.65초에 전 국가 응답(국가 필터가 무시됨) | 만들 수 있음. IMF는 지표별 하루 1회 스냅샷 방식이어야 함 |
| news.search (외부 1) | GDELT DOC 2.0(키 없음, 5초에 1회), 기존 자체 133018(HN, 기술 뉴스만) | GDELT 첫 호출이 13.7초 뒤 429("5초에 1회") | **실시간 대체로는 불안정**. 캐시·범위 표시를 붙여도 성공률이 낮을 것. 보류 권장 |
| events.search (범용 멤버 없음) | 키 없는 범용 행사 API 없음(Ticketmaster·Eventbrite·PredictHQ는 키 필요). Nager.Date 공휴일, Wikidata 축제 | Nager.Date 0.46초 200 | **범용 불가**. "국가 공휴일·정기 축제 한정 + coverage 표시"로만 가능 |

## 5. GitHub Advisory 재측정

1차(이름@버전 필터) 27/30. 고친 판(패키지 단위 + 직접 범위 판정)은 시간당 한도(이 맥 IP 공유 60회) 때문에 05:35 리셋 뒤 다시 잽니다. 결과는 이 절과 `gold-github-advisory-tuning-v2.json`에 적습니다.

## 6. 시험·재현

```bash
nice -n 10 .venv-tests/bin/python -m pytest -q tests/test_fallback_agents.py     # 43 passed (네트워크 없음)
.venv/bin/python -m agent_market.fallback_agents.nvd_sync --full                  # 스냅샷 첫 빌드
.venv/bin/python -m agent_market.fallback_agents.gold_check nvd-cve cisa-kev --out /tmp/x.json
```
