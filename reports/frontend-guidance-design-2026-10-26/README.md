# Compact guidance and Workspace Overview design

## Applied design

이전 안내는 이미 보이는 선택·결과 옆에 설명 문단을 반복해 주요 작업과 경쟁했다. 실제 로그인된 Overview에서도 주요 버튼이 세로로 분리되고, 초대·권한·이름 변경이 한 영역에 섞이며 입력과 버튼이 붙어 있었다. Chrome Computer Use로 재현하고, 수정 후에는 격리 브라우저의 가상 고객 화면으로 배치와 기능을 검증했다.

이번 기준은 **현재 상태는 짧게, 추가 설명은 선택적으로, 필수 동의와 오류는 명확하게**다. 상세 설명을 삭제하거나 hover 전용 툴팁으로 숨기지 않고 키보드·터치로 여는 native disclosure로 통일했다. 새로운 실행/검색/크레딧 정책은 도입하지 않았다.

- **Home:** 여러 안내 문단과 daily snapshot을 `About these numbers` 한 곳으로 묶었다. 정상 갱신 시 중복 상태 문구는 숨기며, 갱신 오류는 계속 표시한다. 원래 snapshot 시각과 검색 메타데이터는 유지한다.
- **Explore / Status:** 범위 배지는 유지하고 검색 규칙·상태 정의는 짧은 펼침 항목으로 분리했다. 넓은 테두리 안내 박스는 제거했다.
- **Chat:** 추천마다 길게 출력되던 선정 기준을 `Why these matches?` / `Why these workflows?`로 접었다. 검증 증거와 실제 결과는 그대로 보인다. 프로토콜 안내도 한 줄로 줄였다.
- **Public Workflows:** `Default template` / `Restored selection` 등 짧은 상태와 `Selection details`를 같은 줄에 배치했다. 실행 불가 안내와 실제 단계 수는 유지한다.
- **Workspace:** 라이브러리·템플릿은 짧은 결과 수와 선택형 도움말로 정리했다. AI 화면은 입력 공유 동의 등 필요한 조치가 있을 때만 한 줄 상태를 표시한다. 정상 준비 상태를 반복 설명하지 않는다. 크레딧 잔액 설명도 선택형이며, 가입 약관·개인정보 확인·성인 동의와 실행/입력 공유 승인은 접어 숨기지 않았다.

## Overview layout

주요 Create with AI / Browse templates 버튼은 명확한 주·보조 스타일과 같은 행 배치를 적용했다. 좁은 화면에서는 공간에 맞게 줄바꿈한다. 제목·상태·카드의 가로 정렬과 최대 폭도 맞췄다.

펼친 관리 화면은 다음처럼 재구성했다.

- Members and invitations: 초대 폼 / 멤버 권한 관리 / 보낸 초대를 기능별로 묶었다. 넓은 화면은 2열, 좁은 화면은 1열이다.
- Workspace settings: 이름 변경을 팀 초대 영역에서 옮기고, 나가기·보관 동작과 간격을 분리했다. 이름 변경의 기존 관리자 권한 표시 조건도 유지한다.
- Workspace chooser / Invitations / Individual tasks: 같은 disclosure 여백, label–input 간격, 버튼 높이와 필드·작업 행 규칙을 적용했다.
- 멤버 식별자·역할 선택·Save role/Remove가 겹치지 않고 긴 내용은 줄바꿈한다. 단순 조회 완료 배너는 숨기며 실제 작업 확인·오류는 남긴다.

이동한 컨트롤은 기존 노드와 이벤트를 보존했다. 고객 권한·요청 검증·CSRF·서버 측 관리 권한·크레딧·삭제 확인을 바꾸지 않았다.

## Verification

