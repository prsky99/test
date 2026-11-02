# 카테고리별 운영자 템플릿 확장 결과

검증 시각: 2026-10-25T09:11:09+09:00

운영자 템플릿 17개를 추가해 공개 Workflows 허브가 총 25개가 됐습니다. 기준은 현재 워크플로우 허브의 8개 분류입니다. 전체 에이전트 탐색의 별도 20개 분류를 이 허브에 임의로 추가하지 않았습니다. 기존 8개 템플릿과 고객 저장 워크플로우는 유지했습니다.

## 현재 공개 API의 실제 분류별 개수

- **Travel & Weather**: 3개, 기록된 실행 사전 조건 통과 3개.
- **Developer Tools**: 4개, 기록된 실행 사전 조건 통과 4개.
- **Data & Utility**: 3개, 기록된 실행 사전 조건 통과 3개.
- **Finance & DeFi**: 3개, 기록된 실행 사전 조건 통과 3개.
- **Automation**: 3개, 기록된 실행 사전 조건 통과 3개.
- **Sports & Health**: 3개, 기록된 실행 사전 조건 통과 3개.
- **Productivity**: 3개, 기록된 실행 사전 조건 통과 3개.
- **Docs & Knowledge**: 3개, 기록된 실행 사전 조건 통과 3개.

각 분류를 공개 API의 category 조건으로 직접 조회해 분류 일치와 최소 3개를 확인했습니다. 개발 도구는 기존 4개를 유지하고 나머지 7개 분류는 각 3개입니다. 전체 25개는 운영자가 제공하는 공용 수동 실행 템플릿이며 사용자 개인 워크플로우를 공개한 것이 아닙니다.

## 신규 항목 및 실제 운영 실행


**Travel & Weather 신규 항목**

- Accessible Travel Evidence Pack — ID 51, 실제 공개 실행 4.654초, 전체 단계 성공.
- Three-Destination Country Comparison — ID 50, 실제 공개 실행 1.564초, 전체 단계 성공.
- Destination Country & Tourism Research — ID 49, 실제 공개 실행 4.345초, 전체 단계 성공.

**Finance & DeFi 신규 항목**

- Financial Risk Research Board — ID 54, 실제 공개 실행 6.578초, 전체 단계 성공.
- Financial Technology Evidence Digest — ID 53, 실제 공개 실행 5.438초, 전체 단계 성공.
- Annual Economic Context Brief — ID 52, 실제 공개 실행 3.091초, 전체 단계 성공.

**Automation 신규 항목**

- Research-to-News Enrichment Pipeline — ID 57, 실제 공개 실행 4.822초, 전체 단계 성공.
- JavaScript Toolchain Release Inventory — ID 56, 실제 공개 실행 4.705초, 전체 단계 성공.
- Package Release Security Evidence Pipeline — ID 55, 실제 공개 실행 7.335초, 전체 단계 성공.

**Sports & Health 신규 항목**

- Sports Science Reading Pack — ID 60, 실제 공개 실행 5.480초, 전체 단계 성공.
- Two-Country Longevity Comparison — ID 59, 실제 공개 실행 1.404초, 전체 단계 성공.
- Population Health Context Brief — ID 58, 실제 공개 실행 1.851초, 전체 단계 성공.

**Productivity 신규 항목**

- Startup Market Background Pack — ID 63, 실제 공개 실행 5.636초, 전체 단계 성공.
- Frontend Technology Evaluation Pack — ID 62, 실제 공개 실행 6.310초, 전체 단계 성공.
- Technology Meeting Research Brief — ID 61, 실제 공개 실행 4.062초, 전체 단계 성공.

**Docs & Knowledge 신규 항목**

- Software Licensing Reference Pack — ID 65, 실제 공개 실행 5.780초, 전체 단계 성공.
- Knowledge Base Research Pack — ID 64, 실제 공개 실행 7.860초, 전체 단계 성공.

## 검증과 공개 조건

- 공개 전 실제 World Bank·npm·OSV·Crossref·Hacker News 데이터를 사용해 정확한 그래프를 검증했습니다. 등록된 도구 계약을 거치는 격리 MCP 실행 환경을 사용했습니다. 검증된 최신 버전은 각 후보 2회 성공했습니다.
- 초기 대량 검증에서 정상 MCP 호출 한도가 작동했습니다. 한도를 제거하지 않고 요청마다 간격을 둬 다시 검증했습니다. 실제 소스 검증과 운영 한도는 그대로 유지했습니다. 빠른 합성 단위 테스트만 짧은 테스트용 시간 창을 사용하며, 실제 호출 성능·한도를 그 테스트로 주장하지 않습니다.
- Package Release Signal Pipeline의 뉴스 원천 질의가 한 번 실패해 그대로 공개하지 않았습니다. 정확한 버전의 보안 권고와 소프트웨어 공급망 연구를 연결한 Package Release Security Evidence Pipeline으로 바꾸고, 수정한 그래프를 2회 다시 실행했습니다. 최초 실패 증적과 수정 증적을 함께 보존했습니다.
- 실행 증적의 그래프·입력·스키마·최신 시각과 운영 고정 연결을 다시 검사했습니다. 신규 항목을 합쳐도 분류별 실행 가능한 공개 템플릿이 3개 미만이면 추가 트랜잭션을 중단합니다.
- 운영 반영 후 공개 HTTPS 실행 서비스에서 17개를 다시 실행했고 모두 succeeded입니다. 각 항목의 ZIP 다운로드·무결성 검사도 통과했습니다. 실행 키 없는 결과 조회는 17개 모두 HTTP 404였습니다. 실행 키는 보고서에 저장하지 않았습니다.
- 같은 검증본을 운영 DB에 재적용해도 중복 생성이나 기존 정의 덮어쓰기가 없었습니다. 기존 8개 공개 항목과 고객·크레딧·일정·알림 설정은 변경하지 않았습니다.
- 단위/API 회귀 48개와 격리 브라우저·보안 회귀 12개가 통과했습니다. 브라우저에는 1440px·390px의 모든 분류 필터, 검색 조합, 실제 개수, 모바일 선택 후 스크롤, 기존 채팅의 CSP·출력 이스케이프·비밀값 비노출을 포함했습니다. 새 파일 정적 검사 및 JavaScript 구문 검사가 통과했고 공개 콘텐츠 265개 파일에서 위반이 없었습니다.

