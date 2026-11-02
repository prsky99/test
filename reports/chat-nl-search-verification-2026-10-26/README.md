# 채팅 자연어 검색 소스 분석과 품질 검증 (2026-10-26)

대상: 공개 프론트 Chat의 자연어 요청 → 에이전트 추천 경로. 오늘 진행된 `chat-recommendation-quality-*`, `weather-news-quality` 작업을 포함한 **현재 작업 트리** 소스를 기준으로 했다. 운영 프론트는 `frontend-chat-task-quality-20261026-r3` 릴리스로 돌고 있어 작업 트리(18:00 이후 수정분 포함)와 일부 다를 수 있다.

## 1. 처리 경로 분석

| 단계 | 모듈 | 역할 |
|---|---|---|
| 입력·라우팅 | `concierge/fast_chat.py` `FastConcierge.handle/_fast_route` | 2,000자 상한, 프로토콜 선택자 검증, 후속 명령(details/more/outcome), 워크플로 분기 |
| 프로토콜 | `concierge/protocols.py` | 명시 선택자 > 문장 속 프로토콜. 자동/Any는 A2A 우선 후 MCP, x402는 명시할 때만 |
| 작업 조건 | `concierge/chat_task_spec.py` | `parse`(PDF 입력, OCR, 표, JSON 출력, DOI, 타임스탬프, 인증/가입 불필요), `merge`(후속 조건과 새 작업 구분), `tool_fit`(도구별 3상태 판정), `task_proof`(도구 단위 근거) |
| 언어 정규화 | `chat_query_rewrite.py`, `llm.LocalLLM.rewrite_task` | 검색어가 0개일 때만 로컬 모델로 영어 정규화. 원문 구간 대응 검증, 예산 1.8초. 운영 모델 `gemma4-e4b-mlx` |
| 검색어 | `selection.search_terms`, `capability_terms` | 별칭 확장, 기능어와 주제어 분리(`TOPIC_BOUNDARY`) |
| 후보 검색 | `concierge/discovery.py` (+`gateway/rag.py`) | PostgreSQL 전문 검색과 pgvector ANN을 RRF로 결합, 최대 600개 |
| 적격 판정 | `selection.QualityRecommender._search_protocol`, `task_requirements.py`, `execution_policy.py` | 안전 엔드포인트, 최근 성공 증거(A2A는 실행 성공 필수), 실패 우선 제외, F등급 제외, 작업 범위·입력 요구·스키마·날씨/뉴스 범위·도구 일관성 |
| 정렬 | 같은 모듈 | 최근 성공 검증 → 최근 활동 → 등급 → 점수 → 신뢰도 → 지연 (AGENTS.md 일치) |
| 응답 | `fast_chat._brief` | 최대 3개, 결제·가격 문구 표시 제외(`DISPLAY_RESTRICTED`), 선택 도구 확인 여부 표시 |

## 2. 검증 방법

1. 관련 회귀 16개 파일 실행: **355 passed**, 실패 0건 (`.venv-tests`).
2. 운영 카탈로그를 **읽기 전용 세션**(`default_transaction_read_only=on`)으로 열고, 서비스와 같은 설정(`service_host` 프로필 적층: `agentcon.env` + `local-model.env` + `embedding.env` …)으로 하이브리드 검색과 실제 `QualityRecommender`를 직접 호출했다. 방문자 기록, 대화 기록, 제공자 실행은 0건이다(`nl_eval.py`).
3. 질의 27개: 영어 13, 한국어 5, 일본어 2, 조건 2, 프로토콜 3, 비과제 2 (`queries.json`, 결과 `results-operating-profile.json`).
4. 적합성은 추천된 도구의 이름·설명으로 수동 판정했다. 표본이 작으므로 전체 정확도로 일반화하지 않는다.

## 3. 결과 요약

- 과제 질의 24개 중 1위가 적합한 경우는 **12개(50%)**, 부분 적합 4개, 부적합 8개였다.
- 정책은 모두 지켜졌다: 최대 3개, 자동/Any는 A2A 먼저, 명시하지 않으면 x402 없음, 명시 선택자 우선, 정렬 순서, 결제 문구 비표시.
- 응답 시간(검색 단계): 0.4~4.2초, 대부분 1.5~3초.

