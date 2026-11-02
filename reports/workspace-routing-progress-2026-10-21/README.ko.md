# 워크스페이스 진입 경로와 중앙 로딩 수정

완료 기준: 워크스페이스 첫 화면에서 Workflows를 클릭하면 실제 워크플로우 스튜디오로 이동하고 Workflows만 활성화됩니다. 사용자 작업의 로딩은 화면 중앙에 표시되고 완료·실패·이동 취소 후 종료되며 자동 조회에는 표시되지 않습니다.

기존에는 `/customer/workspaces` 첫 화면의 Workflows가 `/customer/organizations`로 연결돼 Overview로 이동했습니다. 앞선 수정은 조직 화면에서의 중복 활성 표시만 해결했고 첫 화면의 잘못된 공통 링크는 놓쳤습니다. 이제 기본 Workflows 링크는 `/customer/workflows`로 연결합니다. 현재 권한을 다시 조회해 작업 공간이 하나이면 해당 스튜디오를 열고, 여러 개이면 이름으로 선택하며, 없으면 생성·초대 안내를 보여줍니다. 선택 화면에서도 Workflows만 활성화됩니다. 이름은 textContent로 출력하고 workspace ID를 검증해 HTML 삽입과 외부 URL 이동을 막습니다.

공통 진행 표시를 뷰포트 중앙으로 옮기고 모바일에서 문구가 불필요하게 줄바꿈되지 않도록 했습니다. 클릭·전송·변경으로 시작한 작업에만 표시하고 완료·실패 시 정리합니다. 저장하지 않은 내용 때문에 브라우저의 페이지 이동 확인을 취소해도 입력과 현재 화면이 유지되고 진행 표시는 종료됩니다. 구글·깃허브 로그인은 요청된 버튼 내부 진행 표시를 유지합니다.

고유 테스트 128개(브라우저 41개, 보안/API 87개)가 통과했습니다. 최종 결합 실행은 57개 통과이며 이 중 16개 API 테스트는 87개에 포함돼 중복 합산하지 않았습니다. `final-regressions.xml`, `security-regressions.xml`이 증적입니다. 공개 콘텐츠 237개 파일 검사 위반 0건. Bandit은 기존 HTML 문서 문자열을 SQL로 오인한 B608 1건을 검토했고 실행 가능한 SQL 변경은 없습니다. 보고서 `bandit.json`과 `summary.json`에 범위를 기록했습니다.

회귀에서 발견한 이동 취소 시 진행 표시 잔류도 수정했습니다. 예전 재시도 테스트는 401 이후 현재 보안 정책과 달리 로그인 화면 전환을 기대하지 않아, 복구 가능한 503 장애를 사용하도록 고쳤습니다. 401 즉시 비공개 화면 제거·로그인 이동 검증은 별도 세션 보안 테스트에서 유지됩니다. 초기 실패 결과도 보존했습니다.

증적: `before-wrong-workflows-route.png`, `fixed-workflows-1440.png`, `fixed-workflows-390.png`, `multiple-workspaces.png`, `centered-progress-desktop.png`, `centered-progress-mobile.png`, 동일 이름의 `-dark.png`.

현재 상태: 사용자 재시작 후 운영 검증 완료. PID가 98141에서 10810으로 변경됐고 검증 소스 해시가 일치합니다. 실제 공개 Chrome에서 `/customer/workspaces` 첫 화면의 Workflows를 클릭해 새 진입 경로를 거쳐 실제 스튜디오로 이동하고 Workflows만 활성화됨을 확인했습니다. 실제 Read current history 조회 중 중앙 진행 표시를 캡처했고 뷰포트 중앙 오차는 1px 이내였습니다. 조회가 끝나면 표시가 사라지고 버튼이 다시 활성화됩니다. 운영 증적은 `live-workflows-entry-fixed.png`, `live-centered-progress.png`, 서버 코드 반영 증적은 `post-restart-checks.json`입니다. 다중·빈 작업 공간과 모바일·실패·취소·자동 조회는 격리 검증 범위입니다. 이번 운영 확인은 기존 이력 조회만 수행했고 외부 워크플로우 실행·크레딧 사용·계정 변경·서버 재시작은 하지 않았습니다.
