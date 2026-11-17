# 외부 시험 호출 공용 장부 (운영·SRE, 2026-11-14, PM 전체 연계 점검)

남의 서버에 부하를 주지 않는 것이 먼저다.
- 지금까지는 진주 배치, 역할 과제 시험, 목걸이 재시험·관문, 자체 대체 시험이 호출 수를 각자 셌다. 그래서 한 제공자를 하루에 합쳐 몇 번 부르는지 아무도 몰랐다.
- 이제는 모두 하나의 장부에 먼저 묻고, 허락될 때만 부른다.
- 코드: `agent_market/provider_budget.py`
  - 장부는 `gateway-data/provider-budget/<YYYYMMDD>.json`(KST 하루, git 제외)이다.
  - 파일 잠금으로 이 맥의 모든 스크립트·서비스가 같은 수를 본다.
  - 이 장부는 제공자나 DB를 직접 부르지 않는다.

## 1. 규칙
| 규칙 | 값 |
|---|---|
| 묶는 단위 | **등록 도메인**(예: `api.example.com`·`www.example.com` → `example.com`). 호스팅 플랫폼(`*.vercel.app`, `*.pages.dev`, `*.up.railway.app` 등)은 입주자 하위 도메인 하나를 한 제공자로 본다 |
| 도메인당 하루 합계 | 기본 **60회**(`DAILY_TOTAL`, 모든 시스템 합). 예외: 원문 한도를 확인한 공개 기관은 `DOMAIN_TOTAL`(아래 표). 제공자가 한도를 공개한 도메인(`necklaces/member_terms.json`의 `declared_limit`)은 그 한도의 20%(`SHARE_OF_DECLARED`, 최대 1,000 `DECLARED_CAP`). 한도가 작으면 60보다 작아진다(예: 하루 100이면 20, 11-17 코드 확인). 그날 계획이 관문 호출을 잡아 두었으면 그만큼까지 오르되 공개 한도는 넘지 않는다(PM 11-15 17:16) |
| 공개 목걸이 실행 | 시험과 실제 실행을 합쳐 그날 한도의 80%(`LIVE_SHARE`)까지. 넘으면 그 자리의 다음 멤버로 넘기고 `quota_exhausted`로 남긴다(실패 아님, `live_reserve`) |
| 시스템별 몫(`SHARE`, 60 기준) | 목걸이 재시험 35 · 대체 감시(`fallback_watch`) 30 · 녹화(`cassettes`) 20(2026-11-24까지, 뒤에는 0) · 정답 대조(`reference_checks`) 10 · AD Coin 심사 RDAP(`ad_review_rdap`) 10 · 도메인 만료 RDAP(`lifecycle_rdap`) 50 · 제공자 소유 확인(`provider_claims`) 6 · 지문(`fingerprints`) 6 · 역할 과제 시험 5 · 자체 대체 시험 5 · AD Coin 차단 목록(`ad_blocklists`) 4 · 진주 배치 3 · 그때그때 확인 2 · **관문은 합계에서 남은 만큼**. 합계가 60이 아닌 도메인에서는 몫이 같은 비율(합계 ÷ 60)로 바뀐다. 역할 과제 시험 몫은 합계가 허락하면 최소 4(`ROLE_TEST_MIN`, 시험 1건 = 요청 4개) |
| 닫힌 도메인 | `CLOSED_DOMAINS`(약관상 쓰지 않기로 한 곳)은 하루 합계가 0이라 모든 예약을 거절한다 |
| 429 | 한 시스템이라도 429를 받으면 **그날 남은 시간 동안 모든 시스템이 그 도메인을 부르지 않는다**. 예외: `HOURLY_PAUSE_DOMAINS`(지금 gdeltproject.org)는 다음 정각까지만 멈추고, 공개 실행은 하루 24회(`LIVE_DAY_CAP`) 안에서 쓴다. 같은 프로세스 안에서는 `provider_rest`가 Retry-After를 따로 지킨다 |
| 호출 간격 | 장부와 별도로 각 시스템이 지킨다(같은 호스트 동시 1, 2초 이상, 관문 문서 3절) |

