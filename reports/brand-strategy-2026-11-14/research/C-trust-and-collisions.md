# 브랜드 조사 C: AI 신뢰·평가 브랜드와 이름 충돌 사례 (2026-11-14 조사)

- 범위: 웹 공개 자료만 읽음. 게시·가입·연락 없음.
- 표기 규칙
  - "1차": 회사·법원·기관 자체 문서
  - "2차": 언론·로펌 블로그
  - "약함": 집계 사이트나 재게시뿐이라 사실 확인이 더 필요함
- 확인하지 못한 것은 "미확인"으로 적었고 결론에 쓰지 않았다.

---

## A. 신뢰·검증·평가 브랜드

### A-1. 이름과 포지셔닝

| 브랜드 | 이름·자기 소개 | 신뢰 근거로 내세우는 것 | 날짜·출처 |
|---|---|---|---|
| Artificial Analysis | "an independent AI benchmarking and insights provider" | 익명 계정과 일반 개발자 계정으로 측정해 조작을 막는다. 등재는 자기 재량이고 무결성 약관을 지키지 않으면 내린다. 랩이 돈을 내는지는 페이지에 없다. | 방법론 페이지(1차, 2026-11-14 확인) [link](https://artificialanalysis.ai/methodology/performance-benchmarking). 수익원은 기업 구독과 비공개 맞춤 벤치마크다(Latent Space 인터뷰, 2차) [link](https://podwise.ai/episodes/6756174). |
| Chatbot Arena → LMArena → **Arena** | 2025-04: 회사 Arena Intelligence Inc., 브랜드 LMArena. 2026-01-28: "LM"을 떼고 Arena(arena.ai)로 바꿈. 이유는 "we have outgrown the 'LM'", 그리고 범위가 코딩·검색·이미지·에이전트로 넓어진 것. | 사람 투표 기반 공개 순위. 바꾼 이름에는 "trustworthy, precise, academic" 느낌을 노렸다고 적었다. 중립성 선언은 없다. | Bloomberg 2025-04-17(2차) [link](https://www.bloomberg.com/news/articles/2025-04-17/popular-ai-ranking-website-chatbot-arena-is-becoming-a-real-company), Maginative(2차) [link](https://www.maginative.com/article/chatbot-arena-rebrands-as-lmarena-becomes-a-company/), Arena 블로그 2026-01-28(1차) [link](https://arena.ai/blog/lmarena-is-now-arena/) |
| Arena 자금 | 2025-05 시드 1억 달러(a16z·UC Investments, 기업가치 6억 달러). 2026-01-06 시리즈 A 1.5억 달러(약 17억 달러). | 대학 프로젝트에서 시작한 회사. 랩에 평가를 팔면서 동시에 심판을 맡는다는 이해충돌 논쟁이 있다. | Bloomberg 2025-05-21(2차) [link](https://www.bloomberg.com/news/articles/2025-05-21/lmarena-goes-from-academic-project-to-600-million-startup). 시리즈 A는 집계 사이트뿐이라 약함 [link](https://seedtable.com/companies/lmarena/funding-rounds/series-a-2026-01). |
| Scale AI SEAL Leaderboards | 2024-05-29 출시. "Safety, Evaluations and Alignment Lab". | 비공개 데이터셋이라 학습에 섞일 수 없다. 검증된 분야 전문가가 평가한다. 프롬프트를 봤을 수 있는 개발사는 참여를 제한한다. | Scale 블로그(1차) [link](https://scale.com/blog/leaderboard), SiliconANGLE 2024-05-29(2차) [link](https://siliconangle.com/2024/05/29/scale-ai-publishes-first-llm-leaderboards-ranking-performance-ai-models-specific-domains/). 반론: 비공개 큐레이터가 자기 데이터로 학습한 모델에 유리하게 편향될 수 있다(arXiv 2503.04756, 2025-03) [link](https://arxiv.org/html/2503.04756v1). |
| Vals AI | "The independent evaluator of artificial intelligence" | 비공개 테스트셋을 쓰고, 모델을 만드는 회사가 직접 하는 벤치마크와 다르다고 강조한다. 도구 일부는 공개했다. 법률 분야 보고서 VLAIR을 2025-02에 냈다. | About(1차, 2026-11-14 확인) [link](https://vals.ai/about). 2026-08 시리즈 A 4천만 달러(a16z)는 재게시·Sacra만 확인돼 약함 [link](https://sacra.com/c/vals-ai). |
| Epoch AI | 비영리 연구 기관이며 FrontierMath를 만들었다. | 연구 투명성 | 2025-01: OpenAI가 FrontierMath 제작비를 댔다는 사실을 o3 발표 때까지 밝히지 않아 비판받았다. Epoch는 "made a mistake"라고 인정하고 비공개 문제 세트를 따로 두었다. TechCrunch 2025-01-19(2차) [link](https://techcrunch.com/2025/01/19/ai-benchmarking-organization-criticized-for-waiting-to-disclose-funding-from-openai) |
| HELM (Stanford CRFM) | "Holistic Evaluation of Language Models". 2025-03-20에 HELM Capabilities를 냈다. | 프롬프트 단위 투명성(원문 프롬프트를 볼 수 있음), 오픈소스 프레임워크로 재현할 수 있음, 학계 소속 | CRFM 블로그 2025-03-20(1차) [link](https://crfm.stanford.edu/2025/03/20/helm-capabilities.html). "새 평가 추가 중단"이라는 주장은 3자 사이트뿐이라 미확인. |
| HF Open LLM Leaderboard | 같은 설정에서 재현할 수 있는 점수를 냈다. v1은 2024-06에 보관했다. 2025-03-13에 전체 은퇴를 발표했다(1.3만 개 넘는 모델 평가). | 재현성: 하네스 버전·명령을 공개하고 결과 데이터셋도 공개했다. | HF 보관 문서(1차) [link](https://huggingface.co/docs/leaderboards/en/open_llm_leaderboard/archive), 은퇴 발표 스레드 2025-03-13(2차) [link](https://threadreaderapp.com/user/clefourrier) |

### A-2. MCP·에이전트 신뢰 장치와 마켓플레이스 "검증"

| 대상 | 무엇을 검증하나 | 날짜·출처 |
|---|---|---|
| Glama MCP 점수 | 보안·라이선스·품질 세 축으로 A–F 등급을 매긴다. 품질 = 도구 정의 품질(TDQS) 70% + 서버 일관성 30%. TDQS는 6개 차원이다. 서버 단위 점수 = 평균 60% + 최저 40%라서 나쁜 도구 하나가 점수를 끌어내린다. LICENSE가 없으면 설치할 수 없다. 보안 검사는 소유권을 주장한 서버만 하고, 나머지는 "not tested"로 표시한다. | TDQS 블로그 2026-04-03(1차) [link](https://glama.ai/blog/2026-04-03-tool-definition-quality-score-tdqs), 방법론(1차) [link](https://glama.ai/mcp/methodology) |
| Smithery | 공식 "verified" 배지 기준은 **찾지 못함**. 개발자 글에 따르면 Smithery는 서버에 0–100 점수를 매기고, 설명과 inputSchema를 갖추면 점수가 오른다. | 개발자 블로그(2차, 날짜 미상) [link](https://dev.to/francofuji/your-mcp-server-scores-60100-on-smithery-what-it-means-and-how-to-hit-100-1h2b). 배지 기준은 미확인. |
| 공식 MCP Registry | 2025-09-08 미리보기로 출시. 이름 공간을 역도메인 형식(io.github.user/…, com.example/…)으로 쓰고, GitHub OAuth·OIDC·DNS·HTTP로 소유를 확인한다. 품질은 평가하지 않고 메타데이터만 둔다. | 공식 문서(1차) [link](https://modelcontextprotocol.io/registry/about) |
| AWS Marketplace "AI Agents and Tools" | 2025-07-16 출시, 등재 800–900개 이상(출처마다 다름). 등재에 MCP·A2A 지원 여부를 표시한다. "Deployed on AWS" 배지는 **미확인**. | PYMNTS 2025(2차) [link](https://www.pymnts.com/artificial-intelligence-2/2025/aws-unveils-ai-agent-marketplace-as-one-stop-shop-for-enterprise-deployment/), AWS APN 블로그(1차) [link](https://aws.amazon.com/blogs/apn/aws-partner-guide-to-ai-agents-and-tools-in-aws-marketplace) |
| Microsoft 365 Agent Store | 2025-05 출시, 처음 70개 넘는 에이전트로 시작했다. 파트너 에이전트는 보안·준수·성능을 검증한 뒤 올라가고, 관리자가 설치 허용을 정한다. "Microsoft 365 Certified" 에이전트 배지는 **미확인**. | MS 개발자 블로그 2025-05(1차) [link](https://devblogs.microsoft.com/microsoft365dev/introducing-the-agent-store-build-publish-and-discover-agents-in-microsoft-365-copilot/), 도입 가이드 PDF(1차) [link](https://adoption.microsoft.com/files/agents/AgentStorePracticalGuide.pdf) |
| Salesforce AgentExchange | 2025-03-04 출시, 파트너 200곳 넘음. "Trusted Marketplace"라고 부르며 "rigorous security reviews"를 거쳤다고 하지만, 출시 때 리뷰 기준은 밝히지 않았다(언론 지적). | Salesforce IR 2025-03(1차) [link](https://investor.salesforce.com/news/news-details/2025/Salesforce-Launches-AgentExchange-the-Trusted-Marketplace-for-Agentforce/default.aspx), Channel Insider(2차) [link](https://www.channelinsider.com/news-and-trends/salesforce-agent-exchange/) |
| "Know Your Agent"(KYA) 신뢰 계층 스타트업 | Vouched: 2025-09 시리즈 A 1,700만 달러. 에이전트 평판 디렉터리 KnowThat.ai를 운영한다. t54 Labs: 2025 시드 500만 달러(Ripple·Franklin Templeton), 첫 구성요소를 "know your agent"라고 부른다. Baselayer: 2026-09-22 시리즈 A 3,500만 달러, "trust layer for the agentic economy"를 내세운다. | BusinessWire 2025-09-04(1차) [link](https://www.businesswire.com/news/home/20250904708838/en/Vouched-Announces-$17-Million-Series-A-to-Accelerate-Expansion-Building-on-Know-Your-Agent-KYA-Suite-Success), The Block(2차) [link](https://www.theblock.co/post/391273/ripple-franklin-templeton-ai-agent-trust-startup-t54-labs), SiliconANGLE 2026-09-22(2차) [link](https://siliconangle.com/2026/09/22/with-35m-in-series-a-funding-baselayer-is-building-the-trust-layer-for-the-agentic-economy/) |

### A-3. 논란과 신뢰 조건

| 사건 | 내용 | 날짜·출처 |
|---|---|---|
| "The Leaderboard Illusion" (Cohere Labs 외) | 일부 제공사(Meta·Google·OpenAI·Amazon)가 비공개 변형을 많이 시험하고 가장 좋은 것만 공개했다고 주장한다. 극단적인 예로 한 곳은 변형 27개를 시험했다. 표본 추출과 모델 은퇴도 불공평했다고 본다. 제안은 비공개 시험 한도 공개, 점수 철회 금지, 공정한 표본 추출. NeurIPS 2025에 실렸다. | arXiv 2504.20879, 2025-04-29(1차) [link](https://arxiv.org/abs/2504.20879) |
| LMArena 반박 | 비공개 시험 정책은 2024-03-01부터 공개돼 있었고 "no secret or unstated policy"라고 했다. 공개된 모델의 점수만 싣는다고 했다. | LMArena 응답(1차, 2025-04) [link](https://news.lmarena.ai/our-response), Simon Willison 2025-04-30(2차) [link](https://simonwillison.net/2025/Apr/30/criticism-of-the-chatbot-arena/) |
| Epoch–OpenAI 자금 비공개 | 자금 관계를 늦게 밝혔고, 데이터 대부분을 OpenAI가 볼 수 있었다. o3 점수를 독립적으로 검증하지 못했다. | TechCrunch 2025-01-19 [link](https://techcrunch.com/2025/01/19/ai-benchmarking-organization-criticized-for-waiting-to-disclose-funding-from-openai) |
| 비공개 평가 데이터의 위험 | 비공개 큐레이터(예: Scale)가 만든 평가는 재현할 수 없고 편향될 수 있다. | ICLR 2025 블로그 [link](https://iclr-blogposts.github.io/2025/blog/risks-private-evals) |

**평가자의 신뢰를 만드는 요소** (위 사례에서 반복되는 것. 해석이며 출처는 각 줄)
1. **독립성과 이해관계 공개**: Epoch 사례는 늦게 밝히면 신뢰를 잃는다는 것을 보여 준다. Arena·Vals는 랩에 돈을 받는 구조라 늘 의심받는다.
2. **방법 공개와 재현성**: HELM의 프롬프트 공개, HF의 하네스 명령 공개, Glama의 가중치 공개.
3. **오염 방지와 공개의 균형**: Scale·Vals는 비공개 데이터로 오염을 막지만 재현성 비판을 받는다. Epoch는 비공개 보류 세트를 남겼다.
4. **조작 방지 측정**: Artificial Analysis는 익명 계정으로 측정하고, 조작이 드러나면 등재를 뺀다.
5. **규칙 사전 공개와 평등한 적용**: Leaderboard Illusion의 핵심은 결국 "정책이 있었느냐"보다 "모두에게 똑같이 적용되고 보이느냐"다.
6. **검증 범위를 정확히 말하기**: MCP Registry는 소유권만, Glama는 정의 품질과 보안 스캔을 본다. 감사가 아니라 선별 신호라는 점을 밝힌다.

---

## B. 이름 충돌·상표 사례 (확인된 것만)

| 사례 | 무슨 일 | 결과·현황 | 날짜·출처 |
|---|---|---|---|
| xAI "Grok" vs Groq | Groq CEO가 2023-11에 공개 서한으로 이름을 바꾸라고 요구했다. USPTO는 Groq·Grokstream 등과 혼동 우려로 xAI 출원을 보류·거절했다. 2025-06-17에는 "XAI GROK"과 로고 출원도 선행 28건을 이유로 거절했다. **하우스 마크(XAI)와 로고를 더해도 넘지 못했다.** | xAI는 이름을 계속 쓰지만 등록은 막혀 있다(2025-06 기준). | Techdirt 2023-11-30 [link](https://www.techdirt.com/2023/11/30/groq-sends-elons-grok-a-cease-desist-though-a-funny-one), Gerben Law 2025-06-19 [link](https://www.gerbenlaw.com/blog/uspto-hits-elon-musks-grok-trademark-with-another-wave-of-refusals/) |
| Groq vs Groq Health | Groq가 비슷한 이름 회사를 제소했다. | 2026-05 원칙 합의 | Bloomberg Law [link](https://news.bloomberglaw.com/ip-law/groq-ai-hardware-firm-settles-trademark-suit-against-groq-health) |
| OpenAI "GPT" 상표 거절 | USPTO가 "merely descriptive"로 최종 거절했다. 대중은 GPT를 OpenAI 고유 이름이 아니라 기술 종류로 인식한다고 봤다. | 다른 회사도 GPT를 쓸 수 있음 | TechCrunch 2024-02-15 [link](https://techcrunch.com/2024/02/15/no-gpt-trademark-for-openai) |
| OpenAI vs Open Artificial Intelligence (Guy Ravine) | 2015 "Open AI" 보조 등록과 open.ai 도메인을 가진 쪽을 OpenAI가 제소했다. 9순회가 예비 금지명령을 유지했다(2024-11-13, 2대 1). 2025-07-21 약식판결로 피고 상표가 무효·취소됐다(USPTO 기만 판단). | 먼저 등록하고 도메인을 가졌어도, **실제 상업 사용과 2차적 의미**가 이겼다. 상대는 항소 의사를 밝혔다. | IPWatchdog 2024-11-14 [link](https://ipwatchdog.com/2024/11/14/ninth-circuit-upholds-injunction-openai-dissents-charge-abuse-discretion/), Quinn Emanuel [link](https://www.quinnemanuel.com/the-firm/news-events/quinn-emanuel-secured-a-complete-summary-judgment-for-openai-against-open-artificial-intelligence-inc/) |
| OpenAI·Jony Ive "io" vs iyO | iyO가 2025-06-09에 제소했고 TRO로 OpenAI가 io 발표 게시물을 내렸다. 9순회가 TRO를 유지했다(2025-12, 판결 확정 통지 12-29). | io 이름으로 비슷한 하드웨어를 팔 수 없다. 이후 예비 금지명령 문서가 있다(날짜 미확인). | MacRumors 2025-12-05 [link](https://www.macrumors.com/2025/12/05/openai-device-barred-from-io-name/), AppleInsider 2025-06-23 [link](https://appleinsider.com/articles/25/06/23/openai-pulls-jony-ive-promo-video-over-trademark-dispute) |
| OpenAI Sora "Cameo" vs Cameo | TRO(2025-11-21경), 예비 금지명령(2026-02-14경). OpenAI가 기능 이름을 "Characters"로 바꿨다. | 일반 단어라도 그 분야에서 쓰이는 등록 상표면 막힌다. | Engadget [link](https://www.engadget.com/ai/openai-cant-use-the-term-cameo-in-sora-following-temporary-injunction-213431626.html), TechCrunch 2026-02-17 [link](https://techcrunch.com/2026/02/17/u-s-court-bars-openai-from-using-cameo/) |
| Clawdbot → Moltbot → OpenClaw | Anthropic이 "Claude"와 철자·발음이 비슷하다며 상표 문제를 제기했다. 2026-01-27 Moltbot으로 바꿨다. 이름을 바꾸는 사이 옛 X 핸들을 사기꾼이 몇 초 만에 가로챘다. 01-30에 OpenClaw로 다시 바꿨다(자발적). | 오픈소스 개인 프로젝트도 이름을 바꿔야 했고, **바꾸는 과정에서 계정·핸들 탈취 위험**이 생겼다. | Business Today 2026-01-28 [link](https://www.businesstoday.in/technology/news/story/why-viral-ai-assistant-clawdbot-was-forced-to-become-moltbot-513239-2026-01-28), Laravel News [link](https://laravel-news.com/clawdbot-rebrands-to-moltbot-after-trademark-request-from-anthropic) |
| Google "Gemini" vs Gemini Data | 2024-09-11 N.D. Cal.에 제소. 소장은 USPTO가 Google의 등록 시도를 거절했다고 주장한다. | 2026-01 수정 소장 이후 결과 **미확인** | The Register 2024-09-12 [link](https://www.theregister.com/2024/09/12/google_gemini_ai_lawsuit), IPWatchdog [link](https://ipwatchdog.com/2024/09/13/google-hit-allegations-trademark-infringement-gemini-chatbot/) |

**확인하지 못해 뺀 것**: Devin, Cursor(Anysphere는 CURSOR 상표 등록만 확인되고 분쟁은 없음), Pi, Bolt(StackBlitz), Rabbit, Humane. 이번 조사에서 이름 분쟁의 근거를 찾지 못했다.

### B-2. 이름이 기존 행사·커뮤니티와 겹칠 때의 대응 (관찰과 실무)

- **하우스 마크나 로고만 붙이는 것으로는 부족하다.** xAI가 "XAI GROK"과 로고로 다시 출원했지만 거절됐다(Gerben 2025-06-19). 핵심 단어가 같으면 덧붙인 말로 혼동이 풀리지 않는다고 본다.
- **같은 분야·같은 고객이면 위험이 크다.** 혼동 판단의 중심은 "무엇을 하나, 같은 거래 경로인가"다(Gerben 인용, 2025-06).
- **먼저 쓰고 알려진 쪽이 이긴다.** Open AI 사례에서는 등록이 먼저였어도 실제 사용과 인지도가 앞선 쪽이 이겼다.
- **일반 단어도 그 분야에서는 보호된다.** Cameo 사례.
- **이름을 바꿀 때는 핸들·도메인·패키지 이름을 먼저 확보한다.** Clawdbot은 바꾸는 사이 옛 핸들을 빼앗겼다.
- **큰 회사도 결국 바꾼다.** OpenAI는 io·Cameo 둘 다 접었고 Google은 소송 중이다. 작은 서비스가 버틸 비용은 더 크다.
- **이름을 바꾸면서 범위를 정리한 예**: LMArena → Arena(2026-01). 접두사를 떼고 넓어진 범위에 맞췄다. 이번 건은 충돌 때문이 아니라 범위 때문이었다.

---

## 시사점: "Agentcon"이 AgentCon(Global AI Community)과 겹치는 소규모 서비스

AgentCon 현황(1차, 2026-11-14 확인)
- 소개: "AI Agents Developer Conference", "free, community-driven conference series"
- 규모: 66개 행사, 35개국. 2025-04 Utrecht부터 2027 행사까지 올라와 있다 [link](https://globalai.community/events/agentcon/).
- AvePoint가 2026년 6개 도시(서울 2026-04-16 포함)를 공동 주최한다 [link](https://www.avepoint.com/lp/agentcon-conference-2026).
- 페이지에 상표 표시는 없다. 서드파티 상표 집계 사이트에서 "AGENTCON" 정확 일치 출원도 찾지 못했다. **USPTO·KIPRIS 공식 검색은 하지 않았다.**

1. **혼동 위험은 실재한다.** 같은 "AI 에이전트" 분야, 같은 개발자 대상이고 서울 행사도 있었다. 검색과 SNS에서 66개 행사 페이지에 밀려 우리 이름이 묻힐 가능성이 크다. Grok 사례처럼 철자가 같거나 대소문자만 다른 정도로는 구분되지 않는다.
2. **"Agentcon by Agent Concierge" 같은 덧붙이기는 법적 해결책이 아니다.** XAI GROK 거절 사례가 근거다. 보조 표기로는 쓸 수 있지만 주 이름을 바꾸는 편이 안전하다.
3. **지금은 상표 출원이 없어 보여도 먼저 쓰고 알려진 쪽은 저쪽이다.** 2025-04부터 66개 행사를 열었다. Open AI 판례의 논리(실제 사용과 인지도)로 보면, 우리가 나중에 출원해도 이기기 어렵다. 공식 USPTO·KIPRIS 검색을 사람이 한 번 확인할 것.
4. **공개 이름은 이미 쓰는 "Agent Concierge"(agentconcierge.biz)로 통일하는 것이 가장 싸다.** 도메인·MCP Registry 이름 공간(biz.agentconcierge/…)·연락 메일이 이미 이 이름이다. Registry 이름 공간이 도메인으로 소유를 증명하므로 신뢰 신호와도 맞는다.
5. **"Agentcon"이 내부 이름(서비스·명령·launchd 이름)이라면 외부 노출만 걷어낸다.** 공개 페이지, 메타 태그, 등재 설명, 소셜 카드에서 빼고, 내부 이름은 비용을 보고 천천히 바꾼다.
6. **바꿀 때는 핸들·패키지 이름·도메인을 먼저 확보한다.** Clawdbot은 핸들을 탈취당했다. 비용 0 범위에서는 무료 핸들과 패키지 이름 예약만 한다.
7. **신뢰 브랜드는 이름보다 공개 방법론으로 만든다.** 평가·추천 서비스라면 다음을 공개한다.
   - 측정 방법·가중치(Glama TDQS처럼)
   - 익명·일반 경로 측정(Artificial Analysis처럼)
   - 이해관계: 광고와 순위의 분리를 명시. 광고 상품(USDC)이 있으므로 Arena·Epoch식 논란을 미리 막는다.
8. **"verified"라는 말은 범위를 정확히 쓴다.** 예: "연결 확인됨(날짜)", "소유 확인됨". 마켓플레이스들도 기준을 밝히지 않으면 비판받았다(AgentExchange 출시 때 지적).
9. **이름을 바꾸면서 정체성을 다시 설명할 기회로 쓴다.** LMArena→Arena처럼 짧게, 범위에 맞춘 이유 한 줄과 옛 주소 리디렉션을 함께 둔다.
