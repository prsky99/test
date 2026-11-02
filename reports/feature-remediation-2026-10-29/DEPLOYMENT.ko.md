# 운영 반영·확인 결과

2026-10-29 KST. 승인된 상태 테이블·인덱스 추가와 네 서비스 r4 적용을 완료했고, 추가 승인된 웹 두 서비스는 검색 정렬·화면 보완 r2까지 전환했습니다.

## 최초 승인 범위의 r4 적용 기록

- frontend: `qa7-repair-frontend-20261029-r4` → `experience-frontend-20261029-r4`, b 슬롯.
- admin: `qa7-repair-admin-20261029-r4` → `experience-admin-20261029-r4`, b 슬롯.
- jobs: `qa7-repair-jobs-20261029-r4` → `experience-jobs-20261029-r4`.
- execution: `qa7-repair-execution-20261029-r4` → `experience-execution-20261029-r4`.
- 이전 웹 프로세스는 배포 관리자의 정상 롤백 정책에 따라 보존했습니다. PostgreSQL·모델 서버·프록시 프로세스 자체는 재시작하지 않았습니다.
- 상태 기록 테이블 1개와 동시 생성 인덱스 2개를 추가했습니다. 마이그레이션의 기존 행 변경은 0건이며 후속 check는 ready=true입니다.

## 실제 운영 검증

- 전환 중 공개 `/status.json`을 97회 확인했고 HTTP 응답 실패는 0회였습니다. 이는 약 4분의 표본 관측이며 영구 가용성 보장은 아닙니다.
- 홈·Chat·Explore·Workflows·로그인 페이지, 배포 자산 해시, 공개 캐시/304, HEAD, RFC 9457 오류, 상태 관측 등 10항목이 통과했습니다. 잘못된 워크플로우 ID의 오류 계약만 검사했으며 그 요청으로 워크플로우를 실행하지 않았습니다.
- 실제 브라우저 WebMCP에 검색·추천 도구가 등록됐고 `weather forecast for Seoul`의 MCP 검색 호출을 성공했습니다. 단순 모사 시험 외에 실제 등록·공개 검색 호출까지 확인한 범위입니다.
- 실제 Chat에서 서울 날씨 추천을 받고, 두 번째 항목을 선택한 뒤 `it`을 보냈을 때 동일한 Smarter Weather를 유지했습니다. 제공자 설명, 품질 구성 펼치기, 피드백 사유 입력/취소, 두 에이전트 비교가 정상입니다. 실제 실행하지 않은 외부 에이전트에 성공 피드백을 남기지 않았습니다.
- Technology News 예제를 두 번 실행했습니다. 첫 실제 데이터 조회는 게이트웨이 855ms·전체 1.5초였고 3개 항목을 반환했습니다. 재실행은 게이트웨이 117.3ms·전체 935ms였으며, 실행 시각과 별도로 원본 조회 시각 및 `(cached)`를 표시했습니다. 이는 두 요청의 실측이지 p75 성능 추정은 아닙니다.
- Explore의 2글자 자동완성, ArrowDown/Enter 선택과 최종 검색 결과 표시를 확인했습니다. 자동완성 후보는 로컬 사전으로 계산하지만 기존 Explore의 디바운스 자동 검색은 유지됩니다. 페이지 전체가 입력 중 네트워크 요청을 전혀 하지 않는다는 뜻은 아닙니다.
- jobs 시작 후 실제 상태 관측이 0→6건 이상으로 증가했고 성공 관측이 누적됐습니다. 해당 점검 시 90일 만료 메시지·관심사는 각각 0건이었습니다. 해당 점검에서는 만료 대상이 없어 과거 대화를 실제로 삭제한 건수는 0건입니다. 자동 유지관리 작업은 활성화됐고 관련 오류 로그가 없습니다.
- 점검용 원시 DB 집계 스크립트의 Decimal JSON 저장 오류는 스크립트에서 수정했습니다. 운영 상태 API는 Store의 숫자 정규화로 이미 정상이며, 제품 오류로 오인해 준비하던 불필요한 후보는 배포하지 않고 정리했습니다. 운영 r4와 동일한 집계 소스의 네이티브 PostgreSQL 직렬화 검사도 8개 통과했습니다.

