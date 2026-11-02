# Frontend layout system — 2026-10-26

## Scope and design

공개 9개 메뉴와 고객 화면 12종, 푸터 폼을 조사하고 배치·필드·버튼 간격을 정리했다. 실제 로그인된 Chrome에서 Overview, Provider connections, Support를 확인하고, 전체 화면 비교는 가상 고객과 격리 API를 연결한 Chromium으로 수행했다. 관리자 화면이나 검색/추천/실행 알고리즘을 변경하는 작업은 아니다.

공통 기준은 필드 안쪽 **8px**, 동작 사이 **12px**, 기능 그룹 사이 **24px**다. 관련된 선택과 실행은 함께 두고, 중요한 버튼은 보조 동작과 구분한다. 태블릿에서도 읽는 폭을 확보하고, 장식이 본문과 겹치지 않게 한다. 작은 화면은 필요한 지점에서 한 열로 바꾼다. 기존 Pearl 테마, Lucide 아이콘, 키보드 포커스, light/dark와 reduced-motion을 유지했다.

각 화면에 예외 여백을 흩어 놓는 대신 `new/live-assets/layout-system.css`를 공개 빌드와 고객 화면이 공유한다. 데이터·메타데이터·인증·필수 동의·실행 승인·크레딧 정책은 유지한다.

## Changes by screen

- **Home / Agent Status:** 지표·카드·상태 표의 간격과 읽는 폭을 맞췄다. 기존 안내 접힘과 집계 기준은 유지한다.
- **Learn:** 태블릿에서 지나치게 좁던 프로토콜 설명 카드를 읽기 쉬운 행으로 재배치하고, 본문 옆 메뉴를 작은 화면에서 위쪽으로 정리했다.
- **About:** 제목과 장식 진주가 겹치던 구성을 제거했다. 제목 크기·소개 폭·원칙 카드와 본문의 열 전환을 정리했다.
- **Explore:** 검색 필드·프로토콜·카테고리의 label 높이를 맞추고, 태블릿에서 가운데 떠 있던 검색 동작을 정렬했다. 긴 프로토콜 문구의 줄바꿈도 보완했다.
- **Test:** 도구와 요청 입력의 여백을 맞추고, 입력이 하나일 때 반쪽 폭으로 남던 필드를 넓혔다. 실행·초기화·결과 보기·고급 옵션의 간격을 정리했다.
- **Public Workflows:** 실행·다운로드·초기화·단계 수와 페이지 이동 도구가 좁은 화면에서 자연스럽게 재배치되도록 했다.
- **Chat:** 추천 카드·선정 설명·업데이트 버튼이 붙지 않게 하고, 긴 결과와 동작의 줄바꿈을 보완했다.
- **List Your Agent:** 폼 간격과 endpoint 확인 동작을 정리했다. 320px에서 잘리던 프로토콜 버튼 3개가 필드 안에 보이도록 수정했다.
- **Footer:** 모바일 문의 폼의 너무 좁던 2열을 1열로 바꾸고 label 간격과 제출 버튼을 정리했다. 알림·개인정보 선택·동의 동작은 유지한다.
- **Workspace access / Sign-in:** 공통 버튼의 width가 모바일 메뉴 버튼까지 늘려 화면을 밀어내던 문제를 수정했다. 로그인 카드가 grid 높이에 맞춰 불필요하게 늘어나는 문제도 수정했다.
- **Workspace account / credits:** 계정 화면의 중복 제목과 작업에 맞지 않는 소개를 정리했다. 가입 동의, 이력, 긴 설명과 링크의 간격·줄바꿈을 맞췄다.
- **Workspace AI / library / templates / review:** 생성 보조 동작을 한 그룹으로 묶고, 검색창–그룹 제목 간격, 탭·페이지 이동·필드·검토 화면의 뒤로 가기 위치를 정리했다. 새 선택이나 화면 이동이 저장/실행으로 이어지지 않는다.
- **Provider connections:** 검색·키 입력·공유 동의·저장/인증 확인의 여백과 주 동작을 정리했다. 키 마스킹·권한 제한·미선택 동의는 유지한다.
- **Support:** 넓은 화면에서 새 요청과 요청 목록을 나란히 보여 주고, 작은 화면은 한 열로 바꿨다. 입력 필드와 문의/답변 버튼의 간격을 맞췄다.
- **Private task / Recovery:** draft/snapshot 선택과 해당 조회 버튼을 묶고, 복구 승인·철회·확인 동작을 분리했다. 기존 컨트롤을 이동하며 ID와 이벤트, 권한/승인 경계를 유지한다.

