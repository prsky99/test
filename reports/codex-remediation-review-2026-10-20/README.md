# Codex 개선 작업 검수 결과

검수: 2026-10-20 21:30~ KST · 대상: 운영 서버(PID 65868, 21:24 재시작, 수정 파일 모두 재시작 전 저장 확인)와 공개 사이트 agentconcierge.biz
기준: `frontend-global-ux-ai-review-2026-10-20` 지적 사항, 전체 테스트에서 실패했던 21건, Codex 보고서(`public-ux-remediation-2026-10-20`)

## 1. 해결 확인 (운영에서 직접 확인)

| 지적 | 결과 |
|---|---|
| C-1 Chat 74~89초 + 화면 8초 중단 | **해결.** 공개 도메인 5건 모두 200, 2.8~7.6초. 화면 제한 30초로 변경 |
| C-2 PDF 송장 → IAM 정책 에이전트 | **해결.** 송장 질문에 송장 구조 추출(HALOWERK ZUGFeRD/Factur-X), 문서 추출(Second Eyes) 추천 |
| H-1 홈 지표 12.8초·빈 화면 | **해결.** `/api/overview` 0.8~3.2초 |
| H-2 모바일 첫 화면·로고 겹침 | **해결.** 첫 화면에 입력창·버튼, 로고 정상 |
| G-3/F-1 푸터 이메일 깨짐 | **해결.** `contact@agentconcierge.biz` 정상 표시 |
| R-1 AI 공시 링크 | **해결.** `#ai-transparency` → `ai` 경로 연결 |
| robots.txt 관리 경로 노출 | **해결.** `admin` 문구 없음 |
| G-1 메뉴 이동 시 스크롤 유지 | **해결.** 이동 후 맨 위 |
| G-4 쿠키 거부 후 추가 팝업 | **해결.** 팝업 없음, 선택 유지 |
| T-2 Test 결과 원시 JSON | **해결.** 제목·게시일·출처 카드, 시각 UTC |
| E-3/E-4 상세 화면 내부 용어, 실행 불가 항목의 Test 버튼 | **대부분 해결.** 인증 표현 사용자 언어로 변경, Use in Test → 도구 6개 정상 로드 |
| 인증 화면 JS 중복 선언(5건), SDK 동기화, 저장소 점검 CLI, ISO 날짜 | **해결.** 이전 실패 테스트 통과 |
| W-1/W-3 워크플로 0ms·원시 JSON·다이제스트 | **해결(Codex 운영 실측 기록 기준).** 실제 경과 시간·출처 카드 표시 |
| X-1 워크스페이스 순차 로딩 | **코드상 해결.** 멤버·초대·초안 병렬 조회 (세션 만료로 화면 미확인) |
| X-4 저장 워크플로 29개 드롭다운 | **해결.** 검색 가능한 라이브러리 카드 |
| X-7 체크박스 접근성 이름 | **코드상 해결.** 모든 체크박스 label 연결 |

## 2. 부분 해결 / 남은 문제

| 항목 | 상태 |
|---|---|
| **Chat 추천 관련성** | 송장은 해결됐지만 "latest stock market news" → 암호화폐 시세 도구(ManyLives), "battery recycling 논문" → 설명이 결제 플랫폼인 Agent Embassy(도구명 "Research Paper"만 일치). 도구 이름만 맞는 후보가 아직 통과함 |
| **Chat 답변 형식(C-3)** | 여전히 `Endpoint / Call / Tool / Grade` 기술 목록, 도구명이 "…he…"처럼 잘림. 추천 이유·한계 문장 없음 |
| **X-5 AI 워크플로 생성** | 지원 못 하는 요구(뉴스·요약)를 `needs_details`로 정직하게 안내하도록 바뀜. 그러나 실제로 뉴스 계약을 쓰는 계획 생성·요약 단계는 여전히 불가 (Codex가 범위 밖으로 명시) |
| **X-8 모호한 완료 문구** | `Current workspace action confirmed.`가 조직 화면·기존 작성 화면 2곳에 남음 |
| **E-3 카테고리 표기** | 상세 화면에 "travel maps weather"(내부 ID를 풀어 쓴 형태), 시각은 UTC가 아닌 EDT |
| **Explore 정확한 이름 검색** | "Weather & Geo Intel MCP"를 그대로 검색해도 1위가 아님(3,982건 일치) |
| **Cloudflare Web Analytics** | CSP 차단 콘솔 오류 계속. Cloudflare 대시보드에서 Web Analytics 자동 주입을 끄는 사용자 작업 필요 |

## 3. 아직 실패하는 테스트 (6건)