| 질의 | 1위 | 판정 |
|---|---|---|
| research papers about battery recycling | Crossref `search_works` | ✓ (2위 문서 요약기는 부적합) |
| technology news about AI chips | Faceabot `news_search` | ✓ 3/3 |
| weather forecast for Seoul tomorrow | Geocoding & Weather | ✓ (2·3위 캠핑카 적합도, 스키장 예보) |
| translate English text to Korean | 아카이브 필드 번역 제안 | ✗ 실제 번역 도구는 5·7위 |
| convert a PDF invoice into structured JSON | JSON→PDF 생성기 | ✗ 방향 반대, 정답은 3~5위 |
| current price of bitcoin | A2A 비트코인 Q&A | ✓ |
| web search for recent AI news | ManyLives Web search | ✓ (같은 제공자 2개 중복) |
| send an email | 견적 요청 전송 | ✗ 실제 발송 도구는 5위 |
| generate an image | Suede 이미지 생성 | ✓ |
| paper metadata by DOI | `doi_lookup` | ✓ |
| summarize a YouTube transcript | 오디오 전사 | △ |
| read-only SQL on Postgres | ClickHouse 시장 데이터 | ✗ |
| GitHub repositories about MCP servers | GitHub trending | △ (주제 "MCP"가 MCP 필터로 바뀜) |
| 배터리 재활용 논문 (KO) | DOI로 논문 1건 조회 | ✗ 주제 소실, 2위 "Urantia Papers" |
| 계약서 불리한 조항 (KO, 설계 F1) | 문서 요약 브리프 | △ (F1 검색어 추출은 해결됨) |
| 서울 날씨 (KO) | 날씨 도구 | ✓ |
| 영어→한국어 번역 (KO) | 한국 주소 정규화 | ✗ |
| AI 기술 뉴스 (KO) | 뉴스 검색 | ✓ |
| 東京の天気 (JA) | Geocoding & Weather | ✓ (정규화 1.2초) |
| 論文を検索 (JA) | 신뢰 인덱스 검색(A2A) | ✗ |
| papers + DOI + no API key + JSON | CiteMe | ✓ (조건 doi, no_api_key 보존) |
| 624자 긴 요청 (설계 F2) | 결과 없음 | ✗ |
| MCP weather for Tokyo | Geocoding & Weather | ✓ |
| x402 bitcoin (명시) | x402 BTC 반감기 | △ |

## 4. 확인된 결함 (원인까지 재현)

| # | 심각도 | 결함 | 원인 위치 | 재현 |
|---|---|---|---|---|
| D1 | 높음 | 관련성 문턱이 느슨해 약하게 관련된 후보가 정답보다 먼저 나온다 (설계 F4 미해결) | `selection` 적격 판정: 도구명 단어 1개 일치로 통과, 이후 최근성 정렬 | 번역 1~3위 부적합(정답 5·7위), 이메일, 논문 2위 |
| D2 | 높음 | `pdf_input` 조건이 방향을 보지 않는다. "PDF를 만든다"도 입력 충족으로 판정 | `chat_task_spec.tool_fit`: 설명 전체에서 `\bpdf\b`만 검사 | PDF 송장→JSON 1·2위가 JSON/HTML→PDF |
| D3 | 높음 | "search for X"의 X를 주제로 분리해 기능이 'search'만 남는다. 정규화 모델이 자주 이 표현을 출력하므로 일본어 등 미지원 언어 경로가 체계적으로 영향을 받는다 | `capability_terms`의 `TOPIC_BOUNDARY`(for). "look for"는 예외 처리됨 | `Search for papers` → core `['search']`, 결과는 신뢰 인덱스 검색·사전 |
| D4 | 중상 | 긴 서술형 요청은 첫 절만 기능어로 써서 결과가 없다 (설계 F2는 길이 문제만 해결) | `capability_terms`가 첫 경계 앞만 사용 | 624자 요청 → core가 planning/photography, 결과 0 |
| D5 | 중 | API 키 불필요 조건의 다른 표현을 인식하지 못한다 | `chat_task_spec` 패턴 | "must not require an API key", "should not need an API key", "no authentication" → 조건 없음 |
| D6 | 중 | 한국어 요청의 주제어가 사라져 단어 일치 오탐이 생긴다 | 한국어 별칭 사전 범위 | "배터리 재활용 논문" → research/paper만, "Urantia Papers" 통과 |
| D7 | 중 | 한국어 번역 요청에 주소 정규화 도구가 통과 | 관련성 판정(언어명 'korean' 일치) | "영어 문장을 한국어로 번역" → WIA Address |
| D8 | 중(정책) | 주제로 언급한 프로토콜을 선택자로 처리. x402는 언급만으로 x402 전용 검색이 된다 | `protocols.requested_protocol` | "about MCP servers" → mcp, "tutorials about x402 payments" → x402 |
| D9 | 낮음 | 같은 제공자의 다른 배포가 중복 추천된다 | `recommendation_identity`가 설명까지 해시 | ManyLives 59915·59900 |
| D10 | 참고 | 평가한 추천 전부 "Selected tool check: not separately recorded". 보고서 3,894건 중 3,841건에 도구명이 있으나, 추천된 후보에는 보고서가 없어 도구 단위 근거가 표시되지 않는다 | 정상 동작이지만 사용자에게 주는 정보는 작다 | — |