## 제공 범위

새 기능은 기존 6개 운영자 데이터 에이전트를 조합합니다. 여행 항목은 국가 정보·관광 및 접근성 연구이며 실시간 예약·날씨를 약속하지 않습니다. 금융 항목은 연간 통계와 출처가 있는 연구·기술 기사이며 투자 결론을 생성하지 않습니다. 건강 항목은 집계 통계·논문 목록이며 개인 진료나 운동 처방을 제공하지 않습니다. 자동화 항목은 수동 시작하는 수집·연결 파이프라인으로, 일정이나 외부 발송을 몰래 활성화하지 않습니다.

외부 원천의 향후 장애까지 보장하지 않습니다. 기존 실행 제어·스키마 고정·제한 시간·출처·캐시·실패 처리를 유지했고 결과를 만들어 성공으로 처리하지 않았습니다.

## 화면 개선 및 운영 반영 상태

템플릿 데이터 25개는 현재 서비스에 반영돼 있습니다. 추가 UI 개선은 별도 준비 릴리스에 담았습니다.

- 누락된 Docs & Knowledge 필터 추가.
- 모든 카테고리에 실제 개수 표시 및 선택 상태 aria-pressed 적용.
- 모바일에서 긴 허브 아래쪽 항목을 선택하면 선택된 워크플로우 제목으로 이동. 백그라운드 기본 선택에는 자동 이동하지 않음.
- 공개 페이지의 JavaScript URL 버전을 변경해 이전 캐시와 구분.

준비 릴리스: `frontend-template-categories-20261025-r1`. 최신 운영 `agent-discovery-frontend-20261025-085641`을 복제해 JS 1개와 해당 자산을 참조하는 HTML 9개만 수정했습니다. 다른 기능과 배포 내용은 보존했습니다. 사용자가 릴리스를 적용했고 현재 운영 버전과 자산 일치를 확인했습니다. 이번 확인 과정에서는 중복 교체나 프로세스 종료를 하지 않았습니다.

## 파일 및 증적

`operator_workflow_categories.py`, `operator_workflow_templates.py`, `publish_operator_templates.py`, `new/en/assets/pearl-ui.js`, 공개 HTML 9개, 카테고리 단위·브라우저 테스트를 추가·수정했습니다. 내장 HTML과 extracted_html.txt는 변경하지 않았으며 일치 상태를 확인했습니다.

실행: `live-source-execution.json`, `corrected-candidate.json`, `review-proof-final.sqlite3`, `publication.json`, `live-public-execution.json`, `live-category-counts.json`.

검증: `unit.log`, `category-final.log`, `integration.log`, `candidate-browser.log`, `content-check.log`, `lint.log`, `idempotent-publication.json`.

화면: `screenshots/docs-category-1440.png`, `screenshots/docs-category-390.png`. 현재 단계에서는 준비한 UI의 격리 검증 화면이며 운영 적용 후 화면과 구분합니다.


## 프론트엔드 적용 후 운영 확인

검증 시각: 2026-10-25T09:30:04+09:00. 사용자 재시작 후 활성 프론트엔드가 `frontend-template-categories-20261025-r1`임을 확인했습니다. 프론트엔드·어드민 readiness 정상, 홈 HTML HTTP 200 및 CSP 정상, 새 JavaScript 버전 URL과 검증한 릴리스의 실제 자산 해시 일치를 확인했습니다.

실제 공개 자산·API를 사용하는 Chromium에서 별도 JS 가로채기 없이 1440px·390px를 확인했습니다. 8개 분류를 모두 클릭해 개발 도구 4개·나머지 7개 각 3개가 표시되고, 선택 상태·문서/지식 필터·템플릿 선택 후 제목으로 이동이 정상입니다. 가로 넘침 0px·JavaScript 오류 0건입니다. 공개 API의 총수 25개와 기록된 실행 사전 조건 통과 25개도 확인했습니다. 실행 사전 조건은 완료 결과 보장이 아니며, 실제 17개 운영 실행 성공 증적은 앞 항목에 별도로 기록했습니다.

운영 증적: `live-deployment-verification.json`, `live-browser-after-deploy.json`, `screenshots/live-docs-1440.png`, `screenshots/live-docs-390.png`. 화면 개선의 운영 반영까지 완료됐습니다.