**쓰는 법**(검색과 RAG, 워크플로우, 에이전트 팀, 운영·SRE 모두)
```python
from agent_market.provider_budget import reserve, note
ok, why = reserve(url, 'necklace_retest')   # 부르기 전에. ok가 False면 부르지 않고 why를 기록한다
response = client.post(url, ...)
note(url, 'necklace_retest', response.status_code)   # 부른 뒤에. 429면 그날 그 도메인을 멈춘다
```
- 새 시스템은 `SHARE`에 이름과 몫을 더하는 커밋으로만 생긴다. 모르는 이름은 오류를 낸다.
- 그날 상황 보기: `.venv/bin/python -m agent_market.provider_budget [--day YYYYMMDD]`
  - 많이 부른 도메인, 멈춘 도메인을 보여 준다.

## 2. 60으로 정한 근거 (PM 제안 40 대신)
- **관문 한 회차가 하루에 끝나야 한다.**
  - 11-14 PM이 승인한 출시 관문(`deploy/NECKLACE_GATE.md` 3절)은 회차마다 목걸이 30번과 외부 멤버 단일 30번을 돈다. 그래서 호스트당 하루 60회가 든다.
  - 40이면 한 회차가 이틀로 늘어 관문이 4일 걸린다. 회차 사이 4시간 간격 조건은 그대로다.
  - 관문은 다른 시스템이 쓰고 **남은 만큼만** 쓴다. 이미 공개된 목걸이에 든 진주는 재시험이 먼저 쓰고, 관문은 그만큼 날을 나눈다.
- **60회는 예의 범위다.**
  - 하루 평균 24분에 1번이다. 2초 간격으로 몰아 불러도 2분이다.
  - 첫 목걸이 후보의 공개 원천 제한과 견주면 아주 작다.
    - Open-Meteo 무료는 하루 1만 건이다. (OpenAlex의 "하루 10만 건"은 옛 문서였다. 11-16 원문 확인: 키 없이 하루 $0.10, 검색 1,000건에 $1이라 검색 약 100회. 우리 합계는 그 절반인 50, 아래 표)
    - NVD는 키 없이 30초에 5건이다. 그래서 2초 간격이면 그 아래다.
- **도메인 단위라 호스트 단위보다 엄격하다.** 한 회사의 여러 호스트가 한 몫을 나눠 쓴다.
- 목걸이 재시험 35 = 정답 세트 30 + 계약 시험 3 + 여유 2(워크플로우 설계 b-4)
- 진주 배치 3은 지금 규칙("제공자당 하루 3회")을 그대로 옮겼다.
- **이 장부에 들지 않는 것**: 수집기의 헬스 점검·도구 조사(호스트별 간격·하루 1~6번 안팎, `provider_rest` 적용)와 사용자 요청으로 생긴 게이트웨이 실행
  - 이것들은 시험 호출이 아니라 서비스 동작이다.
  - 헬스 점검까지 합쳐도 한 도메인에 하루 70번 안팎이다.

## 3. 적용 순서
1. 운영·SRE: 이 라이브러리와 시험(`tests/test_provider_budget.py`), 운영·SRE 스크립트
   - 대상: 목걸이 관문 `scripts/necklace_gate.py`, 매일 재시험, 재현 확인
   - 처음부터 장부를 쓴다.
2. 검색과 RAG: 진주 배치(`scripts/pearl_batch.py`, 11-15 02:30 첫 실행 전)와 역할 과제 시험(09:12)에 `reserve`/`note`를 넣는다.
3. 워크플로우·에이전트 팀: 목걸이 정답 세트 실행과 자체 대체 시험에 넣는다.
4. 운영·SRE가 매일 아침 전날 장부를 보고 현황판에 한 줄로 적는다.
   - 내용: 도메인 수, 상한에 닿은 도메인, 429로 멈춘 도메인
   - 몫이 모자라거나 남으면 수치를 조정하는 커밋을 낸다.

## GitHub 시간당 몫 (PM 11-14)

GitHub 무인증 REST 한도는 이 맥 IP 하나에 시간당 60번(core)이다. 여러 시스템이 이 한도를 함께 쓴다(자체 대체 github-advisory·software-incident·github-repo, 역할 시험, 목걸이 재시험, 관문).

