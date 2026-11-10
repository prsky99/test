# 메인 화면 품질 기준선 (2026-11-11, 성장·유통)

도구: scripts/ui_quality_audit.py + ui_audit.js(AD Coin 팀, 64311fd0). 공개 주소, 운영 버전 csp-frontend-20261111-r1(b8d69962).
화면마다 1280×800·375×812, 밝은·어두운 모드 4가지를 합친 값입니다. 원자료: baseline.json, 원인별 집계(밝은 모드, 예시 상한 없음): baseline-causes.json.

| 화면 | 겹침 | 44px 미만(화면 고유) | 44px 미만(공용) | 정렬 | 간격 토큰 | 이름표 | 대비 | 콘솔 |
|---|---|---|---|---|---|---|---|---|
| home | 82 | 76 | 6 | 14 | 0 | 0 | 0 | 0 |
| explore | 58 | 458 | 6 | 4 | 46 | 0 | 0 | 0 |
| chat | 46 | 66 | 6 | 2 | 0 | 0 | 0 | 0 |
| status | 46 | 54 | 6 | 108 | 4 | 0 | 0 | 0 |
| learn | 54 | 36 | 6 | 2 | 0 | 0 | 0 | 0 |
| test | 356 | 110 | 6 | 48 | 0 | 8 | 4 | 0 |
| workflows | 92 | 84 | 6 | 12 | 12 | 0 | 0 | 0 |
| list_agent | 270 | 118 | 10 | 8 | 0 | 4 | 0 | 0 |
| about | 30 | 30 | 6 | 0 | 6 | 0 | 0 | 0 |
| agent_detail | 0 | 34 | 4 | 0 | 0 | 0 | 0 | 0 |
| category | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| ranking | 0 | 122 | 4 | 0 | 0 | 0 | 0 | 0 |
| task | 0 | 74 | 4 | 0 | 0 | 0 | 0 | 0 |
| **합계** | **1034** | **1270** | **70** | **198** | **68** | **12** | **4** | **0** |

가로 스크롤·깨진 이미지·초점 안 보임·실패 요청은 모두 0입니다.

## 주요 원인 (밝은 모드, 두 화면 크기)
- 44px 미만: button.btn.sm 191, a.nav-tab 48, summary 51, a.btn.small 36, button.chip-btn 55, a.footer-link-btn 33, a.brand-box 24, 쿠키 띠 버튼 36, a.pf-email 18, 모바일 메뉴 버튼 9
- 겹침: 바닥글 링크(a.footer-link-btn.pf-link)와 본문 요소 약 60, 쿠키 띠(p.cookie-banner-text와 버튼)와 본문 약 60, 시험 화면 칩 버튼과 select·label
- 정렬: 표 머리칸과 본문칸(th|td, th|th) 52, 아이콘 원과 제목(span.icon-disc|h3) 12

## 1차 수정 뒤 (11-11, touch-frontend-20261111-r1, 커밋 56b41edc)

공용 44px 규칙(styles.css 끝, 공용 클래스만)과 첫 화면 설명 문장 수정 뒤 같은 도구로 공개 주소를 다시 쟀습니다. 원자료: after-touch.json

| 화면 | 44px 미만 전→후 | 공용 전→후 | 겹침 전→후 | 정렬 전→후 |
|---|---|---|---|---|
| home | 76 → 0 | 6 → 0 | 82 → 76 | 14 → 14 |
| explore | 458 → 0 | 6 → 0 | 58 → 52 | 4 → 4 |
| chat | 66 → 0 | 6 → 0 | 46 → 44 | 2 → 2 |
| status | 54 → 0 | 6 → 0 | 46 → 46 | 108 → 106 |
| learn | 36 → 0 | 6 → 0 | 54 → 52 | 2 → 2 |
| test | 110 → 0 | 6 → 0 | 356 → 352 | 48 → 48 |
| workflows | 84 → 0 | 6 → 0 | 92 → 94 | 12 → 16 |
| list_agent | 118 → 12 | 10 → 0 | 270 → 276 | 8 → 4 |
| about | 30 → 0 | 6 → 0 | 30 → 30 | 0 → 0 |
| agent_detail | 34 → 0 | 4 → 0 | 0 → 0 | 0 → 0 |
| category | 8 → 8 | 0 → 0 | 0 → 0 | 0 → 0 |
| ranking | 122 → 4 | 4 → 0 | 0 → 0 | 0 → 0 |
| task | 74 → 0 | 4 → 0 | 0 → 0 | 0 → 0 |
| **합계** | **1270 → 24** | **70 → 0** | **1034 → 1022** | **198 → 196** |

