# 자리 연결의 출발 자료: 정규화 함수 표와 값 유실을 세는 방법 (에이전트 팀, 2026-11-15)

PM 17:10 지시 1번입니다. 코드는 고치지 않고 지금의 연결이 어떻게 동작하는지만 정리했습니다. 근거 코드는 `agent_market/necklaces/runner.py`입니다(`unwrap`, `NORMALIZERS`, `STAGED_FIELDS`, `render`, `Runner._call`, `Runner.run`).

## 1. 지금의 연결 방식

1. 멤버 답 → `unwrap()`: JSON-RPC result, MCP structuredContent/content, A2A parts를 벗기고, JSON 글은 구조로 바꿉니다.
2. → 계약별 정규화 함수(`NORMALIZERS[contract]`, 없으면 `norm_generic`). None을 돌려주면 그 시도는 `contract_invalid`로 실패하고 다음 멤버로 넘어갑니다.
3. → 다음 자리(`depends_on`)는 앞 자리 첫 답의 **스칼라 칸**(str·int·float, bool 제외)만 `slot.<자리>.<칸>`으로 받습니다.
4. → `render()`가 `{{slot.X.Y}}`·`{{input.x}}` 틀을 채웁니다. **값이 비면 그 인자를 조용히 뺀 채로 멤버를 부릅니다.**
5. 관문은 `slot_reference_problems()`로, 정의가 읽는 `slot.X.Y`가 X 자리의 정규화가 내는 칸(`STAGED_FIELDS`)인지 미리 검사합니다.

## 2. 정규화 함수 10개

| 함수 | 계약 | 받는 답의 모양 | 뽑는 칸(다음 자리가 읽는 것) | 실패 조건 | 알려진 실패·약점 |
|---|---|---|---|---|---|
| norm_advisories | package.advisories.v1 | 섞임: 글 전체에서 정규식으로 찾음 | items[id], urls(목록이라 다음 자리로 안 넘어감) | 오류 답 | 구조를 보지 않아, 다른 패키지 이야기 속 GHSA·CVE 번호도 같이 잡힘 |
| norm_record | cve.record.v1 | 섞임: 구조에서 CVSS 점수, 없으면 글 | cve_id, cvss_score | 입력 CVE 번호가 답에 없음 | 11-14 CVSS 판 번호(3.1)를 점수로 읽음 → find_score에서 벡터·판 제외(invalid-…-cvss-normalizer 기록) |
| norm_exploited | cve.exploited.v1 | 구조의 bool, 없으면 글의 긍정·부정 문구 | cve_id(kev는 bool이라 안 넘어감) | 다른 CVE 답, 판단 불가 | 문구 목록에 없는 표현은 실패(지어내지 않음, 의도) |
| norm_generic | 그 밖 전부 | 글 | text(4,000자) | 오류·빈 답 | 칸 구분 없이 글을 통째로 넘김. 다음 자리가 text를 인자로 받으면 남의 글이 그대로 인자가 됨(주입 위험, 아래 3절) |
| norm_registry | company.registry.v1 | 구조만 | cik, ticker, lei, legal_name | 이름·번호 모두 없음 | 여러 ticker·symbol 키 중 첫 값을 씀("symbol"이 다른 뜻일 수 있음). cik·lei만 형 검사, ticker는 형 검사 없음 |
| norm_package_releases | package.releases.v1 | 구조만 | latest_version, latest_date, repository_github, text | 판·저장소 모두 없음 | **package → GitHub 저장소 넘기기(11-15, aa8e154c)**: repository_github가 없으면 url 칸에서 github.com을 찾음. url이 홈페이지·미러면 엉뚱한 저장소가 될 수 있음 |
| norm_location | geocode.address·airport.lookup·ip.lookup | 섞임: 구조의 좌표, 없으면 "lat X lon Y"·"X, Y" 글 | lat, lon, point, place, country_code, timezone | 좌표 없음, (0,0) | **airport-lookup "lat X lon Y" 읽기 실패(11-15, b8bcc377에서 LATLON_TEXT 추가)**. 글 속 "118.41 W"처럼 방향 글자로 쓴 좌표는 부호를 모름(정규식은 부호 숫자만 읽음). country_code는 키 이름 "country"의 두 글자 값도 받음 |
| norm_quakes | earthquake.feed.v1 | 섞임: GeoJSON·구조, 없으면 우리 usgs-quakes 문장 | count(목록은 안 넘어감) | 사건 없음을 구조로 말하지 않음 | 문장 형식이 바뀌면 사건을 못 읽음(우리 문장에 묶임) |
| norm_filings | sec.filings.v1 | 글(norm_generic) | text | 오류·빈 답 | "SEC 등록 없음"을 문구로만 알아봄 |
| norm_book | book.search.v1 | 섞임: 구조 우선, 없으면 "author X" 글 | author, year, title, text | 저자 없음 | 첫 노드의 저자를 씀. 여러 판·번역서가 섞이면 다른 책의 저자가 될 수 있음 |