## 검색 정렬과 화면 보완 r2 적용 완료

사용자의 단계별 명시적 승인에 따라 검색 API 보완 r1과 화면 보완 r2를 모두 적용했습니다. 현재 활성 웹은 아래 두 r2입니다.

- frontend: `experience-search-frontend-20261029-r2`, b 슬롯.
- admin: `experience-search-admin-20261029-r2`, b 슬롯.
- jobs·execution: 기존 `experience-jobs-20261029-r4`·`experience-execution-20261029-r4` 유지. PID도 각각 74786·75010으로 그대로입니다. DB를 다시 변경하지 않았습니다.

서버는 관련성보다 프로토콜 순서를 먼저 적용하던 통합 로직을 수정했고, 화면은 서버 순서를 A2A 우선으로 다시 덮어쓰던 정렬을 제거했습니다. 정확한 이름·작업을 명시한 이름·첫 설명을 우선하며 같은 단계에서 기존 증거·프로토콜 순서를 유지합니다. 공개 안내 문구와 embedded HTML·extracted HTML·manifest도 맞췄습니다.

실제 운영에서 확인했습니다.

- 자동/MCP 지정 GitHub 이슈 검색의 첫 항목: GitHub Issues and Pull Requests, ID 214845. 명시적 A2A는 A2A 결과만 유지합니다.
- 실제 카드 보기의 앞 네 항목: GitHub Issues and Pull Requests → landmine → Compuute MCP Security Scanner → SYNTHORA — M2M Intelligence Mesh.
- 목록 보기로 전환한 뒤에도 첫 항목 ID 214845 유지. 카드·목록 모두 가로 넘침 0이며 실제 배치와 텍스트를 캡처했습니다. 카드 보기로 복원했습니다.
- r2 정적 자산이 동결 후보 해시와 일치하며 기존 클라이언트 재정렬 코드가 제거됐습니다. API·프로토콜 필터·상태를 포함한 5개 운영 검사가 통과했습니다.
- r2 전환 중 공개 상태 주소 73회 관측에서 HTTP 응답 실패 0회입니다. 앞선 r1 관측은 78회 모두 성공했으며 별도 파일로 남겼습니다. 이는 관측 시점의 결과이며 무제한 가용성 보장은 아닙니다.
- 격리 검증: 서버/API 회귀 171개, 화면 순서 보존을 포함한 브라우저 20개, 보안 회귀 88개, 공개 콘텐츠 318파일과 두 동결 후보의 PostgreSQL·파일 해시 검증 통과.

이전에 자동 승인 검토가 정확한 r2 후보의 별도 승인이 없다고 거부했으나, 이후 사용자가 해당 두 r2를 명시적으로 승인하여 정상 배포했습니다. 현재 이 검색 정렬 변경에 남은 배포 승인 요청은 없습니다.

운영 화면 증적은 `deployment-search-r2-live.jpg`, `deployment-search-r2-list-live.jpg`, `deployment-search-r2-ax.txt`, `deployment-search-r2-ui.json`입니다. 검증용 `search-render-preview-*.png`는 격리 데이터이며 운영 캡처와 구분합니다.

## 증적

`deployment-status.json`, `deployment-schema-apply.json`, `deployment-schema-check.json`, `deployment-http-verification.json`, `deployment-public-monitor.json`, `deployment-maintenance-before.json`, `deployment-maintenance-after.json`에 실제 결과를 남겼습니다.

- 실제 비교 화면: `deployment-compare-live.jpg`.
- 실제 뉴스·캐시 화면: `deployment-news-cached-live.jpg`.
- 실제 UI 상태: `deployment-chat-ax.txt`, `deployment-news-live-ax.txt`, `deployment-news-cached-ax.txt`, `deployment-explore-ax.txt`.
- 실제 WebMCP 결과: `deployment-webmcp-search.json`.
- 추가 정렬 검증: `deployment-search-order-regression.log`, `deployment-search-order-browser.log`, `search-order-candidates.json`, `search-order-frozen-verification.json`.

Web Bot Auth의 실제 신뢰 키 등록, 실제 결제 정산, 사람·스크린리더 사용자 시험과 운영 장기 성능 관측은 기존 별도 수용 항목으로 유지합니다.
