# 이름 후보 상표·충돌 조사 (D) — 2026-11-14

읽기 전용 조사다. 계정 생성, 출원, 도메인 구매, 문의는 하지 않았다. 법률 의견이 아니다. 출원하기 전에는 변리사 검색이 필요하다(지출 0 원칙 때문에 지금은 하지 않음).

## 0. 한눈에 보기

| 결론 | 내용 |
|---|---|
| 가장 위험 | **Agent Concierge(현재 이름)**: 같은 일을 하는 경쟁 서비스 `agentconcierge.io`가 있다("Find the Right AI Agent Across Every Marketplace"). 미국에는 같은 문자 상표 출원 `AGENT CONCIERGE`(Snagabiz LLC, 99797306, 42류 AI 비서·자율 에이전트, 2026-04-30 출원, 심사 중)도 있다. |
| 그다음 위험 | **Agentcon / Agentcon Gateway**: 등록 상표는 없다. 그러나 같은 분야(AI 에이전트)에서 Global AI Community의 **AgentCon** 행사(서울 포함 여러 도시)와 agentcon.io 행사가 이미 이름을 쓰고 있다. 영어 "con"에는 사기라는 뜻도 있다. |
| 소유자 후보 | **AgentValCon**: 4개 데이터베이스에서 같은 이름 0건, .com/.ai/.io/.dev는 NS가 없다(미등록 추정). 다만 등록된 VALCON(미국 7244888, 9·35·42류 데이터 소프트웨어)과 Qualys "Agent Val"(AI 에이전트 제품)이 가깝다. 검색 엔진은 AgentCon으로 고쳐 버린다. "con" 문제는 남는다. |
| 소유자 후보 | **Agent Value Gateway**: 같은 이름 0건. 하지만 설명적 표장이라 단독 상표 등록은 어렵다(아래 4절). 분류 설명어(descriptor)로 쓰기에 적합하다. |
| 새 후보 중 가장 깨끗함 | **Pearlstring**, **Nacrelink**: 4개 데이터베이스 0건, 웹 충돌 없음. Pearlstring.com은 판매용 주차 도메인이라 지출 0 원칙으로는 살 수 없다. 나머지 .ai/.io/.dev는 NS가 없다. |
| 주의 | Olas(Valory)의 AI 에이전트 앱스토어 이름이 **Pearl**이고, Claude용 기능 이름이 **Pearl Connect**다. 디자인 시스템 이름 "Pearl Connection"과 아주 가깝다. 공개 화면이나 상품명으로 쓰면 충돌 위험이 있다. |
| 권장 구조 | **"<만든 이름> — Agent Value Gateway"**. 만든 이름(coined)이 상표·검색 식별을 맡고, 설명어가 에이전트와 LLM에 기능을 알린다. 도메인은 당분간 agentconcierge.biz를 유지한다(지출 0). |

## 1. 상표 데이터베이스를 계정 없이 검색하는 방법과 실제 결과

### 1.1 USPTO Trademark Search (tmsearch.uspto.gov)
- 사람이 쓰는 방법
  1. https://tmsearch.uspto.gov/search/search-information 을 연다. 로그인은 필요 없다.
  2. 검색창에 단어를 넣는다. 기본은 wordmark 검색이다. `*`로 앞뒤를 열 수 있다(예: `agentcon*`).
  3. 왼쪽 필터에서 **Status = Live**와 **International Class 009·035·042**(소프트웨어·광고·SaaS)를 고른다.
  4. 결과의 일련번호(serial)를 누르면 TSDR 기록으로 넘어간다(상태, 지정상품, 거절 이유 문서).
  5. 비슷한 발음과 철자도 검색한다(예: `agent con`, `agentkon`, `agentcom`).
- 이번 조사에서 한 일: 웹 앱이 쓰는 백엔드 주소 `POST https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch`(Elasticsearch 질의, 공개 문서는 없음)를 키 없이 직접 불렀다. 같은 질의를 "google"로 시험해 295건이 나와 검색이 실제로 되는 것을 확인했다. 색인에는 2026-10-22 출원까지 들어 있었다.
- 결과(wordmark·pseudo 필드 AND 검색)

