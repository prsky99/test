# Chat 답변 품질 측정과 1차 개선 (2026-11-01)

- **목표:** CLAUDE.md "응답 시간 정책". RAG 답변은 5초 안에, 정확도 99%를 목표로 한다.
- **범위:** 공개 Chat의 자연어 요청 → 추천 1위. 워크스페이스 워크플로 생성은 따로 다룬다(아래 "남은 것").

## 측정 방법
- **스크립트:** `scripts/evaluate_chat_answer_quality.py`
  - 운영 카탈로그를 읽기 전용 연결로 연다.
  - 운영 코드의 `FastConcierge.handle`을 그대로 호출한다. 단계: 안내 판정 → 프로토콜 → 재작성 → 검색 → 대체 검색.
  - 쓰기(대화 기록·관측 기록)만 빈 함수로 바꿨다.
- **사례:** `tests/data/chat_answer_quality_cases.json`
  - `tuning` 105건: 영어·한국어·일본어·스페인어, 조건, 프로토콜, 오타, 긴 문장, 여러 의도, 안내·거절.
  - `holdout` 54건: 개선 전에 따로 써 두었고, 조정에 쓰지 않았다.
- **판정**
  - 추천이 있으면 1위의 "선택된 도구 이름과 설명"이 사례의 기능과 맞아야 한다. 묶음 서비스가 목록 설명에 모든 기능을 적어 두면 통과하던 문제를 막으려는 것이다.
  - 결과가 없으면, 사례에 미리 정해 둔 깨끗한 기준 문구로 다시 찾는다. 그것도 맞는 기능을 못 찾을 때만 "작동하는 에이전트 없음"으로 통과한다.
  - 예: 길찾기 후보 Openrouteservice·Mapbox는 실행이 실패한 상태라 제외하는 것이 맞다.
  - 안내·거절 사례는 상태값(`needs_redaction`, `needs_authorized_task` 등)으로 판정한다.
- **주의:** 같은 코드로 두 번 재도 1~2건이 오간다(검색 단계 시간 예산). 차이가 1~2건이면 잡음으로 본다.

## 원인 분석
- 추천 관문(`selection._search_protocol`)은 핵심어(`capability_terms`)의 대부분(4개 이상이면 75%)이 후보 글에 있어야 통과시킨다.
- 그런데 핵심어에 주제어가 섞인다.
  - "remote software engineering jobs" → `[remote, software, engineering, jobs]`. 원격 일자리 도구(Curaiz)는 "software engineering"이 없어 탈락했다.
  - "restaurants near Times Square" → `[restaurants, near, times, square]`.
  - 긴 문장은 첫 구절만 보고 `[small, shop, every, morning]`이 되어 'weather'가 빠졌다.
- 오타("wheather in pariss")는 맞는 단어가 없어 0건이었다. "my password is hunter2"는 비밀번호 노출로 걸러지지 않았다.

## 시도와 판단
- **버린 것 1:** 카탈로그 도구 이름에 자주 나오는 단어를 기능어로 보는 규칙. 'search', 'price', 'code' 같은 흔한 단어만 남기고 구체적인 단어를 버렸다.
- **버린 것 2:** 상승도(후보 비율 ÷ 카탈로그 비율)만 쓰는 규칙. 'engineering'(114)이 'jobs'(85)보다 높게 나왔다.
- **채택:** 결과가 0건일 때만 도는 대체 검색(`fast_chat.capability_focus`). 이미 결과가 있는 요청은 바뀌지 않는다.
  - 방식은 의사 관련성 피드백이다. 검색 엔진이 찾은 후보 120개 중, 가장 많이 공유된 단어의 절반에 못 미치는 단어는 주제어로 보고 뺀다.
  - 전치사·시간어("near", "last night")와 문장 중간의 대문자 고유명사("Times Square")는 빼고, 카탈로그 5% 이상에 나오는 흔한 단어만 남으면 다시 찾지 않는다.
  - 한 단어만 남으면 후보의 30% 이상이 공유하고 카탈로그 0.2% 이하에 나올 때만 쓴다.
  - 다시 찾은 결과는 남긴 단어가 모두, 선택된 도구 글에 온전한 단어로 있어야 보인다. "directions"가 "Directory"로 걸리는 것을 막으려는 것이다.