- **시간 단위 장부:** `gateway-data/provider-budget/github-YYYYMMDDHH.json`
  - 하루 장부와 같은 파일 잠금을 쓴다.
  - 서비스는 저장소 루트에서 돌기 때문에 모든 역할과 스크립트가 같은 파일을 본다.
- **함수**
  - `github_reserve(system)`: 호출 전에 몫을 확인한다.
  - `github_observe(headers)`: 응답 뒤에 GitHub가 알려 준 남은 수를 기록한다.
- **몫(시간당):** 두 칸을 합친 규칙이다.
  - 전체 상한은 60에서 바닥값 5를 뺀 55다.
  - 시스템별 몫

    | 시스템 | 몫 |
    |---|---|
    | fallback_live | 50 |
    | necklace_retest | 8 |
    | role_tests | 5 |
    | substitute_tests | 5 |
    | pearl_batch | 2 |
    | adhoc | 2 |
    | gate | 나머지 |
- **공동 정지:** GitHub 헤더의 남은 수가 5 미만이면 모든 시스템이 reset 시각까지 멈춘다. 다른 사용자가 이 IP 한도를 쓴 경우도 여기서 잡힌다.
- `/rate_limit` 조회는 GitHub가 세지 않으므로 장부에도 세지 않는다.
- **연결된 곳:** `agent_market/fallback_agents/net.py` 한 곳이다. 자체 대체와 그 시험이 모두 이 경로를 지난다.
  - 시험 맥락이면 그 시스템 이름으로 센다.
  - 실제 답변이면 fallback_live로 센다.
- **사용량 보기:** `.venv/bin/python -m agent_market.provider_budget --github 1` (지난 1시간, 시스템별 사용 수와 거절 수, GitHub가 마지막으로 알려 준 남은 수)
- **토큰:** 토큰을 쓰면 시간당 5,000번이다. 하지만 계정과 자격 증명 문제라서 사용자가 결정한다. 필요하면 필요 호출량을 근거로 PM에 올린다.

## 공개 데이터 기관의 자체 대체 시험 몫 (PM 결정 3, 11-14 06:4x)

- `SHARE_OVERRIDE`: 공개 데이터 기관에 한해 `substitute_tests` 몫을 하루 5에서 30으로 올린다.
  - 대상 도메인: gleif.org, sec.gov(www·data), nist.gov, cisa.gov, wikipedia.org, wikidata.org, wiktionary.org, gdeltproject.org, census.gov, npmjs.org(뒤의 셋은 11-15 추가, 11-17 코드 확인)
- 도메인당 하루 합계 60은 그대로다.
- github.com은 이 덮어쓰기에서 빠진다(GitHub 시간당 몫을 따른다).
- 기관별 속도 상한은 에이전트의 호스트별 간격이 지킨다(`fallback_agents/limits.py`).
- 측정 시간에는 시험을 시작하지 않는다(gold_check, 0de007c2).

## 정답 대조 조회 (PM F15, 11-14)

`scripts/data_quality._fetch_json`은 데이터 품질 점수의 정답 대조에 쓰는 공개 기준값을 읽는다(환율, 최신 버전, USGS 피드, Scorecard, MET Norway). 이 조회도 장부를 지난다.
- 시스템 이름은 `reference_checks`이고, 몫은 도메인당 하루 10회, GitHub은 시간당 2회다.
- 사용자 실행 예산과 따로 센다.
- 몫이나 도메인 하루 합계를 다 썼으면 조회하지 않는다. 그날 429를 준 도메인도 조회하지 않는다. 이때 정확성 대조는 "대조 안 됨"이 된다.
- 원천이 429를 주면 그 도메인은 모든 시스템이 그날 멈춘다. 다시 부르지 않는다.
- 10분 캐시는 그대로다.

## 제공자 소유 확인 (에이전트 팀, 11-15)

`docs/PROVIDER_SELF_CLAIM.md`의 셀프서비스 소유 확인도 장부를 지난다.
- 시스템 이름은 `provider_claims`이고, 몫은 도메인당 하루 6회다. 도메인 하루 합계 60은 그대로다.
- 제공자가 "확인"을 누를 때 GET 1회, 30일마다 다시 확인할 때 origin마다 GET 1회를 쓴다.
- 몫을 다 썼거나 그날 429를 준 도메인이면 부르지 않고, 확인은 '장부 거절'로 끝난다.