- 오늘 짚은 결함 넷의 위치
  - ticker 오해 → norm_registry. 코드 결함이 아니라 오판이었습니다. 에이전트 팀이 "58997의 ticker 입력이 늘 비어 있다"고 보고했는데, 실제로는 norm_registry가 채우고 있었습니다(정정 보고함). 자리 사이에 무엇이 넘어가는지 보이지 않아 생긴 일이라, 4절의 기록이 필요한 이유이기도 합니다.
  - "lat X lon Y" → norm_location(고침)
  - package → GitHub → norm_package_releases(새 경로)
  - 서경 부호 유실 → 실행기가 아니라 채점 쪽(gold_check.py의 airport-lookup 판정이 같은 글을 읽다 부호를 잃음, 워크플로우가 고침)입니다. 같은 "글에서 좌표 읽기"가 실행기와 채점에 따로 구현돼 있어 한쪽만 고쳐질 수 있습니다. 어댑터는 이것을 한 곳으로 모아야 합니다.
- 공통 약점
  - 형 검사가 칸마다 다릅니다. cik·lei·좌표 범위·IANA 시간대는 검사하지만, ticker·판 번호·날짜(앞 10자리만)·통화는 검사하지 않습니다.
  - 칸의 출처가 기록되지 않습니다(구조의 어느 키인지, 글의 어느 문장인지).

## 3. 값이 버려지는 곳 (지금은 기록이 없음)

| 지점 | 무엇이 버려지나 | 지금 남는 기록 |
|---|---|---|
| unwrap | 봉투 밖 메타, 여러 data 부분 중 하나만 고를 때 나머지 | 없음 |
| 정규화 | 답에 있었지만 칸으로 못 뽑은 값, 목록·bool 칸 | 실패면 `contract_invalid`만, 성공이면 없음 |
| 다음 자리로 넘기기 | 목록·dict·bool, 두 번째 이후 답 | 없음 |
| render | `{{slot.X.Y}}` 값이 비어 빠진 인자 | **없음.** 인자가 빠진 채 멤버를 불러서, 실패가 그 멤버 탓(relay_200·invalid 등)으로 기록됨 |
| 실행 기록 run_event | 시도별 오류·인자 | 몸통 없는 줄이라 자리별 stage만 남음 |

## 4. "멤버는 답했는데 다음 자리가 값을 못 받은" 사례를 세는 방법

### 지금 있는 기록으로 세기 (11-15 집계, 작업본 gateway-data/necklaces)

- `retest/<날짜>.jsonl`의 시도 줄: `ok=false`이고 `error_class="contract_invalid"`이면 "답은 왔지만 정규화가 값을 못 뽑음"입니다.
  - 11-15 기록 3개 파일(445줄)에서 **0건**입니다. 실패는 relay_403(42), budget_paused_429(74), timeout·late·deadline(16), relay_200(7)이었습니다.
- `relay_200`: HTTP 200에 JSON-RPC 오류가 든 답입니다. 인자가 빠지거나 틀린 경우가 여기로 섞여 들어옵니다. 11-15의 company-due-diligence 7건은 모두 241601의 "execution is unavailable"이라 연결 문제가 아니었습니다.
- `results/<slug>/selftest-*.jsonl`(keep_raw 켠 자기 시험): 자리별 attempts와 원문 앞부분이 있어 사람이 원인을 볼 수 있습니다.
- 결론: 오늘의 결함 넷은 실행 기록이 아니라 코드 읽기와 자기 시험에서 찾았습니다. **지금 기록으로는 연결 실패를 셀 수 없습니다.**

