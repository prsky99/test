# r2 실제 운영 적용 확인

2026-10-25 19:42~19:46 KST 확인. 활성 프론트엔드는 `frontend-request-quality-20261025-r2`, jobs는 `jobs-request-quality-20261025-r2`이며 서비스 상태는 stable이다. 실행 중인 공개 JS/CSS는 활성 릴리스 파일과 해시가 일치했다. 이 점검에서 서버를 다시 교체하거나 결제·크레딧·계정·워크플로우를 변경하지 않았다.

확인 결과:

- 공개 REST·A2A·MCP에서 AI 뉴스, 스포츠 뉴스, 서울 날씨, 일반 문서 검색, 불명확한 AI 요청, 불가능한 요청 6종을 실제 전송했다. 6종 모두 추천 ID가 일치했다. 후보가 있는 4종의 첫 번째 상세 조회도 세 경로에서 일치했다.
- AI 뉴스 첫 추천은 실제 기사 반환을 검증한 Technology News였다. 불명확한 요청은 작업 구체화를 요청하고, 불가능한 요청은 결과를 임의로 채우지 않았다.
- 공개 테스트 API와 MCP 연결 경로의 뉴스 실행은 모두 성공했다. 기사 2건의 제목·URL·발행일이 동일했다. 테스트 API 약 1.41초, MCP 약 0.80초였다. 캐시 상태가 달라 경로별 성능 우열을 의미하지 않는다. r1에서 확인했던 공개 실행 503은 이 확인 요청들에서 재발하지 않았다.
- 실제 데스크톱·모바일 Chromium에서 Chat 추천→Review task in Test를 클릭했다. 축약형 `params`/`required` 명세에서도 `ai news`가 실제 query 입력과 JSON에 보존됐다. 자동 실행 0회, JS 오류 0건, 수평 화면 넘침 없음, Run Test 활성화를 확인했다.
- 별도로 데스크톱의 Run Test 버튼을 실제 클릭했다. 원래 요청으로 기사 1건을 반환했고 제목·URL·발행일을 포함했다. HTTP 200, execution_succeeded=true, 실행 후 버튼 재활성화와 결과 영역의 Completed 표시까지 확인했다. 입력 limit=1에 따른 정상 결과다.
- jobs heartbeat는 정상 갱신 중이다. 19:44:36 KST 스냅샷에서 r2 jobs 시작 이후 색인 완료 162건, 최근 배치 완료 11건·실패 0건이었다. RAG 상태는 outbox였고 마지막 완료 시각은 시작 이후였다. 스냅샷 사이의 최근 배치 완료와 게시 행 증가도 확인했다. 재시작 이후 로그에서 기존 backfill database_error는 재발하지 않았다.

위 결과는 실제 수행한 대표 요청과 관측 구간의 수용 검사다. 모든 외부 에이전트의 전체 기능·언어·계정 조건이 항상 성공하거나 재방문율이 이미 개선됐다는 뜻은 아니다. 새 유입과 변경 작업이 계속 발생하므로 outbox 잔량을 항상 0으로 유지해야 한다는 의미도 아니다.

기능을 차단하지 않는 후속 UX 검토 항목: Chat에서 가져온 요청의 실행 전 안내가 실행 후에도 위쪽에 남는다. 아래 결과 영역은 정상적으로 Completed를 표시한다. 향후 문구 개선 시 실행 전·후 안내를 구분하면 더 명확하다. 이번 운영 확인은 핵심 검색·입력 전달·실행 결과·벡터 적재 동작을 대상으로 했다.

증적:

- `live-results.json`, `live-check.log`: 실제 공개 세 경로 비교와 뉴스 2건 일치.
- `browser-results.json`, `browser-check.log`: 데스크톱·모바일 요청 전달 검증.
- `browser-run-results.json`, `browser-run-check.log`: 실제 Run Test 클릭 및 결과 표시.
- `jobs-snapshots.json`: r2 시작 시각 이후의 색인 완료와 최근 배치 상태.
- `desktop-chat-before.png`, `desktop-test-after.png`, `mobile-chat-before.png`, `mobile-test-after.png`, `desktop-news-run-after.png`: 실제 운영 화면의 클릭 전후 캡처.

공급자 응답 전체는 0600 권한의 private 파일로 보관했다. 세션 토큰이나 방문자 신원은 보고서에 기록하지 않았다. 이전 r1 실패 증거는 기존 `post-deploy` 폴더에 보존했다.
