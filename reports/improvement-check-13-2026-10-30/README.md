# 개선 확인 13차 대응 (2026-10-30)

13차 보고서(QA 세션)를 운영 상태와 대조하고, 같은 시험을 이 세션에서 다시 돌렸다. Explore 항목(오타 검색 `translte`·`gihtub`, `8004`, Agent Weather 금융 분류)은 다른 세션 담당이라 제외. x402 501 정책은 사용자 결정 사항이라 제외.

## 재측정(활성 `qa12-frontend-20261030-vary-r1`)
- 에이전트 시나리오: **PASS 74, WARN 1, FAIL 0** (12차 69/7). 남은 WARN은 x402 501(검사 전용 정책).
- UI/UX 40회 측정: LCP p75 0.72초, CLS 최대 0.083, INP 최대 64ms, axe 0, 24px 미만 타깃 0, 포커스 테두리 누락 0/980, 가로 넘침 0.

## 13차 새 문제
1. **Chat 번역 추천(수정)**: 언어 조건 검사가 `translation`에서만 켜지고 `translate`에서는 꺼져 있었음. 또 Bhasini는 언어 목록(`cap_languages`)이 비어 있어 걸러지지 않음.
   - `selection.py`: `translate`·`translator`에서도 검사. 언어 목록이 비면 설명의 지역 언어 범위(인도어 계열)를 보고, 요청 언어가 그 범위 밖이면 제외(`_regional_languages_cover`). "100+ languages" 같은 범용 표현은 통과.
   - `chat_task_spec.py`: 한국어 언어명 별칭 추가(스페인어·독일어·프랑스어·중국어·힌디어).
   - 시험 `tests/test_qa13_chat_gaps.py`(영→한 문서, 한국어 계약서, 스페인어, "스페인어로 번역해줘"는 Faceabot, 힌디어·언어 미지정은 Bhasini 유지). 추천·Chat 시험 297개 통과.
2. **Origin 검사(변경 없음)**: 이미 적용돼 있음. 다른 출처에서 `/a2a` → 403, 로그인 시작 `/api/customer-auth/begin` → 403, 세션 조회에는 CORS 허용 헤더 없음, `/mcp` 실행 `call` → 403. 13차는 공개로 연 읽기 도구만 시험한 것. 참고로 x402 게이트웨이 경로는 쿠키 없이 쓰는 공개 경로라 `*`.
3. **다크 모드 홈 INP 592ms(재현 안 됨)**: 같은 조건 3회 56·64·112ms, 전체 측정 최대 64ms.

## 13차 "그대로인 것" 대조
운영에서는 이미 해결된 상태: 24px 타깃 0, Chat SPF/DKIM(VerifyPulse)·이미지(Suede AI Agent)·사이트 감시(Shiftmoor+FlowCastle) 추천 정상, 크롤러 본문·카테고리 150단어·llms.txt와 OpenAPI 경로·상세 API 한도 헤더 모두 시나리오 PASS. 13차 측정이 12차 배포 전 상태를 본 것으로 보임.

## 릴리스
- `qa13-frontend-20261030-r1` = 활성 `qa12-frontend-20261030-vary-r1` + `selection.py`·`chat_task_spec.py`(바뀐 파일 2개만). 스테이징 시험 94개 통과, 패키징·검증 완료. **2026-10-31 사용자 승인 후 배포(frontend 활성 b, 이전 vary-r1은 a에 보존).** 운영 Chat 확인: `translate an English document into Korean`·`translate a Korean contract`·`translate to Spanish`·`스페인어로 번역해줘` 모두 1위 Faceabot Translate(Bhasini 없음), `translate Hindi to English`는 Bhasini 1위 유지.

## 후속(2026-10-31): Explore 오타 검색
- 운영 확인: `translte`·`gihtub`가 0건(교정 제안만 있음). `corrected_task`(검증된 오타 목록)가 Chat에서만 쓰이고 Explore 검색에는 쓰이지 않았음.
- 수정 `front.py` `/api/explore`: 목록에 있는 오타면 교정어로 검색하고 `corrected_query`와 `search_notice`("Showing results for "translate" instead of "translte".")를 돌려줌. 화면은 기존 `search_notice` 표시를 그대로 씀. 시험 `tests/test_explore_retest_fixes.py::test_known_misspelling_searches_the_intended_word`.
- 릴리스 `qa13-frontend-20261031-r2` = 활성 `explore-a1-frontend-20261031-r18`(qa13 번역 수정 포함 확인) + `front.py`만. 스테이징 시험 59개 통과, 패키징·검증 완료. 2026-10-31 사용자 승인 후 배포(frontend 활성 b, r18은 a에 보존). 운영 확인: `translte` 10건(1위 Translate), `gihtub` 9건(1위 GitHub), `wether` 10건(1위 Weather, Agent Weather는 상위에서 빠짐) 모두 교정 안내 표시. `weather`는 안내 없이 그대로, `8004` 레지스트리 안내 유지, Chat `translate to Spanish` 1위 Faceabot 유지.
- 손대지 않은 것:
  - Agent Weather 분류: AI 에이전트 생태계를 날씨에 빗댄 서비스라 현재 규칙으로도 날씨/금융 점수가 같음. 저장 분류 일괄 갱신(VERSION 9)이 승인 대기라 그 결정에 묶음.
  - `8004`: ERC-8004 등록 에이전트 목록과 "registry, not a task category" 안내가 이미 나옴(설계대로).
  - Explore 3초 꼬리: Explore 세션이 r17·r18에서 처리 중.