해결이 확인된 항목:
- 설계 F1: 한국어 계약서 표현에서 검색어가 추출된다.
- 2,000자 상한: 500자 절단이 없다.
- 일본어 정규화: 운영 모델에서 0.7~1.2초에 정상 변환된다.
- 조건 보존: doi, no_api_key, pdf_input, json_output이 파싱된다.
- 프로토콜 정책, 정렬 정책, 결제 문구 비표시.

정정: 처음에 하네스가 옛 설정(`gemma3:1b`)을 읽어 일본어 정규화가 실패한 것처럼 보였다. 서비스와 같은 프로필 적층으로 고친 뒤 재측정했고, 해당 항목은 결함에서 뺐다. 참고로 옛 모델은 콜드 로딩 7.5초, 출력 형식 오류가 있었다.

## 5. 권고 (우선순위)

1. **D3 수정 (작은 변경, 효과 큼):** `search for`, `searching for`, `look up`을 "look for"처럼 기능 동사구로 처리한다. 정규화 출력 경로까지 회귀 테스트를 추가한다.
2. **D2 수정:** `pdf_input`은 입력 스키마의 파일/URL 필드나 "from/of a PDF", "PDF … into" 같은 방향 표현을 요구한다. "to PDF", "PDF synthesis", "generate PDF"는 위반이나 불명으로 판정한다.
3. **D1 개선:** 최근성 정렬은 유지하되(AGENTS.md), 적격 문턱을 강화한다. 기능 동사와 작업 대상이 같은 도구에서 함께 맞아야 하고, 데모·고정 샘플·다른 대상 전용 도구(퀴즈, 아카이브 레코드, 주소)를 제외한다. 동률 묶음 안에서만 관련도를 쓰는 방안도 검토한다.
4. **D4·D5:** 긴 요청은 모든 절에서 기능어를 모은다. API 키 조건 패턴을 넓힌다.
5. **D8:** "about/on/for + 프로토콜명" 같은 주제 표현을 선택자로 보지 않는다. x402는 명시 선택(선택자 또는 "x402 only/via x402") 때만 켠다.
6. 이 27개 질의를 고정 평가 세트로 삼아 수정 전후 Top-1과 Top-3 적합 수를 비교한다. 설계의 대표 600건 평가로 확장한다.

## 6. 증적

- `queries.json`: 질의 27개와 기대 결과.
- `results-operating-profile.json`: 운영 프로필로 실행한 결과(추천 ID, 도구, 근거, 지연).
- `nl_eval.py`: 읽기 전용 평가 하네스. 운영 DB 쓰기와 제공자 호출이 없다.

## 7. 결함 수정 (2026-10-26 밤)

우선순위대로 수정했다. 작업 트리 기준이며 **운영 배포 전**이다(운영 프론트는 활성 배포본 `weather-news-contracts-20261026-r1`).