에이전트 상세·순위 화면은 배포 직후 엣지가 이전 styles.css(버전 표시 없는 주소)를 주던 몇 분 사이에 쟀습니다. 그래서 그 두 화면(그리고 분류·등록)만 몇 분 뒤 다시 쟀고, 위 표에는 다시 잰 값을 넣었습니다(첫 측정: 합계 77, 공용 2).

남은 44px 미만(24): 분류 화면 목록 안 링크 8(a 107x17), 등록 화면 본문 안 작은 링크 12(a 15px), 순위 화면 짧은 링크 4(폭 39~42px).

겹침과 정렬은 아직 고치지 않았습니다(다음 단계). 시험: tests/test_main_ui_touch_targets.py(8화면 × 1280/375, 44px 미만·가로 스크롤·콘솔 오류 0)를 release_gate frontend에 넣었습니다.

## 최종 보고 (11-11, 운영 audit-fix-frontend-20261111-r1, 커밋 60b6a555)

### 1. 공개 주소 최종 숫자

배포 뒤 공개 주소에서 13화면 × 1280/375 × 밝은/어두운을 쿠키 선택 전과 후에 각각 쟀습니다(각 52가지). 원자료: final-public.json

| 항목 | 작업 전 기준선(옛 도구) | 최종, 옛 도구 (선택 전 / 후) | 최종, 새 도구 (선택 전 / 후) |
|---|---|---|---|
| 겹침 overlaps | 1,034 | 592 / 592 | 0 / 0 |
| 44px 미만 small_targets | 1,270 | 0 / 0 | 0 / 0 |
| 공용 44px 미만 design_system_small | 70 | 0 / 0 | 0 / 0 |
| 정렬 misaligned | 198 | 150 / 150 | 0 / 0 |
| 이름표 없는 입력 unlabeled_fields | 12 | 12 / 12 | 0 / 0 |
| 대비 contrast_failures | 4 | 4 / 4 | 0 / 0 |
| 첫 화면 가려진 조작 요소 covered_controls (새 항목) | 42 (쿠키 띠, 새 도구로 잼) | - | 0 / 0 |
| 고정 층 겹침 overlay_overlaps (새 항목) | 236 | - | 0 / 0 |
| 콘솔 오류 · 가로 스크롤 · 초점 안 보임 | 0 | 0 | 0 / 0 |

CLS(처음 연 뒤 0.8초까지, 104가지): 최대 0.04(선택 전), 0.079(선택 후). 0.05 이상은 Chat 폰 0.079, 워크플로 폰 0.063뿐입니다. 이전 운영 값: 홈 0.181, 탐색 폰 0.223, 탐색 데스크톱 0.10~0.12.

### 2. 줄어든 수 나누기: 실제로 고친 것과 측정에서 뺀 것

옛 도구(64311fd0)로 작업 전 기준선과 최종 화면을 잰 차이가 "실제로 고친 것"입니다. 최종 화면에서 옛 도구 값(새 도구는 0)이 "측정에서 뺀 것"입니다.

