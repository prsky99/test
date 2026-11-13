# 홈·탐색·llms.txt 중심 전환안 — 목걸이를 맨 앞에 (PM 11-14 04:3x 3번, 안만, 배포 전 PM이 사용자 확인)

**결론: 새 디자인이 필요 없다.** 시안 자체가 이미 목걸이 중심이다.
- 홈 시안(`new/design/pages/01-home-full.png`)의 첫 화면은 "Valuable alone. Remarkable together."와 진주 목걸이 그림이다.
- 워크플로우 시안(`04-workflows.png`)은 진주 셋을 실로 이은 실행 화면이다.
- 지금 운영 화면은 이 시안을 따르되, 주 버튼과 예시가 "에이전트 찾기"를 앞세운다.
- 그래서 전환은 다음 셋이다. 디자인 시스템(Pearl Connection), 워크스페이스 틀, 공용 assets는 그대로 쓴다.
  - 블록 순서
  - 주 버튼
  - 예시를 **실제 목걸이 데이터**로 채우기
- 목걸이가 0개인 동안에는 바꾸지 않는다. 첫 목걸이가 판정(외부 진주 2개 이상, Δ > 0, 재시험 통과)을 통과한 날부터 적용한다. 빈 목걸이 칸을 보이지 않기 위해서다.

## 1. 홈 (시안 01 블록별)

| 시안 블록 | 지금 운영 | 전환안 |
|---|---|---|
| 첫 화면 왼쪽: 머리말·H1·설명 | 머리말 "Agent Concierge · For developers and AI agents", 설명은 에이전트 찾기 | H1은 시안 그대로("Valuable alone. Remarkable together."). 설명을 "Verified agents, connected into workflows that beat any single one."로(숫자는 목걸이 표에서). 머리말은 브랜드 결정(Agentcon)을 따른다 |
| 첫 화면 버튼 둘 | 주 버튼 "Find an agent", 보조 "Explore workflows" | **주 버튼 "Run a necklace"**(목걸이 목록), 보조 "Find an agent". 시안의 두 버튼 자리·모양 그대로, 순서만 바꿈 |
| 첫 화면 입력칸(A2A·MCP·x402·Any) | 에이전트 찾기 | 그대로 둔다. 찾기는 진주 발굴의 기반(전략 4절 5) |
| 첫 화면 오른쪽 진주 목걸이 그림 + "From individual agents to one useful brief" 카드 | 개념 미리보기(Concept preview) | 카드 안을 **오늘의 목걸이 하나**로: 이름, 진주 3개 이름, "Δ +N%p vs best single", 최근 성공률. 그림의 진주 이름표(Research·News·Documents)는 그 목걸이의 진주 역할로. 그림 자체는 About과 같은 목걸이 그림 그대로(`keep-design-visuals`) |
| "Turn individual strengths into a shared outcome." 3단계 | 그대로 | 3단계 글을 진주 발굴 → 진주 인증 → 목걸이 공급으로(시안 문장 길이 유지) |
| "Start with something useful." 카드 3장 | 예시 쓰임새(Technology news 등) | **목걸이 카드 3장**: 이름, 한 줄, Δ, 1회 비용·지연, 성공률, "Run" 버튼. 카드 모양·진주 그림 그대로 |
| "Evidence you can inspect." 에이전트 보고서 | 개별 에이전트 증거 | 위치를 한 칸 아래로. 제목 그대로, 내용은 "목걸이에 쓰인 진주의 카드"로 소개 |
| "A clear path from agents to outcomes." | 개념 미리보기 | 실제 목걸이 하나의 단계(진주 → 진주 → 결과)와 최근 시험 결과 링크 |
| FAQ·끝 버튼 | "Find an agent" 먼저 | 끝 버튼도 "Run a necklace" 먼저 |

## 2. 탐색(Explore)

- 결과 맨 위에 **"Necklaces for this task"** 한 줄 영역을 둔다(목걸이가 질의와 맞을 때만, 최대 2개). 그 아래에 지금의 에이전트 결과를 둔다.
- 에이전트 결과 카드에는 그 에이전트가 들어간 목걸이가 있으면 "Pearl in: <목걸이 이름>" 작은 표시를 단다(진주 카드 연결).
- 응답 시간: 목걸이 영역은 공개 목록 스냅샷(작은 JSON)을 읽는다. 요청 경로에 실시간 DB 확인을 새로 넣지 않는다(속도 정책). 탐색 3초 차선 목표를 시험한다.
- Chat은 Explore와 역할이 다르다(11-01 결정). Chat 추천 답에서는 목걸이가 질의와 맞으면 맨 앞에 두는 안을 검색과 RAG와 따로 정한다.

## 3. llms.txt·llms-full.txt

| 지금 순서 | 전환안 순서 |
|---|---|
| 1. 서비스 소개(찾기) 2. 찾기 사용법(MCP·A2A·API) 3. 연결 4. 페이지 목록 … | 1. 한 줄 정체성(Agent Value Gateway) 2. **Necklaces you can run**: 목걸이마다 이름·한 줄·Δ·성공률·실행 방법(MCP 도구 이름, A2A 기술 id, 웹 주소) 3. 찾기 사용법 4. 연결 5. 페이지 목록 |

- 숫자는 목걸이 표에서 매일 다시 만든다(손으로 쓰지 않는다).
- `/.well-known/agent-card.json`의 기술 목록, MCP tools/list도 목걸이를 찾기 기술 앞에 둔다.

## 4. 사이트맵·구조화 데이터

- 사이트맵 첫 부분을 목걸이 페이지로 한다(성장 부분 앞).
- 목걸이 페이지 JSON-LD: `SoftwareApplication`(applicationCategory "AI agent workflow") + `isBasedOn`으로 쓰인 진주 카드 주소를 단다. 평점·리뷰 마크업은 쓰지 않는다(근거 없는 별점 금지).

## 5. 확인 방법 (배포 전)

- 시안 대조: 1280·375 × 밝음·어두움 사진을 시안 01·04와 나란히 둔다. 간격·정렬은 토큰 그대로이고, 디자인 시스템 밖 스타일은 0이어야 한다.
- 픽셀 도구(`scripts/css_pixel_compare.py`)로 바꾸지 않은 블록이 그대로인지 확인한다.
- 화면 정책: 목걸이 영역은 그 영역에만 로딩을 보이고, 데이터는 누를 때 불러온다(첫 화면 고정 글은 HTML에 바로).
- Chat 비교 새 실패 0, 탐색·페이지 차선 목표.

## 6. PM에 묻는 것

1. 홈 주 버튼을 "Run a necklace"로 바꾸는 것(첫 목걸이가 생긴 날부터)
2. Explore 결과 위 목걸이 영역(최대 2개)
3. llms.txt 순서 전환
4. 브랜드 머리말은 브랜드 결정을 따른다(`brand-agentcon-impact.md`)