이번 고객 화면 12종은 account, enrollment, support, workspace access, provider connections, private task, recovery, AI create, library, templates, template review, sign-in이다. 기존 Overview 배치도 관련 회귀에 포함했다. 외부 Google/GitHub/에이전트 제공자 승인 페이지와 게시되지 않은 디자인 reference 문서는 재설계 범위가 아니다.

## Verification

- [공개 기능·보안 회귀](public-regressions-final.log): **113 passed**. 메뉴, 검색/메타데이터, 첫 로딩, About, 푸터 접수·조회·알림 취소·개인정보 선택 및 CSP/XSS를 포함한다.
- [고객 기능·보안 회귀](workspace-regressions.log): **46 passed**. 로그인, 역할, Overview, 가입·크레딧, 연결 마스킹/동의, 워크플로우 검토·실행·다운로드, 복구, 세션 만료를 가상 계정으로 확인했다.
- [관련 API·권한·보안](api-security.log): **209 passed**.
- [최종 배치·시각 검사](layout-browser-final.log): **15 passed**, **57개 화면 상태**를 캡처했다. 공개 320/768/1440px와 고객/팝업의 모바일·데스크톱을 포함한다. 전체 가로 넘침뿐 아니라 프로토콜 버튼 개별 잘림, label 간격, 좁은 문의 폼, 메뉴 버튼 폭과 읽는 폭을 검증한다.
- 합계 **383개 고유 검사 통과**, 위 네 그룹 실패/skip 0. 마지막 간격 조정 후 [로그인·AI 화면 18건](auth-studio-final.log), [관련 재검증 4건](final-style-regressions.log)도 통과했으며 중복을 누적 건수에 더하지 않았다. 후자의 15 deselected는 명시한 선택 범위 밖 검사다.
- [공개 콘텐츠](content.log): **294 files / violations 0**. Python/JavaScript 구문, 빌드 및 embedded/extracted HTML 동기화 확인. 이번 변경은 기존 embedded HTML 내용 자체를 수정하지 않는다.
- [SQL catalog](sql-catalog-check.log): **3,802 statements / 232 tables**, 현재 소스와 일치. 새 SQL/스키마/DB migration은 없다.
- [Bandit](bandit.json): 기존 빌드 스크립트의 `assert` 경고 B101 1건(low), 분석 오류 0. 이번 변경 지점의 인증·SQL 실행 문제가 아니며 결과를 보존한다. 전체 플랫폼 무취약 보장을 의미하지 않는다.

초기 공개 검사 실패는 About 장식 표시를 강제하던 기대값과 오래된 푸터 테스트 데이터였다. 현재 화면 의도에 맞춰 장식 기대값을 바꾸고, 테스트용 날씨 에이전트에 명시적 도구와 version-bound 실행 증거를 만들었다. 운영 추천/검증 게이트를 약화하지 않았다. 지원 폼 캡처 fixture에는 격리 지원 스키마 초기화를 추가했다. 초기 실패 기록을 보존했다. 중복 시작한 격리 검사 한 건은 종료 후 최종 로그를 별도 파일로 남겼다. 운영 서비스는 종료하지 않았다.

실제 고객의 크레딧·계정·초대·권한·문의·키·워크플로우는 변경하지 않았다. 기능 검사의 저장/전송/과금 관련 동작은 가상 계정·합성 제공자 안에서 수행했다. 운영 의존성은 변경하지 않고 이전에 준비한 임시 테스트 도구를 사용했다. TestClient httpx deprecation warning은 남아 있다.

## Visual comparisons

- [About before](before/public-about-768.png) → [after](after/public-about-768.png)
- [Learn before](before/public-learn-768.png) → [after](after/public-learn-768.png)
- [Mobile workspace access before](before/workspace-access-390.png) → [after](after/workspace-access-390.png)
- [Support before](before/workspace-support-1440.png) → [after](after/workspace-support-1440.png)
- [Agent listing](after/public-register-320.png), [mobile inquiry](after/footer-contact-390.png)
- [AI create](after/workspace-create-1440.png), [library](after/workspace-library-390.png), [template review](after/workspace-template-review-390.png)

이미지는 가상 데이터다. 목록 수, availability 문구, 잔액을 운영 상태로 해석하지 않는다. 화면 이미지는 기본/준비 상태를 확인하며 모든 로딩·오류 상태의 시각적 완전성을 보장하는 자료는 아니다.

## Rollout

검증 패키지 **frontend-layout-system-20261026-r1**을 frontend에만 반영한다. [release.json](release.json)과 [소스 일치 확인](package-source-check.json)을 참조한다. 운영 서비스는 재시작·교체하지 않았다.

```bash
cd <저장소>
./agentcon deploy frontend frontend-layout-system-20261026-r1
```