| 질의 | 건수 | 주요 내용 |
|---|---|---|
| `agentcon` | 0 | |
| `agentcon*` | 10 | 모두 AGENTCONNECT 계열이다(MoneyGram 등록 9·36·38류, United Insurance 36류 등). 소프트웨어 분야의 살아 있는 건은 MoneyGram 9류 송금 소프트웨어 1건이다. |
| `"agent concierge"` | 1 | **AGENT CONCIERGE, sn 99797306, Snagabiz LLC(플로리다주 올랜도), 42류, 2026-04-30 출원, 1(a) 사용 기반, 상태 NON-FINAL ACTION MAILED(심사관 거절 통지)**. 지정 서비스는 AI 가상 비서 SaaS, 자율 에이전트, 워크플로 자동화 PaaS, 챗봇이다. Trademarkia에는 최초 사용일 2026-02-01로 나온다. |
| `agentvalcon`, `agentval*`, `"agent val"` | 0 | |
| `valcon` | 11 | **VALCON 등록 7244888(Valcon A/S, 덴마크, 9·35·42류, 빅데이터 관리 소프트웨어) LIVE**. Qioptiq VALCON 9류(적외선 카메라) 출원도 살아 있다. |
| `"agent value"` | 1 | FULL AGENT VALUE(41류, 포기) |
| `"agent gateway"` | 3 | Tetrate.io AGENT GATEWAY(9·42류, 포기 2026-04), **WALMART AGENT GATEWAY(35·42류, 2026-10-22 출원, 심사 전)**, 부동산 1건(포기) |
| `agent AND value AND gateway` | 0 | |
| `pearlstring`, `pearlstrand`, `"pearl string"` | 0 | |
| `pearlink*` | 5 | **PEARLINK 등록 6206546(Airius IP Holdings, 9류, IoT 팬 제어 소프트웨어) LIVE**. Merck 안료 건과 1건의 소프트웨어 출원(2000)은 소멸했다. |
| `agentstrand`, `"agent strand"` | 0 | |
| `strandline*` | 1 | STRANDLINE WEALTH(36류, 포기) |
| `pearlwork*`, `nacreon`, `nacrelink`, `nacrely` | 0 | |
| `nacre*` | 47 | 9·42류 중 살아 있는 건은 NACRE(9류 전기 콘센트, Byrne) 하나다. 나머지는 화장품·시계·의류다. |
| `pearlchain` | 2 | PEARLCHAIN AI(42류 블록체인 호스팅, 2026-08-31 출원), 의료 카테터 |
| `strand` | 672 | 너무 흔하다. STRANDSYNC(42류 SaaS, 2026 출원) 등이 있다. |
| `clasp` | 161 | 9·42류에 살아 있는 건이 여러 개 있다(Baby List, Clasp Legal 등). 후보에서 뺐다. |

### 1.2 WIPO Global Brand Database (branddb.wipo.int)
- 사람이 쓰는 방법
  1. https://branddb.wipo.int/en/similarname 을 연다. 로그인은 필요 없다.
  2. 처음 열면 "Verifying..." 자동 확인 화면이 몇 초 나온다. 클릭할 것은 없었다.
  3. Brand name에 단어를 넣는다. 전략 **Simple**(단어 포함)과 **Fuzzy**(비슷한 단어)를 둘 다 본다.
  4. 왼쪽 필터에서 Nice class 9·35·42, 상태(Active), 국가를 고른다.
  - URL로 바로 열 수도 있다: `https://branddb.wipo.int/en/similarname/results?sort=score%20desc&start=0&rows=30&asStructure={"_id":"1","boolean":"AND","bricks":[{"_id":"2","key":"brandName","value":"<단어>","strategy":"Simple"}]}` (URL 인코딩 필요). 처음 열 때 자동 확인 뒤 질의가 사라지면 한 번 더 열면 된다.
- 이번 조사: 내장 브라우저로 위 URL을 열어 읽었다(90개 데이터 출처, 약 7,750만 건).

| 질의 | 결과 |
|---|---|
| agentcon (Simple) | 1건: **AGENTCON―SIPIO**(일본 4234930, 9·35·42류 등, 2009 만료) |
| agentcon (Fuzzy) | 712건. 상위: **AGENTACON**(독일 302015229962, AGENTAINVEST GmbH, 35류, 등록), **AgentOn**(일본 7033330, LegalOn Technologies, 9·35·42류 등, 2026-04-06 등록), AGENTCOM(프랑스, 만료), Agent.com(일본 42류, 등록) |
| agent concierge | **AGENT CONCIERGE 캐나다 TMA1021180**(Redline Realty, 35·36·37류 부동산, 2019 등록), **미국 99797306 Snagabiz(42류, 출원 중)**, UK00004096182 "concierge"(Concierge AI Technologies, 9·42류, 2024 등록) |
| agentcon gateway | 별도 일치 없음(AGENTCON―SIPIO와 GATEWAY 일반 건만 나옴) |
| agentvalcon | 0 |
| agent value gateway | 같은 이름 없음. 비슷한 것: AGENT GATEWAY(캐나다 1395457, 9·35·36·42류, 종료), Tetrate AGENT GATEWAY(미국, 종료), **VALUE GATEWAY(한국 4020190102649, 주식회사 데모데이, 35·36·38류, 종료)** |
| pearlstring, pearlwork, nacreon, nacrelink, agentstrand | 0 |
| pearlink | 8건. 살아 있는 건은 미국 PEARLINK 6206546(9류)뿐이다. |
| strandline | 2건: The Strandline(영국, 14류 보석, 2025 등록), STRANDLINE WEALTH(미국, 종료) |

