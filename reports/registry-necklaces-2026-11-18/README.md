# 공개 목걸이를 외부 카탈로그에 올리는 안 (성장·유통, 11-18 19:2x, PM 생산 체계 v2 과제 1)

게시 실행은 하지 않았다. 이 문서는 PM이 고를 안과 계정 없이 가능한 곳의 목록이다. 계정이 필요한 곳은 목록만 만들고 사용자 확인으로 넘긴다.

## 0. 먼저 확인한 사실
- 공식 MCP Registry 항목은 **서버 하나**를 가리킨다. 스키마(2025-12-11, 직접 받아 검증)에는 도구 목록 칸이 없다. 쓸 수 있는 것은 name(`^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$`), title(100자), description(**100자**), version, websiteUrl, icons, remotes, packages다. 그래서 목걸이를 "도구로 올리는" 방법은 설명 문구에 넣거나, 목걸이마다 서버 항목을 따로 두는 두 가지뿐이다.
- 지금 올라간 항목은 `biz.agentconcierge/agent-concierge` 1.0.0(11-09)이고, 1.1.0 초안(`deploy/mcp-registry/server.json`)은 11-17 기준 아직 게시 전이다. 서버의 `serverInfo.version`(front.py 3792·3811줄)과 맞춰 올리는 규칙이 있다(README 4절).
- 목걸이 도구 이름은 `necklace_<slug>`이고, 이미 `/mcp`의 `tools/list`에 나간다(정식·미리보기 모두, 표면 코드 f5fba286). 레지스트리를 거쳐 연결한 클라이언트는 연결한 뒤에 도구 목록으로 목걸이를 본다.
- 지금 공개된 목걸이는 website-trust 하나이고 **미리보기**다("Preview — test runs in progress", 관문 미통과). 외부 문구에서 "검증됐다"·"관문 통과" 같은 말을 쓰면 안 된다.

## 1. 안 A — 서버 항목 하나에 문구만 더하기 (권장 1순위, 코드 변경 없음)
- 새 초안 `deploy/mcp-registry/server-1.2.0.draft.json`: version 1.2.0, description **"Find AI agents for a task; run workflows built from agents we tested, in one call."**(82자). 공식 스키마로 검증 통과.
- 문구 근거: 멤버(진주)는 시험을 거친 에이전트라 "agents we tested"는 사실이다. 목걸이 자체가 검증됐다는 말은 넣지 않았다(미리보기).
- 이유: 공식 Registry는 Glama·API Tracker·mcptry·PulseMCP 같은 곳이 원천으로 가져간다(11-17 보고서 1절). 한 번 고치면 따라온다.
- 필요한 것: 서버 `serverInfo.version`을 1.2.0으로 올린 코드 배포가 먼저(front.py), 그다음 README 3절대로 login → publish(PM, 키 `~/.mcp-registry/key.pem`).
- 1.1.0은 건너뛴다(같은 항목을 두 번 올릴 이유가 없다). 1.1.0의 title·x402 제거는 1.2.0에 그대로 들어 있다.

## 2. 안 B — 목걸이마다 서버 항목 따로 (효과 큼, 코드 필요)
- 형태: `biz.agentconcierge/website-trust` 같은 항목마다 자기 `remotes` 주소를 가진다. 주소는 지금 없다. `/mcp/necklace/<slug>`처럼 그 목걸이 도구와 `necklace_details`만 내는 경로를 만들어야 한다(front.py MCP 처리기, `necklace_surface.available()`로 필터).
- 이점: 레지스트리·집계자 검색에서 목걸이 이름과 한 줄 설명으로 직접 찾힌다. "website trust check" 같은 과제 문구로 닿을 수 있다.
- 부담: 목걸이 수만큼 항목과 버전 관리, 미리보기→정식 전환·중단 때 항목 갱신. 같은 서버를 가리키는 항목이 여러 개인 것을 레지스트리가 어떻게 보는지는 확인하지 못했다(규칙 문서에서 중복 금지 문구를 찾지 못함, 추정 아님·미확인).
- 권고: 안 A를 먼저 하고, 효과(MCP clientInfo.name 수, 11-16 기준선)를 7일 본 뒤 정식 목걸이가 둘 이상 되면 안 B를 코드로 만든다. 미리보기는 별도 항목으로 올리지 않는다(관문 전에 독립 항목은 과한 주장).

## 3. 안 C — 코딩 에이전트용 skill 파일 (정식 목걸이만)
- `/skill.md`는 이미 있다(entry llms). 목걸이마다 `/necklaces/<slug>/skill.md`(정적 한 쪽: 쓸 때, 호출 방법 `necklace_<slug>`, 입력 칸, 한계)를 두고 `llms.txt`에서 링크한다. 저장소 없이 공개 주소로만 읽힌다.
- 이름이 비슷한 공식 skill 목록·마켓은 GitHub 저장소나 PR이 필요해 11-10 결정(GitHub 비사용)으로 하지 않는다.
- 미리보기에는 만들지 않는다. 정식(live)이 되는 날 정의에서 자동 생성하는 것이 맞다(홍보 숫자는 잰 값만).

## 4. 계정 없이 가능한 곳 (11-17 보고서 그대로, 지금 상태 변화 없음)
PM 제출 후보 — 값은 11-15 제출표(reports/growth-plan-2026-11-14/directory-submissions.md)의 공통 정보를 그대로 쓴다. 제출 중 로그인·약관 동의가 나오면 멈춘다.
| 곳 | 받는 것 | 방법 | 목걸이 반영 |
|---|---|---|---|
| 공식 MCP Registry | MCP 서버 | login(도메인 키)→publish, 계정 없음 | 안 A 문구 |
| Glama·API Tracker·mcptry·PulseMCP | 공식 Registry에서 자동 | 따로 할 일 없음, 다음 날 이름·설명 확인 | 안 A가 따라감 |
| LocalMark (localmark.ai/submit) | A2A | 카드 URL 한 칸 | 카드(`/.well-known/agent-card.json`)의 skills에 목걸이가 이미 나간다 |
| mcpub.dev | MCP | 웹 폼 또는 submit 도구, 계정 언급 없음 | 설명 문구는 안 A와 같게 |
| agents.ml | A2A 프로필 | 이름과 엔드포인트 | 같음 |
| mcpservers.org | MCP | 같은 주소로 이름 갱신 요청 | 같음 |
사용자 확인으로 넘길 곳(계정·약관·지출이 있음): AI Agent Store(가입 불명확), HOL Registry Broker(계정·크레딧), Glama 수동 수정(재게시로 안 바뀔 때), a2a-registry claim(로그인), Prowl(가입 필요, 대상 불명확).
하지 않는 곳: GitHub 저장소·PR이 필요한 곳 전부, a2alist.ai(등록비 $0.99), Fetch.ai Agentverse, Claude Connectors Directory(11-15 중단).

## 5. 순서 제안과 PM에게 묻는 것
1. 안 A 승인 → 서버 버전 1.2.0 코드(front.py `serverInfo.version`, 정책 해시 밖, 작은 변경)를 낮 묶음에 → 배포 뒤 PM이 login/publish.
2. 같은 문구로 mcpub·agents.ml·LocalMark 제출(계정 없이, PM 실행).
3. 7일 뒤 안 B 여부와 안 C(정식 목걸이 생길 때) 결정.
- 묻는 것: ① 안 A 문구 승인(82자, "agents we tested"), ② `serverInfo.version` 1.2.0 코드 변경을 제가 만들어도 되는지, ③ 안 B를 7일 뒤로 미루는 것.
