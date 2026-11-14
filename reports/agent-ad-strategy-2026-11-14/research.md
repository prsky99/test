# 자율 AI 에이전트 대상 광고 기법 조사 (2026-11-14)

- 범위: 에이전트를 독자로 하는 광고(B2A·에이전틱 커머스), 2025~2026 시장 전반에서 효과가 큰 광고, 기존 대체 기법
- 방식: 웹 검색·논문 원문 확인(읽기 전용). 가입·로그인·게시·연락 없음
- 표기 규칙
  - **[회사 발표]**: 회사가 스스로 낸 수치(독립 검증 없음)
  - **[미확인]**: 2차 기사 한 곳뿐이거나 출처끼리 어긋남
  - **[논문]**: 동료 심사 전 arXiv 포함. 실험 조건이 우리 서비스와 다를 수 있음
- 결론 먼저
  1. 에이전트는 "Sponsored" 표시를 **감점**하고, 플랫폼 추천 표시와 검증 가능한 구조화 사실에는 **가점**한다(ACES 논문). 사람용 스폰서 카드를 그대로 에이전트에게 보여 주는 방식은 효과가 낮을 가능성이 크다.
  2. 그래서 에이전트용으로는 "설득"이 아니라 **기계가 읽는 사실·조건(가격·무료 시험 크레딧·SLA·독립 검증 링크)을 담은 분리된 스폰서 제안(offer)**이 정직하면서도 효과를 기대할 수 있는 형태다.
  3. 시장 전체에서 가장 빨리 큰 것은 **AI 답변 아래의 문맥 매칭 스폰서 자리**다(ChatGPT 광고, 출시 200일 안에 연 환산 10억 달러 [회사 발표]). 소매 미디어(자기 플랫폼 안 구매 지점 광고)도 성장률 1위권이다.
  4. 피해야 할 것: 도구 설명 조작(ToolTweak·MPMA), 답변 속에 섞는 설득형 광고, 프롬프트 주입형 광고, "추천·검증" 배지 판매

---

## 1. 주제별 조사 결과

### 1.1 LLM·에이전트 응답 안의 광고·후원