- **긴 문장:** 모델 요약 기준을 300자에서 100자로 내렸다(`chat_query_rewrite.SUMMARY_MIN_CHARS`). 요약어+원문으로 못 찾으면 요약어만으로 한 번 더 찾는다.
- **오타:** 카탈로그 어디에도 없는 단어가 있는 영어 요청은 기존 정규화 모델로 철자를 고쳐 한 번 더 찾는다. 이미 번역·재작성된 요청에는 하지 않는다.
- **비밀번호 노출:** "password is …", "비밀번호는 …", "암호: …"를 `needs_redaction`으로 처리한다(`chat_guidance.SECRET`). "password reset tool", "비밀번호 변경하는 방법"은 그대로 둔다.
- **진행 표시:** 새 단계로 'respell'(철자 확인)과 'narrow'(후보가 공유하는 기능으로 다시 찾기)를 추가했다.

## 결과 (운영 데이터, 릴리스 사본 코드)
| 세트 | 운영(snapshot-progress-r2) | 개선(chat-recovery-r1) |
|---|---|---|
| tuning 105 | 96 (91.4%) | 98 (93.3%) |
| holdout 54 | 44 (81.5%) | 49 (90.7%) |
| 합계 159 | 140 (88.1%) | 147 (92.5%) |

- **새로 통과한 것:** 식당(geo3), 원격 일자리(job1), 긴 날씨 요청(long1·h44), 논문 검색 한국어(h37), PDF 요약 긴 문장(h43), 오타 2건(h48·h49), 비밀번호 노출(h54).
- **응답 시간:** p50 1.3초, p95 3.3~4.5초. 5초를 넘은 것은 1건(long2 5.9초, 결과 없음)이다.
- **시험:** `tests/test_chat_zero_result_recovery.py`(9건). 릴리스 사본에서 Chat 관련 51개 파일을 돌렸고, 기준 사본과 같은 실패 15건 외에 새 실패는 없다.

## 남은 것 (99%까지)
- **정책 파일 `selection.py`를 고쳐야 하는 것:** "text to speech"(핵심어가 'convert'만 남음), "convert miles to kilometers", "movie recommendations similar to …", 위키 검색.
  - `explore_documents.policy_hash()`에 든 파일이라 frontend와 jobs를 함께 배포해야 한다. 그러면 검색 문서 재생성(약 100분)이 따른다.
- **카탈로그에 작동하는 에이전트가 없는 것:** 길찾기, 레시피 등. 정답은 "결과 없음"이고 이미 그렇게 답한다.
- **검색 단계가 흔들리는 것:** wk1·h9처럼 같은 코드로도 결과가 바뀐다. 시간 예산 안에서 벡터·후보 단계가 달라지는 것으로 보이며, 원인 조사가 필요하다.
- **워크스페이스 워크플로 생성:** 검색 전용(news·docs·product) 범위다. 10-31 시험에서 30건 중 6건만 성공했다. 실패 이유 표시, 모호한 요청 되묻기, 해로운 의도 거르기가 남았다(`reports/Workspace 워크플로우 생성 테스트.md`).

## 배포 (16:32, 활성 a)
- `chat-recovery-frontend-20261101-r1`을 배포했다. 슬롯 b에는 `snapshot-progress-frontend-20261101-r2`가 남아 있다. 프론트엔드 세션의 미배포 `support-lock-frontend-20261101-r1` 변경도 함께 나갔다.
- 운영 확인(공개 `/chat`):
  - 원격 일자리 → Himalayas·Remote Jobs by Country·Curaiz
  - "wheather in pariss" → 날씨 도구 3개
  - 식당 → Dish Directory·Safe Bite
  - 번역 → translate_text 도구 3개
  - 비밀번호 노출 → `needs_redaction`
  - 응답 0.8~4.4초, 배포 뒤 5xx 0건
