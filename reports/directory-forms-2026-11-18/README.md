# 계정 없이 되는 디렉터리 4곳: 양식 칸, 넣을 문구, 약관의 자동·대리 등록 조항 (성장·유통, 11-18 19:3x)

PM 지시: 한 표로 만들고 등록 실행은 PM이 한다. 네 곳의 제출 화면과 약관 페이지를 읽기만 했다(가입·제출·입력 없음). 값은 11-15 제출표의 공통 정보와 PM이 11-18에 승인한 한 줄 설명을 쓴다.

## 넣을 값 (공통)
| 항목 | 값 |
|---|---|
| 이름 | AgentValCon |
| 한 줄 설명(승인, 82자) | `Find AI agents for a task; run workflows built from agents we tested, in one call.` |
| 엔드포인트 | `https://agentconcierge.biz/mcp` (Streamable HTTP, 키 없음) |
| 웹사이트 | `https://agentconcierge.biz/connect` |
| A2A 카드 | `https://agentconcierge.biz/.well-known/agent-card.json` |
| 공식 Registry 이름 | `biz.agentconcierge/agent-concierge` |
| 연락 메일(사이트 공개 주소) | `contact@agentconcierge.biz` |
- 목걸이가 검증됐다거나 관문을 통과했다는 문구는 쓰지 않는다(지금 공개된 것은 미리보기 하나). 숫자는 쓰지 않는다.

## 표
| 곳 | 제출 화면의 칸 | 넣을 값 | 약관의 자동·대리 등록 조항 | 막힐 수 있는 것 | 판단 |
|---|---|---|---|---|---|
| LocalMark (localmark.ai/submit) | **Card URL** 한 칸(공개 HTTPS 주소, `/.well-known/agent-card.json` 또는 옛 `agent.json`). 제출하면 자동 검사 대기열에 들어감 | `https://agentconcierge.biz/.well-known/agent-card.json` | 약관(2026-10-28.2)에 자동·대리 등록을 금지하거나 허용하는 조항이 없음. "광고할 권한이 있는 카드만 제출", 사칭·유해·방해 금지, 목록 제외·삭제 권리. 소유 주장(claim)은 카드 호스트 제어와 메일 확인이 필요하지만 제출에는 필요 없음. "제출은 등재를 보장하지 않는다" | 화면에 CAPTCHA·로그인 언급 없음(제출 전에는 알 수 없음) | **제출 가능**. 로그인이나 CAPTCHA가 나오면 멈춤 |
| mcpub.dev | 웹 폼 **URL**과 **description**, 또는 MCP `submit` 도구(`https://mcpub.dev/mcp`, 인자 url·description). 사전 조건: 도메인에 `/.well-known/mcp.json`(내용 아무거나) | URL `https://agentconcierge.biz/mcp`, description 승인된 한 줄 | **약관 페이지를 찾지 못함**(링크 없음). 사이트가 에이전트용 `submit` 도구를 직접 제공하므로 자동 제출이 사이트의 정식 경로다. "If your server responds, it's listed — no gatekeepers" | 사전 조건 파일은 우리가 이미 내보냄(11-17 운영 200 확인, 제출 직전에 한 번 다시 확인) | **제출 가능**. 약관 문서가 없다는 것을 기록에 남김 |
| agents.ml (agents.ml/claim) | **Agent name**, **URL slug**(agents.ml/your-agent), **Email**(소유 확인용, 공개 안 됨). 그 뒤 메일 확인을 거쳐 엔드포인트·설명·링크를 추가 | 이름 AgentValCon, slug `agentvalcon`(되면), 메일 `contact@agentconcierge.biz`. 확인 뒤 엔드포인트와 설명 추가 | 약관(2026-04-08)에 자동·대리 등록 조항은 없음. "소유하거나 대표할 권한이 있는 에이전트만 claim", 스팸·악용 금지, 재량으로 삭제, 13세 이상 | **폼에 "Human verification is required"가 있어 CAPTCHA가 있다.** 이 세션과 PM 세션은 CAPTCHA를 풀 수 없다. 메일 확인 링크도 받은편지함에서 눌러야 함 | **사용자 몫**(사람이 CAPTCHA와 메일 확인). 아니면 보류 |
| mcpservers.org (/submit, 화면은 한국어로 뜸) | 서버 이름, 카테고리(목록), 간단한 설명, 저장소·웹사이트·문서 링크, 공식 MCP Registry 이름(선택), "원격 연결 지원" 체크, **연락처 이메일**, 제출 요금제(무료 $0 / 프리미엄 $39) | 이름 AgentValCon, 카테고리 검색(Search), 설명 승인된 한 줄, 링크 `https://agentconcierge.biz/connect`, Registry 이름 위 값, 원격 연결 체크, 메일 `contact@agentconcierge.biz`, **요금제 무료** | 약관·개인정보 링크를 찾지 못함. 자동·대리 등록 조항 확인 불가(문서 없음) | 무료는 심사 최대 2주. 프리미엄 $39는 지출이라 하지 않음. 화면에 CAPTCHA 언급 없음 | **제출 가능**(무료 요금제만). 약관 문서가 없다는 것을 기록에 남김 |

## 순서와 주의
1. 공식 Registry 1.2.0 게시(배포 뒤 PM)를 먼저 하는 것이 낫다. 이름과 설명이 새 문구로 바뀐 뒤 제출하면 같은 한 줄이 모든 곳에 맞는다. mcpservers.org의 "공식 MCP Registry 이름" 칸은 그 항목을 가리킨다.
2. 각 곳 제출 중 로그인·CAPTCHA·약관 동의·결제가 나오면 멈추고 그 한 건만 사용자에게 넘긴다.
3. 제출 뒤 하루 뒤에 각 사이트 검색으로 이름과 설명이 맞는지 읽기만 하고 PM에 보고한다(성장·유통).
4. 약관을 못 찾은 곳(mcpub.dev, mcpservers.org)은 "약관 없음"이지 "허용"이 아니다. 요구하는 것은 사이트가 제시한 칸뿐이라 그 안에서만 넣는다.