### 어댑터 첫 단계로 남길 기록 (제안, 코드는 아직 안 고침)

시도마다 한 줄씩 남깁니다. 몸통(입력·답 원문)은 넣지 않고 모양과 칸 이름만 넣습니다. run_event의 개인정보 원칙은 그대로 지킵니다.

```
{"run": …, "slot": "location", "member": 86011, "answer_shape": "text" | "json" | "mixed" | "error",
 "staged": {"lat": "struct:latitude", "lon": "text:LATLON"},      # 칸 → 어디서 뽑았나
 "dropped": ["timezone(list)", "second_answer"],                    # 버린 것
 "type_checks": {"lat": "ok", "ticker": "unchecked"},
 "downstream_missing": {"quakes": ["slot.location.point"]}}        # 다음 자리가 원했는데 비어 있던 틀
```

- `downstream_missing`은 render에서 빠진 인자를 그대로 적으면 됩니다. 이것이 PM이 묻는 "답했는데 다음 자리가 값을 못 받음"의 직접 계수입니다.
- 이 기록이 쌓이면 실패 유형(형 불일치, 칸 이름 다름, 글에만 있음, 부호·단위)을 셀 수 있습니다.

## 5. PM 조건에 비춰 본 지금 연결의 빈틈

| PM 조건 | 지금 | 빈틈 |
|---|---|---|
| 모르면 멈춤 | 정규화가 None이면 그 시도 실패, 다음 멤버로 넘어감 | render가 빈 값 인자를 빼고 **계속 부름**: 멈추지 않고 인자 없는 호출이 나감 |
| 답은 자료, 지시 아님 | 다음 자리로는 스칼라 칸만 감, 도구·주소는 정의에 고정 | norm_generic·norm_filings·norm_book의 `text` 칸이 다음 자리의 인자가 될 수 있음(긴 남의 글이 인자로 들어감). 칸 길이·문자 제한이 없음 |
| 요청 경로에 모델 없음 | 정규식·키 이름 규칙만 씀 | 지킴 |
| 단위·식별자 형 검사 | cik·lei·좌표 범위·시간대만 | ticker·통화·날짜·판 번호·방향 글자 좌표 |
| 지문이 바뀌면 재검증 전 사용 금지 | 승인된 자체 대체는 지문에 묶임 | 외부 멤버의 연결 규칙(정규화)은 지문과 묶여 있지 않음 |

- 지금 바로 고칠 만한 것 둘(어댑터 설계와 별개로 작음)
  - render에서 `{{slot…}}` 값이 비면 멤버를 부르지 않고 그 시도를 `input_absent`로 실패시키기
  - 다음 자리로 넘기는 칸에 형·길이 제한 두기(특히 text)
  - 두 가지 모두 runner.py를 고치는 일이라 워크플로우 팀 파일입니다. PM 설계 문서가 나온 뒤 함께 정합니다.

## 6. PM 17:12 "정할 것"에 대한 제안 (에이전트 팀)

### 6.1 규칙의 표현: JSON으로 적는 제한된 단계 목록(새 의존성 없음)을 권합니다

| 후보 | 장점 | 걸리는 점 |
|---|---|---|
| JSONata(jsonata-python 0.7.2, Apache-2.0, 순수 파이썬·의존성 없음, PyPI 11-15 조회) | 식 언어가 성숙했고 모델이 잘 앎 | 파이썬 구현이 0.x이고 마지막 판이 11-13(이틀 전)이라 검증 기간이 짧음. JSON만 다뤄 **글로 답하는 멤버(지금 멤버 상당수)는 결국 정규식이 따로 필요함**. 식 언어가 넓어 무엇을 하는지 검토하기 어려움 |
| JMESPath(1.1.0, MIT) | 경로 추출만 하는 작은 언어 | 변환·글 추출이 없음. 운영 venv에 없음 |
| **제한된 단계 목록(제안)** | 규칙이 코드가 아니라 자료(JSON)라 eval이 없고, 지문을 붙이기 쉬움. 허용된 단계만 실행되므로 주입이 규칙을 바꿀 수 없음. 글과 JSON을 같은 규칙으로 다룸 | 단계 종류를 우리가 만들고 시험해야 함 |