| # | 수정 | 위치 |
|---|---|---|
| D3 | 문장 시작의 "search/look/hunt for X"는 X를 기능 대상으로 둔다. 정규화 문구 "academic paper search for …", "web search for …"는 기존 경계를 유지한다. 원문 뒤에 붙는 정규화 결과(". Search for papers")에도 적용한다 | `selection.SEEK_PHRASE`, `capability_terms` |
| D2 | `pdf_input`은 방향을 본다. PDF를 만드는 표현("to a PDF", "PDF synthesis", "generate/render … PDF")만 있고 읽는 근거("from an invoice PDF", "PDF into JSON", extract/merge/fill 등)가 없으면 위반 | `chat_task_spec.PDF_READS/PDF_WRITES`, `tool_fit` |
| D1 | (a) 데모·목업·고정 샘플 도구 제외(도구 이름이나 명시 문구 기준, 사용 예제 문구는 제외 대상 아님). (b) 기능어가 하나일 때 그 기능을 요청에 없는 대상에 묶은 도구 제외(`translate_quiz`, `address_translate`, `bitcoin_network`, `get_country_travel_weather`). 네임스페이스·줄임말·일반 대상(text/data/document)은 허용. (c) 언어 이름은 기능어가 아님. (d) 요청에 특정 플랫폼(YouTube, GitHub, arXiv 등)이 기능으로 있으면 그 플랫폼을 다루는 도구만. (e) 한 에이전트 안에서는 요청어를 가장 많이 담은 도구를 표시 | `selection._real_tool`, `_bound_elsewhere`, `_platform_served`, `_coverage`, `LANGUAGE_NAMES` |
| D5 | API 키 불필요 표현 확장("must not require/should not need an API key", "no authentication", "keyless", "doesn't need credentials"). 파서와 실제 필터가 같은 정의를 쓴다 | `chat_task_spec.AUTH_NONE`, `task_requirements.input_requirements_match` |
| D6 | 한국어 내용어가 두 별칭 사전에 없으면(배터리, 재활용, 유튜브, 시세 등) 언어 정규화를 시도한다. 모두 알려진 요청은 계속 모델을 부르지 않는다 | `selection.untranslated_words`, `fast_chat._fast_route` |
| D8 | about/regarding/concerning/explain/learn about 뒤의 프로토콜 이름은 주제다. 다른 위치에서도 언급하면 선택자로 본다 | `protocols.TOPIC_PROTOCOL` |
| D9 | 같은 이름·같은 상위 도메인의 배포(manylives.me / api.manylives.me)는 한 선택 | `task_requirements.provider_identity`, `selection` 중복 제거 |

| D4 | 300자 이상 요청이 0건일 때만 로컬 모델이 필요한 기능을 2~6단어로 요약한다(`summarize_task`, 0.4~1.1초). 요약은 원문에 없는 이름·숫자·URL을 넣으면 거부하고, 단어 절반 이상이 원문에 근거해야 한다. 검색은 "요약 for 원문"으로 해서 기능어는 요약에서, 주제·조건은 원문에서 온다. 짧거나 결과가 있는 요청은 모델을 부르지 않는다. 응답 데이터에 `task_focus`를 남긴다 | `chat_query_rewrite.SUMMARY_SYSTEM/validate_summary`, `llm.summarize_task`, `fast_chat._recommend_unobserved`, `front.py`·`gateway/server.py` 등록 |
| 추가 | 계정 불필요 표현 확장("should not need an account", "no login/registration") | `chat_task_spec.ACCOUNT_NONE` |
| 추가 | "find/search/look for … paper(s)/scholarly articles"를 논문 검색으로 정규화(번역 결과 "Find a paper about …" 포함) | `discovery.normalize_task` |

### 운영 카탈로그 재평가 (같은 27개 질의, 읽기 전용)

