# 공용 번들 최소 분리: 페이지별 operating.js 필요 여부 (2026-11-14, 성장·유통, PM 16:5x 지시, 목표 11-17)

## 방법
- 주 화면 9개를 공개 주소에서 두 번씩 열었습니다(1280, Playwright).
  - 한 번은 그대로 엽니다.
  - 한 번은 `bundle.js` 요청을 `operating`만 뺀 같은 목록의 번들로 바꿔서 엽니다(서버는 목록대로 번들을 만듦).
- 비교한 것: 콘솔 오류, 활성 패널의 글자 수와 조작 요소 수, 화면 사진 픽셀 차이, 주요 함수의 존재.
- 원자료는 `no_operating.jsonl`, 차이 사진은 `about-diff.png`(위가 원래, 아래가 operating 없음)와 `learn-diff.png`입니다.
- 나머지 공개 페이지 30여 개(정책·계정·로그인·워크스페이스 등)는 이미 `app.js`(28KB)만 씁니다.

## 결과
| 페이지 | operating.js 필요 | 근거 | 빼면 줄어드는 양(페이지당) |
|---|---|---|---|
| index(/) | 필요 | 첫 화면은 같음(차이 0%). 아래쪽 대시보드 숫자(`loadOverview`)와 Chat 시작이 operating에 있음 | — |
| explore | 필요 | 결과 카드 15개가 0개로(글자 8,015 → 746) | — |
| chat | 필요 | 보내기·답변 그리기(`sendChat`)가 operating에 있음 | — |
| test | 필요 | 예제·실행 조작 요소가 줄어듦(27 → 24) | — |
| workflows | 필요 | 템플릿 카드 8개가 0개로 | — |
| list-agent | 필요 | 등록 화면 글자 1,232 → 686 | — |
| learn | 일부 필요 | 본문은 같음. "Search learning guides" 검색 칸만 operating에 있음 | 검색 칸을 옮기면 약 89KB(br)·412KB(원본) |
| **about** | **불필요** | 본문 같음. 차이는 메뉴의 '현재 페이지' 밑줄뿐(0.02%) | **약 89KB(br)·412KB(원본), 실행 시간 약 0.5~1초** |
| **agent-status** | **불필요** | 본문 같음. 차이는 메뉴 밑줄뿐(0.04%) | **같음** |

- 공통 문제: operating을 빼면 모든 페이지에서 `PAGE_METAS is not defined` 오류가 납니다. `pearl-ui.js` 69행이 operating.js의 `PAGE_METAS`를 씁니다. 빼는 페이지에서는 이 줄이 operating 없이도 돌게 해야 합니다.
- 메뉴 밑줄은 HTML에 `aria-current="page"`와 활성 클래스를 미리 넣으면 operating 없이도 같게 보입니다. 이렇게 하면 화면 재작성도, 디자인 변경도 아닙니다.

## 판단
- 화면 재작성 없이 지금 뺄 수 있는 곳은 **about·agent-status 2개**입니다. learn은 검색 칸 하나만 옮기면 3개가 됩니다.
- 그러나 경로 손실로 느렸던 **workflows·chat·test·index·explore는 operating.js가 꼭 필요합니다.** 이 페이지들의 바이트를 줄이려면 operating.js를 패널별로 나누는 일, 곧 F16의 일부가 필요합니다. "최소 분리"만으로는 줄지 않습니다.
- 그래서 PM이 고를 것이 두 가지입니다.
  1. (작음, 11-15 가능) about·agent-status(+learn 검색 칸)만 operating 없이. 효과는 방문이 적은 페이지에 한정됩니다.
  2. (큼, 11-17 목표 가능 여부 미정) operating.js를 패널별로 나눔. 먼저 패널별 코드 크기와 서로의 의존을 재야 합니다. 화면·기능은 그대로 두고 파일만 나누지만, 시험 범위가 넓습니다.

## (2) operating.js 패널별 크기와 의존 (11-14 17시, PM 지시)
- 구역 머리말 기준 크기(원본 KB / gzip KB), 전체 원본 402KB, 통째 gzip 108KB:
  - 공통 핵심 약 70KB: head 9.2/2.8, 모달 12.1/3.8, 서식 2.9/1.4, 탭 전환 15.9/5.1, 쿠키 동의 6.8/2.1, 정책 문서·대화상자 19.5/6.7, 맨 위로 3.2/1.2, 시작 0.9/0.3
  - 화면별: overview 16.4/4.7, learn 68.1/18.9, explore 23.0/7.7, 등록 28.9/8.2, chat 60.4/17.2, 에이전트 상세 서랍 24.8/6.8, 워크플로우 스튜디오 68.9/18.1, 테스트벤치 41.7/11.1
- "공통 핵심 + 자기 화면"만 받을 때 페이지마다 줄어드는 양(추정):

| 페이지 | 남는 원본 | 줄어드는 원본 | 줄어드는 압축(108KB 중) |
|---|---|---|---|
| index(overview+chat 시작) | 147KB | 255KB | 약 66KB |
| explore(+상세 서랍) | 118KB | 284KB | 약 73KB |
| chat(+상세 서랍) | 156KB | 247KB | 약 64KB |
| test(+상세 서랍) | 137KB | 266KB | 약 70KB |
| workflows | 139KB | 263KB | 약 69KB |
| list-agent | 99KB | 303KB | 약 79KB |