- [공개 브라우저·보안 회귀](public-browser.log): **96 passed**.
- [Workspace·Overview·가입·세션 회귀](workspace-browser.log): **35 passed**. 320/390/900/1440px와 light/dark에서 모든 Overview 영역 및 중첩된 새 workspace 폼을 펼쳐 확인했다. label 간격·컨트롤 경계·버튼 겹침·주/보조 스타일·조회 중 POST 없음도 검증했다.
- [관련 API·권한·메타데이터](api-security.log): **134 passed**.
- [공개 주요 화면 시각 검증](visual-browser.log): **2 passed**. 390/1440px의 Home/Explore/Chat/Workflows/Status 이미지와 접힌 도움말 높이(38px 이하), 가로 넘침을 확인했다.
- 합계 **267 passed / failed·skip 0**. 초기 실패는 중첩된 create 폼을 열지 않은 배치 fixture와 의도적으로 바뀐 접힘/문구 기대값을 수정한 뒤 해소했다. 기존 권한 검증을 약화하지 않았다.
- [공개 콘텐츠](content.log): **293 files / violations 0**. 영어 전용, Chat 금전 표현, private/development 표시, embedded/extracted HTML 동일성 검사 통과.
- Python/JavaScript 구문, Pearl 빌드, 공유 도움말 CSS 동기화 통과.
- [SQL catalog](sql-catalog-check.log): **3,802 statements / 232 tables**, 현재 소스와 일치. source fingerprint만 갱신했으며 새 SQL/스키마/DB migration은 없다.
- [Bandit](bandit.json): 기존 `customer_organization_service.py:20` HTML/JavaScript 문자열에 대한 B608 1건. `organizations_page`는 HTML 응답 생성이며 SQL 실행 경로가 없는 오탐으로 검토했다. 결과를 보존했으며 무시 주석을 추가하지 않았다. 전체 플랫폼 무취약 보장을 의미하지 않는다.
- FastAPI TestClient httpx deprecation warning은 남아 있다. 검사는 기존 임시 테스트 도구를 재사용했고 운영 의존성을 바꾸지 않았다.

실제 고객의 저장/실행/초대/권한 변경/크레딧 차감은 하지 않았다. 수정본 운영 반영 후 실제 계정 화면은 별도 확인 대상이다.

## Visual checks

- [Overview · desktop · all sections open](overview-open-light-1440.png)
- [Overview · mobile · dark · all sections open](overview-open-dark-390.png)
- [Chat · compact selection help](public-chat-1440.png)
- [Workflows · selection status and details](public-workflows-1440.png)
- [Home · mobile](public-overview-390.png)

위 이미지는 가상 고객·격리 카탈로그다. 이미지의 availability 메시지나 목록 수를 실제 운영 에이전트 상태로 해석하지 않는다.

## Rollout

검증 패키지: **frontend-guidance-design-20261026-r1**. [release.json](release.json)과 [소스 일치 확인](package-source-check.json)을 참조한다. 운영 서비스는 변경하지 않았다.

```bash
cd <저장소>
./agentcon deploy frontend frontend-guidance-design-20261026-r1
```

배포 후 공개 화면과 Workspace를 전체 새로고침한다. frontend만 반영하면 되며 admin/jobs/execution 및 DB 변경은 필요 없다.

## Operator deployment verification

사용자 배포 후 `frontend-guidance-design-20261026-r1`, `ready=true`, 패키지 해시 일치를 확인했다. [운영 읽기 점검](deployed-smoke.json) **9건 통과 / 실패 0건**이다. 공개 안내·공유 스타일·크레딧 안내의 배포본과 비인증 private workflow 접근의 로그인 이동을 확인했다. 초기 Chat 문구 검사는 정적 HTML 대신 실제 동적 코드가 제공되는 operating.js로 바로잡았고 최초 결과를 보존했다.

로그인된 실제 Chrome Overview에서 Members and invitations, Individual tasks, Workspace settings, Workspace chooser, 중첩된 새 workspace 폼, 받은 Invitations를 펼쳐 확인했다. 초대/멤버 열, 역할 선택·버튼 간격, 초안 입력, 설정으로 옮긴 이름 변경, 주/보조 버튼 및 하단 영역이 수정본으로 표시된다. 실제 저장·초대·권한 변경·워크플로우 실행·크레딧 사용은 하지 않았다.

추가 공개 탭 이동 중 Computer Use가 Chrome 사용자 변경을 알려 추가 조작을 중단했다. 공개 화면의 이번 배포 검증은 HTTP/해시 확인과 기존 격리 시각 검증을 근거로 하며, 실제 계정 Overview 화면 확인과 구분한다. 이번 점검에서 추가 소스 수정이나 서비스 재시작은 없었다.