| 질의 | 수정 전 1~3위 | 수정 후 1~3위 |
|---|---|---|
| PDF 송장 → JSON | JSON→PDF, HTML→PDF, 송장 추출 | 송장 추출 3개 (모두 정답) |
| 624자 촬영 일정 (설계 F2) | 결과 없음 | 요약 "weather forecast" → 날씨 예보 도구 |
| 401자 송장 요청 | (신규) | 요약 "invoice data extraction" → PDF 송장 추출, pdf_input·json_output·no_account 유지 |
| 배터리 재활용 논문 (KO) | DOI 단건 조회, Urantia Papers | CiteMe, Crossref |
| 論文を検索して / Search for papers | 신뢰 인덱스, 지식 검색, 위키백과 | ArXiv 논문 검색, Crossref, Research Papers |
| translate English text to Korean | 아카이브 필드, 퀴즈, 고정 예문 데모 | 경전 구절 조회(부적합), AgentBIT 번역, AgentPay 번역 |
| 영어 문장을 한국어로 번역 | 주소 정규화 1개 | 위와 동일 (2/3 적합) |
| summarize a YouTube transcript | 오디오 전사 3개 | 적합 없음 (카탈로그에 활성 YouTube 자막 도구 없음, 정직한 무결과) |
| web search for recent AI news | ManyLives ×2, Agent Exchange | ManyLives, Agent Exchange, 게임 검색(약함) |
| weather forecast for Seoul | 날씨, 캠핑카 적합도, 스키장 | 날씨, 캠핑카 적합도, 날씨 |
| 논문 + DOI + API 키 불필요 | CiteMe, Diogenes, AgentBIT | CiteMe, Diogenes, Genexxis |

과제 질의 24개 기준 1위 적합: 수정 전 12 → 수정 후 14, 부적합 1위는 8 → 5로 줄었다.
- 새로 맞게 된 것: PDF, 일본어 논문
- 무결과로 바뀐 것: YouTube (이전 1위가 부적합했으므로 개선)
- 번역 2건은 3개 중 2개가 적합해졌지만 1위는 여전히 부적합(경전 구절 조회)
- 결과는 `results-after-fixes.json`.

남은 사례(D1 잔여):
- 번역 1위 "Read Quran Today get_ayah": 이름에 기능어가 없어 대상 묶음 규칙이 적용되지 않는다.
- 이미지 생성 1위 "Agent Market — General work contracts"(범용 작업 마켓 A2A): 수정과 무관하게 실행 검증 시각이 갱신돼 올라왔다.
- 비트코인 3위 "hiring signal".
- 이들은 설명 문장의 목적어까지 보는 판정이나 의미 재정렬이 필요하다.

### 검증
- 새 회귀 `tests/test_chat_nl_quality_fixes.py` 45건(D4 요약 검증·호출 조건, 논문 정규화 포함).
- 최종 회귀 524건 중 520건 통과. 실패 4건(`test_discovery_workflow_upgrade`)은 수정 전 기준선에서도 같이 실패하는 기존 결함이다.
- 넓은 회귀(194개 파일)의 실패 57건 전부가 기준선(운영 배포본 소스)에서도 동일하게 실패함을 확인했다. 즉 이번 수정으로 생긴 실패는 없다.
- 기존 채팅 품질 스위트 355건과 채팅 브라우저 26건 통과.
- 정적 검사: 수정한 운영 모듈 5개 지적 0건.

### 사고 기록: 테스트가 운영 서비스를 중지시킴
- 19:55:24, 넓은 회귀 실행 중 `tests/test_agentcon_cli.py`가 저장소의 실제 `agentcon`을 start/restart/stop으로 호출했다. 관리형 `gateway-data/services/state.json` 때문에 이 호출이 실제 launchd 서비스 제어(`scripts.service_deploy`)로 넘어가 운영 frontend·admin·proxy가 중지됐다. jobs·execution은 계속 동작했다.
- 사용자 승인 후 20:00경 `./agentcon start`로 기록된 활성 배포본을 복구했다. 상태 `stable`, 공개 사이트 200, `/admin/next` 200을 확인했다. 중단은 약 5분이다.
- 재발 방지: 이 테스트는 이제 임시 프로젝트 폴더에 `agentcon` 복사본을 두고 실행한다(`gateway-data` 없음 → 레거시·PID 파일 경로만 가능). 수정 후 실행 전후 서비스 PID가 동일함을 확인했다. 넓은 회귀 실행기는 실행 전후 launchd PID를 비교한다.