- 의존
  - 탭 전환(`switchTab`)이 한 페이지 안에서 다른 화면으로 넘어갑니다. 나누면 아직 받지 않은 화면의 코드를 그때 불러오거나 페이지 이동으로 바꿔야 합니다(지금 메뉴는 `<a href>`라 이동으로 대체 가능).
  - 공통 head가 워크플로우 스튜디오 정의 18개, 테스트벤치 정의 20개를 참조합니다. 시작 코드가 여러 화면 상태를 함께 만집니다.
  - 정책·쿠키 코드는 head와 등록 화면에서도 쓰입니다.
- 판단
  - 11-17까지는 안전하게 어렵다고 봅니다. 의존을 풀고, 화면 코드를 그때 불러오는 장치를 넣고, 9개 화면 전체를 기능 캡처로 시험하는 데 2~3일 걸릴 것으로 봅니다.
  - 효과는 큽니다(페이지마다 압축 64~79KB, 실행 시간도 비례해 감소).
  - 제안: 첫 목걸이 공개(11-21) 뒤 F16의 첫 단계로 index → workflows → chat 순서로 진행합니다.

## (1) 실행: site-policy.js 분리와 about·agent-status·learn의 operating.js 제거 (11-14 18시, PM (가) 결정)
- 쿠키 동의와 정책 대화상자 코드를 operating.js에서 `site-policy.js`(32KB)로 옮겼습니다.
  - 옮긴 범위는 옛 637~995행과 1064~1077행입니다. 함수·상수 이름은 그대로입니다.
  - operating.js는 412KB → 390KB가 됐습니다.
  - 9개 주 화면 모두 `panels-bootstrap → site-policy → operating(있으면) → …` 순서로 싣습니다.
  - operating.js가 있는 페이지에서는 정의만 하고, 배너 시작과 버튼 처리는 operating이 예전처럼 합니다(두 번 돌지 않음).
- about·agent-status·learn에서는 operating.js를 뺐습니다.
  - 이 세 페이지에서는 site-policy.js가 동의 배너를 시작하고 정책 버튼 23개를 직접 처리합니다.
  - 확인 대화상자·알림은 operating이 없을 때만 같은 모양의 대체 코드를 씁니다.
  - pearl-ui.js는 operating이 있을 때만 그 함수를 감쌉니다(PAGE_METAS 오류 해결). 테마·메뉴·상태 새로 고침·현재 메뉴 밑줄·필터·앵커·바닥글 정책 링크는 공통으로 처리합니다.
- 이 세 페이지에서 달라지는 한 가지(PM 승인): '알림(Notifications)' 대화상자 안의 작업 알림 관리 목록은 Chat 코드에 묶여 있어 옮기지 못했습니다. 그 자리에 "Manage task notifications on the home page" 링크(`/#cancellation`)를 둡니다. 대화상자는 빈 채로 열리지 않습니다(시험).

### 동의 동작: 옛 코드(공개, 운영 중) 대 새 코드(작업본), 같은 클릭 순서 (`consent-before-after.jsonl`)
| 페이지 | 첫 방문 배너 | 수락 저장 값 | 재방문 배너 | 거절 저장 값 | 설정 저장 값 | 설정 대화상자 닫힘·확인 창 | 저장 키·쿠키 | 오류 |
|---|---|---|---|---|---|---|---|---|
| 9개 모두, 옛 = 새 | 뜸 = 뜸 | all, true, true, gpc false = 같음 | 안 뜸·값 유지 = 같음 | essential, false, false = 같음 | custom, true, false = 같음 | 닫힘·"Custom Preferences Saved" = 같음 | `agent_cookie_consent_v2` 하나, 필드 analytics·gpc·level·marketing·timestamp, 쿠키 0 = 같음 | 0 = 0 |

- 위 표는 9개 페이지 각각 옛·새 18건의 원자료를 줄인 것입니다. 다른 localStorage 키(`concierge_swr_…`)는 화면 데이터 캐시라 동의와 관계없습니다.
- 고친 동의 시험(설정 저장 뒤 확인 창이 뜨고 OK로 닫힘)은 옛 코드에서도 같은 순서로 통과합니다. 기준을 느슨하게 한 것이 아니라 예전 동작에 맞춘 것입니다.

### 불안정했던 시험 1건의 원인 (375·라이트·about 정책 대화상자)
- 원인은 시험 환경이었습니다. 모듈 단위로 같이 쓰던 앱에 모든 요청이 같은 시험 주소로 들어갔고, 앞의 동의 시험 9개가 요청을 쌓은 뒤 about·agent-status 페이지 요청이 요청 한도(429)에 걸려 빈 오류 페이지가 왔습니다. 진단에서 `(429, '/new/en/about.html')`가 기록됐습니다.
- 고친 것: 시험마다 앱을 새로 만듭니다. 바닥글이 없으면 응답 상태를 담아 바로 실패하는 진단을 남겼습니다.
- 이후 `test_site_policy_browser.py` 48건 + `test_lite_pages_browser.py` 5건이 함께 53 passed입니다.

### 시험
- 화면·번들·보안 묶음 199건 통과: test_pearl_frontend 전체, front_workflow_browser, workflow_library_build, main_ui_touch_targets, front_copy_style, home_about_layout, page_asset_bundles(번들 순서 기대값을 새 순서로 갱신), qa_round3_fixes, f17, front_dashboard_menus, front_security, pyflakes 정의, 새 시험 2개
- 게이트 목록에 넣은 것: 동의 9건, 알림 대화상자 3건, operating 없는 페이지 5건. 대화상자 36건 행렬은 시간이 길어 게이트 밖에서 돕니다.
