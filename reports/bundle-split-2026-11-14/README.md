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
