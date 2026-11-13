# 홈 UI 정리와 About 진주 목걸이 복원 (성장·유통, 11-13, PM 09:4x·09:5x)

- 측정: `scripts/home_about_layout.py`. 같은 Chromium으로 1280·768·375, 어두운·밝은 화면을 열어 상자 위치를 읽었다.
  - 전(before): 공개 주소, 운영 align-frontend-20261113-r2(89ebf80b), 09:4x
  - 후(after): 이 작업본을 `--local`로 열었다. /new/en/은 작업본에서, 데이터는 공개 API에서 받는다. scripts.build_critical_css --local과 같은 경로다.
- 화면 사진: before/·after/에 홈·About 첫 화면(세 폭 × 두 테마)과 홈 전체(1280·375, 어두운 화면)를 남겼다. 원자료는 각 layout.json이다.
- 표는 어두운 화면 값이다(밝은 화면도 같은 값).

## 1. 홈 (토글 제거, 왼쪽·오른쪽 선, 세로 리듬)
| 폭 | 항목 | 전 | 후 |
|---|---|---|---|
| 1280 | 토글 | 있음 | 없음 |
| 1280 | 왼쪽 선(hero / band 내용 / 프로토콜) | 40 / 71 / 40 | 40 / 40 / 40 |
| 1280 | 오른쪽 선(지표 그리드 / 프로토콜 / 섹션) | 1209 / 1240 / 1240 | 1240 / 1240 / 1240 |
| 1280 | 프로토콜 카드 사이 | [20, 20] | [24, 24] |
| 1280 | hero 글 열 위 끝 − 목걸이 위 끝 | 7 | 0 |
| 1280 | hero→band / band 안 그리드→다음 | 8 / 0 | 32 / 16 |
| 1280 | 프로토콜 섹션 위 끝→첫 카드 | 27 | 41 |
| 1280 | See what's new.: 제목→다음 / 안내 문구→본문 | 14 / 24 | 12 / 24 |
| 1280 | Turn individual strengths in: 제목→다음 / 안내 문구→본문 | 14 / None | 24 / None |
| 1280 | Start with something useful.: 제목→다음 / 안내 문구→본문 | 14 / 16 | 12 / 24 |
| 1280 | Evidence you can inspect.: 제목→다음 / 안내 문구→본문 | 14 / 28 | 12 / 24; 그리드→note 28→24, note→details 20→24 |
| 768 | 토글 | 있음 | 없음 |
| 768 | 왼쪽 선(hero / band 내용 / 프로토콜) | 24 / 47 / 24 | 24 / 24 / 24 |
| 768 | 오른쪽 선(지표 그리드 / 프로토콜 / 섹션) | 721 / 744 / 744 | 744 / 744 / 744 |
| 768 | 프로토콜 카드 사이 | [20, 20] | [24, 24] |
| 768 | hero→band / band 안 그리드→다음 | 8 / 0 | 32 / 16 |
| 768 | 프로토콜 섹션 위 끝→첫 카드 | 27 | 41 |
| 768 | See what's new.: 제목→다음 / 안내 문구→본문 | 14 / 24 | 12 / 24 |
| 768 | Turn individual strengths in: 제목→다음 / 안내 문구→본문 | 14 / None | 24 / None |
| 768 | Start with something useful.: 제목→다음 / 안내 문구→본문 | 14 / 16 | 12 / 24 |
| 768 | Evidence you can inspect.: 제목→다음 / 안내 문구→본문 | 14 / 28 | 12 / 24; 그리드→note 28→24, note→details 20→24 |
| 375 | 토글 | 있음 | 없음 |
| 375 | 왼쪽 선(hero / band 내용 / 프로토콜) | 18 / 35 / 18 | 18 / 18 / 18 |
| 375 | 오른쪽 선(지표 그리드 / 프로토콜 / 섹션) | 340 / 357 / 357 | 357 / 357 / 357 |
| 375 | 프로토콜 카드 사이 | [20, 20] | [24, 24] |
| 375 | hero→band / band 안 그리드→다음 | 18 / 0 | 32 / 16 |
| 375 | 프로토콜 섹션 위 끝→첫 카드 | 1 | 33 |
| 375 | See what's new.: 제목→다음 / 안내 문구→본문 | 14 / 24 | 12 / 24 |
| 375 | Turn individual strengths in: 제목→다음 / 안내 문구→본문 | 14 / None | 24 / None |
| 375 | Start with something useful.: 제목→다음 / 안내 문구→본문 | 14 / 16 | 12 / 24 |
| 375 | Evidence you can inspect.: 제목→다음 / 안내 문구→본문 | 14 / 25 | 12 / 24; 그리드→note 25→24, note→details 20→24 |