배포 후 공개 화면과 Workspace를 전체 새로고침한다. admin/jobs/execution 재배포나 DB 변경은 필요 없다. 수정본의 실제 로그인 계정 최종 화면 반영은 운영 배포 후 확인한다.

## Deployment verification — 2026-10-26

사용자 배포 후 활성 frontend A 슬롯이 `frontend-layout-system-20261026-r1`인 것을 확인했다. 로컬/공개 각각 index, customer support, customer sign-in 총 6개 GET은 HTTP 200이며 CSP를 유지한다. 두 공개 CSS 응답의 SHA-256이 검증 릴리스 파일과 일치하고 고객 페이지에도 새 layout skin이 포함된다. [읽기 점검 결과](deployment-readonly-check.json).

실제 Chrome 새로고침 후 About·Learn의 수정된 배치와 화면 이동을 확인했다. 기존 Support 탭은 새로고침 후 재로그인 안내로 전환되어 인증된 고객 폼의 운영 시각 검증은 아직 확인하지 않았다. 로그인 만료 원인은 이 읽기 점검에서 확정하지 않았다. 실제 계정·크레딧·워크플로우·문의 데이터는 변경하지 않았다. 앞선 격리 기능·보안 383건 결과는 유지하며, 이번에는 소스 수정 없이 배포 확인만 수행했다.

## Authenticated operating review and final contrast correction — 2026-10-26

사용자 재로그인 후 실제 Chrome(데스크톱, 110% 확대)에서 Overview 기본/멤버 초대·설정 펼침, AI 생성 기본/보조 동작, 템플릿 목록·검토, 내 워크플로우 목록, 계정, 제공자 연결 선택·모달, 플랜·크레딧 이력 펼침, 고객지원을 확인했다. 새 입력·버튼·구역 간격과 Support의 좌우 폼/목록 배치는 운영에 반영됐다. 새로운 로그인 오류나 배치 중첩은 이 점검에서 발견하지 않았다. 모바일은 기존 격리 브라우저 검증 범위이며 실제 모바일 장치 검증으로 확대 해석하지 않는다.

다크 모드 템플릿 검토 배지는 밝은 고정 배경과 테마 글자색이 조합돼 흐리게 보였다. `workspace-studio.css`의 해당 배경을 `--aqua`, 글자색을 `--teal`로 함께 맞췄다. 기존 배포 r1과 새 r2의 실행 소스/자산 차이는 이 CSS 한 줄뿐이다. 라이트/다크 텍스트 대비 4.5:1 이상을 두 viewport에서 검사하도록 기존 배치 검사를 강화했다. [수정 후 가상 화면](after/workspace-template-review-dark-1440.png).

[관련 격리 브라우저 회귀](postlogin-regressions-final.log) **21 passed**, [공개 콘텐츠 검사](postlogin-content.log) **294 files / 0 violations**. 21건은 앞선 383건과 중복되므로 합산하지 않는다. 최초 샌드박스 실행은 Chromium Mach bootstrap 권한 오류로 시작하지 못했으며 기록을 `postlogin-regressions.log`에 보존했다. 허용된 격리 브라우저 실행 환경에서 최종 21건이 통과했다. 새 API, JavaScript, SQL, 인증, CSP 변경은 없다.

실제 계정 저장·워크플로우 생성/실행·크레딧 지출·제공자 연결·문의 발송은 수행하지 않았다. 실제 계정 화면 캡처는 보고서에 복사하지 않았다. 읽기 점검 완료 후 지원 화면을 열어 둔 상태다.

색상 수정까지 반영할 **최종 frontend 전용 패키지**는 `frontend-layout-system-20261026-r2`다. [패키지](release-r2.json), [소스·이전 릴리스 차이 검증](package-source-check-r2.json). r1은 이미 운영 확인됐으며 r2는 아직 배포하지 않았다.

```bash
./agentcon deploy frontend frontend-layout-system-20261026-r2
```

공개 화면·워크스페이스를 전체 새로고침한다. admin/jobs/execution/DB 변경은 필요 없다.

## Final deployment acceptance — 2026-10-26

사용자가 r2 배포를 완료했다. 활성 frontend B 슬롯은 `frontend-layout-system-20261026-r2`이며 패키지 매니페스트 검증도 통과했다. 실제 로그인된 Chrome에서 템플릿 카탈로그와 검토 화면을 열어 배지의 다크/라이트 모드 배경·글자 대비 수정이 반영됐음을 확인했다. 원래 다크 테마를 복원하고 내 워크플로우 목록으로 돌아왔다. 저장·실행·크레딧 차감은 없었다. 추가 소스 수정이나 검증 범위 확대 없이 이번 화면 배치 개선과 배포 확인을 완료했다. [최종 반영 기록](deployment-final-r2.json).