- 단계는 허용 목록으로만 둡니다.
  - `path`: 경로나 키 이름으로 넓이 우선 찾기. 지금 `_walk`와 같은 방식입니다.
  - `regex`: 우리가 검토해 등록한 패턴만 씁니다. 입력 길이에 상한을 두고, 모델이 새 정규식을 쓰면 합성 때 검토 대상이 됩니다.
  - `first`, `all`, `pick_where`(조건 칸이 입력값과 같은 노드)
  - `cast:<형>`(6.3의 형)
  - `unit`: 단위 환산은 표로 정한 것만 합니다.
  - `require`: 없으면 "값 없음"으로 멈춥니다.
- 실행기는 작은 해석기 하나(파이썬 수백 줄 예상)입니다. 운영 venv에 새 의존성을 넣지 않습니다. JSONata는 나중에 필요가 보이면 운영 밖 합성 도구에서만 검토합니다.

### 6.2 합성에 쓸 모델

- 1차는 **사용자 API 키의 Claude 모델**을 제안합니다.
  - 운영 밖에서 연결 한 쌍당 한 번 돕니다. 실제 답 표본 약 10개, 뒤 자리 스키마, 단계 목록 문법을 주고 후보 3~5개를 받습니다.
  - 하루 4달러 상한 안에서 씁니다. 첫 합성의 실제 토큰·비용을 재서 보고합니다(지금은 추정하지 않음).
- 맥미니 로컬 모델은 동시 4개 자리를 검색과 RAG가 쓰고 있습니다. 2차 비교용으로 같은 표본에 돌려 정확도만 비교합니다.
- 모델이 만든 규칙은 정답 세트 통과(손으로 쓴 함수와 같은 사례 대조 포함)와 사람 검토(PR에 규칙 JSON이 그대로 보임)를 거친 뒤에만 실립니다.

### 6.3 형이 붙은 중간 값(처음 묶음)

| 형 | 검사 |
|---|---|
| Coordinate | lat −90~90, lon −180~180, (0,0) 거부. N/S/E/W 글자를 부호로 바꿈(오늘 부호 유실 대응) |
| Date / DateTime | ISO 8601, DateTime은 UTC로만. 앞 10자리 자르기 대신 실제로 해석 |
| Money | 금액(Decimal) + ISO 4217 통화. 통화가 없으면 값 없음(추정 금지) |
| Identifier | 종류별 형식: CIK(1~10자리, 10자리로 채움), Ticker(대문자·점·하이픈 1~10), LEI(ISO 17442 검사 숫자), CVE, GHSA, npm 패키지 이름, GitHub owner/name, SemVer, IANA 시간대, ISO 국가 2자, 공개 https URL, 도메인 |
| Number | 범위·정수 여부를 칸마다 정함(오늘 규모 4.5를 정수 칸이 거절한 건 대응) |
| Text | 길이 상한. **다음 자리의 도구 인자로는 넘기지 않음**(표시용). 주입 차단의 핵심 |

### 6.4 1차 범위 순서(이번 주)

1. 기록 먼저: 자리마다 `read`(규칙이 읽음), `stopped`(값 없음), `filled_by_other`(멈춘 뒤 다른 멤버가 채움)와 버린 칸을 남깁니다(4절). 이 수치가 "어떤 상황에서도"의 보고 숫자입니다.
2. 해석기와 형 6종, 그리고 손으로 쓴 함수와 대조하는 시험
3. 연결 셋 합성과 대조: npm → GitHub(norm_package_releases와 대조, 정답 holdout-v2-activity), cve 기록 → 패치 권고(cve-incident-brief holdout-v2-fix), topic 뉴스 자리(gdelt-news 관문 세트)
4. 맞으면 새 목걸이부터 어댑터로 연결하고, 기존 함수는 하나씩 옮깁니다.

- runner.py는 워크플로우 팀 파일입니다. 어댑터는 새 모듈(`agent_market/necklaces/adapter/`)로 만들고, runner.py에는 "계약에 고정 규칙이 있으면 그것을, 없으면 기존 함수를" 쓰는 연결 한 곳만 바꾸도록 워크플로우와 맞추겠습니다.
