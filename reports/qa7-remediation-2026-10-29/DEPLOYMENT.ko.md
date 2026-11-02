# 운영 배포 및 공개 서비스 검증

2026-10-29, 사용자의 ‘배포해줘. 그리고 확인해줘.’ 승인으로 네 서비스를 배포했다. 현재 서비스 상태는 `stable`이다. PostgreSQL·Ollama·맥미니 모델 서버는 재시작하지 않았다.

## 적용 내역

- 프론트엔드: `qa7-web-20261029-r3` → `qa7-repair-frontend-20261029-r4`, 활성 슬롯 a.
- 어드민: `qa7-web-20261029-r3` → `qa7-repair-admin-20261029-r4`, 활성 슬롯 a.
- jobs: `ux7-jobs-20261028-r1` → `qa7-repair-jobs-20261029-r4`.
- execution: `ux7-execution-20261028-r1` → `qa7-repair-execution-20261029-r4`.

웹은 후보 슬롯의 준비 확인 후 프록시를 전환했고, 이전 r3 웹 프로세스는 롤백용으로 보존했다. 슬롯 a에 있던 더 오래된 r2 대기 프로세스는 배포 도구가 정리하고 새 프로세스로 교체했다. jobs·execution은 소유권과 기동 준비 확인을 거쳐 교체했다. 서비스별 파일 무결성은 배포 도구가 다시 확인했다.

## 실제 실행 결과

Test 예제 5개 모두 공개 API와 실제 Chromium 화면의 실행 버튼에서 성공했다. 모든 결과의 `execution_succeeded=true`, `simulated=false`를 확인했다.

- Technology News: API 1.28초.
- Research Papers: API 1.80초.
- Country Profile: API 1.10초.
- Package Metadata: API 0.97초.
- GitHub Issues and Pull Requests: API 1.59초.

UI에서도 예제마다 입력을 불러온 후 버튼이 활성화되고, 실행 후 Completed가 표시되는 것을 확인했다. 선택 직후 0.18~0.80초 준비 시간이 있었다. 최초 화면 자동화의 즉시 `is_enabled()` 관측은 이 준비 중 상태를 읽어 false로 기록했으므로, 그 결과를 실패나 완료로 단정하지 않고 실제 준비 완료를 기다린 뒤 다섯 버튼을 각각 클릭해 확인했다. 응답을 가로채거나 강제 클릭하지 않았다.

공개 운영자 워크플로우 3개도 실제 실행했다. 각각 트리거 외 조회 단계 두 개가 모두 `succeeded`이고, 단계 간 데이터 흐름 기록 두 개를 확인했다. 대체 제공자 자동 전환은 허용하지 않았다.

- Package Metadata & Advisory Review, #40: 1.93초.
- Country & Economic Indicator Brief, #39: 2.19초.
- Daily Tech News & AI Research Digest, #38: 4.55초.

jobs의 자동 재검증 로그도 `checked=7, succeeded=7`이었다. 실제 실행 검증 이력은 보존했다. 가짜 보고서·평가 성공 기록을 추가하지 않았다.

## 추천·화면·API 결과

안정 상태의 공개 Chat 재확인:

- ‘Translate English text into Korean’: Faceabot Translate 1위, 2.66초.
- ‘weather forecast for Seoul’: Faceabot Weather 1위, 2.32초.
- ‘Search GitHub issues about React hydration bugs’: GitHub Issues and Pull Requests 1위, 2.33초.

MCP에서도 날씨와 GitHub 이슈의 1위가 각각 동일했다. 번역 문서 요청에서도 Faceabot Translate가 1위였다. 한국어 ‘그 두 번째 것’ 후속 질문은 두 번째 후보의 상세로 이어졌다. 실제 화면에서 MCP 선택, Enter 제출, Calling details 열기, Learn 검색·검색 결과 이동이 동작했다.

Home·Chat·Workflows·Test·Explore를 320·390·768px, 총 15개 화면 조건으로 캡처했다. 문서 폭이 화면 폭을 넘는 경우는 없었고 프로토콜 버튼을 실제 클릭할 수 있었다. 브라우저 pageerror는 0개였다. 모바일 Workflows의 이번 짧은 측정에서 layout-shift 합계는 최대 약 0.038이었다. 실제 사용자 p75 CLS 측정이나 전체 사이트 접근성 인증을 의미하지 않는다.

공개 Markdown 응답, llms.txt, 에이전트 카드, skill.md가 정상 응답했다. 없는 에이전트의 API는 404와 `application/problem+json`을 반환했다. 허용한 출처의 MCP preflight는 204, 미허용 출처는 403이었다. 비공개 경로에는 CORS 허용 헤더가 없고, 공개 Explore 읽기는 wildcard 읽기 정책을 유지했다.

## 관측한 한계

jobs 교체 직후 첫 시험 중 번역 Chat 요청 한 번이 503 `SERVICE_BUSY`였다. 같은 시각 자체 에이전트 분석·증거 기록에 카탈로그 경합 경고가 있었다. 해당 Chat 오류 처리에서 실제 예외를 별도로 남기지 않으므로 503의 정확한 원인을 경합으로 단정하지 않는다.

같은 번역 요청의 후속 재시도는 200·2.16초였고, 이후 안정 상태의 번역·날씨·GitHub 세 요청도 모두 200이었다. 실제 브라우저 번역도 성공했다. 따라서 현재 정상 응답을 확인했지만 ‘배포 과정에서 오류 0건’이나 ‘503이 앞으로 발생하지 않는다’고 보고하지 않는다. 최초 원본 결과와 재검증 결과를 모두 보존했다.

실제 결제, 사용자 계정의 비공개 워크플로우 변경, 외부 메시지 발송은 하지 않았다. 어드민은 배포 도구의 준비·트래픽 전환 확인 범위이며, 이번에 관리자 71개 화면 전체를 재시험한 것은 아니다.

## 증적

- 활성 서비스: `deployed-status.json`.
- 공개 Chat·MCP·Test·HTTP: `postdeploy-api.json`.
- 초기 503 재확인: `postdeploy-retry.json`, `deployed-steady-verification.json`.
- 실제 화면·버튼: `deployed-browser.json`, `deployed-ui-examples.json`.
- 실제 워크플로우: `deployed-workflows.json`.
- 화면: `deployed-{overview,chat,workflows,test,explore}-{320,390,768}.png`.
- 완료 화면: `deployed-ui-completed-{technology-news,research-papers,country-profile,package-metadata,github-issues}-390.png`.
- 추가 화면: `deployed-chat-details-390.png`, `deployed-learn-390.png`.

시험 방문자 8명, 관심사 10건, 대화 24건, 전용 QA 방문 집계 2건은 비공개 백업 후 삭제했다. 실제 고객 데이터는 삭제하지 않았다. 실행 권한과 방문 토큰이 포함된 원본 응답은 공개 보고서가 아닌 접근 제한 디렉터리에 보관했다.
