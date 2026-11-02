# 경고 26건·실패 11건 해결 및 운영 재점검

2026-10-27. 사용자가 프론트엔드 적용 명령을 실행한 후 실제 공개 서비스에서 확인했다.

**운영 결과: PASS 28 · WARN 26 · FAIL 11 → PASS 65 · WARN 0 · FAIL 0.** 동일한 판정 ID로 37개 항목을 각각 대조했다. 실제 제공자 실행·결제·워크스페이스 계정 사용은 포함하지 않는다.

## 실제 반영 확인

- 활성 프론트엔드: `autonomous-agent-interop-20261027-r2`.
- 공개 HTTP 요청 48회에서 판정 65개 모두 통과.
- 배포 패키지 1,300개 파일 해시 검사: 불일치 0개.
- 예전 WARN/FAIL 37개가 모두 PASS인 것은 `closure-37.json`에 항목별로 기록했다.
- 이번 점검 중에는 운영 프로세스를 재시작·교체하지 않았다. 사용자가 실행한 배포의 결과를 검증했다.

## 경고 26건

공개 MCP 도구 13개 각각의 행동 표시와 출력 스키마를 보완했다. 경고 등급만 바꿔 없앤 것이 아니다. 실제 `tools/list`에서 보완된 필드를 읽어 26개 판정이 모두 PASS인지 확인했다.

- 읽기 전용·파괴 가능성·중복 호출 특성·외부 접촉 여부를 작업의 실제 동작에 맞게 표시한다. 대화 이력을 저장하는 검색을 읽기 전용으로 잘못 표시하지 않는다.
- 출력 스키마를 제공하고 실제 도구 응답의 구조화 결과를 검증했다. 클라이언트가 structuredContent만 읽어도 안내를 잃지 않도록 text를 포함한다.
- 격리 환경에서 공개 도구 13개를 각각 호출하여 선언한 스키마와 실제 결과를 대조했다. 외부 실행 도구는 거부 결과를, 워크플로우 상세는 없는 항목 결과를 사용하는 등 외부 효과를 만들지 않는 경로로 검증했다. 모든 도구의 모든 실행 분기를 인증한 것은 아니다.
- 스키마는 공통 결과와 확장 필드를 수용한다. 제공자마다 달라지는 모든 결과를 완전히 정의하는 명세라고 주장하지 않는다.

## 실패 11건

1. **문서 HEAD 8건**: robots.txt, llms.txt, llms-full.txt, sitemap.xml, agent-card.json, mcp.json, agent-entry.json, skill.md의 GET/HEAD가 모두 200이고 HEAD 본문은 비어 있다.
2. **카테고리 1건**: `/agents/category/social`이 404에서 200으로 바뀌었다. 검증 증거의 유무가 알려진 카테고리 주소를 사라지게 하지 않는다. 후보 조회는 제한된 배치로 수행하고 현재 연결 버전·실행 증거를 확인한다.
3. **사전 요청 1건**: 서비스 출처에서 `/mcp` OPTIONS가 204이며 필요한 POST·전송 헤더를 허용한다.
4. **Origin 검사 1건**: 미허용 HTTPS 출처의 MCP 요청은 403으로 거부한다. 허용 출처 목록은 정확한 HTTPS Origin만 받고 와일드카드·잘못된 포트·경로·자격 증명 형태는 허용하지 않는다.

CORS는 공개 전송 경로에만 적용한다. 워크스페이스·관리자 API나 쿠키 공유를 일괄 개방하지 않는다. 외부 브라우저 앱은 정확한 출처를 `AGENT_BROWSER_ORIGINS`에 등록해야 한다. 임의의 모든 웹사이트에 접근 권한을 주는 방식으로 문제를 숨기지 않았다.

## 논문·공식 규격·SNS 근거

