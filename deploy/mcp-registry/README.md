# 공식 MCP Registry 게시 절차 (승인 대기, 2026-11-09 작성)

`server.json`은 공식 MCP Registry에 `https://agentconcierge.biz/mcp`(streamable-http)를 올리는 메타데이터다. 실제 게시와 도메인 확인은 **사용자 승인 뒤 사용자가 직접** 한다. 개인 키는 저장소·보고서·다른 세션에 남기지 않는다.

## 1. 확인한 공식 기준 (11-09 문서 기준, Registry 문서는 아직 preview)
- 스키마: `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`. 필수는 `name`, `description`(100자 이하), `version`이다.
  - 이 파일은 그 스키마로 검증했다(`tests/test_growth_pages.py`가 길이·형식을 다시 확인).
- remote 서버는 `remotes: [{"type": "streamable-http", "url": ...}]`로 적는다. SSE는 deprecated다. 공개 주소여야 한다.
- Registry는 remote URL의 소유를 확인하지 않는다. 확인하는 것은 **이름 공간(namespace)** 소유뿐이다.
- 도메인 확인을 하면 이름 공간은 도메인을 뒤집은 `biz.agentconcierge/*`가 된다. GitHub 로그인으로는 개인 이름 공간(`io.github.<사용자>/*`)만 된다.
- 하위 도메인 허용 여부는 문서에 없다. 우리는 apex(`agentconcierge.biz`)만 쓴다.
- 출처: [remote servers](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/remote-servers.mdx), [authentication](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/authentication.mdx), [quickstart](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx)

## 2. 도메인 확인 방법 비교

| 방법 | 하는 일 | 장점 | 주의 |
|---|---|---|---|
| **HTTP (권장)** | `https://agentconcierge.biz/.well-known/mcp-registry-auth`에 공개 키 한 줄 | DNS·Cloudflare 설정을 바꾸지 않는다. 우리 서버가 이미 제공 준비됨 | Registry는 Google Cloud에서 `User-Agent: mcp-registry/1.0`로 요청한다. 200만 인정(리다이렉트 불가), 10초 제한 |
| DNS TXT | apex에 `v=MCPv1; k=ed25519; p=<공개 키>` TXT 레코드 | 서버와 무관 | Cloudflare DNS 변경(사용자 승인 사항) |

11-09 확인: `curl -A 'mcp-registry/1.0' -H 'Accept: text/plain' https://agentconcierge.biz/.well-known/mcp-registry-auth`가 Cloudflare 차단 없이 우리 서버의 404를 받았다. 파일을 두면 200이 된다.

### 우리 서버의 HTTP 확인 파일 제공 방식
- 경로: `/.well-known/mcp-registry-auth` (`agent_market/concierge/growth_pages.py`).
- 파일: `logs/service-frontend/public-pages/mcp-registry-auth` (`LOG_DIR/public-pages/`, git 제외). 파일이 없으면 404다.
- 내용은 `v=MCPv1; k=ed25519; p=<base64 공개 키>` 한 줄만 허용한다. 형식이 다르거나 4096바이트를 넘으면 404로 막는다(개인 키를 실수로 두어도 공개되지 않게).
- 응답은 `text/plain`, 200, 리다이렉트 없음. 배포 없이 파일만 두면 바로 반영된다.

## 3. 사용자 실행 절차 (승인 뒤)
macOS 기본 LibreSSL은 Ed25519를 만들지 못하므로 Homebrew의 openssl@3을 쓴다. 키는 저장소 밖(예: `~/.mcp-registry/`)에 둔다.

```bash
brew install openssl@3 mcp-publisher
```

```bash
mkdir -p ~/.mcp-registry && cd ~/.mcp-registry && /opt/homebrew/opt/openssl@3/bin/openssl genpkey -algorithm Ed25519 -out key.pem && chmod 600 key.pem
```

```bash
cd ~/.mcp-registry && PUBLIC_KEY="$(/opt/homebrew/opt/openssl@3/bin/openssl pkey -in key.pem -pubout -outform DER | tail -c 32 | base64)" && mkdir -p ~/workspace/A2A_Discovery/logs/service-frontend/public-pages && echo "v=MCPv1; k=ed25519; p=${PUBLIC_KEY}" > ~/workspace/A2A_Discovery/logs/service-frontend/public-pages/mcp-registry-auth
```

```bash
curl -sS -o - -w '\n%{http_code}\n' -H 'Accept: text/plain' -A 'mcp-registry/1.0' https://agentconcierge.biz/.well-known/mcp-registry-auth
```
(한 줄과 200이 나와야 한다.)

```bash
cd ~/.mcp-registry && PRIVATE_KEY="$(/opt/homebrew/opt/openssl@3/bin/openssl pkey -in key.pem -noout -text | grep -A3 'priv:' | tail -n +2 | tr -d ' :\n')" && mcp-publisher login http --domain agentconcierge.biz --private-key "${PRIVATE_KEY}"
```

```bash
cd ~/workspace/A2A_Discovery/deploy/mcp-registry && mcp-publisher validate && mcp-publisher publish
```

```bash
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=biz.agentconcierge/agent-concierge"
```

DNS 방식으로 하려면 Cloudflare에서 apex TXT `v=MCPv1; k=ed25519; p=<PUBLIC_KEY>`를 추가하고 `mcp-publisher login dns --domain agentconcierge.biz --private-key ...`를 쓴다.

## 4. 게시 뒤
- `version`은 게시마다 올린다(같은 버전 재게시 불가). 서버의 `serverInfo.version`(지금 1.0.0)과 맞춘다.
- 0단계 계측(`agent_market/concierge/traffic.py`)의 MCP `clientInfo.name` 수로 효과를 본다. 기준선은 11-16.
- 이 파일을 바꿀 때는 `tests/test_growth_pages.py`를 돌린다.