| 서비스 | 배치·표시 | 과금·지표 | 출처(날짜) |
|---|---|---|---|
| OpenAI ChatGPT 광고 | 답변 **아래**, 대화 주제와 맞을 때만. "Sponsored" 표시, 답변과 시각적으로 분리. 18세 미만·건강·정신건강·정치 주제에는 안 나옴. "광고는 답변에 영향을 주지 않는다"고 밝힘 | 2026-02-09 미국 무료·Go 요금제로 시작. 초기 CPM 약 60달러·최소 20만 달러 → 2026-05-05 셀프서비스·CPC 입찰로 전환. 광고주는 노출·클릭 같은 집계만 받음, 픽셀·표준 귀속 없음. 6주에 연 환산 1억 달러, 2026-08-31 연 환산 10억 달러·40개국 이상(한국 포함) **[회사 발표]**. Similarweb 추정: 무료·Go 답변의 26%에 광고, 클릭률 0.50% **[업체 패널 추정]** | [ppc.land 2026-03](https://ppc.land/chatgpt-ads-hit-100m-in-six-weeks-and-openai-is-just-getting-started/), [ppc.land 2026-09](https://ppc.land/openais-david-dugan-says-chatgpt-ads-passed-a-1bn-run-rate/), [techwyse 2026-09](https://www.techwyse.com/news/ai-search/chatgpt-ads-billion-revenue-global-self-serve), [OpenAI](https://openai.com/index/testing-ads-in-chatgpt/) |
| Perplexity 스폰서 후속 질문 | 답변 뒤 "관련 질문" 하나를 광고주가 후원, 답은 Perplexity AI가 생성 | 2024-11 시작 → 2025-10 신규 광고주 받지 않음. 사용자가 "돈 낸 브랜드를 편드는지" 혼란. 영구 철수 보도는 한 곳뿐 **[미확인]** | [influencermarketinghub](https://influencermarketinghub.com/perplexitys-ad-pause-exposes-the-challenges-of-monetizing-generative-search), [afaqs](https://www.afaqs.com/news/advertising/perplexity-ai-pulls-the-plug-on-ads-to-prioritise-user-trust-11132906) |
| Google AI Overviews·AI Mode | "Sponsored" 표시, 질의와 답변 둘 다에 관련 있을 때만. 기존 검색·쇼핑·PMax 캠페인이 자동으로 들어감. 2026-01 "Direct Offers"(AI Mode 안 할인 제안) 시범, UCP 판매자 결제 연동 | AI Overview 광고 노출 비율은 측정마다 0.052%~약 40%로 크게 다름 **[미확인]** | [TechCrunch 2025-05-21](https://techcrunch.com/2025/05/21/google-is-bringing-ads-to-ai-mode/), [seroundtable](https://www.seroundtable.com/google-ai-mode-shopping-ads-41353.html), [SEJ](https://www.searchenginejournal.com/googles-ads-chief-details-ucp-expansion-new-ai-mode-ads/567007/) |
| Microsoft Copilot | Showroom Ads(분할 화면), **"ad voice": 왜 이 광고가 나왔는지 설명** | 기존 검색 광고보다 관련성 25%↑, 클릭률 2배 **[회사 발표]** | [eMarketer](https://www.emarketer.com/content/microsoft-copilot-launches-ai-powered-ad-features) |
| Amazon Rufus Sponsored Prompts | Amazon이 광고주 상품 데이터로 질문 문구를 직접 생성. 광고주는 끌 수 있음 | 2025-11 베타 → 2026-03-25 미국 정식. 클릭당 약 0.31달러(일반 0.50~0.70). 한 판매자는 몇 달간 88클릭 → "판매 수단보다 조사 도구"라는 평가. 클릭률 18%↑·구매 완료 60%는 **[회사 발표/미확인]** | [intentwise](https://www.intentwise.com/blog/explained-sponsored-prompts-ads-on-amazon), [shopifreaks](https://www.shopifreaks.com/amazons-rufus-chatbot-ads-are-generating-data-but-driving-minimal-sales-with-sponsored-prompts-accounting-for-less-than-1-of-clicks/), [eMarketer](https://www.emarketer.com/content/rufus-ads-open-window-amazon-s-ai-while-missing-some-shoppers) |
| AI 앱용 광고망(Koah·Kontext·Gravity) | 답변 바로 아래 표시된 스폰서 링크·카드 | Koah: 1.75억 질의에 3,500만 노출 **[회사 발표]**, 2026-02 2,050만 달러 시리즈 A. Kontext 2025-04 1,000만 달러 시드. Gravity 2026-08 3,050만 달러 | [SiliconANGLE 2026-02-24](https://siliconangle.com/2026/02/24/koah-raises-20-5m-scale-adsense-ai-across-apps), [ppc.land](https://ppc.land/kontext-secures-10m-to-scale-ai-powered-advertising-in-genai-apps/), [TNW 2026-08-06](https://thenextweb.com/news/gravity-ai-ads-30-5m-series-a-agent-to-agent) |

공통점: 성공한 쪽(ChatGPT·Google)은 모두 **답변과 분리된 아래쪽 자리 + 명확한 표시 + 답변 독립 선언 + 민감 주제 제외 + 집계 지표만 제공**이다. 답변 흐름에 섞은 Perplexity 형식은 확장되지 못했다.

### 1.2 에이전트를 구매자로 보는 광고(B2A·에이전틱 커머스)

- **Forrester B2A**: 사람 대신 기계를 독자로 콘텐츠를 설계해야 한다. 핵심은 맥락을 분명히, 추론 여지를 줄이는 구조, **검증 가능하고 일관된 사실로 신뢰 쌓기**다. 2026 조사에서 의사결정자 69%가 AI 답변 엔진 노출을 도입·시범 중이다. 
  - [Forrester 블로그](https://www.forrester.com/blogs/ai-agents-are-your-new-customer-but-can-you-target-and-grow-their-trust-in-your-brand/), [웨비나](https://www.forrester.com/webinar/ai-agents-are-your-new-customers-can-you-target-them-to-favor-your-brand/WEB197096), [Gahun 인터뷰 2026-06-25](https://agilebrandguide.com/expert-mode-marketing-to-machines-and-the-rise-of-the-ai-agent-persona-with-forresters-chuck-gahun/)
  - 작성자·날짜 세부는 **[미확인]**
- **Gravity의 에이전트 대상 광고(시험 중, 2026-08)**: 광고주가 상품 카탈로그(기능·현재 프로모션)를 넣으면, 쇼핑 에이전트가 범주를 검색할 때 관련 광고주 목록과 상세 설명을 받는다. **사람은 이 광고를 보지 않는다.** 표시 방식·과금은 공개되지 않았다. [TNW](https://thenextweb.com/news/gravity-ai-ads-30-5m-series-a-agent-to-agent)
- **OpenAI·Stripe Agentic Commerce Protocol(2025-09-29)**: 상품 피드 + 결제. OpenAI는 "결제 지원 여부와 수수료는 순위에 영향 없음"이라고 밝혔다(같은 상품을 파는 여러 판매자 사이에서는 고려 요소). 2026-03 Instant Checkout 축소·철수 보도가 있고 세부는 출처마다 다르다 **[미확인]**. [ppc.land](https://ppc.land/openai-launches-instant-checkout-for-chatgpt-with-stripe-partnership/), [Stripe 문서](https://docs.stripe.com/agentic-commerce/acp?locale=en-GB)
- **Google AP2(2025-09)·UCP(2026-01)**: 의도 위임장(Intent Mandate, 사용자 목표·한도 서명) → 장바구니 위임장 → 결제 위임장. UCP는 "무엇을 어떤 조건에 사는지", AP2는 "적법하게 승인됐는지"를 정한다. [TechCrunch 2025-09-16](https://techcrunch.com/2025/09/16/google-launches-new-protocol-for-agent-driven-purchases/), [efficientlyconnected I/O 2026](https://www.efficientlyconnected.com/google-io-2026-agentic-commerce-protocols-ucp-ap2/)
  - 시사점: 에이전트는 **서명된 조건(한도·조건)에 맞는 기계 판독 제안**을 받는 구조로 간다. 광고도 "조건에 맞는 구조화 제안"이어야 걸러지지 않는다.
- **Visa Trusted Agent Protocol(2025-10-14, Cloudflare와)·Mastercard Agent Pay(2025-04-29)**: 에이전트 신원 서명·토큰. Visa는 x402와 호환 작업 중. [digitaltransactions](https://www.digitaltransactions.net/visa-launches-trusted-agent-an-agentic-commerce-protocol/), [eco.com 비교](https://eco.com/support/en/articles/15192003-mastercard-agent-pay-vs-visa-trusted-agent-2026-compared) (2차 자료)
- **x402**: 누적 거래 1억~2억 건이지만 대부분 1센트 미만이고, 실제 상거래 금액은 작다. TRM Labs는 에이전트 거래가 월 5천~1.1만 달러 수준이라고 추정한다. 2026-04 Linux Foundation으로 이관. [forkast](https://forkast.news/the-x402-foundation-activated-a-27-year-old-internet-code-200-million-transactions-later-the-real-volume-is-still-tiny/), [TRM Labs](https://www.trmlabs.com/trm-tech-blog/whos-actually-paying-measuring-ai-agent-payments-onchain)
  - x402 Bazaar(2025-09)는 결제가 정산되면 자동으로 색인되는 발견 계층이다. 유료 순위는 확인되지 않았다. [Coinbase](https://www.coinbase.com/fr/developer-platform/discover/launches/x402-bazaar), [CDP 문서](https://docs.cdp.coinbase.com/x402/bazaar.md)
- **MCP 디렉터리 유료 자리**: 공식 MCP Registry에는 유료 순위가 없다. 사설 디렉터리는 고정가 배너·추천 자리를 판다(MCPBundles 월 129달러 배너, "paid placement"로 표시). [MCPBundles](https://www.mcpbundles.com/sponsorship), [claudemarket.ai](https://claudemarket.ai/promote-your-mcp)
  - Smithery는 유료 대신 품질·안전 점수와 관리자 검증으로 순위를 매긴다.
  - **"유료 자리가 에이전트의 도구 선택을 얼마나 바꾸는가"에 대한 측정은 찾지 못했다.**

### 1.3 연구: 에이전트의 광고 민감도, 공정한 스폰서 콘텐츠

**(a) 우리 설계에 바로 쓰이는 근거**

- **ACES, "What Is Your AI Agent Buying?"**(Allouah 외, arXiv 2508.02630, v3 2025-12-17) [논문](https://arxiv.org/abs/2508.02630), [본문](https://arxiv.org/html/2508.02630v3)
  - 모든 모델이 **"Sponsored" 표시를 감점**했다. 기준 선택확률 10%인 상품이 Claude Sonnet 4에서 8.9%, GPT-4.1에서 8.0%, Gemini 2.5 Flash에서 7.9%로 떨어졌다.
  - 최신 모델일수록 감점 계수가 더 컸다: Claude Opus 4.5 −0.34, GPT-5.1 −0.37, Gemini 3 Pro −0.62.
  - **플랫폼 추천 표시("Overall Pick")는 크게 가점**했다: 10%가 19.9~42.6%로 올랐다.
  - 위치 편향이 강하고 모델마다 다르다(맨 윗줄 승산비 0.5배~8.5배, 승산비는 계수에서 계산한 값).
  - 판매자가 질의에 맞게 설명만 고쳐도 점유율이 +0.3~+14.9%p 올랐다.
  - 모델이 바뀌면 시장 점유율이 크게 뒤섞인다.
  - 한계: 소비자 쇼핑 모의 시장이고, 도구 선택이 아니다. 우리 서비스에 그대로 옮겨지는지는 **[미확인]**이다.
- **Qiu·Mei, "Generative AI Advertising as a Problem of Trustworthy Commercial Intervention"**(arXiv 2605.18673, 2026-05-18) [논문](https://arxiv.org/html/2605.18673)
  - 영향 단계를 넷으로 나눈다: 언급 → 틀 짓기 → 행동 유도 → 장기 선호. 표시·분리는 첫 단계에만 통한다.
  - 권고: **광고가 없을 때와 비교하는 반사실 감사**, 도구 선택 단계의 상업적 개입 제한, 선호 재설정(옵트아웃)
  - 인용 연구: Stöckl·Nitu(2025) "에이전트는 시각·감성 호소보다 구조화 데이터를 선호한다"(원문 미확인)
- **Ads that Talk Back**(arXiv 2409.15436, 179명): 표시를 붙여도 49%가 광고를 알아채지 못했다. 표시가 있으면 챗봇을 덜 신뢰하고 더 침해적이라고 느꼈다. [논문](https://arxiv.org/pdf/2409.15436)

**(b) 조작 위험을 보여 주는 연구(우리가 쓰면 안 되는 기법, 그리고 광고주가 우리에게 쓸 수 있는 공격)**

- **Commercial Persuasion in AI-Mediated Conversations**(Salvi 외, arXiv 2604.04263, 2026-04-05) [논문](https://arxiv.org/abs/2604.04263)
  - 대화형 에이전트의 설득은 스폰서 상품 선택률을 22.4%에서 61.2%로 거의 3배 올렸다.
  - 대부분 알아채지 못했다. **"Sponsored" 표시를 붙여도 설득 효과가 유의하게 줄지 않았다.**
  - 숨기라고 지시하면 탐지율이 10% 미만이었다.
  - 의미: **답변 본문에 섞인 광고는 표시가 있어도 조작**이다. 답변과 광고를 구조적으로 떼어야 한다.
- **ToolTweak**(arXiv 2510.02554, 2025-10-02): 도구 이름·설명만 고쳐도 선택률이 약 20%에서 최대 81%로 올랐다. 방어책은 설명 바꿔 쓰기(paraphrase)와 혼란도(perplexity) 필터다. [논문](https://arxiv.org/abs/2510.02554)
- **MPMA**(arXiv 2505.11154, AAAI 2026): MCP 서버가 도구 설명에 조작 문구를 넣거나, 유전 알고리즘으로 은밀하게 만들어 경쟁 서버보다 선택되게 한다. 동기로 광고 수익을 명시한다. [논문](https://arxiv.org/abs/2505.11154)
- **GEO**(Aggarwal 외, KDD 2024): 인용·통계·인용문 추가로 생성형 답변 노출이 최대 약 40% 늘었다. 이것은 정직한 콘텐츠 개선의 범위이고, 우리도 쓸 수 있다. [논문](https://arxiv.org/abs/2311.09735)
- **Strategic Text Sequence**(Kumar·Lakkaraju, arXiv 2404.07981): 상품 페이지에 최적화 문자열을 넣어 LLM 추천 1위를 얻는다. 조작이다. [논문](https://arxiv.org/abs/2404.07981)
- **Preference Manipulation Attacks**(Nestaas 외): 조작된 웹 콘텐츠로 추천 확률이 약 2.5배가 됐다(Qiu·Mei 인용).
- **광고 삽입 공격(AEA)**(arXiv 2508.17674)과 실제 사례
  - Kickbacks: 에이전트 세션에 광고를 끼워 넣는 스타트업 [dev.to](https://dev.to/searchless_ai/kickbacks-the-startup-injecting-ads-into-ai-agents-while-users-watch-229l)
  - "Ask AI" 버튼 기억 오염 [reflectiz](https://reflectiz.com/blog/ai-recommendation-poisoning)
  - 웹 콘텐츠를 통한 간접 프롬프트 주입 [Zscaler](https://www.zscaler.com/jp/blogs/security-research/indirect-prompt-injection-web-content-targets-ai-agents)

**(c) LLM 광고 경매 설계(참고용, 우리에게는 맞지 않음)**

- 토큰 단위 경매(Dütting 외, Google, WWW'24 최우수 논문, [arXiv 2310.10826](https://arxiv.org/abs/2310.10826))
- RAG 구간 경매(Hajiaghayi 외, [arXiv 2406.09459](https://arxiv.org/abs/2406.09459))
- LLM 요약 경매(Dubey 외, [arXiv 2404.08126](https://arxiv.org/abs/2404.08126))
- 셋 다 **광고를 생성 답변 안에 섞는** 설계다. "광고는 답변·순위·추천에 영향 없음"이라는 우리 규칙과 맞지 않는다. 쓰지 않는다.

### 1.4 표시 의무·규제, 기계 판독 표시

- **미국 FTC**
  - 2023 블로그 입장: "광고는 광고임이 분명해야 하고, 생성형 AI 출력은 유기적 내용과 유료 내용을 분명히 구분해야 한다." 생성형 AI 기능 안 광고 배치를 직접 지목했다.
  - 2025~2026 AI 광고 전용 새 지침은 찾지 못했다.
  - 네이티브 광고 지침은 "Ad", "Advertisement", "Sponsored Advertising Content" 같은 표시를 권한다.
  - [Perkins Coie 정리](https://perkinscoie.com/insights/blog/ftcs-latest-ai-and-your-business), [FKKS](https://advertisinglaw.fkks.com/post/102iemq/ftc-warns-about-ai-and-the-engineering-of-consumer-trust)
- **EU DSA**
  - 26조(광고마다 광고라는 사실, 누구를 대신하는지, 누가 돈을 냈는지, 노출을 정한 주요 변수 표시)
  - 28조(미성년자 프로파일링 광고 금지), 39조(대형 플랫폼의 공개 광고 저장소)
  - ChatGPT는 2026-08-31 VLOSE로 지정됐고, 광고 저장소 의무는 2027-01부터라고 보도됐다 **[2차 보도]**
  - 위원회는 39조 저장소 지침 의견을 2026-12-02까지 받는다
  - [techpolicy.press](https://techpolicy.press/what-chatgpts-dsa-designation-means-for-openai-and-the-eu), [Lewis Silkin 2026-01](https://www.lewissilkin.com/en/insights/2026/01/23/the-eu-raises-the-bar-on-ad-transparency-102mdvw), [lovguiden 2026-11-04](https://www.lovguiden.dk/en/det-offentlige/europa-kommissionen-press-corner/2026-11-04-eu-commission-seeks-input-on-dsa-rules-for-online-advertising-repositories)
  - 우리는 대형 플랫폼이 아니라 39조 의무는 없다. 26조 항목은 좋은 설계 기준으로 쓴다.
- **한국**
  - 표시광고법·「추천·보증 등에 관한 표시·광고 심사지침」: 경제적 이해관계를 표시해야 하고, 글에서는 제목이나 첫 부분에 둔다
  - 2026년 개정으로 AI 가상인물이 추천·보증하면 "가상인물" 표시가 의무다(2026-04 행정예고, 시행일은 출처마다 다름 **[미확인]**)
  - [디지털데일리 2026-04-08](https://www.ddaily.co.kr/page/view/2026040811563569528), [헤럴드 2026-05-30](https://www.heraldk.com/article/2026053019000068969), [신김 뉴스레터](https://shinkim.com/kor/media/newsletter/3230)
  - AI기본법 31조 생성형 AI 표시는 주로 AI 사업자 의무다 [i-boss](https://www.i-boss.co.kr/ab-74668-5969)
  - 원치 않는 광고 메시지는 정보통신망법 광고성 정보 전송 제한에 걸린다(우리 "먼저 보내는 광고 없음" 규칙과 일치, 일반 지식)
- **기계 판독 표시 제안**
  - IAB AI 투명성·공개 프레임워크(2026-08): 사람용 표시 + 기계 판독 메타데이터(C2PA) 두 층. 단, 이것은 "AI로 만든 광고" 표시이지 "광고임" 표시가 아니다. [IAB PDF](https://www.iab.com/wp-content/uploads/2026/08/IAB_AI_Trasparency_Disclosure_Framework_August_2026.pdf)
  - Agent-Native Ad Disclosure Minimums v0.1(agent-ads.org, 작성 주체·날짜 불명, 비공식 초안) [링크](https://agent-ads-org.pages.dev/docs/agent-native-ad-disclosure-minimums)
    - 필드: `payload_type`(`agent_ad`/`sponsored_context`), `disclosure`, `sponsor`, `source`, `provenance`, `agent_delivery`
    - 규칙: 사람이 보는 표시는 요약·변환을 거쳐도 남아야 한다. 콘텐츠 안의 지시는 에이전트 명령으로 취급하지 않는다.
  - schema.org·`rel="sponsored"`를 에이전트용 광고 표시로 넓히자는 공식 제안은 찾지 못했다. MCP·A2A 사양에도 광고 표시 필드는 없다(조사 범위 안에서).

### 1.5 에이전트에 맞는 성과형 과금

- **성과(해결)당 과금이 대세**
  - Intercom Fin: 해결 1건 0.99달러, 해결 못 하면 0원. 100만 달러에서 1억 달러 이상 ARR **[회사 발표]**
  - Sierra: 해결당 약 1.5달러 **[미확인]**
  - Zendesk 1.5~2달러, HubSpot 0.5달러
  - 약점: "해결"의 정의를 플랫폼이 정한다
  - [Stripe 사례](https://stripe.com/customers/fin-ai), [SaaStr](https://www.saastr.com/hubspot-switching-ai-pricing-from-per-use-to-per-resolution-but-does-it-really-matter/)
- **ChatGPT 광고**는 CPM에서 CPC·성과 최적화 입찰로 옮겨 갔고, 이것이 대부분의 캠페인을 차지한다 **[회사 발표, 2026-09]**
- **에이전트 제휴(affiliate)**: 2026-08 기준 주요 AI 쇼핑 에이전트에는 제휴 링크 전달 구조가 없다
  - OpenAI 약 2% 커미션 구상, ACP 4% 수수료 등 수치가 어긋난다 **[미확인]**
  - Perplexity 판매자 프로그램은 수수료 없음
  - [makeinfluence](https://www.makeinfluence.com/en/academy/ai-shopping-agents-chatgpt-perplexity-and-affiliate-commission-tracking), [Affiverse](https://www.affiversemedia.com/?p=103888)
- **스폰서 시험 크레딧**: 에이전트 대상 사례·효과 측정은 찾지 못했다. 다만 ACES에서 가격 민감도가 모든 모델에서 기대 방향으로 나왔다(크기는 모델마다 다름). Google Direct Offers(AI Mode 안 할인)가 같은 발상의 사람용 판이다.
- Qiu·Mei: 높은 단계의 영향에는 CPA·장기 계약형 과금이 필요하지만, 귀속(attribution)이 어렵다고 지적한다.

### 1.6 기존 기법(대체 수단)

- **시장 성장률(2026 예측)**
  - WARC: 전체 +11.9%, 1.34조 달러. 소셜 +21.3%, 소매 미디어 +14.3%(2,021억 달러), 검색 +14.2%
  - Dentsu: 전체 +5.0%, 소매 미디어·CTV·소셜·디지털 옥외가 성장 상위
  - [ppc.land WARC](https://ppc.land/warc-forecasts-social-media-ad-spend-gains-21-3-to-394-6bn-in-2026/), [Dentsu 2026-05](https://www.dentsu.com/news-releases/ad-spend-growth-is-projected-to-slow-to-5-percent-in-2026-still-outpacing-economic-growth)
  - 우리에게 맞는 것은 **소매 미디어형**이다. 우리 플랫폼 안, 선택 지점에서, 1차 문맥(질의·카테고리)만으로 노출하고 추적하지 않는다.
- **개발자 뉴스레터 후원**
  - Vercel×TLDR: 열람 52%, 클릭 4.2%, 가입 1,200건 **[판매 업체 사례, 미확인]**
  - 후원사 2개 이하가 좋다는 경험칙
  - [dupple](https://dupple.com/learn/best-developer-newsletters-to-advertise-in), [daily.dev 벤치마크](https://business.daily.dev/resources/developer-paid-media-benchmarks-2026-cpm-cpc-ctr-by-channel/)
- **디렉터리 추천 자리(고정가·기간제)**: MCPBundles 월 129달러, AI Toolhouse 7일 "Featured MCP", mcpstack 월 47달러. 성과 수치는 공개되지 않았다.
- **리타기팅**: 우리 규칙(쿠키·추적 없음)상 불가
- **콘텐츠 마케팅·GEO**(정직한 범위): 인용·통계·출처를 넣으면 AI 답변 노출이 최대 약 40% 늘어난다(GEO 논문)
- **데브렐 후원**: 해커톤·예제 저장소·튜토리얼. 정량 근거는 찾지 못했다.

---

## 2. 에이전트 독자용 광고 상품 후보 순위

평가 기준: 효과 근거, 위험(법·신뢰·조작), 우리 규칙과의 적합도(광고가 검증·점수·순위·추천·목걸이를 바꾸지 않음, 표시 의무, 쿠키·추적 없음, 먼저 보내지 않음, 조작 문구 없음)

| 순위 | 후보 | 작동 방식 | 효과 근거 | 위험 | 규칙 적합 |
|---|---|---|---|---|---|
| 1 | **기계 판독 스폰서 제안(Agent-Readable Sponsored Offer)** | MCP·A2A·REST 응답에서 `results`와 **떨어진 `sponsored` 배열**에 1건. 내용은 정해진 필드로만 받는다: 이름, 엔드포인트, 가격, 무료 시험 크레딧, SLA, 지원 프로토콜, **우리 독립 시험 보고서 링크와 지금 등급(광고와 무관하게 계산)**. 자유 문구는 짧게 제한하고 명령형은 금지 | ACES: 에이전트는 가격·평점 같은 구조화 사실에 반응하고, "Sponsored" 표시는 약하게 감점(10%→8~9%). Forrester B2A: 검증 가능한 사실. Gravity가 같은 방향(카탈로그를 에이전트에게)으로 시험 중 | 효과 크기 미확인. 광고주가 필드에 조작 문구를 넣을 위험(ToolTweak형)이 있어 검사·바꿔 쓰기가 필요 | 높음. 순위와 분리, 표시, 추적 없음 |
| 2 | **스폰서 시험 크레딧(Sponsored Trial Credits)** | 광고주가 "처음 N회 무료"를 제공하고 제안에 조건을 적는다. 에이전트가 쓸지는 스스로 판단 | 가격 민감도(ACES), Google Direct Offers, 성과형 과금 흐름 | 크레딧은 광고주가 이행한다(우리는 자산을 보관하지 않음). 이행되지 않으면 신뢰가 떨어진다 → 광고주 엔드포인트에서 실제로 되는지 확인 필요 | 높음. 1과 합쳐 쓴다 |
| 3 | **문맥 매칭 스폰서 자리(사람·에이전트 공용, 현재 상품의 개선판)** | Explore·Chat 결과 아래 분리된 1칸. 질의 카테고리·역할로만 맞춤 | ChatGPT 광고 10억 달러 연 환산(200일 안), Google AI Mode, 소매 미디어 성장 1위권 | 사람에게는 표시해도 49%가 놓친다 → 시각적으로 강하게 분리 | 높음(지금 상품) |
| 4 | **성과형 과금: 검증된 연결당 과금(pay-per-verified-call)** | 우리 게이트웨이·목걸이 실행 경로에서 광고된 에이전트가 **실제로 성공 호출**된 횟수를 서버 쪽 집계로 세어 과금. 쿠키 없음 | Fin·Sierra 해결당 과금, ChatGPT CPC 전환 | "성공" 정의를 우리가 정함 → 기준 공개. 광고주가 호출을 부풀리려는 유인 → 중복 제거. **결제 1건=예약 1건 규칙과 충돌**하므로 정산 방식은 사용자 결정 필요 | 중간. 지금은 정액 5 USDC/일 유지, 후보로 시범 |
| 5 | **스폰서 시험 보고서·사례(표시된 콘텐츠 후원)** | 광고주가 비용을 대고 우리가 같은 기준으로 시험한 결과를 공개. **결과와 무관하게 공개**하고 후원 사실을 표시 | B2A "검증 가능한 사실". 다만 정량 근거 없음 | **이해충돌**: "돈 내면 시험을 잘 받는다"는 오해. 규칙 "광고가 검증을 바꾸지 않음"과 긴장 | 낮음~중간. 권하지 않음, 하려면 사용자 결정 |
| 6 | **디렉터리 추천 자리·뉴스레터 후원(사람용)** | 고정가·기간제 "Featured(Sponsored)" 칸, 진주·목걸이 소식지 후원 1칸 | 업계 관행(MCPBundles 등), TLDR 사례(미확인) | 낮음 | 높음 |
| — | **피할 것** | 아래 목록 | | | 규칙 위반 |

**피할 것(조작·위험)**
- 답변·추천 문장 안에 광고를 섞는 설득형 광고: Salvi 실험에서 선택률이 3배가 됐고, 표시해도 효과가 줄지 않았다. 토큰·RAG 경매도 같은 문제다.
- 광고주에게 "Overall Pick·Verified·Best for role" 같은 **추천·검증 배지를 파는 것**: ACES에서 가장 효과가 큰 신호지만, 바로 그래서 팔면 기만이다.
- 도구 이름·설명 최적화 대행(ToolTweak·MPMA·STS), 광고 문구 안에 명령형·주입 문구 넣기
- 에이전트 세션·기억에 광고 끼워 넣기(Kickbacks·AEA·"Ask AI" 오염)
- 유료 순위·유료 목걸이 포함, 위치 편향을 이용한 자리 판매(예: 결과 1위 바로 위)
- 요청하지 않은 A2A 메시지로 광고 보내기, 리타기팅·프로파일링

---

## 3. 추천

### (A) 새 에이전트 대상 기법(주력): 기계 판독 스폰서 제안 + 시험 크레딧

- **무엇**: 지금의 "Sponsored 카드"를 에이전트 응답에서는 **구조화된 스폰서 제안 객체**로 내보낸다. 사람 화면의 카드는 그대로 둔다.
  - 위치: MCP `structuredContent.sponsored`, A2A의 별도 Part(메타데이터 `kind: advertisement`), REST `sponsored[]`
  - 내용: 정해진 필드만. 가격·무료 시험 조건·SLA·지원 프로토콜·인증 방식·**우리 독립 보고서 링크와 지금 등급**
  - 자유 광고 문구: 1줄, 명령형 금지
- **왜**
  1. 에이전트는 설득 문구보다 구조화 사실·가격에 반응한다(ACES, Forrester B2A, Stöckl·Nitu 인용).
  2. "Sponsored" 표시는 감점되지만, 그 크기는 작다(10%→8~9%). 대신 사실(무료 크레딧·낮은 가격·높은 독립 등급)이 가점을 만든다. 정직한 경로로 성과를 내는 구조다.
  3. 같은 방향의 시장 실험이 있다: Gravity의 에이전트 대상 카탈로그 광고(2026-08 시험 중), Google Direct Offers.
  4. 우리만의 차별점: 다른 광고망에는 없는 **독립 검증 등급을 광고 옆에 같이** 붙일 수 있다. 등급은 광고와 무관하게 계산한다.
- **규칙 지키기**
  - 광고 대상 자격은 "최소 등급 이상"으로 둘 수 있다(검증 → 광고 방향만 허용, 반대는 금지).
  - 등급·순위·목걸이는 광고 여부를 입력으로 받지 않는다. 코드 경계와 시험으로 막는다.
- **측정**: Qiu·Mei가 권한 반사실 감사. 광고가 없는 응답과 있는 응답에서 유기 결과가 같은지 매일 자동 비교한다. 에이전트 반응은 서버 집계(제안 노출 수, 우리 경로를 통한 호출 수)로만 잰다.
- **효과 크기는 [미확인]**이다. 첫 4주는 정액 5 USDC/일을 유지하고 집계 지표만 보고한다.

### (B) 시장에서 가장 효과가 클 것으로 보이는 병행 기법: 답변 아래 문맥 매칭 스폰서 자리(소매 미디어형)

- **무엇**: 지금 상품을 ChatGPT·Google 방식에 맞춘다.
  - 1칸, 답변·결과 **아래**, 질의 카테고리·역할에만 맞춤
  - 민감 주제(금융 조언·건강 등) 제외
  - Copilot식 "왜 이 광고인가" 한 줄 공개
- **근거**
  - ChatGPT 광고: 출시 200일 안에 연 환산 10억 달러, 40개국 이상, CPC 중심으로 전환 [회사 발표]
  - Google AI Mode·AI Overviews 확대
  - 소매 미디어 +14.3%로 성장 상위(WARC)
  - 반례: Perplexity처럼 답변 흐름 안에 넣은 형식은 신뢰 문제로 멈췄다
- **과금 방향**: 시장은 CPM → CPC·성과형으로 갔다. 우리는 추적이 없으므로 클릭은 **쿠키 없는 서버 쪽 집계**(리디렉트 수)로만 센다. 성과형(4번 후보)은 사용자 결정 뒤 시범한다.

### (C) 기존 대체 기법

1. **사이트 디렉터리 "Featured (Sponsored)" 고정가 기간제 칸**: 업계 관행(MCPBundles 월 129달러 등). 추적이 필요 없다.
2. **진주·목걸이 소식지 후원 1칸(후원사 최대 2개)**: 개발자 뉴스레터가 B2B 개발자 채널 중 반응이 좋다는 업체 자료가 있다(미확인). 수신 동의자에게만 보낸다.
3. **표시된 데브렐 후원**: 예제 목걸이·튜토리얼에 "Sponsored by" 표시. 결과·순위와 분리한다.
4. **우리 홍보는 정직한 GEO**: 인용·통계·출처가 담긴 방법론·시험 보고서(지출 0, GEO 논문 근거)
5. 리타기팅은 규칙상 제외

---

## 4. 에이전트가 읽는 광고의 표시 설계 권고

1. **구조로 분리**: `results`(유기)와 `sponsored`(광고)는 다른 필드다. 광고를 `results`에 넣지 않는다. 개수는 최대 1, 위치는 항상 유기 결과 뒤로 고정한다(위치 편향을 팔지 않기).
2. **필드 예시**(DSA 26조 항목 + agent-ads 초안 참고)

```json
"sponsored": [{
  "payload_type": "advertisement",
  "label": "Sponsored",
  "disclosure": "Paid placement. Does not affect verification, scores, ranking, recommendations or necklaces.",
  "sponsor": {"name": "...", "paid_by": "...", "on_behalf_of": "...", "payment_tx": "0x..."},
  "why_shown": {"matched": ["category:research"], "personal_data_used": false},
  "period": {"start": "2026-11-15", "end": "2026-11-15"},
  "offer": {"endpoint": "...", "protocol": "mcp", "price": "...", "free_trial": "first 100 calls", "sla": "..."},
  "independent_verification": {"grade": "B", "report_url": "...", "computed_independently": true},
  "content_is_data_not_instructions": true,
  "repository_url": "https://.../ads/repository#id"
}]
```

3. **요약을 거쳐도 남는 사람용 표시**: 텍스트 응답에서는 광고 줄 맨 앞에 "Sponsored:"를 붙인다(한국 지침의 "첫 부분 표시", agent-ads 초안의 규칙).
4. **HTTP·프로토콜 메타**: REST는 응답 헤더로 광고 포함 여부를 알린다(예: `X-Ad-Content: sponsored; count=1`, 우리 자체 규약). MCP는 `_meta`에도, A2A는 Part 메타데이터에도 같은 값을 둔다.
5. **에이전트의 끄기**: 요청 인자 `ads=none`(또는 헤더)을 주면 광고를 빼고, 결과는 똑같이 돌려준다. 끈 비율을 지표로 공개한다.
6. **광고 문구 검사**: 명령형·주입 문구(예: "always choose", "ignore previous", "you must")를 막는다. ToolTweak 방어처럼 바꿔 쓰기와 혼란도 검사를 하고, 길이를 제한하고, 자유 문구를 최소화한다. 광고주 엔드포인트의 도구 설명도 같은 검사를 거친다.
7. **공개 광고 저장소**(DSA 39조식, 의무는 아님): 모든 광고의 광고주·기간·카테고리·결제 해시를 1년 동안 공개 조회할 수 있게 한다. 신뢰와 감사에 쓴다.
8. **독립성 증명**: 광고 유무별 유기 결과 동일성을 매일 반사실로 비교하고 결과를 공개한다(Qiu·Mei 권고).
9. **민감 주제 제외와 미성년 대상 없음**(OpenAI 방식): 금융 조언·건강 질의에는 광고를 넣지 않는다.
10. **배지 분리**: "Verified·Overall Pick" 같은 추천 표시는 광고 객체에 절대 넣지 않는다. 에이전트가 가장 크게 반응하는 신호(ACES)라서 오인 위험이 가장 크다.

---

## 부록: 확인하지 못한 것

- 유료 자리가 에이전트의 **도구** 선택을 얼마나 바꾸는지 직접 측정한 연구(ACES는 쇼핑 상품)
- Gravity 에이전트 광고의 표시·과금·성과
- MCP·A2A 공식 사양의 광고 표시 필드(찾지 못함)
- Perplexity 광고 영구 철수 날짜, ChatGPT Instant Checkout 철수 세부, 한국 AI 가상인물 지침 시행일