## 공개 데이터 기관의 하루 합계 (PM 11-15 11:40 결정 5, 목걸이 100개 계획)

상업 제공자는 도메인당 하루 60회를 기본으로 한다(공개 한도가 있으면 1절의 20% 규칙). 공개 데이터 기관은 그 기관이 공개한 요청 한도를 운영·SRE가 원문에서 확인한 경우에만 하루 합계를 정한다. 정한 값은 그 한도를 하루로 환산한 값의 절반 이하이고, 한도에 따라 60보다 늘리거나 줄인다. 각 시스템 몫도 같은 비율(합계 ÷ 60)로 늘어난다(`provider_budget.DOMAIN_TOTAL`, `DOMAIN_LIMIT_SOURCE`).

| 도메인 | 하루 합계 | 공개 한도(원문) | 하루 환산의 절반 | 출처(11-15 확인) |
|---|---|---|---|---|
| sec.gov | 600 | 10 requests/second | 432,000 | https://www.sec.gov/os/accessing-edgar-data |
| arxiv.org | 600 | one request every three seconds | 14,400 | https://info.arxiv.org/help/api/tou.html |
| met.no | 600 | total traffic below 20 requests/second | 864,000 | https://api.met.no/doc/TermsOfService |
| openalex.org | 50 | 키 없이 하루 $0.10, 검색 1,000건에 $1(검색 약 100회) | 50 | https://help.openalex.org/access/example-costs/ (11-16 확인) |

- OpenAlex는 API 키 없이 하루 50회로 계속 진행한다(사용자 결정 11-16 "OpenAlex는 하루 50회로 계속 진행").
  - **11-16 기준 50은 그대로 유지한다. 11-18 하루만 80회(PM 위임 결정, 11-17)**: 50은 남의 약관이 아니라 우리 장부 규칙이다(무료 크레딧 약 100회의 절반). 근거는 topic v2 정답 재빌드이고, 코드는 `ONE_DAY_TOTAL`(날짜가 지나면 저절로 끝남)이다. papers 정답 기준을 두 색인(papers-two-index-v1)으로 바꾸면서 holdout-r5-2i와 holdout-r6-2i(각 30건, 빈 주제는 채움 목록으로 바꿔 OpenAlex·Crossref 각 72~80회까지)를 새로 만든다. 무료 $0.10(검색 약 100회) 안이라 지출은 0이다. 그날 관문은 OpenAlex를 쓰지 않으므로(v2 papers 자리는 Crossref 133019) plan-20261118의 OpenAlex gate 예약을 0으로 했다.
  - **Crossref 11-18 하루 예외(PM 11-17 결정)**: 하루 합계 220회(기본 60, 11-17 PM이 150에서 올림: 정답 빌드 72+133019 재측정 19+관문 회차 60~120+여유), reference_checks 몫 72회. 220을 승인한 근거는 Crossref에 하루 상한과 요금이 없고 정답 빌더가 polite 풀(초당 10·동시 3)로 부른다는 것이다(아래 공식 문서). 같은 날 관문 회차의 research-papers(133019)도 Crossref를 부른다. Crossref 공개 REST API는 가입·요금·하루 상한이 없고 속도 제한만 있다. 공개 풀 초당 5·동시 1, polite 풀 초당 10·동시 3이고, polite 풀은 `mailto` 인자나 `agent` 헤더에 연락 메일을 넣어야 들어간다. 근거: https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/ (2025-10-16 갱신, 11-17 확인), https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/ (2025-10-24, 결과 캐시·순차 요청·429면 물러남). 정답 빌더(gold_topics_two_index, gold_topics_r3.CROSSREF 주소)는 Crossref polite 풀(mailto=contact@agentconcierge.biz, 사이트에 공개된 주소), 순차 1건씩, reference_checks로 부른다. 관문 회차의 research-papers(owned_data_agents engine)는 User-Agent에 사이트 주소만 넣고 mailto는 보내지 않아 공개 풀(초당 5, 동시 1)이고, CROSSREF 페이서로 순차로 보낸다. 지출은 0이다.

