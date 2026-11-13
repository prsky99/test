# 새 수집 원천 조사 (2026-11-14, 검색과 RAG)

PM 초격차 전략 보완 4를 조사했습니다. 순서는 HOL Registry Broker → Agentverse → Glama·Smithery·PulseMCP(원격만) → Virtuals·NANDA입니다.

- 수집 조건: 키 없이 받을 수 있고, 약관이 막지 않아야 합니다. 그렇지 않으면 수집하지 않습니다.
- 그대로 두는 것: 호스트 쏠림 상한, 사설 주소 차단, x402 수집 중지(`COLLECT_X402=0`)
- 조사 방법: 공식 문서와 키 없는 읽기 요청 1~2회(응답 1~2건). 가입, 키 사용, 폼 제출은 하지 않았습니다.
- 직접 다시 확인한 것(05:2x)
  - HOL `/stats`: 키 없이 200, 249,183건, 16곳
  - NANDA: 응답 헤더 `x-ratelimit-limit: 120`(60초)
  - Glama: 키 없이 401

## 표
| 원천 | 목록 API | 키 | 약관(자동 접근·재배포) | 규모 | 원격 MCP 구분 | 한도 | 권고 |
|---|---|---|---|---|---|---|---|
| HOL Registry Broker | `GET hol.org/registry/api/v1/search?q=&page=&limit≤500&registries=&type=` | 필요 없음(키를 쓰면 한도 버킷만 바뀜) | 약관 페이지 403으로 못 읽음. robots에 `search=yes, ai-train=no, use=reference`, crawl-delay 1초 | 249,183(16곳: erc-8004 70,896, agentverse 46,591, virtuals 41,887, x402 28,424, pulsemcp 24,173, nanda 2,637 등) | `metadata.protocol`, `connectionTransport`, `connectionUrl` | 공개 수치 없음, 429와 백오프만 안내 | **약관 확인 뒤 수집** |
| Fetch.ai Agentverse | `POST agentverse.ai/v1/search/agents` | 문서는 키 요구, 실측은 키 없이 응답 | fetch.ai 약관이 로봇·자동 수단 접근과 API 자동 사용·재공개를 금지 | 약 46,591(HOL 집계) | 해당 없음(uAgents 프로토콜, A2A·MCP 아님) | 없음 | **수집하지 않음** |
| Glama | `GET glama.ai/api/mcp/v1/servers` | **필요**(키 없이 401) | 키 없는 접근 금지, 우회 스크래핑 금지, 대량 재배포 금지, **경쟁 디렉터리 구축 금지** | 120,661(원격 47,377) | `hosting:remote-capable` | IP당 초당 100 | **수집하지 않음** |
| Smithery | `GET registry.smithery.ai/servers?page=&pageSize=` | 문서는 키, 실측은 키 없이 응답 | 약관 페이지 없음. Arcade 인수 뒤 10-31 API 종료 공지(아직 응답) | 20,751 | `remote`, `deploymentUrl`, `connections[].type` | 없음 | **확인 뒤 수집(지금은 보류)** |
| PulseMCP | `GET api.pulsemcp.com/v0.1/servers` | **필요**(파트너 전용 키, 발급은 메일 문의) | 약관 못 찾음 | 21,552 | `remotes[]` 대 `packages[].transport` | 분 200, 하루 10,000 | **수집하지 않음**(공식 MCP Registry로 대신) |
| Virtuals ACP | 공식 문서 없음. SDK가 `acpx.virtuals.io/api/agents/v4/search` 사용 | 실측상 필요 없음(문서 근거 없음) | 약관 못 찾음 | 44,115 | 해당 없음(지갑 기반, 유료 작업) | 없음 | **보류**(결제 없는 시험 불가, 약관 미확인) |
| NANDA Index v2 | `GET api.nandaindex.org/api/v1/index`, `/api/ard/agents`(A2A 카드 URL) | 필요 없음(공개 읽기 면) | 약관 못 찾음. 코드는 Apache-2.0, 데이터 라이선스 미표기 | 기관 약 125곳 | `type=application/a2a-agent-card+json`, `url` | 분당 120 | **지금 수집** |

## 원천별 주의
- **HOL**
  - 검색 1회 결과가 10,000건에서 잘립니다. 레지스트리·유형별로 나눠 받아야 합니다.
  - 재배포분(Agentverse, Virtuals, x402)의 약관 문제는 HOL을 거쳐도 그대로 남습니다. 그래서 수집할 때는 이 원천들을 `registries`에서 뺍니다.
    - 받는 것: erc-8004(우리 직접 수집과 겹침 확인), nanda, a2a-registry, hashgraph-online, godaddy-ans 등
  - pulsemcp 출처의 `connectionUrl`은 실제 MCP 주소가 아니라 소개 페이지입니다. 원본 저장소나 공식 MCP Registry로 다시 확인합니다.
  - 약관 확인: hol.org/terms가 자동 요청에 403을 줍니다. 사람이 브라우저로 확인해야 합니다(PM 판단 요청).
- **NANDA**
  - 규모가 작고 시험·데모 항목이 섞여 있습니다.
  - 개인 에이전트 식별자에 **개인 이메일**이 들어 있어, 저장 전에 `subjectAccount`와 이메일을 버립니다.
  - 데이터 라이선스가 없어 재배포 대신 링크와 요약으로 씁니다.
  - 분당 120회 이하, 1초 간격으로 받습니다.
- **Smithery**: 운영사 변경과 API 종료 공지가 있습니다. Arcade가 공식 API와 약관을 내놓으면 다시 봅니다. 남은 `deploymentUrl`(*.run.tools)은 죽은 주소일 가능성이 높습니다.
- **Virtuals**: 에이전트를 쓰려면 온체인 유료 작업이 필요합니다. 그래서 결제 없는 읽기 전용 시험 원칙으로는 품질을 검증할 수 없습니다.

## 첫 적용 계획 (11-19)
1. NANDA Index v2 수집기
   - `collector/registries.py`에 원천을 추가합니다. A2A 카드 URL만 받습니다.
   - `check_public_url`, 호스트 쏠림 상한, 개인정보(이메일) 제거를 적용합니다.
   - 시험과 실제 1회 수집 결과를 COLLECTOR.md에 남깁니다.
2. HOL: PM이 약관을 확인하면 허용된 하위 원천만 `registries`로 걸러 수집합니다.
   - 중복 제거는 카드 URL과 MCP 엔드포인트 기준입니다.
3. 운영 DB 구조 변경은 필요 없습니다. 기존 resources·출처 칸을 씁니다.

원자료(응답 1~2건씩)는 scratchpad `reg/`에 있습니다(공개 저장소에 넣지 않음).