### 1.3 KIPRIS (kipris.or.kr) — 한국
- 사람이 쓰는 방법
  1. https://www.kipris.or.kr 에서 상단 탭 **상표**를 고른다. 회원가입은 필요 없다(검색식 저장·다운로드만 회원 기능).
  2. 검색창에 영문과 한글 발음을 **둘 다** 넣는다(예: `AGENTCON`, `에이전트콘`). 한국 심사는 발음(칭호)이 비슷한지도 보기 때문이다.
  3. 상세검색에서 **상표명칭**에 넣고 **상품분류 09, 35, 42**와 행정상태(출원·공고·등록)를 고르면 범위가 좁아진다. 유사군 코드(예: G390802 컴퓨터 소프트웨어, S0601 등)로도 찾을 수 있다.
  4. 결과를 누르면 지정상품, 거절 이유, 존속 상태가 나온다.
- 이번 조사: 내장 브라우저에서 KIPRIS 자유검색(국내 상표)으로 찾았다. URL 파라미터만으로는 검색이 실행되지 않았다. 페이지의 검색창에 입력하고 Enter를 눌러야 했다. 시험 질의 "CONCIERGE"는 12,689건이 나와 검색이 실제로 되는 것을 확인했다. 자유검색은 지정상품 글자까지 찾는다. 그래서 두 단어 질의는 명칭이 아닌 결과도 섞인다.

| 질의 | 결과 |
|---|---|
| AGENTCON / 에이전트콘 | 0 / 0 |
| AGENT CONCIERGE / 에이전트컨시어지 | 명칭이 같은 건은 없다. 영문 질의 결과는 지정상품 글자 일치(Meta 상표 등)뿐이었다. 한글 질의는 0건. |
| AGENTVALCON | 0 |
| AGENT VALUE GATEWAY | 명칭이 같은 건은 없다(지정상품 글자 일치 170건: GMO PAYMENT GATEWAY 등) |
| PEARLSTRING, PEARLINK, STRANDLINE, PEARLWORK, NACRELINK | 0 |
| NACREON | ANACREON(1996, 소멸)만 나옴 |
| AGENT STRAND | **STRANDS AGENTS(아마존 테크놀로지스, 4020250150625, 9류, 출원 중)** |

- 확인하지 못한 것: 한글 발음 변형(펄스트링, 네이커링크 등)은 넣지 않았다. 유사군 코드 검색도 하지 않았다.