- 섹션 사이는 섹션마다 위·아래 여백 var(--space-7)(40px, 375에서는 var(--space-6) 32px)과 위 구분선으로 만든다. 상자끼리는 맞붙어 있고(간격 0), 구분선에서 다음 내용까지가 41px(375에서는 33px)이다.
- 간격 토큰(pearl-live.css :root): --space-1~8 = 4·8·12·16·24·32·40·48px.
  - 제목→안내 문구는 --space-3(12px), 안내 문구→본문은 --space-5(24px)다.
  - 안내 문구가 없는 섹션은 제목→본문이 --space-5(24px)다.
  - Evidence 안의 그리드→note→details는 --space-5다.
- catalog-band는 양옆 테두리와 안쪽 여백을 없애고 위·아래 구분선만 둔 띠로 바꿨다. 그래서 다른 섹션과 같은 왼쪽 선과 오른쪽 선에 맞는다.

## 2. About (진주 목걸이)
| 폭 | 항목 | 전 | 후 |
|---|---|---|---|
| 1280 | 목걸이 | 없음 | 520~1280 × 141~576 (배경 그림 있음) |
| 1280 | 인용문 | 1040~1240, 위 260 | 1040~1240, 위 189 |
| 1280 | 이미지 요청 / 실패 | ['pearl.webp'] / 0 | ['about-pearls-760.webp', 'pearl.webp'] / 0 |
| 768 | 목걸이 | 없음 | 264~744 × 462~736 (배경 그림 있음) |
| 768 | 인용문 | 숨김 | 숨김(원래 1100px 이하 숨김) |
| 768 | 이미지 요청 / 실패 | ['pearl.webp'] / 0 | ['about-pearls-760.webp', 'pearl.webp'] / 0 |
| 375 | 목걸이 | 없음 | 18~357 × 536~730 (배경 그림 있음) |
| 375 | 인용문 | 숨김 | 숨김(원래 1100px 이하 숨김) |
| 375 | 이미지 요청 / 실패 | ['pearl.webp'] / 0 | ['about-pearls-760.webp', 'pearl.webp'] / 0 |

- 다른 화면(About 패널은 숨은 템플릿)의 목걸이 그림 요청과 ERR_ABORTED(후, 1280 어두운 화면): {"/": {"about_art": ["pearl.webp"], "aborted": []}, "/new/en/explore.html": {"about_art": ["pearl.webp"], "aborted": []}, "/new/en/chat.html": {"about_art": ["pearl.webp"], "aborted": []}, "/new/en/test.html": {"about_art": ["pearl.webp"], "aborted": []}, "/new/en/agent-status.html": {"about_art": ["pearl.webp"], "aborted": []}}
  - pearl.webp는 원래 각 화면의 다른 진주 장식이 쓰는 파일이다. about-pearls 요청은 0건이다.
- 방식
  - 진주 12개(11-11 1cb53b6f 전 SVG 배치 그대로)를 한 장으로 합성했다(about-pearls-760.webp 14.9KB, about-pearls-1520.webp 39KB).
  - 이 그림을 CSS 배경 image-set으로 깔았다. 숨은 패널은 배경을 받지 않는다.
  - 실은 벡터 path로 두고 stroke=currentColor(테마의 --gold)를 쓴다.
  - 장식이라 aria-hidden="true"로 두었고, img/image 요소가 없으니 alt를 쓸 곳이 없다.
  - 레이아웃 흔들림을 막으려고 상자 크기를 CSS로 고정했다(760×435, 1180px 이하는 aspect-ratio 700/400).
- 배치
  - 1180px 초과: 제목 오른쪽 뒤에 깐다. 글 열은 600px로 줄이고 인용문은 위로 붙여, 진주가 글을 가리지 않는다.
  - 1180px 이하: 글 아래에 오른쪽으로 붙여 흐름 안에 둔다(최대 480px). 1100px 이하에서 인용문이 숨는 것은 원래 규칙이다.
  - 가로 넘침: 1200·1181·1101·1024·800에서 scrollWidth − innerWidth = 0.
- About 공개 첫 요청(전, 09:5x, 1초 1건, 새 연결)
  - about.html 0.87·4.66·3.27초(UPDATING·HIT·UPDATING), 압축 27.3KB
  - 자원 5개(문서 1·CSS 1·스크립트 2·이미지 1)
  - 후는 배포 뒤 같은 방법으로 잰다. 이미지가 1개 늘어 6개가 될 것으로 본다.

## 3. 첫 화면 CSS
- 9개를 다시 만들었다(build_critical_css --local). 결과 데이터가 늦게 오면 카드 규칙이 빠지므로 --local 대기 시간을 1.2초에서 2.5초로 늘렸다.
- explore.css는 오늘 공개 데이터에 MCP 결과 카드가 나오지 않아 .acard.k-mcp 규칙 하나가 빠졌다. 그래서 원래 파일의 규칙을 그대로 두고 출처 해시만 현재 묶음 값으로 바꿨다.
  - explore 화면의 규칙은 이번 변경과 무관하다.
  - test_critical_css(현재 묶음에 있는 규칙인지)와 test_critical_css_browser(첫 화면 CSS만으로 그린 화면이 전체 CSS와 같은지)가 통과한다.
