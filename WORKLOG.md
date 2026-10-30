# 작업 기록 (짧게 유지: 끝날 때마다 몇 줄 갱신)

## 완료 (최근 것만)
- 개선 확인 12차 대응(2026-10-30, Explore 항목 제외): 24px 타깃(헤더 Test 탭·숨긴 select), Chat PostgreSQL 0건·`sending` 보정(Chat 전용 `retrieval_text`), 주 OpenAPI에 v1 entry·badge·openapi. 시험 통과, frontend `qa12-frontend-20261030-r2` 배포(r9 위 오버레이, Explore 세션은 r2 기준으로 다음 릴리스를 만들어야 함). CORS는 설계상 제한이라 사용자 결정 대기 → `reports/improvement-check-12-2026-10-30/README.md`
- CORS 절충안(2026-10-30, 사용자 결정): `/chat`·`/mcp` 읽기 전용 도구를 모든 사이트에 `*`로 개방(쿠키·Authorization 제거, Origin별 분당 60회), 실행·연락처·피드백·`/a2a`는 허용 목록만. frontend `qa12-cors-frontend-20261030-r2` 배포(r11 위). Explore 세션은 이 릴리스 기준으로 다음 릴리스를 만들어야 함
- 12차 남은 항목(2026-10-30 오후): 크롤러 본문은 이미 해결, 카테고리 페이지 본문 보강, Chat 사이트 감시+텔레그램(채널 표현·부분 채우기), 감사 스크립트 CORS 기준 갱신. 시험 통과, rest r1~r3 배포 후 Explore r15(내 변경 포함)가 활성. 재측정: 24px 0·axe 0·포커스 0, 시나리오 PASS 69/WARN 7. 엣지 워커가 다른 출처 `call`을 원 서버 검사 없이 처리 → worker.mjs 수정·시험 통과, 엣지 `05579c7d…` 배포·운영 확인(다른 출처 call 403)
- 12차 후속(2026-10-30): `hello` 설명 "Start here" 제거, `/` HTML·JSON에 `Vary: Accept`, 카탈로그 수 WARN은 판정 오류라 스크립트 수정, 메일 1위는 데이터(mifactory 검증 오르내림)라 코드 수정 없음. 릴리스 `qa12-frontend-20261030-vary-r1`(r16 + front.py·mcp_contract.py) 배포(슬롯 a, r16 보존)·운영 확인, 시나리오 mcp 17/17·llm_fetcher 6/6 PASS. 다음 frontend 릴리스는 vary-r1 기준
- 13차 대응(2026-10-30): 재측정 시나리오 74/1(남은 WARN x402 정책), UI/UX 타깃·axe·포커스 0, INP 최대 64ms. Chat 번역 언어 조건 수정(`translate`에서도 검사, 인도어 전용 범위, 한국어 언어명 별칭) → 릴리스 `qa13-frontend-20261030-r1`(vary-r1 기준) 패키징·검증, 배포 승인 대기. Origin·INP는 변경 없음. 기록 `reports/improvement-check-13-2026-10-30/`
- 남은 작업 진행(2026-10-28 저녁): Chat AI 고지·피드백·중지, Test 지연·캐시 표시, /status.json, Explore 커서, 전문 검색 SQL 3~4배(흔한 단어), 워크스페이스 이름·중복 안내·공급자 연결 바로 이동. ux6 배포·확인 → `reports/improvements-2026-10-28/README.md`
- 4차·UI/UX·워크스페이스 평가 반영(2026-10-28): 정적 파일 읽기 한도 제외(정상 사용자 15분 차단 해결), 내용 해시 캐시, 대비 0(라이트·다크), 포커스·24px, RFC 9457 인자 오류, 한도 헤더, 오타 제안, Chat 대안 요청, 워크스페이스 문구·이름, 기능 텍스트 v2(탐색 -23%) → `reports/improvements-2026-10-28/README.md`
- 기능 텍스트 사전 저장(2026-10-28): `agentcon_search.capability_text` 설치, jobs가 183k건 채움, Explore 콜드 약 9% 개선(결과 동일, 위반 0/199k). 홈 일일 스냅샷을 서버 원본에서 기본 접힘으로 변경 → `reports/capability-text-design-2026-10-28/README.md`
- QA 3차 후속(2026-10-28): MCP·A2A 규격 경계, 공개 조회 GET CORS, llms.txt 일일 스냅샷 숫자, 사설 주소·유료 call 문구, 결제 이유 코드(원 서버 501+reason, 엣지 워커가 결제 헤더를 원 서버로 전달), Chat 오타 교정 표시. `qa4-*` 4역할과 엣지 워커 배포·확인. 승인된 문의 1건 삭제. Explore 콜드 속도는 도구 계약 요약을 DB에 저장하는 설계 필요
- 개선 확인 3차 대응(2026-10-28): 체크박스 요청 1건, x402 카드 이름 보존, 429 대기 시간, 순번 후속 질문, 8004 안내, 다단어 오타 제안. 기능 색인 사전 계산은 측정 결과 효과 2%·메모리 0.5GB라 미적용. 전체 트리로 `qa3-*-20261028-r1` 4역할 배포 → `reports/qa-round3-2026-10-28/README.md`
- MCP·x402·A2A 수집·헬스체크·인증·사용 안내·평가, 14개 카테고리(agent_infra 포함, 분류 v5, 정밀도 84.9%)
- 맥 이전: 소스는 브랜치, 수집 DB는 `exports/` 스냅샷으로 전달 완료
- 사용자 맥 커밋: 관리 대시보드, 에이전트 전용 프론트(:8400, 로컬 LLM), SNS 피드
- 토큰 절약 조사 보고서(`reports/클로드코드 토큰 절약 방법.md`), CLAUDE.md·전역 규칙 적용

