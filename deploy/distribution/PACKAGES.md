# PyPI · npm · Claude Code 플러그인 배포 경로 (GitHub 없이)

11-10 사용자 결정에 따라 GitHub은 유입 채널로 쓰지 않습니다. 세 가지 모두 GitHub 저장소 없이 배포할 수 있습니다.
게시는 사용자 승인 뒤에 합니다. 아래 빌드는 끝났고, 아무것도 게시하지 않았습니다.

## 요약

| 채널 | 이름 | 사용 여부(11-10 확인) | 필요한 것 | 빌드 결과 |
|---|---|---|---|---|
| PyPI | `agent-concierge` | 비어 있음(404) | pypi.org 계정, 2단계 인증, API 토큰 | 휠과 소스 묶음 빌드, 설치·가져오기 확인 |
| npm | `agent-concierge` | 비어 있음(404) | npmjs.com 계정, 2단계 인증 | `npm test` 통과, `npm pack` 묶음 4개 파일 |
| Claude Code 플러그인 | `agent-concierge` | 해당 없음 | 우리 사이트에 파일 두 개 공개(11-10 PM 승인) | 우리 사이트에서 제공. 플러그인 `claude plugin validate` 통과 |

같은 이름이 먼저 등록되면 쓸 수 없습니다. 게시를 정하면 이름부터 먼저 등록하는 편이 안전합니다.

## 1. PyPI

- 소스: `integrations/python/` (선택 의존성 `langchain`, `crewai`, `openai-agents`)
- 빌드(운영 맥): `cd integrations/python && uv build --out-dir dist`
  - `.venv`와 `.venv-tests`에는 setuptools가 없어서 `uv build`를 씁니다. uv가 격리된 환경에 setuptools를 받습니다.
- 게시(사용자 승인 뒤, 사용자 토큰으로): `uvx twine upload dist/*`
  - 토큰은 사용자가 직접 입력합니다. 저장소·보고서·세션 메시지에 남기지 않습니다.
  - Trusted Publishing은 GitHub Actions 같은 CI가 필요하므로 쓰지 않습니다. 프로젝트 범위 API 토큰을 씁니다.
- 처음에는 TestPyPI(`--repository testpypi`)에 올려 설치를 시험해 볼 수 있습니다. 계정은 따로 필요합니다.

## 2. npm

- 소스: `integrations/js/` (Node 18 이상, 의존성 없음)
- 확인: `npm test`, `npm pack --dry-run`
- 게시(사용자 승인 뒤, 사용자 계정으로): `npm login` 후 `npm publish --access public`
  - 2단계 인증 코드는 사용자가 입력합니다.
  - `repository` 필드는 GitHub 주소가 없으므로 넣지 않았습니다. 홈페이지는 `https://agentconcierge.biz/connect` 입니다.

## 3. Claude Code 플러그인

Claude Code 문서(code.claude.com, 11-10 확인)에 따르면 마켓플레이스는 GitHub 저장소 말고도 아래로 추가할 수 있습니다.

- 아무 git 주소
- `marketplace.json` 파일의 HTTPS 주소

HTTPS 주소로 추가하면 Claude Code는 `marketplace.json`만 받습니다. 그래서 플러그인 위치는 상대 경로를 쓸 수 없고, 다음 같은 객체로 줘야 합니다.

- `archive` (zip 주소와 sha256)
- `npm`
- `url` (git)

**권장: 우리 사이트에 직접 올리기(외부 계정 불필요)**

| 공개 주소 | 내용 |
|---|---|
| `https://agentconcierge.biz/claude-plugins/marketplace.json` | 마켓플레이스 파일. 플러그인 위치는 `archive`와 아래 zip의 sha256 |
| `https://agentconcierge.biz/claude-plugins/agent-concierge-plugin-0.1.0.zip` | 플러그인. `plugin.json`, `.mcp.json`, `skills/find-agent`, README 포함 |

사용자는 이렇게 설치합니다.

```
/plugin marketplace add https://agentconcierge.biz/claude-plugins/marketplace.json
/plugin install agent-concierge@agent-concierge
```

- 플러그인이 하는 일: 원격 MCP 서버 `https://agentconcierge.biz/mcp` 를 연결하고, 과업으로 에이전트를 찾는 스킬 하나를 더합니다.
- 11-10 PM 승인으로 공개했습니다. `agent_market/concierge/plugin_dist.py`가 `claude_plugin/`(integrations 사본, 시험으로 같은지 확인)에서 매번 같은 바이트의 zip을 만들고, `marketplace.json`에 그 sha256을 넣습니다.
- `archive` 출처는 Claude Code v2.1.224 이상에서 됩니다(문서 기준). 이 맥의 2.1.89 검증기는 마켓플레이스 파일을 거부하고, 플러그인 자체는 통과합니다. 옛 버전 사용자는 `/connect`의 `claude mcp add` 한 줄을 쓰면 됩니다.
- npm 패키지로 게시하는 방법도 있습니다(`"source": "npm"`). npm 계정이 생기면 함께 쓸 수 있습니다.
- Anthropic 공식 디렉터리(claude.ai/directory)는 다음 조건이 필요해 지금은 해당하지 않습니다.
  - 플러그인을 담은 GitHub 저장소
  - 유료 claude.ai 요금제

## 빌드 결과 위치

빌드한 파일은 세션 스크래치 폴더에 있습니다(커밋하지 않음). 게시하기로 하면 위 명령으로 다시 만듭니다.

- 휠: `agent_concierge-0.1.0-py3-none-any.whl`. 7개 파일이 들어 있고, `--target` 설치 뒤 `import agent_concierge`가 되는 것을 확인했습니다.
- 소스 묶음: `agent_concierge-0.1.0.tar.gz`
- npm: `agent-concierge-0.1.0.tgz` (4개 파일)
- 플러그인 zip(6개 항목)과 `marketplace.json`. sha256은 zip을 다시 만들면 바뀌므로, 공개할 때 다시 계산합니다.

## 확인하지 못한 것

- LangChain, CrewAI, OpenAI Agents SDK 선택 의존성을 실제로 설치해서 돌려 보지는 않았습니다. 시험은 가짜 응답으로 했습니다.
- 자체 호스팅 마켓플레이스로 실제 `/plugin install`은 해 보지 않았습니다. 이 맥의 Claude Code(2.1.89)가 `archive` 출처를 지원하지 않습니다.