| 테스트 | 판단 |
|---|---|
| `test_a2a::test_deactivated_registration_withdraws_agent` | **실제 결함.** ERC-8004에서 비활성화된 등록이 수집기에서 내려가지 않음(active=1 유지) |
| `test_concierge::test_every_first_read_says_agents_only` | 테스트 기대값이 옛것. robots.txt 첫 줄이 의도적으로 바뀜 → 테스트 갱신 필요 |
| `test_concierge_llm::test_free_text_uses_local_aliases_without_llm` | 추천 URL이 게이트웨이 주소로 바뀐 의도적 변경 → 테스트 갱신 필요 |
| `test_gateway_execution_regression` · `test_managed_agent_gateway_browser` (2건) | 실제 사용자 경로(Explore → Use in Test)는 정상. 테스트가 `onTestbenchAgentChange()`를 직접 호출할 때 기본 예제 로딩과 겹쳐 선택이 무시됨(직접 호출 시 null 반환 재현). 경합 처리 또는 테스트 수정 필요 |
| `test_workspace_responsive_studio::test_primary_ai_action_library_search_themes_and_mobile` | 1920×780 화면에서 AI 입력 영역이 첫 화면 아래로 밀림 |

## 4. Codex가 의도적으로 범위 밖으로 둔 제안 (미구현)

SSE 스트리밍·통합 Ask(⌘K), 의미 검색 재순위, 범용 계획기·요약 계약, Explore 답변 박스·비교 도구, Chat 후속 질문 칩, 정책 문서 독립 URL, 카테고리 쏠림(S-2), 주간 큐레이션, 크레딧 시험 지급 표기(X-10), 조직 이름 불일치(X-3). `/new/en/*.html` 경로는 현재 게시 경로라 유지.

---

## 5. 후속 수정 (2026-10-20 밤, Claude)

서버는 재시작하지 않았습니다. Python 변경(추천·문구·Explore)은 **사용자 재시작 후** 반영되고, 공개 화면 정적 파일(`new/en`)은 다시 빌드해 즉시 반영됩니다. 빌드 전 `new/en`은 세션 임시 폴더에 백업했습니다.

| 항목 | 조치 | 파일 |
|---|---|---|
| Chat 추천 관련성 | ① 여러 스킬에 같은 홍보 문구를 복사한 경우, 도구 *이름*만으로는 근거로 쓰지 않음 ② 도구 하나가 작업어를 함께 다뤄야 통과(서로 다른 도구를 합쳐 하나의 역량으로 보지 않음) ③ "about/for/on" 뒤의 주제어(배터리 재활용 등)는 역량 판단에서 제외 ④ send/get/check 같은 흔한 동사 제외 ⑤ 주식 요청에 암호화폐 전용 도구 배제 ⑥ 디렉터리 검색 요청은 기존 예외 유지 | `concierge/selection.py` |
| 운영 데이터 읽기 전용 진단 | 논문 → ArXiv 논문 검색(이전: 결제 플랫폼 Agent Embassy), 주식 뉴스 → 미국 주식 데이터(이전: 암호화폐 시세), 번역 → 번역 도구 보유 AI Hub, 송장·날씨·웹 검색·지오코딩 유지 | — |
| Chat 답변 이유 | 서버가 일치한 작업어(`matched_terms`)를 함께 반환. 웹 카드에 "Why selected" 줄(일치 작업어 + 도구 설명), 텍스트 답변에 `Why`/`What it does` 줄. 도구명 80→140자 | `selection.py`, `fast_chat.py`, `extracted_html.txt`→`front.py`, `new/en` |
| Test 화면 선택 경합 | 늦게 끝나는 기본 예제 로딩이 사용자 선택을 덮어쓰지 않게 함 | `extracted_html.txt`, `new/live-assets/pearl-ui.js` |
| Test 결과 출처 누락 | `structuredContent`만 표시하고 텍스트 본문(두 번째 출처 등)을 버리던 결함 수정 | `extracted_html.txt` |
| 상세 화면 표기 | 카테고리 전체 이름 표시(“Travel, Maps & Weather”), 시각 EDT → UTC | `extracted_html.txt` |
| Explore 정확한 이름 | 검색어와 이름이 정확히 같거나 포함하면 맨 앞(추가 SQL 없음) | `concierge/front.py` |
| 워크스페이스 문구 | “Current workspace action confirmed.” → 작업별 문구(조직 생성·이름 저장·초안 저장·초대 발송) | `customer_organization_service.py`, `customer_authoring_view.py` |
| 옛 기대값 테스트 | ERC-8004 철회(새 설계: 비활성화 대신 `registry_missing_since` 기록), robots/llms/첫 화면, 게이트웨이 URL, 쿠키 확인 창 제거, 접힌 JSON 편집기, 결과 링크 카드 | 테스트 6개 파일 |
| 회귀 테스트 추가 | 상투 스킬명·주제어 분리·도구 묶음·흔한 동사·주식/암호화폐·단일 도구·정확한 이름 검색 | `tests/test_selection_capability_rules.py` |