| 항목 | 기준선 | 실제로 고친 것 | 측정에서 뺀 것 | 뺀 근거 |
|---|---|---|---|---|
| 겹침 | 1,034 | 442 (쿠키 띠를 본문 흐름으로 옮겨 고정 층 겹침 236 등) | 592 | 전부 닫힌 details 안 요소 |
| 44px 미만 | 1,270 (+공용 70) | 1,270 (+70) 전부 | 0 | 이름표 안 링크 예외는 표본에서 보여 되돌리고 고침 |
| 정렬 | 198 | 48 | 150 | 닫힌 details 48, 표 같은 줄 칸 80, 가운데 맞춤 묶음 12, 문장 안 inline 링크 8, 여러 줄 격자 항목 2 |
| 이름표 없는 입력 / 대비 | 12 / 4 | 0 | 12 / 4 | 닫힌 details 안 요소 |

### 3. 감사 도구에서 바꾼 것 (scripts/ui_audit.js, 커밋 35008403 · db9a3027 · 60b6a555)

- 닫힌 `<details>` 안의 요소(요약 줄 제외)는 보이지 않는 것으로 봅니다. 근거: 화면에 그려지지 않는데 Chrome이 위치 값을 돌려줌. 공개 화면 202개 전부 checkVisibility()=false.
- 고정·sticky 층과의 겹침은 overlay_overlaps로 따로 셉니다(지우지 않음). 대신 첫 화면에서 그 층이 조작 요소를 가리는지 covered_controls로 재고 게이트에 넣었습니다.
- 줄바꿈된 inline 요소는 줄별 상자로 비교합니다. 두 줄에 걸친 링크의 큰 사각형이 옆 링크와 겹친다고 나오던 오판입니다.
- 표의 같은 줄 칸은 "위쪽 끝이 같은지"로 비교합니다. 전에는 세로 묶음으로 보고 왼쪽 끝을 비교했습니다.
- 여러 줄에 걸친 격자 항목은 같은 줄에서 시작하는 첫 항목과 위쪽 끝을 비교합니다.
- 세로 묶음은 왼쪽 끝, 가운데, 오른쪽 끝 중 하나가 1px 안에서 맞으면 정렬된 것으로 봅니다(가운데 정렬 카드).
- 세로 묶음 검사는 block 계열만 봅니다. inline-flex 같은 inline 요소는 문장 안에 나란히 놓이기 때문입니다(이 보정으로 빠진 것: 등록 동의 문장 링크 3개끼리 비교 8건).
- 되돌린 것: 기준선 정렬 줄 예외와 이름표 안 링크 예외는 표본에서 보이는 요소가 나와 삭제하고 화면을 고쳤습니다(상태·워크플로 제목 줄 가운데 정렬, 동의 링크 44px).

### 4. 규칙별 표본 (배포 뒤 공개 주소 실제 화면, 원자료 exclusion-samples.json)

**닫힌 details (202개 중 화면에 그려진 것 0개)**

| 화면 | 요소 | 패널 | 그려짐 |
|---|---|---|---|
| / @1280 | p "Published once daily; current " | Daily search snapshot · 2026-1 | False |
| / @375 | p "Published once daily; current " | Daily search snapshot · 2026-1 | False |
| /new/en/explore.html @1280 | button.chip-btn "Stock Quotes" | More tasks | False |
| /new/en/explore.html @375 | p#xProtocolHelp "Task-focused results first. x4" | Search rules | False |
| /new/en/agent-status.html @1280 | p#uxConnectionMeaning "Healthy and Reachable describe" | What do the statuses mean? | False |

**표 같은 줄 칸 (보임, 정렬 기준만 바꿈)**

| 화면 | 칸 A | 칸 B | 위쪽 끝 차이(px) |
|---|---|---|---|
| /new/en/agent-status.html @1280 | th "Protocol" | th "Healthy" | 0 |
| /new/en/agent-status.html @375 | th "Protocol" | th "Healthy" | 0 |
| /new/en/test.html @1280 | th "Agent Name" | th "Protocol" | 0 |
| /new/en/test.html @375 | th "Agent Name" | th "Protocol" | 0 |
| /new/en/agent-status.html @1280 | th "A2A" | td "153,939" | 0 |

