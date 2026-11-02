# 자율형 Agent 첫 이용·Workflow 발견 기능 개발 결과

완료일: 2026-10-25, Asia/Seoul. 통합 설계의 첫 개발 범위인 **목적별 첫 안내, Workflow 목적 검색, Chat·MCP·A2A 추천 연결, 안전한 재방문 문맥**을 구현하고 Frontend·Admin에 반영했다.

## 사용자 확정 정책

**모든 실행 결과는 크기와 무관하게 Edge가 우선이며, Edge 사용 불가·실패 때만 Origin으로 폴백한다.** 작은 결과를 정상 Origin 경로로 보내는 설계를 두지 않는다. Provider 실행이 이미 점유된 뒤의 응답 손실은 중복 실행 대신 기존 상태·receipt·안전한 결과 회수를 먼저 확인한다.

이 기준으로 설계 문서와 Canvas를 수정했다. **이번 릴리스에서는 Worker 코드·Cloudflare Route를 변경하지 않았다.** 모든 결과를 직접 Edge에서 반환하는 신규 MCP ingress와 Task 전달 확대는 남은 개발 범위이며, 이번 웹 기능 배포를 그 완료로 표현하지 않는다. 기존 Edge 실행·한도·중복 보호는 유지했다.

## 구현한 동작

### 첫 접속과 재방문

`GET /api/agent/v1/entry`, `GET /.well-known/agent-entry.json`과 JSON 홈 응답에서 Agent 추천·Explore·Workflow 검색·작업 재개·기존 task update의 목적별 다음 호출을 제공한다. 공통 Entry는 세션을 생성하지 않고, 기존 보안 헤더의 no-store 정책을 유지한다. 명시적 If-None-Match 확인은 지원한다.

`GET /api/agent/v1/resume`는 유효한 세션 헤더를 요구한다. 다른 세션의 대화나 URL query의 token으로 접근하지 못한다. 현재 작업과 다음 동작을 제공하며 Workflow의 게시 상태·정의 hash·실행 준비 상태가 바뀌었는지 확인한다. 기본 세션 기능을 재사용했으며, 다수 작업을 장기 보관하는 Task Passport 전체 구현은 아니다.

### 공통 Workflow 검색

검토된 공개 투영만 검색하는 `concierge/workflow_discovery.py`를 추가했다. 이름·설명·태그뿐 아니라 노드 이름·도구·입력 key를 참고하고, 한글·영문 동의어를 같은 업무 개념으로 정규화한다. 현재의 작은 템플릿 목록에는 외부 LLM이나 새 Vector DB를 추가하지 않았다.

뉴스·연구, 국가·지표, 패키지·보안 권고에 대해 단어·노드·자연어 목적을 처리한다. 복합 업무의 핵심 능력이 맞지 않거나 명시적 Protocol과 노드가 충돌하면 다른 능력의 Agent로 조용히 대체하지 않는다. 공개되지 않은 문서·테스트 정의·비활성 템플릿·철회된 서명 제품을 노출하지 않는다.

조회는 Provider나 Workflow를 실행하지 않으며 새로운 실행권을 발급하지 않는다. 실행 가능 상태는 기존 recorded preflight 범위를 유지한다. “검색됨”과 “실제 업무가 완료됨”을 구분한다.

### Chat·MCP·A2A 연결

Workflow 요청은 `find_workflow`로 분기해 관련 템플릿 하나, 이유·단계·현재 정의·상세/화면/다운로드 경로를 제공한다. 기존 개별 Agent 추천의 A2A 기본값·명시적 selector·검증/활동/등급 순서는 유지했다. Workflow의 명시적 Protocol 제약은 노드에 적용하며 생략 시 현재 공개 템플릿을 설명한다.

MCP에는 `search_workflows`, `workflow_details`를 추가했다. 기존 11개 도구·별칭·오류 신호를 유지해 현재 도구는 13개다. manifest·tools/list·초기 안내·Agent Card·LLM 안내도 일치시켰다.

`GET /api/workflows/templates/{template_id}`로 현재 공개 정의와 입력·노드·준비 상태를 조회한다. 새 생성·수정 요청은 Workspace 권한 안내로 연결하며 작성·게시·유료 기능의 권한을 검색으로 우회하지 않는다.

Workflow 추천 뒤 `details 1`, `more`, `what's new`는 Workflow 문맥을 유지한다. `what's new`는 실제 정의·준비 상태의 차이를 표시하며 같은 상태를 매번 새 변경으로 알리지 않는다. Workflow의 `failed 1`을 동명이 아닌 Provider ID의 실패 피드백으로 기록하지 않는다. 실제 Workflow 결과는 run key로 확인하도록 안내한다.

### 사람용 화면과 기계용 검색 일치

브라우저의 단순 문자열 필터를 공통 서버 검색으로 연결했다. 입력 debounce·취소·revision 검사를 적용해 늦은 검색 응답이 새 입력을 덮지 못하게 했다. 검색 장애는 “검색 불가”로 표시하며 검색 0건으로 숨기지 않는다. 입력을 비우면 원래 목록으로 돌아간다.