### 1.4 EUIPO eSearch / TMview (tmdn.org/tmview)
- 사람이 쓰는 방법
  1. https://www.tmdn.org/tmview 를 연다. 로그인은 필요 없다. 쿠키 안내에서는 "No thanks, only essential cookies"를 고르면 된다.
  2. 상표명을 넣고 "포함(contains)" 또는 "비슷함"을 고른다. 결과 필터에서 관청(EUIPO, KIPO, USPTO 등), 상품류, 상태를 고른다.
  - URL로 바로 열 수 있다: `https://www.tmdn.org/tmview/#/tmview/results?page=1&pageSize=30&criteria=C&basicSearch=<단어>`
  - EU 상표만 볼 때는 EUIPO eSearch plus(https://euipo.europa.eu/eSearch/)를 쓴다.
- 이번 조사
  - TMview의 JSON 주소를 직접 부르면 방화벽이 막았다("Request Rejected"). 내장 브라우저로는 열렸다.
  - **EUIPO eSearch는 터미널에서 연결이 되지 않았다(응답 0). 브라우저로는 시도하지 않았다. 그래서 EU 결과는 TMview에 들어 있는 EUIPO 자료로만 본 것이다.**

| 질의(포함) | 결과 |
|---|---|
| agentcon | 15건, 모두 AGENTCONNECT·AgentControl 계열(미국 13, 독일 1, 캐나다 1). EUIPO에는 일치가 없다. |
| agent concierge | 5건(캐나다 AGENT CONCIERGE 1832700 부동산 등) |
| agentvalcon, agent value gateway, pearlstring, agentstrand, strandline, nacrelink | 0 |
| pearlink | 11건(미국 Airius 9류 등록, 나머지 Merck 안료) |
| pearlwork | 1건: PEARLWORKSHOP(중국, 40류) |
| nacreon | ANACREON 계열(주류 33류)만 |

### 1.5 제3자 미러 사이트
| 사이트 | 결과 |
|---|---|
| trademarks.justia.com | 읽지 못함. Cloudflare 확인 화면(403 "Just a moment")이 떴다. 우회하지 않았다. |
| uspto.report | 읽지 못함. 같은 Cloudflare 확인 화면이다. |
| trademarkia.com | 읽음. `agentcon` 검색 결과는 10건이고 모두 AGENTCONNECT 계열이다(USPTO 결과와 같다): https://www.trademarkia.com/search/trademarks?q=agentcon . AGENT CONCIERGE 99797306은 Live/Pending, 최초 사용일 2026-02-01, Snagabiz LLC(올랜도)다: https://www.trademarkia.com/agent-concierge-99797306 |

## 2. 웹 충돌과 도메인 관찰

도메인은 공개 DNS(1.1.1.1)의 NS·A 기록과 HTTPS·HTTP 응답만 봤다. 유료 WHOIS는 쓰지 않았다. "NS 없음"은 미등록일 가능성이 높다는 뜻이다. 등록 가능 여부를 확인한 것은 아니다. 새 도메인은 등록비가 들어서 지금의 지출 0 원칙과 맞지 않는다.

| 도메인 | 관찰 |
|---|---|
| agentcon.com | 등록됨(GoDaddy NS). 성인 사이트로 넘긴다(301). |
| agentcon.ai | 등록됨. GoDaddy 주차 화면 |
| agentcon.io | **사용 중: "AgentCon — Steal This Workflow", 2026-05-13 온라인 AI 행사** |
| agentcon.dev | 등록됨(Cloudflare NS). Azure 404 |
| agentcongateway.(com/ai/io/dev) | NS 없음 |
| agentconcierge.com | 등록됨(SiteGround). HTTP로 열면 도박 스팸 글이 나온다(만료 뒤 남이 가져간 것으로 보임). |
| agentconcierge.ai | 등록됨. GoDaddy 주차 화면 |
| **agentconcierge.io** | **사용 중인 경쟁 서비스. 제목은 "AgentConcierge, Find the Right AI Agent Across Every Marketplace". 소개 문구는 "The control plane for your AI agents". OpenAI·Anthropic·Google 등 마켓을 색인해 에이전트를 추천하고 ROI·교체 알림을 준다. 요금은 Free·Pro $11.11·Business $99. 법인명·위치는 표시되지 않음.** |
| agentconcierge.dev | NS 없음 |
| agentconcierge.biz | 우리 도메인(운영 중) |
| agentvalcon.(com/ai/io/dev) | 4개 모두 NS 없음 |
| agentvaluegateway.(com/ai/io/dev) | 4개 모두 NS 없음 |
| pearlstring.com | 등록됨. 주차 화면에 "This domain may be for sale" 문구 |
| pearlstring.(ai/io/dev) | NS 없음 |
| pearlink.com | 등록됨. "Index of /" 빈 서버 |
| pearlink.(ai/io/dev) | NS 없음 |
| agentstrand.com | 등록됨. Afternic 판매 주차 |
| agentstrand.(ai/io/dev) | NS 없음 |
| strandline.com / .ai / .io / .dev | 모두 등록됨. .com은 WordPress, .ai는 GoDaddy 페이지, .io는 오션사이드 웹디자인 회사, .dev는 Namecheap 연락처 확인 정지 |
| pearlwork.com | HugeDomains 판매 중. .ai/.io/.dev는 NS 없음 |
| nacreon.com / .io | 등록됨(Cloudflare NS, 웹 없음). nacreon.dev는 "Coming Soon" |
| nacrelink.(com/ai/io/dev) | 4개 모두 NS 없음 |

웹 충돌 근거

- AgentCon 행사 시리즈(Global AI Community): https://globalai.community/agentcon/ , 도시별 발표자 모집 https://sessionize.com/agentcon-san-francisco/ , 파트너 안내(뉴욕·홍콩·**서울 4/16**·런던 9/8) https://www.avepoint.com/lp/agentcon-conference-2026
- agentcon.io 온라인 행사: https://agentcon.io/
- Qualys Agent Val(2026-03 출시 AI 에이전트): https://docs.qualys.com/en/etm/latest/agentic_ai/agent_val.htm , https://www.qualys.com/intro-agent-val
- "AgentValCon"을 정확히 검색해도 결과가 없다. 대신 AgentCon 행사와 Qualys Agent Val이 나온다(2026-11-14 웹 검색).
- Agent Value 관련: Microsoft Copilot Studio Kit의 "Agent Value" 대시보드·분류 구성요소 https://learn.microsoft.com/ar-sa/microsoft-copilot-studio/guidance/kit-agent-value-dashboard (영문판 경로는 같은 이름 `/en-us/`로 추정, 직접 확인은 안 함)
- Agent Gateway 분야는 붐빈다: Portkey https://portkey.ai/docs/aigw/product/agent-gateway.md , TrueFoundry https://www.truefoundry.com/ar/blog/introducing-agent-gateway-a-unified-control-plane-for-enterprise-ai-agents , Gravitee https://www.gravitee.io/blog/agent-gateway , IBM https://www.ibm.com/de-de/think/topics/agent-gateway , IETF 초안 https://datatracker.ietf.org/doc/draft-agent-gw/ , Webacy https://www.webacy.com/agent-gateway
- "Agentcon Gateway"를 정확히 검색해도 결과가 없다(일반 agent gateway 글만 나옴).
- Agent Concierge 비슷한 이름들: Crescendo Concierge https://www.crescendo.ai/agents/concierge , Agora AI Studio Concierge https://docs.agora.io/en/ai/studio/build/concierge , SignalWire ConciergeAgent https://developer.signalwire.com/sdks/agents-sdk/prefabs/concierge , MCP 서버 "concierge" https://mcpmarket.com/server/concierge
- Pearl 계열: **Olas Pearl(AI 에이전트 앱스토어)** https://olas.network/pearl , **Pearl Connect for Claude** https://itbrief.co.uk/story/olas-launches-pearl-connect-for-claude-coding-agents , NLPearl(AI 음성 에이전트) https://crunchbase.com/organization/nlpearl , Pearl.com(전문가 AI)
- Strand 계열: **AWS Strands Agents(오픈소스 에이전트 SDK)** https://strandsagents.com/ . 한국에는 STRANDS AGENTS 상표 출원이 있다(위 1.3).
- Nacre: Nacre Capital(이스라엘 딥테크 벤처 빌더, AI 회사 포함) https://www.crunchbase.com/organization/nacre-capital
- Pearlstring·Pearlwork·Nacreon·Nacrelink를 정확한 이름으로 검색해도 AI·소프트웨어 제품은 나오지 않았다(2026-11-14 웹 검색 1회씩).

## 3. 비교표

평가 기준
- 충돌: 없음 / 낮음 / 중간 / 높음
- 기억: 상·중·하
- 에이전트 적합: MCP `serverInfo.name`, A2A Agent Card `name`, llms.txt 제목에 쓰기 좋은지(ASCII 한 단어, 뜻 추정 가능, 기존 이름과 헷갈림 없음)
- 등록 가능성: 4절 기준. 내 추정이며 심사 결과가 아니다.

### 3.1 단독 이름

| 이름 | 충돌 (근거) | 상표 조사 결과 | 발음·영어 인상 | 기억 | 에이전트 적합 | 도메인 (.com/.ai/.io/.dev) | 등록 가능성 | 확장성 | 메모 |
|---|---|---|---|---|---|---|---|---|---|
| **Agentcon** | **높음**: 같은 분야 AgentCon 행사 시리즈(서울 포함), agentcon.io 행사 | USPTO 0, KIPRIS 0, TMview·EUIPO 0, WIPO는 일본 만료 1건. 비슷한 것: AGENTACON(독일 35류 등록), AgentOn(일본 9·42류 2026 등록) | "에이전트콘"으로 쉽게 읽힌다. 영어 화자에게는 "conference"(행사 이름)로 먼저 읽히고, "con"(사기, Merriam-Webster https://www.merriam-webster.com/dictionary/con)으로도 읽힌다. USDC 결제를 받는 서비스에는 불리하다. | 상 | 하: LLM과 검색이 행사로 헷갈린다 | 4개 모두 남이 사용·보유 | 만든 말이라 등록 자체는 가능해 보인다. 다만 행사 측의 선사용(미등록 상표, 미국 common law, 한국 부정경쟁방지법)과 부딪칠 수 있다. | 중: 이름이 "행사"로 굳어 있다 | 이름 바꾸기를 권하지 않는다 |
| **Agentcon Gateway** | **높음**: 위와 같다. Gateway는 흔한 분류어다. | USPTO·WIPO·TMview 0(조합으로는). AGENT GATEWAY는 Tetrate 포기, Walmart 출원 중 | Agentcon과 같은 문제다 | 중 | 중: 기능은 전달되지만 행사와 헷갈린다 | 4개 모두 NS 없음 | Gateway는 권리 불요구(disclaimer) 대상이다. 핵심은 Agentcon과 같다. | 중 | |
| **Agent Concierge**(현재) | **높음**: agentconcierge.io가 같은 일을 하는 경쟁 서비스다. AI "Concierge" 제품도 많다. | **USPTO 99797306 AGENT CONCIERGE(Snagabiz, 42류 AI 에이전트, 출원 중, 최초 사용 2026-02-01 주장)**, 캐나다 TMA1021180(부동산), 영국 "concierge"(Concierge AI Tech., 9·42류). KIPRIS 같은 명칭 0 | 뜻이 바로 통한다. 고급 안내 서비스라는 좋은 인상을 준다. | 중 | 중: 뜻은 분명하지만 일반 질의처럼 처리된다 | .com 스팸, .ai 주차, .io 경쟁사, .dev NS 없음, .biz 우리 것 | 설명·암시 경계다. 미국 출원이 거절 통지를 받은 상태라 결과를 볼 필요가 있다. 우리가 미국에서 쓰면 그 출원과 충돌할 위험이 있다. | 하: Value Gateway 방향과 맞지 않는다 | 미국 99797306 진행 상황을 TSDR에서 계속 볼 것 |
| **AgentValCon**(소유자) | **중간**: 같은 이름은 없다. 검색 엔진이 AgentCon으로 고친다. Qualys "Agent Val"(AI 에이전트)가 있다. | USPTO·WIPO·KIPRIS·TMview 모두 0. 다만 **VALCON 미국 등록 7244888(9·35·42류)**이 뒷부분과 같다. | "에이전트-밸-콘". 영어 화자에게는 "Agent Val + con(행사·사기)"으로 끊겨 읽힌다. "Value Concierge"라는 뜻은 설명하지 않으면 전달되지 않는다. | 중하 | 중하: LLM이 Agent Val이나 AgentCon으로 오인할 수 있다 | 4개 모두 NS 없음(미등록 추정, 등록비 필요) | 만든 말이라 식별력은 있다. VALCON(같은 류)과의 유사 판단은 변리사 확인이 필요하다. | 중 | 대소문자(AgentValCon)를 지키지 않으면 agentvalcon으로 읽힌다 |
| **Agent Value Gateway**(소유자) | **낮음**(같은 이름 없음). 하지만 "Agent Gateway"·"Agent Value"라는 말은 널리 쓰인다. | 4개 데이터베이스 같은 이름 0. 가까운 것: Walmart AGENT GATEWAY 출원, VALUE GATEWAY(한국, 종료) | 뜻은 아주 분명하다. 브랜드 느낌은 약하다. | 하 | **상**(기능 설명으로) / 하(고유 이름으로) | 4개 모두 NS 없음 | **단독 등록은 어렵다고 본다**: 서비스 내용을 그대로 말한다(미국 TMEP 1209 "merely descriptive", 한국 상표법 33조 1항 3호 성질표시). | 상(분류어로) | 설명어로 쓰는 것을 권한다 |
| **Pearlstring**(새) | **낮음**: 같은 이름의 AI·소프트웨어 제품이 없다. Pearl 계열(Olas Pearl 등)이 주변에 있다. | 4개 데이터베이스 0 | "펄스트링". 진주 목걸이(string of pearls)가 바로 떠오르고 "연결된 가치"와 맞는다. string은 개발자에게 문자열이라는 뜻도 있어 친숙하다. | 상 | 상: `pearlstring` 한 단어, 소문자 ASCII | .com 판매 주차, .ai/.io/.dev NS 없음 | 암시적(suggestive) 표장으로 보여 등록 가능성이 높다고 본다 | 상: necklace, pearl, clasp 하위 이름을 붙이기 좋다 | 1순위 추천 |
| **Nacrelink**(새) | **낮음**: 웹·데이터베이스 0 | 4개 데이터베이스 0 | "네이커링크". nacre(진주층)를 모르는 사람이 많다. 철자를 틀리기 쉽다. | 중 | 상: 고유하고 link가 연결을 알린다 | 4개 모두 NS 없음 | 만든 말이라 식별력이 높다 | 중 | 2순위 |
| **Pearlwork**(새) | **낮음** | USPTO·WIPO·KIPRIS 0, TMview는 중국 PEARLWORKSHOP(40류)뿐 | "펄워크". 쉽다. 진주 공예 느낌이 난다. | 중 | 중: work가 일반어다 | .com HugeDomains 판매, 나머지 NS 없음 | 암시적 | 중 | |
| **Nacreon**(새) | **낮음~중간**: 소프트웨어 충돌은 없다. 누군가 nacreon.com·.io·.dev를 갖고 있고 .dev에 "Coming Soon"이 떠 있다. | 4개 데이터베이스는 ANACREON(주류)뿐 | "네이크리온". 낯설다. | 중하 | 중 | .com·.io·.dev 남이 보유, .ai NS 없음 | 만든 말 | 중 | 곧 남이 쓸 수 있다 |
| **Strandline**(새) | **중간**: AWS Strands Agents(에이전트 SDK)와 가깝다. 도메인 4개 모두 남이 사용한다. | USPTO 포기 1건, 영국 The Strandline(14류 보석) 등록, KIPRIS 0 | "스트랜드라인". 해안선이라는 뜻도 있다. | 중 | 중하: Strands와 헷갈린다 | 4개 모두 사용·보유 | 암시적 | 중 | 비추천 |
| **Agent Strand**(새) | **높음**: AWS Strands Agents와 단어 순서만 다르다 | USPTO·WIPO·TMview 0. **하지만 KIPRIS에 STRANDS AGENTS(아마존, 9류) 출원이 있다** | 쉽다 | 중 | 하: Strands Agents로 오인된다 | .com Afternic 판매, 나머지 NS 없음 | 아마존 출원과 비슷해 거절될 위험이 있다 | 중 | 비추천 |
| **Pearlink**(새) | **중간**: 같은 이름 등록(9류 소프트웨어) | **USPTO PEARLINK 등록 6206546(Airius, 9류) LIVE**, KIPRIS 0 | "펄링크". 쉽다. | 상 | 중 | .com 보유(빈 서버), .ai/.io/.dev NS 없음 | 같은 류에 같은 이름이 있어 미국에서는 어렵다 | 중 | 비추천 |

### 3.2 조합안 "<고유 이름> — Agent Value Gateway"

설명어는 서비스 분류를 알린다. 상표로 출원할 때 설명어 부분은 보통 "권리 불요구(disclaimer)" 대상이다(USPTO TMEP 1213). 보호는 앞의 고유 이름이 받는다.

| 조합 | 충돌 | 등록 가능성 | 에이전트 적합 | 평가 |
|---|---|---|---|---|
| Agentcon — Agent Value Gateway | 높음(AgentCon 행사) | 앞부분 문제가 그대로 남는다 | 중: 설명어가 기능을 알리지만 이름 검색은 행사로 간다 | 비추천 |
| AgentValCon — Agent Value Gateway | 중간(VALCON, Agent Val, AgentCon 자동 고침) | 앞부분은 가능성이 있다. VALCON 확인이 필요하다. | 중: 설명어 덕분에 "Value Concierge"라는 뜻이 보완된다 | 쓸 수 있다. 단, "con" 인상과 검색 자동 고침이 남는다. |
| **Pearlstring — Agent Value Gateway** | 낮음 | 앞부분 등록 가능성이 높다고 본다 | **상**: `pearlstring`(이름) + "Agent Value Gateway"(기능) | **추천**. 진주(pearl)·목걸이(necklace) 비유와 디자인 시스템이 이어진다. |
| Nacrelink — Agent Value Gateway | 낮음 | 높음 | 상 | 차선 |
| Agent Concierge — Agent Value Gateway | 높음(agentconcierge.io, 미국 출원) | 낮음 | 중: "Agent"가 두 번 나와 어색하다 | 비추천. 다만 바꾸는 동안 이전 이름 표시("formerly Agent Concierge")로는 쓸 수 있다. |

에이전트용 텍스트 예시(제안, 적용하지 않음)
- MCP `serverInfo.name`: `pearlstring`, `title`: "Pearlstring — Agent Value Gateway"
- A2A Agent Card `name`: "Pearlstring", `description` 첫 문장: "Agent Value Gateway: finds verified AI agents and strings them into workflows."
- llms.txt 첫 줄: `# Pearlstring (Agent Value Gateway, formerly Agent Concierge)`
- 공식 MCP Registry 이름 `biz.agentconcierge/agent-concierge`는 도메인 네임스페이스에 묶여 있다. 도메인을 유지하면 그대로 두고 표시 이름만 바꿀 수 있다. 바꾸려면 새 이름으로 다시 게시해야 하며, 이것은 외부 게시라 승인이 필요하다.

### 3.3 지출 0과 도메인
- 새 도메인은 등록비가 든다. 지금 원칙(수익 전 지출 0)에서는 사지 않는다.
- 당분간 agentconcierge.biz에서 새 이름을 표시하는 방법이 있다(제목, 문구, 경로 `/pearlstring` 등). 수익이 생긴 뒤 .ai나 .dev를 사면 된다(사용자 승인 필요).
- 위에서 "NS 없음"으로 나온 도메인도 그 사이에 남이 등록할 수 있다.

## 4. 식별력 기준(짧게)

- **미국 USPTO**: 식별력은 다섯 단계로 본다. 만든 말(fanciful) > 무관한 기존 단어(arbitrary) > 암시(suggestive)는 바로 등록할 수 있다. 설명적(descriptive) 표장은 Lanham Act §2(e)(1)로 거절된다. 5년 이상 계속 사용하는 등 사용으로 식별력(§2(f))을 얻어야 등록된다. 보통명칭(generic)은 등록할 수 없다. 출처: TMEP §1209.01(https://tmep.uspto.gov 에서 1209.01을 찾으면 된다. 원문은 직접 열어 확인하지 않았다. 요약은 2차 출처 https://www.belldavispitt.com/tmc-blog/spectrum-of-distinctiveness-fanciful-arbitrary-suggestive-and-descriptive-trademarks 기준). 설명어 권리 불요구는 TMEP §1213.
- **한국 KIPO/KIPRIS**: 상표법 제33조 제1항 제3호는 상품·서비스의 품질, 효능, 용도 등을 보통의 방법으로 표시한 표장만으로 된 상표의 등록을 막는다(성질표시). 제33조 제2항은 출원 전부터 사용해 수요자가 누구의 상표인지 뚜렷이 알게 된 경우에만, 사용한 상품에 한해 예외를 둔다. 대법원은 이 입증을 엄격하게 본다. 출처 요약: https://www.help-me.kr/blog/article/%EB%82%B4%EC%83%81%ED%91%9C%EB%B3%B4%ED%86%B5%EB%AA%85%EC%B9%AD%EC%9D%B4%EB%82%98%EC%84%B1%EC%A7%88%ED%91%9C%EC%8B%9C%EC%83%81%ED%91%9C%EB%A1%9C%EA%B1%B0%EC%A0%88%EB%90%98%EC%A7%80%EC%95%8A%EC%9C%BC%EB%A0%A4%EB%A9%B4/ , 대법원 판결 PDF https://file.scourt.go.kr/dcboard/1583129525179_151205.pdf . 조문 원문은 국가법령정보센터에서 확인해야 한다(이번에는 열지 않음).
- 적용: "Agent Value Gateway"와 "Agent Concierge"는 설명·암시 경계에 있다(AI 에이전트를 소개·연결하는 서비스를 그대로 말함). Pearlstring과 Nacrelink는 진주 비유를 빌린 암시적·조어 표장이라 식별력이 높다고 본다. 이것은 내 추정이며 심사 결과가 아니다.

## 5. 확인하지 못한 것(정직하게)

- EUIPO eSearch는 직접 열지 못했다(터미널 연결 실패). EU 결과는 TMview에 포함된 자료만 본 것이다.
- Justia와 uspto.report는 Cloudflare 확인 화면 때문에 읽지 못했다. 우회하지 않았다.
- 미국 99797306의 거절 통지 내용(설명적 표장 거절인지 등)은 TSDR 문서를 열지 않아 모른다.
- AgentCon 행사 쪽의 상표 출원은 찾지 못했다. 미등록 사용 권리는 데이터베이스로 판단할 수 없다.
- 우리 "Agent Concierge" 사용 시작일과 Snagabiz 주장 최초 사용일(2026-02-01)의 선후는 확인하지 않았다.
- 도메인의 등록 가능 여부와 가격은 확인하지 않았다(NS·HTTP 관찰만).
- KIPRIS에서 한글 발음 변형(펄스트링, 네이커링크 등)과 유사군 코드 검색은 하지 않았다.
- 웹 충돌 검색은 이름마다 1~2회였다. 아주 새롭거나 작은 프로젝트는 빠졌을 수 있다.
- 모든 상표 검색은 소프트웨어(9·35·42류) 중심으로 봤다. 다른 류는 참고만 했다.