**가운데 맞춤 묶음 (보임, 가운데 차이로 판정)**

| 화면 | 묶음 | A / B | 왼쪽 차이 | 가운데 차이 |
|---|---|---|---|---|
| /new/en/workflows.html @1280 | div text-align:center | h4 / span.badge | 31.1 | -0.0 |
| /new/en/workflows.html @1280 | div text-align:center | h4 / button.link-button | 26.9 | -0.0 |
| /new/en/workflows.html @1280 | div text-align:center | h4 / span.badge | 57 | -0.0 |
| /new/en/workflows.html @1280 | div text-align:center | h4 / button.link-button | 36.8 | -0.0 |
| /new/en/workflows.html @1280 | div text-align:center | h4 / span.badge | 51.7 | 0 |

**문장 안 inline 링크 (보임, 문장 안에 나란히 놓임)**

| 화면 | 묶음 | A / B | 왼쪽 차이 |
|---|---|---|---|
| /new/en/list-agent.html @1280 | span text-align:start | a / a | 212.2 |
| /new/en/list-agent.html @375 | span text-align:start | a / a | -51.8 |
| /new/en/list-agent.html @1280 | span text-align:start | a / a | 396.5 |
| /new/en/list-agent.html @375 | span text-align:start | a / a | -131.3 |

**여러 줄 격자 항목 (보임)**

| 화면 | 격자 | 여러 줄 항목 | 같은 줄 첫 항목과 위쪽 차이 |
|---|---|---|---|
| /new/en/test.html @1280 | div.pearl-selected-example | div.ux-test-primary 1 / 3 | 0 |

보이는 요소가 나온 규칙 가운데 기준선 줄과 이름표 안 링크는 예외를 지우고 화면을 고쳤습니다(지금 표본 0). 표·가운데·격자·inline은 "보이지 않아서 뺀 것"이 아니라 "정렬을 재는 기준을 바로잡은 것"이고, 표본마다 그 기준의 차이가 0입니다. 이 넷을 "고칠 대상"으로 보실지는 PM 판단에 맡깁니다.

### 5. 쿠키 띠(PM 결정 A)와 탐색 CLS, 게이트

- 쿠키 띠: 머리글 위 본문 흐름 안. head 스크립트(응답 nonce)가 저장된 선택을 먼저 읽어 선택 전 방문자에게만 보입니다. 높이 데스크톱 61px, 폰 156px. 수락·거부 같은 크기, 설정은 글자 링크. 선택 뒤 초점은 본문 첫 요소.
- 탐색: 폰은 필터 접힌 상태를 첫 그림부터 CSS로 그리고 토글 자리를 확보(0.223→0.005). 데스크톱은 과제 칩 15개가 한 프레임 다 보였다 4개로 줄던 것을 처음부터 4개만 보이게(0.10~0.12→0.004~0.006).
- 게이트(release_gate frontend): 12화면 × 2폭에서 44px·겹침·정렬·가려진 조작 0, 쿠키 띠 크기·CLS·깜빡임 없음·선택 뒤 초점, 폰 쿠키 띠, 탐색 폰 CLS, 새 탭 콘솔 오류 0.
- 작업 전부터 실패하던 시험(화면 작업 전 커밋 b8d69962에서도 실패): 문의 양식 9(개인정보 전환으로 양식 삭제), Chat 첫 카드, Chat 대안 목록, WebMCP 도구 순서, 메뉴 접근성 표. 추적되지 않는 tests/test_expert_upgrade_browser.py 일부는 없앤 "How we use cookies" 펼침을 기대합니다(설정 링크가 대신함).

### 6. 화면 사진 (첫 화면, 쿠키 선택 전)

screens/ 아래 test · list_agent · status × desktop · mobile × before · after (before는 작업 전 기준선 전체 화면의 첫 화면 부분)

