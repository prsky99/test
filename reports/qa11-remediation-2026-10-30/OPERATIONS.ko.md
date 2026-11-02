# QA11 적용 명령

사용자의 QA11 두 웹 배포 승인을 받아 아래 두 후보를 적용했고, 실제 공개 API·브라우저와 두 웹 준비 상태를 확인했다. 현재 두 웹 모두 QA11 r1 활성 a다. 아래는 실행 이력이며 재실행 요청이 아니다.

```sh
./agentcon status
./agentcon deploy frontend qa11-remediation-frontend-20261030-r1
./agentcon deploy admin qa11-remediation-admin-20261030-r1
./agentcon status
```

배포 전 기준: frontend/admin 모두 qa10-remediation-각역할-20261029-r1, 활성 b. 배포 후: QA11 r1 활성 a, 직전 QA10 r1은 b에 보존. 상태가 바뀌면 다른 작업의 릴리스를 덮어쓰지 말고 먼저 비교한다. 새 후보는 각 역할의 활성 릴리스에 검토한 파일만 추가한 고정 패키지다.

DB 스키마 변경·Cloudflare Worker 재배포·jobs/execution 교체·모델 서버 재시작 없음. 기존 읽기 풀의 최대 연결 수도 유지한다.

적용 후 확인:
- data/api/agent/mcp와 a/*/the and of의 명시적인 카탈로그 안내, 선택 필터 보존, Load More/cursor 중복 없는 다음 페이지.
- weather forecast seoul, translate, github 등 공개 API 지연. 읽기 전용 내부 비교와 공개 HTTP 측정을 혼동하지 않기.
- 일반 날씨·한국어 계약서 번역·4턴 순번/it 참조. 토큰은 세션 전송에만 보관하고 화면·보고서에 노출하지 않기.
- Test 예제 로딩과 선택·실행, 결과 표시. 과거 보고서를 새 실행 기록으로 소급 변경하지 않기.
- MCP 조회 주석·기존 x402 검사 전용 경계·어드민 인증을 유지하는지 확인.

원자료: candidates.json, frozen-verification.json, reviewed-overlay.json, live-baseline.json, live-examples.json, readonly-recommendation-verification.json, readonly-hybrid-benchmark.json, isolated-ui-matrix.json, all-pages-targets.json, test-cls-*.json, test-page-*.png.

실제 적용 결과와 남은 한계는 REPORT.ko.md의 “승인 후 실제 운영 확인”을 참고한다. 추가 승인 없이 다른 후보를 적용하지 않았다.