- 600이면 목걸이 재시험 몫은 350, 대체 에이전트 시험 몫은 50(sec.gov는 기존 30의 10배인 300)이다.
- NVD(nist.gov)와 GLEIF(gleif.org)는 공식 페이지에서 숫자 한도를 확인하지 못해 60을 유지한다. 한도 문서를 확인하면 같은 방식으로 추가한다.
- 기관별 간격(초당 요청 수)은 `fallback_agents/limits.py`의 호스트 간격이 지킨다. 하루 합계를 늘려도 순간 속도는 바뀌지 않는다.

## 우선순위·계획·하루 예외·되돌리기 (11-16, `agent_market/provider_budget.py`)

- **계획과 우선순위**: `gateway-data/provider-budget/plan-<YYYYMMDD>.json`의 `{"holds": {도메인: {시스템: 호출 수}}}`가 그날 잡아 둔 몫이다. 우선순위(`PRIORITY`)는 관문 0, 자체 대체 시험 1, 목걸이 재시험 3, 나머지 2(숫자가 작을수록 먼저)이고, 우선순위가 낮은 시스템은 높은 시스템이 아직 쓰지 않은 잡아 둔 몫을 가져가지 못한다. 계획 파일이 없으면 예전처럼 먼저 온 순서다.
- **하루 예외**: `ONE_DAY`(날짜별 시스템·도메인 몫)와 `ONE_NIGHT_GITHUB`(날짜별 GitHub 시간당 몫)는 그날에만 적용된다. 넣고 빼는 것은 커밋으로 한다.
- **되돌리기**: `release(url, system, n)`은 `reserve()`로 셌지만 우리 쪽 사정(중계 간격·자리, 엣지 가득 참, 마감)으로 실제로 나가지 않은 호출을 돌려준다. 그 시스템이 그날 쓴 만큼까지만 돌려준다(11-16 소스 검토).

## 자체 대체의 녹화·매시 점검 몫 (에이전트 팀, 11-16)

- **녹화(`cassettes`)**: agents.py 분리 전후의 답이 같은지 보이려고 대체 에이전트의 관문 입력·계약 입력·역할 과제를 한 번씩 녹화하는 몫이다(`scripts/fallback_cassettes.py`, 사용법은 `deploy/FALLBACK_AGENTS.md` 7절).
  - 기본 몫은 20(60 기준)이다. 합계가 60이 아닌 도메인은 같은 비율로 바뀐다.
  - sec.gov와 wikipedia.org는 `CASSETTE_OVERRIDE`로 기본값을 4로 고정했다. 합계가 커서 비율대로면 너무 크기 때문이며, 하루 sec.gov 40, wikipedia.org 66이다.
  - `CASSETTES_UNTIL`('20261124', 장부의 날짜 형식 YYYYMMDD) 뒤에는 0이 된다.
- **매시 점검(`fallback_watch`)**: 필수 자리의 유일한 사용 가능 멤버인 대체를 매시 한 번 불러 본다(`fallback_agents/watch.py`). 도메인당 하루 24회이고 몫은 30이다.
- **몫 조회의 함정**: `share_limit(system, name)`을 날짜 없이 부르면 `ONE_DAY`를 읽지 못하고 기본 몫을 돌려준다(코드는 `ONE_DAY.get(day or '')`). `reserve()`는 날짜를 넘기므로 실제 예약에는 하루 예외가 적용된다. 확인할 때는 `share_limit(system, name, day=today())`로 부른다(11-16, 하루 예외 10이 2로 보였던 일).
- **대체 에이전트의 되돌리기**: `fallback_agents/net.get`은 `reserve()`를 먼저 하고 host 간격을 나중에 본다. 지금 코드에서는 간격 거절로 나가지 않은 호출도 몫을 쓴다(11-16 녹화 몫이 iana.org·github.com에서 거의 아무것도 보내지 않고 바닥난 원인). 보내기 전 거절을 `release()`로 돌려주는 수정은 c98dc871이며, 11-17 topic 판정 뒤 반영 예정이다. 시간당 GitHub 몫을 돌려주는 `github_release`는 운영·SRE가 r11 뒤에 만든다.