- Explore 검색 브라우저 테스트(2026-10-26): 개선 17건 → `reports/Explore 검색 브라우저 테스트.md`

- Chat 자연어 요청 브라우저 테스트(2026-10-26): 개선 14건 → `reports/Chat 자연어 요청 브라우저 테스트.md`
- 사이트 전반 브라우저 테스트(2026-10-26): 개선 14건, 핵심은 `#` 주소 변경 시 화면 미전환 → `reports/사이트 전반 브라우저 테스트.md`
- 자율형 에이전트 접속 테스트(2026-10-26): 종류 조사 12종 → `reports/자율형 에이전트 종류 조사.md`, 시나리오 76개 `scripts/agent_scenarios.py`(안내 `docs/qa/autonomous-agent-scenarios.md`), 결과 PASS 42·WARN 30·FAIL 4, 개선 20건 → `reports/자율형 에이전트 접속 테스트.md`
- 등록된 테스트 결과 보고서 품질 분석(2026-10-26): 2,855건(전체 3,998 중), 개선 13건 → `reports/테스트 결과 보고서 품질 분석.md`. 주의: 목록 API를 limit=300으로 90회 연속 호출한 직후 사이트가 502(재시작 필요)였음 — 대량 조회는 1건씩 0.5초 간격으로
- 보고서 개선 방안(2026-10-26): 판정 3단계·스키마·종류별 규칙·검수 R1~R8·적용 순서 → `docs/qa/test-report-improvement-plan.md`
- 등록 기능 테스트(2026-10-26): 개선 13건 → `reports/등록 기능 테스트.md`. 시험 데이터 남음(등록 206598·206599·206602~206604, 문의 7, 개인정보 3, 알림 tw_6a58) — 사용자 정리 필요. inspect는 분당 13회쯤 429, 5회 위반이면 사이트 전체 Auto-jail
- 등록 기능 개선 방안(2026-10-26): 서버 동의 검사·프로토콜 확인 등록·자기 도메인 거절·문의 CRLF/중복/한도·차단 범위·적용 5단계 → `docs/qa/registration-improvement-plan.md`
- 결제 기능 테스트(2026-10-27): 돈 안 씀(잔액 0 일회용 키), 개선 8건 → `reports/결제 기능 테스트.md`. 실제 결제 성공 흐름은 사용자 승인·지갑 필요. 게이트웨이 x402 경로는 20초 10회쯤 429
- 결제 기능 개선 방안(2026-10-27): 실패 이유 코드 10단계·실제 결제 확인 작업·상태 일치·v2 통일·한도·문구·OpenAPI → `docs/qa/payment-improvement-plan.md`
- 워크스페이스 기능 테스트(2026-10-27, 로그인 전 범위): API 138개·화면 6개, 개인 데이터 노출 0, 개선 8건 → `reports/워크스페이스 기능 테스트.md`. 로그인 뒤 기능은 맥 로컬 세션 필요
- Explore 검색 재시험(2026-10-27): 17건 중 개선 9·일부 5·그대로 3, Weather 칩 미동작, 속도 개선 없음(p50 1.8s, max 11.5s, 캐시 없음) → `reports/Explore 검색 재시험.md`
- Chat 재시험(2026-10-27): 14건 중 개선 6·일부 4·그대로 4, 속도 7.3s→4.9s(화면), 도구 매칭 도입·집합형 서비스 쏠림·서울 날씨 오답 → `reports/Chat 재시험.md`
- 개선 확인 종합(2026-10-27): 107건 중 개선 43·일부 18·남음 28·미확인 18 → `reports/개선 확인 종합.md`. 재확인 중 생긴 데이터: 문의 inq_aavyTwAl3VU17-qgKkXlZU8m 1건
- 개선 확인 2차(2026-10-27): 남은 22건 중 개선 1·일부 5·그대로 16, 회귀 4(Chat 다국어·속도, Explore 체크박스, 새 라벨) → `reports/개선 확인 2차.md`. 생긴 데이터: 문의 inq_LPrDvXkFp4nTjCVT_T2A7jtc
- 개선 확인 3차(2026-10-27): /api/agents/{id} 전부 500(Test 실행·Explore 상세 막힘), Chat 다국어·속도 복구, Explore 속도 개선(API p50 0.95s) → `reports/개선 확인 3차.md`. 생긴 데이터: 문의 inq_ObOcUR50djvGsukLwApp8UJi
- 개선 확인 4차(2026-10-28): 상세 API·Test 예제 복구, A2A·MCP 규격 일부 개선, 정적 파일 no-store로 첫 화면 느림 → `reports/개선 확인 4차.md`
- UI/UX 평가(2026-10-28): 기준 `docs/qa/uiux-evaluation-criteria.md`, 측정 `scripts/uiux_audit.js`(axe·Web Vitals·키보드), 종합 64(C) 사람 62·에이전트 62·접근성 69, 개선 20건 → `reports/UI UX 평가.md`
- 개선 확인 5차(2026-10-28): UI/UX 68(C, 접근성 74 B), 정적 캐시·대비 0·커서·server.json 개선, 새 문제 CLS 전 화면 0.15~0.64·x402 게이트웨이 결제 501 → `reports/개선 확인 5차.md`
- 개선 확인 6차(2026-10-28): UI/UX 70(B 경계, 접근성 78), axe 0·포커스 링 4곳·INP 112ms, CLS 원인=첫 방문 2.3~2.9s 뒤 본문 밀림(쿠키 배너 추정) → `reports/개선 확인 6차.md`
- 개선 확인 7차(2026-10-29): UI/UX 71(B), CLS 0.104·검색 최대 1.49s·날씨 분류·오타 개선, 새 문제 모바일 가로 넘침(select#chatProtocol 533px)·Test 예제 전부 502/비활성·Chat 추천 흔들림 → `reports/개선 확인 7차.md`
- 개선 확인 8차(2026-10-29): UI/UX 73(B), 가로 넘침·Test 예제·Chat GitHub/번역 해결, 회귀 MCP readOnlyHint 4개 false. uiux_audit.js가 로그인 버튼을 눌러 Google 페이지를 재던 문제 수정 → `reports/개선 확인 8차.md`
- 개선 확인 9차(2026-10-29): UI/UX 74(B), 속도 개선(Chat 1.9s, Explore 0.71s), 나머지 남은 작업 그대로(readOnlyHint, x402 402 표시, Chat 날씨·지시어) → `reports/개선 확인 9차.md`
- 개선 확인 10차(2026-10-29): UI/UX 75(B), Chat 영어 날씨·계약서 번역, Explore translate 개선. 나머지 그대로 → `reports/개선 확인 10차.md`
- 개선 확인 11차(2026-10-29): UI/UX 75(B) 유지, readOnlyHint·x402 402/403·포커스 링 해결, 회귀: 흔한 단어(data/api/agent/mcp)·의미 없는 검색어 0건, Test CLS 0.16, Explore 다시 느림 → `reports/개선 확인 11차.md`
- 개선 확인 12차(2026-10-30): 새 환경에서 시험 도구 재작성(스크래치 qa/), UI/UX 75(B), 11차 회귀 해결·Chat 지시어·RFC 9457 해결, 남은: Explore 지연 꼬리·오타 일부 회귀·타깃 76·CORS → `reports/개선 확인 12차.md`
- 개선 확인 13차(2026-10-30): UI/UX 75(B), 시나리오 69 PASS, CORS·카테고리 본문·Explore 꼬리·Chat 메일/PDF/PostgreSQL 개선, 회귀 Chat 번역→Bhasini(인도 언어), Origin 검사 → `reports/개선 확인 13차.md`
- 2차 개선 확인 보고서 회귀 해결 및 배포(2026-10-28): Chat 다국어(일/스/한) 의도 매칭 우회 차단 해제, Explore 체크박스 즉시 재조회(force=true), 카테고리 'Data-Analytics' 라벨 정규화(DB 49건 마이그레이션 + 프론트 별칭 매핑), Test 화면 Country Profile 기본 매개변수 매핑(133020 -> country_code: US, 627ms 완료), 결제 10단계 실패 코드 검증, 릴리스 `qa-remediation-frontend-20261028-r1` 배포(슬롯 b 전환, PID 41438), 테스트 문의(inq_LPrDvXkFp4nTjCVT_T2A7jtc) 정리 완료

## 진행 중
- Explore A1(PostgreSQL 검색 문서) 운영 적용(2026-10-30 10:18~10:23): jobs/frontend/admin `explore-a1-*-20261030-r2`. 검색 문서 초기 적재 진행 중(10:25 기준 2,117건, 대기 219,183건). 적재 정체 위험이 있어 `status`로 확인 필요 → `docs/qa/explore-opensearch-design-2026-10-30.ko.md` 8절, `reports/explore-postgres-a1-2026-10-30/REPORT.ko.md` 6절. OpenSearch(B)는 A1 운영 재측정 후 결정
- Explore A1 r5(12:10 기준): jobs/frontend/admin r5·admin r6, 정책 `008d6c3a…`. 일괄 기록으로 약 2,350건/분, 노출 대상 대기 139.7천 건 감소 중(약 13:15 완료 예상) → 완료 후 8.3 조건 재측정. 독립 정답 집합 초안 201개 `docs/qa/explore-eval-tasks-2026-10-30.json`(사람 검토 필요). [15:40] 전체 테스트 624개 완료(실패 1개는 부하 18에서의 화면 대기 시간 초과, 재실행 통과). Chat 지연 분해·회로 차단 같은 이름 조회 색인화(115ms→1ms, 결과 동일) → frontend `explore-a1-frontend-20261030-r15` 배포(15:44, 활성 qa12-rest-frontend-20261030-r3 기준, 반복 Chat 서버 1.7~1.8초). r14는 SQL 목록 재생성 때문에 시작 실패(front.py 보고서 쿼리 누락) → 다른 세션 릴리스 위에 얹을 때 SQL 목록은 재생성하지 말고 내 파일 해시만 바꿀 것. 참고: qa12-rest-r1/r2의 SQL 목록(application_store_sql.json) 파일 해시가 갱신되지 않은 상태였음(r13에서 재생성). [16:10] 검증기 캐시 4096·거부 기억 배포: jobs r6·frontend r16·admin r7, 정책 `57e5ebe0…`, 문서 동등 3,000/3,000, 반복 Chat 서버 1.13~1.47초. 문서 재생성 분당 약 2,300건(17:50 전후 완료 예상) → [22:31] 재생성 완료(225,371건, 대기 0) 후 재측정: 반복 Chat 서버 0.98~1.58초(r16 직후와 같은 수준), Explore API 반복 0.70~0.98초, 오류는 무관한 x402 501 2건뿐. [10-31 01:00] Explore 캐시 미스 개선: 더 보기 재계산 제거(complete 결과 재사용)·중복 제외를 작업어 검사 앞으로·작업 사실 키 단일 계산. 결과 동일 188/188, 1쪽 -15%(p90 3.68→2.71s). frontend r17 패키징(vary-r1 기준) 완료, 배포는 분류기 차단으로 승인 대기 → 설계 문서 8.22. 다른 세션 qa13-frontend-r1은 selection.py(정책 파일) 변경 → frontend만 배포 시 문서 불일치 주의. 전체 시험 627파일: 실패 2(관리 화면 대기 시간 초과는 단독 재실행 통과, CORS 시험은 다른 작업자의 의도된 공개 /mcp 변경을 못 따라감). resource_at은 이미 일괄 처리라 변경 없음 → 설계 문서 8.21. 분류 VERSION 9는 dry-run이 65건이 아닌 1,759건(저장 분류 누적 차이)이라 보류. 미커밋 변경 다수(테스트 수정·scripts/agent_discovery_audit.py·operating.js·protocols.py·front.py 등). frontend r10(14:45, qa12-frontend-20261030-r2 기준)·r11(14:51) 배포: 예시 거짓 가용성·워크플로 사용 불가 안내·Chat 키보드 접근·병합 순서, 보고서 필터 묶음 50건(200건은 문장 제한 5초 초과로 500). 다음 frontend는 최신 활성 릴리스 기준. frontend r7(13:06) Recorded reports 필터 시간 초과 수정(일괄 읽기, 31초→4초)·운영 확인. frontend r6(12:46) 정확한 이름이 작은 limit에서 빠지던 문제 수정·운영 확인. 분류 규칙(ping/날씨어) 수정(dry-run 65건 변경), VERSION 9 일괄 갱신은 dry-run 후 승인 대기. 트리 `classify.py`의 다른 작업자 단독 "forecast"는 미배포, 오분류 유발 → 확인 필요
- 워크스페이스 워크플로우 자연어 생성 테스트: 계획 `docs/qa/workflow-test-plan.md` 작성. 로그인된 맥 Chrome이 필요해 맥 로컬 세션에서 실행 대기

## 다음
- 사용자 요청 대기

## 보류 (아이디어만 기록, 요청 전에는 착수하지 않음)
- Explore 검색 개선 17건 수정(보고서 우선순위 순)
- Chat 개선 14건 수정(의미 기반 매칭·대화 맥락·되묻기 우선)
- 사이트 개선 14건 수정(화면 전환·링크·이미지 우선)
- 에이전트 접속 개선 20건 수정(문장형 추천·sitemap 404·HEAD·MCP 주석·CORS 우선)
- 등록 기능 개선 13건 수정(서버 법적 동의 검사·문의 CRLF·프로토콜 확인 후 등록 우선)
- agent_infra 오분류 61개 추가 정리, 바로잡은 항목의 분야 키워드 보강
- ERC-8004 수집 완료 후 A2A 통계 갱신
- 클라우드 컨테이너의 수집기 종료(맥에서 이어 수집 중)