**검증:** 공개 콘텐츠 237개 파일 위반 0, 변경 파일 한글 0자, JS 문법 통과, `front.py` HTML과 `extracted_html.txt` 일치, ruff F/E9 신규 지적 0(기존 지적은 그대로).

**하지 않은 것 (판단 필요)**
- **AI 워크플로 뉴스 단계:** 코드는 지원. 관리자가 뉴스 제공 에이전트 연결을 승인해야 생성기가 사용. 운영 승인 사항.
- **요약 단계:** 새 계약(요약 기능) 설계가 필요. 별도 결정 사항.
- **Cloudflare Web Analytics 콘솔 오류:** Cloudflare 대시보드에서 자동 주입을 꺼야 함(사용자 작업).
- **추천의 남은 한계:** 이메일 발송·도메인 사용 가능 여부·유튜브 요약처럼 단어 일치로 판별할 수 없는 요청은 의미 기반 재순위가 필요.
- **워크스페이스 화면 배치(1920×780):** 단독 실행 3회 모두 통과. 여러 브라우저 테스트를 함께 돌릴 때만 간헐적으로 실패하는 타이밍 문제로 판단.

---

## 6. 전체 테스트 후속 정리 (2026-10-21, Claude)

전체 7,521건: 37건 실패 → **1건 실패**(아래 "남은 1건"). 서버는 재시작하지 않았습니다.

| 구분 | 내용 | 파일 |
|---|---|---|
| **실제 결함 (공개 사이트)** | 로그인·가입·워크스페이스·계정 화면이 "Checking…"에서 멈춤. 빌드가 원본 화면의 *첫 번째* 스크립트만 복사하는데, Codex가 그 앞에 공통 진행 표시 스크립트를 넣어 실제 로그인 코드가 빠졌음. 공통 스크립트와 화면 스크립트를 순서대로 모두 넣고(미리보기 테마 스크립트만 제외), 화면 스크립트가 없으면 빌드가 실패하도록 함. 재빌드 후 공개 도메인에 반영 확인 | `new/build_en.py`, `new/en` |
| 회귀 (제 변경) | Test 화면 첫 예제 자동 선택, 일반 텍스트 결과 줄바꿈 | `new/live-assets/pearl-ui.js`, `extracted_html.txt` |
| 보조 스크립트 | Chat 실패 시 입력 복원이 옛 문구("Unable to complete")에만 반응하던 것을 새 문구도 인식하도록 함(본체도 복원하므로 이중 안전장치) | `new/live-assets/pearl-ux.js` |
| 옛 기대값 | Explore·Chat·워크플로 진행 표시가 중앙 로더 → 화면 내 표시로 바뀐 Codex 설계 반영(중복 전송 방지·입력 보존 검증은 유지), 쿠키 확인 창 제거, Chat 실패 문구, UTC 시각 | 테스트 6개 파일 |
| 운영 점검 스크립트 | 첫 화면(공개 사이트), robots/llms 첫 줄, Chat에서 연락처·인증 코드를 받지 않고 별도 동의 절차로 안내하는 현재 동작으로 갱신. 운영 서버 대상 26개 항목 통과 | `scripts/check_agent_front.py` |

**검증:** 공개 콘텐츠 237개 파일 위반 0, `front.py` HTML 동기화 일치, 변경 공개 파일 한글 0자, JS 문법 통과.

**남은 1건:** `test_workspace_prelaunch_browser::test_retry_optional_failure_and_invalid_manual_json_keep_editor_usable` — 세션 확인 실패 시 재시도 화면 대신 로그인 화면으로 이동. 2026-10-21 08:01~08:06에 다른 작업자가 수정 중인 `customer_identity_view.py`·`customer_workspace_pearl.py`·`workspace-interactions.js`와 관련된 것으로 보여 손대지 않음.

---

## 7. Chat 장애와 대표 도구 관련성 보강 (2026-10-21, Claude)

**Chat 503 (재시작 후 해결 확인):** 흔한 단어 질문의 A2A 후보 약 2.9만 건(150MB)을 한꺼번에 읽어 저장소 제한(128MB)을 넘음 → 순위 순서대로 500건씩 필요할 때만 읽도록 변경(`RESOURCE_BATCH`). 순위는 동일.