`operating.js`, embedded HTML, `extracted_html.txt`를 동기화하고 Home·Chat·Workflows의 공개 metadata도 갱신했다. 공개 소스의 문구와 주석은 English, 한글 입력 alias는 escape 형식이다. Chat 답변에는 세션 token·원본 JSON·구현 예시·요금 문구를 추가하지 않았다.

## 검증

- 관련 API·Agent 추천·MCP·Workflow·SEO·보안 회귀: **192개 통과**. 기존 OpenAPI Operation ID 중복 경고 1건이 남아 있다.
- 격리 Chromium의 신규 Workflow 검색·실패/복구·최신 입력, 기존 CSP·XSS·Chat 검사: **19개 통과**.
- 실제 Frontend 후보 패키지를 import한 API·브라우저 검사: **97개 통과**.
- 실제 Admin 후보 패키지를 import한 검사: **78개 통과**.
- 공개 Frontend 콘텐츠: **265개 파일, 위반 0건**.
- Python 컴파일, JavaScript 문법, embedded HTML 동기화 확인.

192개와 19개는 별도 검사다. 후보 패키지의 97·78개는 앞 검사와 중복되므로 합산하지 않았다. 처음 발견한 기존 MCP 도구 목록 기대치는 두 신규 도구를 포함하도록 갱신했다. 서명 제품의 철회 검사는 격리 fixture의 다른 공개 템플릿을 제외해 철회 자체를 검증했다. 추천·권한 기준을 완화하지 않았다.

Chromium의 초기 sandbox 실행 제한은 권한 있는 격리 실행으로 해소했다. 실제 외부 Provider 업무 호출이나 운영 서버를 이용한 부하 검사를 대체한 결과는 아니다. Bandit은 환경에 없어 실행했다고 보고하지 않으며, 소스 검토와 위 API·브라우저 보안 회귀를 수행했다.

## 운영 결과

기존 각 역할의 활성 릴리스를 기준으로 **변경 제품 파일 11개만** 반영했다. 다른 manifest 파일은 Frontend 1,202개, Admin 1,190개를 보존했다. 진행 중인 Admin 리뉴얼과 다른 개발 변경은 그대로 유지했다.

- Frontend: `agent-discovery-frontend-20261025-085641`
- Admin: `agent-discovery-admin-20261025-085641`

기존 승인된 A/B 교체를 사용했고 이전 슬롯을 유지했다. 준비 상태·페이지·자산·관리자 접근 차단·패키지 무결성을 확인했다. Jobs·Execution의 PID와 릴리스는 전후 동일하다. Worker 업로드·새 Secret·DB migration은 없다.

운영 공개 API에서 확인한 결과:

- Entry의 목적별 동작 5개, 응답 1,474 bytes.
- MCP 도구 13개와 manifest의 Schema 일치.
- `papers` → AI Research Reading List, Daily Tech News & AI Research Digest의 2개.
- `나라 지표` → Two-Country Economic Comparison, Country Development Snapshot, Country & Economic Indicator Brief의 3개.
- 영어 뉴스·관련 논문 Workflow 추천 문장 → Daily Tech News & AI Research Digest 1개.
- 세션 없는 resume는 401, 공개 상세의 현재 definition hash 일치.

Computer Use로 운영 Workflows → Browse templates → `papers`도 확인했다. 이전의 “일치 템플릿 없음” 대신 두 관련 템플릿이 실제 화면에 표시됐다. 운영 Catalog는 다른 작업으로도 갱신될 수 있으므로 이 수치를 고정 전체 수량으로 사용하지 않는다.

운영 검증은 메타데이터·목록·상세만 조회했다. 검증용 Provider 호출·Workflow 실행·결제는 0건이다. 기존 부하 캠페인·메모리 실패·읽기 전용 추적 파일은 변경하지 않았다.

## 다음 개발 범위

1. 모든 실행 결과를 우선 Edge에서 직접 반환하는 MCP ingress·SDK/Task 결과 경로와, 실패 시 안전한 Origin 전환.
2. 여러 작업을 보관하는 Task Passport·목적별 cursor·변경 이벤트와 compact MCP profile.
3. 승인된 Task의 prepare/run/status/cancel·부분 결과·receipt 회수와 구독·위임 결합.
4. 실제 유입 경로를 위한 Registry 게시·공식 Client·독립 목적 정답셋과 후속 24시간 자원 검증.

위 항목은 이번에 완료했다고 주장하지 않는다. 특히 Edge CPU·heap·이전 24시간 부하 실패는 후속 출시 조건으로 남아 있다.

원본 근거: `affected-api-tests-final.log`, `browser-security-tests.log`, `staged-frontend-tests.log`, `staged-admin-tests.log`, `staged-releases.json`, `live-verification.json`, `activation-result.json`, 작업 전 파일과 변경 patch.
