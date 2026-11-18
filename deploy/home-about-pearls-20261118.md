# 홈·에이전트 현황의 진주 수와 목걸이 칸, About 개편 (성장·유통, PM 11-18 09:4x, 11-19 낮 묶음 목표)

## 무엇이 바뀌나
| 화면 | 내용 |
|---|---|
| 홈(index.html) | 기존 4칸 아래에 둘째 띠: "Verified pearls"(최종+검증 진주 수, 아래에 "N final · M verified", How we test 링크)와 "Necklaces"(공개 목걸이 수) |
| 에이전트 현황(agent-status.html) | 기존 카드 아래에 같은 두 카드(아이콘 원판 형식) |
| About(about.html) | "What are pearls?"(85점·서로 다른 날 2회·최종 진주)와 "What are necklaces?"(3개 이상 연결, 관문 60회 중 57회=95%·95번째 백분위 5초, 직접 할 때와 비교해 잰 값만 공개) 두 절을 "Our belief"와 "Get started" 사이에 추가. 그림은 기존 진주 목걸이 그림과 pearl 장식을 그대로 씀 |
- 기존 CSS 클래스(metric-grid·metrics-band·metrics-cards·reference-about-belief·reference-about-principles)만 쓰고 페이지 전용 스타일은 없다. 첫 화면 CSS(`new/en/assets/critical/`)는 이 세 페이지분을 다시 만들었다.

## 숫자는 어디서 오나
- HTML은 모든 방문자에게 같은 바이트다(숫자 자리는 "—"). 숫자는 로드 뒤 `/api/pearls/public` 한 번(60초 캐시, 엣지 캐시 대상)에서 온다: `counts`(공개 진주 목록 gateway-data/pearls/public-pearls.json의 level final·verified 행 수, 한 에이전트의 여러 역할은 각각 센다)와 `necklaces_live`(gateway-data/necklaces/necklaces.json 판정 스냅샷에서 지금 제공 중인 목걸이 수).
- **목걸이 칸은 `hidden`으로 시작하고 `necklaces_live`가 1 이상일 때만 나타난다.** 0과 1 두 경우를 시험으로 고정했다(tests/test_home_pearl_counts.py). 첫 공개 후보 website-trust가 11-18 21:50 판정을 통과해 11-19 00:30에 공개되면 이 칸이 저절로 나타난다.
- 판정이 안 났거나 파일이 없거나 깨졌으면 진주 칸은 "—"로 남고(숫자 없음, 오류 없음), 목걸이 칸은 숨는다.

## 퍼지가 필요한가 (11-18 엣지 6시간 보관 변경과 같은 페이지)
- 이 변경이 나가면 HTML 세 개와 새 스크립트 해시가 바뀐다. 엣지가 옛 HTML을 최대 6시간(+낡은 사본 허용 1일) 들고 있으면 새 칸과 새 스크립트가 늦게 보인다. **배포 직후 한 번 퍼지를 권한다**: `deploy/cloudflare-purge-urls-home-about-20261118.txt`(4개: 홈 `/`, /new/en/index.html, /new/en/agent-status.html, /new/en/about.html). 옛 HTML이 부르는 옛 `?v=` 스크립트는 이전 릴리스 보관 장치가 계속 서빙하므로 섞여도 깨지지 않는다.
- 진주 수는 하루 세 번(09:12·15:12·20:12) 바뀌지만 페이지 바이트는 바뀌지 않고 숫자만 `/api/pearls/public`(60초)에서 오므로, 숫자 갱신에는 퍼지가 필요 없다.