**대표 도구 관련성 규칙 (`concierge/selection.py`)**
1. 다른 API·에이전트를 찾아 주는 목록 도구("find a paid API", "Find an agent")와 관리 도구(API 키, invocation details, identify, health check 등)는 근거에서 제외. 도구 이름이 요청 단어를 직접 담으면 유지, 디렉터리 요청은 예외 유지
2. 작업어가 2개면 **한 도구**가 둘 다 다뤄야 함. "research/latest" 등 수식어, "to/from/into/in" 뒤 대상어(언어·통화)는 작업어에서 제외. "send"는 작업어로 유지
3. 도구 **이름**에 작업어가 최소 하나 있어야 하고, 설명은 첫 문장(괄호 속 부연 제외)만 근거로 사용. 도구 적은 에이전트 예외도 설명 첫 문장만 사용
4. translate/translation, extract/extraction, geocode/geocoding 같은 어형 변화 인정

**운영 데이터 비교 (읽기 전용)**

| 질문 | 이전 대표 도구 | 이후 |
|---|---|---|
| 웹 검색 (2건) | APEX "find a paid API" / allagents "Find an agent" | Agent Exchange "Web Search / Research" |
| 웹 페이지 스크랩 | APEX "find a paid API" | Flux "Web page to text in a real browser" |
| 이메일 발송 | Whisper "Get a Whisper API key" | 이메일 관련 도구(아래 한계 참고) |
| 푸시 알림 | 무관한 게임 | Clix "Send Push Notification" |
| 번역 | agentsvc.io "Text Translation" | AI Hub "Translate" |
| 유튜브 요약 | Weftly "Extract Vertical Clip" | Weftly "Summarize Video" |
| 지오코딩 | 장소 조회 | geocode 도구 |
| 이미지 생성 | 짧은 영상 클립 | Suede "Agent Image" |
| 환율 변환 | 렌터카 가격 조회 | 해당 없음(정직한 무응답) |
| 논문·주식·날씨·송장·받아쓰기·도메인 | 적합 | 유지 |

**테스트:** 회귀 테스트 4개 추가(목록 도구, 관리 도구·사용법 문구·괄호 부연, 두 작업어·대상어, 어형·이름 예외), 관련 테스트 360건 통과.

**남은 한계 (단어 일치로는 판별 불가):** "send an email" 1위가 이름에 send가 있는 문의 양식("send a brief")일 수 있음, "send a text message"는 에이전트 간 메시지 도구, "convert a PDF to JSON"은 PDF 렌더링 도구. 의미 기반 재순위가 필요.

---

## 8. Chat 간헐 503 (2026-10-21 09:46 재시작 후, Claude)

**증상:** 같은 질문이 몇 초 간격으로 200과 503을 오감(약 1.0초 만에 503). 순서대로 보낸 요청에서도 발생.

**원인 (확인):**
- PostgreSQL 로그에 Chat 세션의 `canceling statement due to lock timeout` 14회(09:47~09:49), Chat 트랜잭션 `lock_timeout=1000ms`와 일치.
- 저장소의 모든 쓰기 트랜잭션은 전역 쓰기 잠금(`WRITER_LOCK`)을 잡음. 60초 관찰에서 이 잠금 보유 시간의 약 40%가 벡터 백필 전체 조회(`vector.ensure.0`, 회당 최대 0.81초, 단독 실행 0.63초)였음. 이 조회가 쓰기 잠금 안에서 실행되어 Chat 방문 기록 쓰기가 1초 제한을 넘김.

**수정:** `PostgresVectorIndex.ensure_jobs`가 후보 조회를 **읽기 스냅샷**에서 먼저 하고, 쓰기 트랜잭션에서는 찾은 후보(최대 50건, 이미 등록된 `vector.ensure.N` 문장)만 기존 루프로 재확인·등록. 후보가 없으면 짧은 쓰기 트랜잭션에서 기존 `_pin`·`_bootstrap`만 수행. 조회 문장은 `_BACKFILL_SELECTION` 상수로 공유해 카탈로그 문장 그대로 사용(`legacy_vector_index.py`, `application_store_vector.py`).

**검증:** 임시 PostgreSQL 클러스터에서 원래 구현과 후보·등록 결과 동일(3건 → 재실행 0건), 조회 중 다른 연결이 쓰기 잠금을 즉시 획득함을 확인하는 테스트 추가(`test_postgres_ann.py`). 벡터·저장소 테스트 183건 + 103건 통과. SQL 카탈로그 `--write`(SQL 변경 없음, 소스 줄 번호·파일 해시만 갱신) 후 `--check` 일치.

**참고:**
- 수집기가 `https://api.carbon-cashmere.de/mcp/`에 대해 약 8초마다 `capability result bundle failed ... invalid_parameters` 경고를 반복함(별도 확인 필요).
- 검증 중 반복 요청으로 로컬 IP에 Chat 요청 제한(429)이 걸림 — 시간이 지나면 해제.