[Tool-DE 논문](https://arxiv.org/abs/2510.22670)은 불완전한 도구 설명과 구조화 정보 보완이 검색·도구 활용에 영향을 준다고 설명한다. 이번에는 서버가 소유한 계약·행동 표시를 보완했다. 제공자 기능을 임의로 만들어 넣거나 논문 성능 수치를 서비스 개선율로 사용하지 않았다.

[ToolRet 논문](https://arxiv.org/abs/2503.01763)은 일반 검색 성능만으로 도구 검색 품질을 판단할 수 없음을 보여 준다. 따라서 메타데이터 확인만으로 끝내지 않고 실제 서울 날씨 추천·후속 상세 조회와 엄격한 MCP 선택을 함께 점검했다.

[MCP 도구 규격](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)에서 outputSchema·annotations는 선택 사항이다. 누락을 치명적 취약점으로 취급하지 않지만, 선언된 스키마가 있으면 결과와 맞아야 한다. 실제 응답 검증을 추가한 이유다. 행동 표시는 실행 권한을 대신하지 않는다.

[MCP 전송 규격](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)은 Origin 검증과 부적합 Origin의 403 응답을 요구한다. 공개 CORS 지원과 비공개 실행 권한을 분리했고, SSE가 없는 `/mcp`의 GET 405는 정상 계약으로 유지했다.

[MCP 유지보수자 논의 #1624](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1624)는 클라이언트별 content와 structuredContent 소비 차이를 다룬다. [VS Code 구현 이슈](https://github.com/microsoft/vscode/issues/290063)도 같은 호환성 위험을 보여 준다. 안내 text와 구조화 결과를 함께 확인했다. 제안 내용을 확정 규격으로 바꾸어 인용하지 않는다.

[Reddit의 원격 MCP 운영 경험](https://www.reddit.com/r/mcp/comments/1vbmi0u/what_implementing_oauth_21_for_a_remote_mcp/)에서는 네이티브 클라이언트와 브라우저의 사전 요청 차이, 클라이언트별 동작 차이를 설명한다. 이는 규격의 보조 근거로 사용했고, API 결과와 실제 TLS/Chromium의 허용·차단을 별도로 시험했다. SNS 게시물의 우회 제안을 그대로 도입하지 않는다.

## 회귀·실제 화면 확인

- API·추천·문맥·보안 및 새 37개 해소 검증: **109개 통과**.
- 별도 실제 TLS CORS·CSP·XSS Chromium 회귀: **14개 통과**.
- 실제 운영 브라우저 확인: Enter 검색, 대안 펼치기, Calling details, MCP 선택 후 검색, 모바일 폭 검사 **5개 통과**, pageerror 0개.
- 공개 콘텐츠 303개 파일 검사: 위반 0건. 영향받는 신규 검증 코드 Ruff 통과.
- 서울 날씨 추천: MCP 3.705초, A2A 1.355초, REST 1.365초. 세 경로 모두 같은 3개 후보와 동일한 1위 날씨 에이전트를 반환하고 상세 조회를 유지했다. 이 세 번의 측정으로 운영 지연 전체의 p95나 외부 예보 정확성을 주장하지 않는다.

실제 화면 증적:

- `chat-before.png`: 공개 Chat 진입 화면.
- `chat-details.png`: 검색 후 Calling details 표시.
- `chat-mobile-after.png`: MCP로 다시 검색한 모바일 화면. 가로 넘침 없음, 요청 완료 후 버튼 복구·aria-busy 해제 확인.

추가 작업에서 변경한 제품 파일을 임의로 되돌리지 않았다. 현재 작업 소스에는 진행 중인 다른 수정과 미리보기 빈 상태 문구 수정 등이 있을 수 있으므로, 이 보고서의 검증 범위는 위 활성 릴리스와 37개 관찰 항목이다. 운영 전체에 모든 최신 작업이 반영됐다는 의미는 아니다.

## 증적 파일

- `post-deploy.json`, `post-deploy-run.log`: 실제 공개 65개 판정.
- `closure-37.json`: 37개 이전/이후 판정 및 활성 릴리스·패키지 해시.
- `candidate-audit.json`: 격리 앱의 동일 판정 검증.
- `regression.xml`, `regression.log`: 109개 회귀 결과.
- `browser-security.xml`, `browser-security.log`: 14개 Chromium 보안 회귀.
- `live-browser.json`, `live-browser.log`, `check_live_browser.py`: 실제 공개 화면 5개 확인.
- `content-check.log`, `lint.log`: 콘텐츠·정적 검사 결과.

실제 지급·결제, 제공자 도구 실행, 서명된 타사 에이전트, 외부 레지스트리 등록, 운영 알림 도달은 이번 작업에서 새로 실행하지 않았다. 37개 해소를 서비스 전체의 무취약 보증으로 표현하지 않는다.
