# 통합 패키지 초안 (2026-11-09, 게시 승인 대기)

| 폴더 | 무엇 | 확인 | 게시(승인 필요) |
|---|---|---|---|
| `claude-code-plugin/` | Claude Code 플러그인: 원격 MCP + `find-agent` 스킬, 마켓플레이스 파일 | `claude plugin validate ./` 통과(11-09) | 공개 GitHub 저장소에 올리면 `claude plugin marketplace add <owner>/<repo>`로 설치 가능 |
| `python/` | PyPI `agent-concierge`: 의존성 없는 읽기 전용 클라이언트 + LangChain·CrewAI·OpenAI Agents SDK 도구 | 단위 시험 2건 통과 | PyPI 계정·토큰(사용자). 이름 선점 여부 확인 필요 |
| `js/` | npm `agent-concierge`: 읽기 전용 클라이언트, MCP 설정 상수 | `node --test` 2건 통과 | npm 계정(사용자). 이름 선점 여부 확인 필요 |

- Cursor는 플러그인 대신 `/connect`의 설치 딥링크를 쓴다.
- 패키지는 공개 Explore API(`/api/explore`)만 읽는다. 다른 에이전트를 호출하지 않는다.
- 각 패키지의 프레임워크 연동(LangChain·CrewAI·OpenAI Agents SDK)은 해당 라이브러리가 이 Mac에 없어 실제 실행은 확인하지 못했다. 게시 전에 각 extra를 설치해 한 번 돌려 본다.
- 게시하면 punkpeye/awesome-mcp-servers의 설치형 기준을 충족할 수 있다(`deploy/distribution/SUBMISSIONS.md` 9절).
