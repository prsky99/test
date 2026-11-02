# PostgreSQL 전환 후 재시작 검증 완료

확인 시각: 2026-10-20T20:04:57.549628+09:00. 서버 PID 27984. PostgreSQL 전환 DB를 사용하고 있으며 이전 SQLite를 여는 운영 프로세스는 없다.

- 현황 API를 포함한 실제 조회 API 9개 모두 200. 보고서는 854건, 검색 결과는 페이지당 45건으로 조회됐다.
- 재시작 후 헬스체크 1,433건, 벡터 게시 558건 확인. 관찰 중에도 헬스 기록이 계속 증가했다. 이는 운영 백그라운드 작업의 실제 기록이며 시험 결과를 운영 DB에 넣은 것이 아니다.
- 재시작 이후 관찰 구간의 ERROR 로그 0건. 스캐너 차단과 잘못된 경로 요청에 대한 기존 보안 경고 3건은 있었다.
- 공개 도메인의 홈·현황·탐색·테스트·워크플로우 브라우저 화면에서 HTTP/JavaScript 오류 0건, 수평 화면 넘침 없음(1440px). Run Workflow 버튼 활성화를 확인했다. 버튼을 눌러 새 제공자 실행이나 외부 전송을 요청하지는 않았다.
- 수정사항을 검증한 격리 PostgreSQL·브라우저·API 회귀 215개 통과. 콘텐츠 검사 235개 파일 위반 0. 추가 재시작은 필요하지 않다.

수정한 원인은 호스트 집계의 일반 결과 제한, 공개 현황 집계의 PostgreSQL 경로 누락, 다른 스레드의 잘못된 조회가 벡터 트랜잭션을 실패 처리하던 동시성 문제다. 확정 롤백은 복구 가능하게 처리하며 실제 커밋 응답 유실은 계속 차단한다.

증거: `post-restart-summary.json`, `post-restart-api.json`, `post-restart-db-before.json`, `post-restart-db-after.json`, `post-restart-logs.json`, `post-restart-public-browser.json`, `post-restart-workflow-browser.json`.

화면: `home-before-restart.png`, `after-restart-overview.png`, `after-restart-status.png`, `after-restart-explore.png`, `after-restart-test.png`, `after-restart-workflows.png`.

최초 브라우저 도구의 워크플로우 선택자 누락은 별도 실제 메뉴 클릭으로 보완했다. 초기 격리 회귀의 필수 데이터 필드 누락 1건은 `native-running-service-final.xml`에서 수정 후 통과했다. 이전 실패 결과를 정상으로 바꿔 기록하지 않았다.
