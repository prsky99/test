# 진주 목걸이 생산체계 (워크플로우 팀, 2026-11-14)

사용자 지시(11-14 06:0x, PM 전달): 지금 워크플로우는 예제입니다. 새 경영 전략·목표·품질 계획에 맞춰 워크플로우 전략과 생성 계획을 세우고, 진정한 가치를 내는 진주 목걸이 생산체계를 확립합니다. 논문과 SNS 조사를 근거로 하고, 기존 예제는 조건이 맞을 때 하나씩 대체합니다.

| 파일 | 내용 |
|---|---|
| 이 문서 | 조사 요약, 워크플로우 전략, 첫 10개 후보, 공정 요약, 일정, 팀 의존 |
| [process.md](process.md) | 공정 9단계 상세, 정답 세트, **공개 스냅샷 계약 확정**, **품질 관문 95%**, 운영·SRE 넘김 묶음, 교체·보류 규칙, 동의 문구 초안 |
| [existing-workflows.md](existing-workflows.md) | 기존 33개 대체 정책(①②③ 분류, 절차, 사용자 영향) |
| [research-production.md](research-production.md) | 논문·실측 근거(평가 통계, 외부 도구 불안정, 합성, 보안, 자동 생성, 지연) |
| [research-demand.md](research-demand.md) | 수요 근거(과제군 15개, 사용량·템플릿·설문) |
| [../necklace-design-2026-11-14/README.md](../necklace-design-2026-11-14/README.md) | 첫 설계안(데이터 모델, 대체 사슬 v2, 기존 fallback 확장). PM 06:3x 승인 |

PM 06:3x 결정 반영: ① 파일 방식 승인 ② 읽기 전용 기준 완화(조건부) ③ 안정성 관문과 관계없이 진행 ④ 옛 공개 워크플로우 is_active=0(메뉴 오른 날, 대체하는 것만) ⑤ 동의 문구 초안은 PM 확인 뒤 사용. 품질 관문 95%(PM 06:2x).

---

## 1. 조사 요약

### 1-1. 수요: 사람과 에이전트가 실제로 원하는 다단계 조회 작업
조사일 11-14. n8n 수치는 템플릿 누적 조회수(실행 수 아님), Smithery 수치는 useCount(정의 비공개, 기본 정렬 앞 262개 표본)입니다. [업체]는 업체 스스로의 주장입니다.

- **리서치·정보 찾기가 사람과 기업 모두에서 상위입니다.**
  - 기업의 주된 에이전트 용도: 리서치·데이터 분석 24.4%(2위), 매일 쓰는 에이전트 2위도 리서치. LangChain 설문 1,340명, 2025-12 https://www.langchain.com/state-of-agent-engineering
  - ChatGPT 대화 중 "정보 찾기" 14% → 24%(1년). NBER w34255, 2025-09 https://www.nber.org/papers/w34255
  - Perplexity Comet 에이전트: 생산성·워크플로우 36%, 학습·리서치 21%, 금융 직군 47%가 생산성 과제. 2025-12 https://arxiv.org/abs/2512.07828
  - n8n 읽기 전용 템플릿 조회 1위: "Host Your Own AI Deep Research Agent" 47,644회
- **에이전트가 많이 부르는 도구(Smithery useCount, 11-14 실측)**: pipeworx 게이트웨이 419,019(= 우리 진주 50972), Brave Search 87,579, 영국 실사(공공 등기) 60,881, 논문 검색 59,106, Agent News 43,392, PubMed 42,137, SEC·거시 40,620, 미국 날씨 17,177, 기업 신원 검증 16,045, NPM Sentinel 13,278, NVD(KEV 포함) 12,481 https://registry.smithery.ai/servers
- **회사 실사**: Zapier Agents "Lead Background Research"[업체], Gumloop "Research a startup"[업체], Relevance AI "Atlas" 복제 407회[업체]
- **보안**: CISA가 2025-09-23 npm 공급망 침해(Shai-Hulud, 패키지 500개 이상)로 의존성 점검을 촉구 https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem . CVSS만으로는 부족하고 KEV·EPSS를 함께 봐야 한다는 연구 https://arxiv.org/html/2502.11070v1 . 다만 n8n CVE 템플릿은 11개(최고 949회)로 수요 층이 얇습니다.
- **여행**: 미국 소비자 29%가 AI로 여행을 계획한 적 있음(Adobe). n8n 여행 템플릿은 31개로 적습니다.
- **맞지 않는 큰 수요**: 영상 생성·SNS 게시(n8n 조회 1위 214.9K), 메일함 관리, 사내 문서 RAG, CRM 기록, 브라우저 조작, 결제. 쓰기·계정·결제가 필요해 목걸이 범위 밖입니다.
- **HN 근거는 약합니다**: 관련 Ask HN 글이 대부분 15점 이하라 근거로 쓰지 않았습니다.

시사점
1. 간판은 주제 브리프(리서치)입니다.
2. 자리는 에이전트가 이미 많이 부르는 단일 도구(웹 검색, 논문, 공공 등기, 공시, 뉴스, 날씨, 보안 DB)에 맞춥니다. 단일 도구와 바로 비교할 수 있어 Δ를 재기 쉽습니다.
3. "여러 출처를 한 번에"는 이미 증명된 수요이고 경쟁자도 있습니다(사용 1위가 데이터 250개 이상 게이트웨이, 같은 도구를 33개로 등록한 ceadigital.io의 "5-Source Parallel Corporate KYB"). **차별점은 모으기가 아니라 출처 교차 검증·대체 사슬·공개 품질 수치**입니다.
4. 보안 과제는 수요 층이 얇지만 정답을 결정적으로 확인할 수 있어(KEV 여부, OSV id) 95% 관문을 먼저 넘길 후보입니다.

### 1-2. 생산 방법 (상세와 링크: research-production.md)
- 30건으로는 95%를 증명할 수 없습니다(29/30의 Wilson 하한 83%). 하한 95%를 보이려면 실패 0개일 때 73건, 1개일 때 110건이 필요합니다. → 출시 관문은 점추정 95%(보류 60건 중 57건), "검증된 95%" 표시는 누적 재시험 110건 중 실패 1건 이하일 때만 씁니다.
- 같은 정답 세트로 후보를 고르면 선택 편향이 생깁니다. → 조정 세트와 보류 세트를 나눕니다.
- Δ의 유의성은 짝지은 McNemar 검정으로 봅니다. 단일 진주만 맞힌 문항이 0개일 때 목걸이만 맞힌 문항이 6개 이상이어야 유의합니다. → 단일 진주가 놓치는 과제(재현율·교차 검증)를 정답 세트에 넣습니다.
- 무작위로 고른 MCP 서버는 48.8%만 연결되고, 도구 계약은 14일에 39.2%가 바뀝니다. → 사슬을 여러 단으로 두고, 지문이 바뀌면 즉시 빼고, 매일 재시험합니다.
- 도구를 과제마다 고정하면(Tool filter) 주입 공격 성공률이 57.7%에서 6.8%로 떨어집니다. 출력을 데이터로만 다루는 구조(CaMeL)가 가장 강합니다. → 정의 파일로 도구를 고정하고, 합성은 결정적 규칙으로 합니다.
- 병렬 호출은 지연을 1.6~3.7배 줄입니다. 헤징은 p99.9를 1,800ms에서 74ms로 줄였습니다(추가 요청 2%). → 웨이브 병렬 실행을 먼저 하고, 헤징은 자리별 p95를 잰 뒤 켭니다.

---

## 2. 워크플로우 전략

### 2-1. 무엇을 만드는가 — 고르는 기준(점수 순서대로 적용)
1. **안전**: 모든 자리가 읽기 전용으로 풀립니다. 자격 증명·결제·x402·쓰기가 없습니다. 멤버는 readOnlyHint=true 명시, destructiveHint≠true, `is_relay_safe_tool` 통과(PM 06:3x ②). 하나라도 안 되면 후보에서 뺍니다.
2. **수요 근거**: 서로 다른 출처 2개 이상(1-1의 설문·사용량·템플릿 조회).
3. **Δ 구조**: 단일 진주보다 나아질 이유가 구조에 있어야 합니다.
   - 같은 역할 fan-out: 출처마다 수록 범위가 달라 재현율이 오르고, 일치 여부를 표시할 수 있습니다(보안 DB, 논문 색인, 뉴스).
   - 여러 측면 합성: 단일 진주가 못 채우는 칸이 있습니다(등기 + 위험 + 면허).
   - 순차 의존이 강한 과제는 피합니다(Google·MIT: 순차 과제에서 39~70% 악화).
4. **진주 공급**: 주 자리에 엄격 기준 진주가 있거나 이번 주 실행 시험으로 진주가 될 후보가 있고, 자리마다 외부 대체 2개 이상과 AgentValCon fallback 1개 이상을 세울 수 있어야 합니다.
5. **정답을 결정적으로 확인할 수 있는가**: 공개 원천(OSV, KEV, NVD, SEC, 등기, World Bank 등)으로 고정 정답을 만들 수 있으면 95% 관문을 빨리 넘깁니다.

### 2-2. 분야 우선순위
| 순위 | 분야 | 이유 |
|---|---|---|
| 1 | 리서치(주제 브리프·논문 교차 검색·뉴스 다이제스트) | 수요 1위. 진주 50972(사용 1위 게이트웨이)가 있음. 논문 색인 fan-out은 Δ 구조가 분명 |
| 2 | 회사·거래상대 실사 | 수요 2위. 진주 3개(50972·276982·156012)로 바로 조립 가능 |
| 3 | 보안(패키지·CVE) | 정답이 결정적이고 진주 2개(367249·276982). 첫 관문 통과 후보 |
| 4 | 웹사이트 AI 노출·준비도 진단 | n8n SEO 템플릿 266개. 진주 2개(50972 ai_visibility_check, 79081 check_brand_agent_readiness) |
| 5 | 여행·도시, 국가·거시 | 수요 중간. 진주 일부(115024·38634, 47609 브라질 한정) |
| 보류 | 주식·예측시장 | 수요는 크지만 투자 조언·거래와 경계가 가까움. 사실 요약만 하는 형태로 12-26 뒤 검토 |

### 2-3. 첫 10개 후보
"진주"는 엄격 기준 진주(검색과 RAG 11-14, 33개)입니다. 다른 번호는 후보이고, 검색과 RAG의 역할 도구 실행 시험을 통과해야 자리에 들어갑니다. 사슬 순서는 자리 자격 시험 뒤 확정합니다. **ceadigital.io(276982)는 같은 도구 묶음을 33개로 등록한 한 장애 영역**이라, 한 사슬에 하나만 넣고 그 자리에 다른 원천의 멤버를 반드시 둡니다.

| # | slug | 과제(입력 → 출력) | 수요 근거 | 진주 자리와 사슬(주 → 외부 대체 → AgentValCon) | Δ 구조 | 정답 세트 계획(보류 60 + 조정 30) |
|---|---|---|---|---|---|---|
| 1 | `package-risk-audit` | 패키지@버전 → 알려진 취약점·공급망 점수·릴리스 상태, 출처 일치 표시 | Shai-Hulud CISA 경보, NPM Sentinel 13,278, 1-1 | 취약점(fanout 2): **367249** check_software → 47161 osv_query_package → 286623 search_vulnerabilities → 130453 → AgentValCon 133023(OSV)·GitHub Advisory(새로) / 공급망: **276982** depsdev_openssf_scorecard·package_health_pulse → 50709 → AgentValCon 133021(npm) | DB마다 수록 범위·반영 속도가 다름(재현율), 일치 표시 | npm·PyPI 패키지@버전(취약 절반). 정답 = OSV·GHSA 고정 스냅샷. 채점: 권고 id 재현율 ≥0.9, 취약한데 "깨끗함"이면 실패 |
| 2 | `cve-incident-brief` | CVE id → CVSS·KEV 등재·EPSS·영향 제품·수정 안내 | NVD 12,481, KEV·EPSS 결합 연구(2502.11070) | 위험(fanout 2): **276982** security_cve_audit·cisa_kev_exploited_vulns·epss_exploit_score → 37259 get_cve → 286623 get_vulnerability → 55398 cve_kev_lookup → AgentValCon NVD·KEV(새로) / 수정: **367249** latest_incidents·get_fix_prompt → 47161 | CVSS만 주는 단일 대비 KEV·EPSS 결합, 출처 교차 | CVE(KEV 등재 절반). 정답 = NVD·KEV·EPSS 고정 스냅샷. 채점: KEV 여부·CVSS·EPSS 구간 정확 |
| 3 | `company-due-diligence` | 회사명·도메인 → 등기·식별자, 위험 신호, 미국 면허(해당 시), 최근 뉴스 | 수요 2위(영국 실사 60,881, 기업 신원 16,045, Zapier·Gumloop 템플릿) | 등기(fanout 2): **50972** company_register_search·company_facts → 47686 foretak lookup_company → 42345 eu-registry → 32966 BUMIT / 위험: **276982** corporate_kyb_and_risk_dossier·gleif_lei_kyb → 50243 MORVS / 면허(선택): **156012** verify_business·verify_license / 뉴스(선택): 50972 news_search → 147960 → AgentValCon 133018 / AgentValCon: GLEIF·SEC EDGAR(새로) | 등기만으로는 위험·평판을 모름. 등기 출처 교차 | 상장사·비상장사(미국·영국·EU). 정답 = SEC CIK·Companies House·GLEIF LEI 고정. 채점: 식별자·설립일·상태 정확, 위험 칸 출처 HTTPS |
| 4 | `topic-evidence-brief` | 주제 → 인용 달린 브리프(논문·백과·웹·뉴스) | 수요 1위(리서치 24.4%, 정보 찾기 24%, 딥리서치 템플릿 47,644) | 웹 근거: **50972** ask_pipeworx_grounded·web_search → 276982 agent_clean_web_grounding / 논문(fanout 2): 47151 → 39577 → 34550 → 34807 → AgentValCon 133019(Crossref) / 백과: 47189 → 143970 → AgentValCon Wikipedia(새로) / 뉴스(선택): 50972 news_search → 147960 → AgentValCon 133018 | 깊이(논문)+최신(뉴스)+교차 확인 | 주제 90개. 같은 역할 과제: 대표 논문 재현율(정답 = OpenAlex 인용 상위 + Crossref 고정). 여러 측면: DOI 실재·주제 관련(LLM 채점, 사람 30건 일치 80% 이상) |
| 5 | `paper-cross-search` | 질의 → 여러 색인을 합친 중복 없는 논문 목록 | 논문 검색 59,106, PubMed 42,137, Semantic Scholar 10,296 | 논문(fanout 3): 47151 openalex → 39577 nobleblocks → 34550 cutgpt → 34807 Paper Finder → 130450 arXiv → 276982 openalex_citation_graph / AgentValCon 133019(Crossref)·arXiv(새로) | 색인마다 수록 범위가 달라 재현율이 오름(가장 깨끗한 Δ) | 질의 90개(분야 고르게). 정답 = 각 색인 상위를 합쳐 사람 판정한 관련 논문 집합. 채점: 재현율@10, 중복 0 |
| 6 | `website-ai-readiness` | 도메인 → AI 검색 노출, 에이전트 준비도, 인증서 이력, llms.txt | n8n SEO 템플릿 266개(온페이지 감사 36,255), Google 보고서 마케팅 46% | 노출: **50972** ai_visibility_check·scan_competitor_ai_presence / 준비도: **79081** check_brand_agent_readiness / 인증서: 276982 crtsh_cert_recon / AgentValCon: robots·llms.txt·sitemap 직접 읽기(새로) / 34856 Quotalis는 readOnlyHint가 없어 제외 | 한 도구는 한 면만 봄 | 도메인 90개. 정답 = 직접 받은 robots·llms.txt·인증서 사실(결정적) + 노출 점수는 측정값 표시만 |
| 7 | `trip-brief` | 도시·날짜 → 날씨, 환율, 행사, 볼거리 | 미국 소비자 29%(Adobe), 날씨 17,177, 도시 비교 12,406 | 행사(fanout 2): **115024** search_events → 57384 / 장소: **38634** num_search_places / 날씨: 37322 → 56036(표시 없음, 제외 가능) → 38062 → AgentValCon Open-Meteo(새로) / 환율: 48762 → 47112 → 226724 → AgentValCon ECB(새로) | 한 곳에서 못 얻는 묶음 | 도시 90개. 날씨 ±3°C(같은 시각 Open-Meteo), 환율 ±0.5%(ECB), 행사는 기간 안 1건 또는 coverage 밖이면 "없음" |
| 8 | `country-economy-snapshot` | 국가(1~2) → 핵심 지표, 환율, 불일치 표시 | SEC·거시 40,620, 정부 통계 도구 노출(중간) | 지표(fanout 2): 47130 IMF → 34791 → 37316 → 33130 → AgentValCon 133022·133020(World Bank) / 브라질이면 **47609** / 환율: 7번과 같음 | 출처 교차·불일치 표시 | 국가 90개 × 지표. 정답 = World Bank·IMF 고정(같은 연도 ±2%) |
| 9 | `news-digest` | 주제 → 여러 매체의 중복 묶은 최신 뉴스 | n8n news 템플릿 385개, Agent News 43,392, Gumloop 브랜드 모니터링[업체] | 뉴스(fanout 3): **50972** news_search → 147960 → 41195(표시 없음, 제외) → 281854 → 43528 → AgentValCon 133018(HN) | 매체 치우침 상쇄, 중복 묶기 | 주제 90개. 정답 = 같은 시각 여러 원천을 합쳐 사람 판정한 주요 기사. 채점: 재현율, 날짜 7일 안, 중복 0 |
| 10 | `library-upgrade-brief` | 패키지·현재 버전 → 최신 버전, 변경 위험, 알려진 취약점, 저장소 활동 | Context7 1m/주[업체 집계], 코딩 비중 36~44%(Anthropic) | 릴리스: 50709 → AgentValCon 133021 / 취약점: 1번 사슬 재사용 / 저장소: **276982** github_repo_pulse → AgentValCon GitHub(133021 확장) | 패키지 감사와 문서·활동을 합침 | 패키지 90개. 정답 = 레지스트리·GitHub API 고정 |

**역할 도구 실행 시험 반영(검색과 RAG 9292edf7, reports/pearls-2026-11-14/role_tests.json, 30건 중 21건 성공)**

| 역할 | 성공 | 실패·건너뜀과 이유 | 영향 |
|---|---|---|---|
| papers.search | 47151·39577·34550·34807 (4/4) | 130450은 하루 상한으로 11-15 | topic-evidence-brief·paper-cross-search 논문 자리 확보(11-20 조건 충족) |
| package.advisories | 47161·286623·130453·367249 (4/4) | — | package-risk-audit 취약점 자리 확보 |
| cve.kev | 37259 | 55398은 429로 11-15 재시도 | cve-incident-brief는 276982 재시험(11-15)과 함께 확정 |
| encyclopedia.summary | 47189·143970 (2/2) | — | 백과 자리 확보 |
| fx.rate | 48762·47112·226724·36306 (4/4) | — | 환율 자리 확보 |
| news.search | 147960 | 41195는 읽기 전용 판정 탈락 | 뉴스 자리는 50972 news_search(11-15) 결과 필요 |
| package.metadata | 40897 | 50709는 읽기 전용 판정 탈락 | 공급망 자리 주는 276982(11-15), 외부 대체 1개뿐 → AgentValCon 133021 필요 |
| weather.forecast | 56036·38062 | 37322는 미국 좌표만(NWS) | 날씨는 지역 제한 표시 필요 |
| events.search | 47538(힌두 축제) | 115024는 SF Bay Area만, 38634는 unauthorized | **trip-brief의 행사 자리가 범용으로 서지 않음** |
| country.indicator | 34791 | 37316 지표 코드 실패, 47130·33130 필수 인자를 못 채움 | country-economy-snapshot은 io 변환(지표 코드 대응표)이 필요해 뒤로 |
| company 자리 | (11-15 09:12 예약 14건) | — | company-due-diligence는 11-15 결과로 확정 |

- **예비 후보(PM 확정, 11-14)**: `website-ai-readiness`(진주 50972·79081). 근거는 역할 시험에서 행사 자리가 범용으로 서지 않은 것입니다(115024 SF Bay Area만, 38634 unauthorized, 47538 힌두 축제). `trip-brief`는 후보 목록에 남기고, 행사 자리를 "선택 자리 + 지역 제한 멤버(coverage) + 범위 밖이면 없음"으로 다시 설계한 뒤 다시 심사합니다.
- **장애 영역 규칙 추가**: caseyjhand.com 한 곳이 47151·47189·47161·47112·47130으로 5개 역할에 걸칩니다. 그래서 다음을 지킵니다.
  1. 한 목걸이 안에서 같은 장애 영역(등록 도메인 묶음: caseyjhand.com, ceadigital.io, agentdiet.dev, datakoot.com, openkrill.app 등)이 **주 멤버인 자리는 하나까지**입니다.
  2. 모든 필수 자리에 그 영역 밖의 멤버가 하나 이상 있어야 합니다.
  3. 판정 작업은 장애 영역별 "그 영역이 멈춘 날 완주율"을 매일 계산합니다(재시험 결과로).
- **지역 제한 멤버**: 사슬 정의에 `coverage`(예: `{"country": ["US"]}`, `{"region": "SF Bay Area"}`)를 적습니다. 입력이 범위 밖이면 그 멤버를 건너뛰고, 실패로 세지 않습니다.

**11-28까지 출시 목표 5개(순서, PM 07:5x 승인)**: 1 `package-risk-audit`, 2 `cve-incident-brief`, 3 `company-due-diligence`, 4 `topic-evidence-brief`, 5 `paper-cross-search`(예비 `website-ai-readiness`, PM 확정).
- 1~3은 주 자리에 진주가 이미 있고 정답이 결정적입니다.
- 4·5의 논문 자리는 11-14 역할 시험으로 외부 4개가 확보됐습니다(47151은 caseyjhand.com 영역이라 주 자리는 39577 또는 34807).
- 진주 276982가 1~5 중 4개에 들어갑니다. 한 사슬에 하나만 넣고 다른 원천 멤버를 반드시 둡니다. 이 진주가 멈추는 날의 완주율을 매일 따로 기록합니다.

새로 만들 AgentValCon fallback 에이전트(키 없는 공개 원천, 지출 0): GitHub Advisory, NVD, CISA KEV, GLEIF, SEC EDGAR, Wikipedia, arXiv, Open-Meteo, ECB, 사이트 공개 파일 — 10개. **헌장 956c74b3(사용자 11-14)으로 개발은 에이전트 팀 몫**입니다. 워크플로우 팀은 자리별 필요 목록과 역할 계약을 넘기고, 2단계(외부 대체 가동)가 생긴 자리를 그날 PM에 보고합니다. 첫 5개에 필요한 순서: ① NVD(cve-incident-brief record) ② CISA KEV(cve-incident-brief exploited) ③ GitHub Advisory(package-risk-audit advisories 두 번째) ④ GLEIF·SEC EDGAR(company-due-diligence) ⑤ Wikipedia·arXiv(topic-evidence-brief, paper-cross-search). 역할 계약은 agent_market/necklaces/contracts/, 고정 과제는 role_tasks/role-tasks-v1.jsonl.

---

## 3. 생산체계(공정) 요약 — 상세는 process.md 1절

수요 선정 → 진주 자리 설계(역할 계약) → 진주·대체 배정(자리 자격 시험) → 조립(정의·템플릿·정책 v2 shadow, 장애 드릴) → 정답 세트 자체 시험(95% 관문) → **운영·SRE 출시 관문 검수(95%)·메뉴 적용** → 성장·유통 공개·홍보 → 매일 재시험 → 교체·보류 → 폐기

| 단계 | 담당 | 통과 기준(요약) |
|---|---|---|
| 수요 선정 | 워크플로우 | 수요 근거 2개, 읽기 전용, 자리 사이 의존 없음 |
| 자리 설계 | 워크플로우 | 필수 자리 2개 이상 또는 fan-out 2, 역할 계약 |
| 진주·대체 배정 | 워크플로우(판정)·검색과 RAG(진주·실행 시험) | 멤버마다 계약 시험 3/3, 자리마다 외부 2 + AgentValCon 1 이상, 주는 엄격 기준 진주 |
| 조립 | 워크플로우 | 정의 검증, 자리마다 1순위 강제 실패 드릴 통과 |
| 자체 시험 | 워크플로우 | 4절 관문 전부(보류 60건 중 57건, Δ > 0, 완주 95%, p95 5초, 보안) |
| 출시 관문 | 운영·SRE | 넘김 묶음으로 공개 주소에서 다시 재서 95% 이상 → 메뉴 적용 |
| 공개·홍보 | 성장·유통 | 표면 계약 3절 |
| 매일 재시험 | 운영·SRE(인프라·지문) | 결과 JSONL |
| 교체·보류 | 워크플로우 | process.md 6절 |

품질 관문(생산 공정 합격선, process.md 4절)
- 종단 성공률 **95% 이상**(보류 60건 중 57건, 조정 30건 중 29건)
- Δ > 0(최고 단일 진주 대비, 같은 역할 과제만 따로 셌을 때도), 유의 여부 함께 표시
- 완주율 95% 이상, 외부만 완주율 70% 이상
- 지연: 복잡한 답변 p95 5초 안(공개 주소·새 연결·처음 보는 입력)
- 보안 시험 통과(도구 고정·지문·출력 주입·자격 증명 0)
- 차선 목표 품질 90%와의 관계: 차선 품질은 탐색·추천 지표이고, 목걸이 관문 95%는 그보다 높은 별도 합격선입니다. 목걸이 보류 과제 5건씩을 real_task_score 묶음에 넘겨 함께 잽니다.

넘김 묶음(운영·SRE 제출, 관문은 deploy/NECKLACE_GATE.md: 관문 세트 30건을 4시간 간격 두 번, 둘 다 95%, approvals.json 두 열쇠): `gateway-data/necklaces/submissions/<slug>-v<version>-<시각>/`에 manifest, 목걸이 계약 JSON, 정의, 역할 계약, 대체 사슬과 자격 시험 결과, 정답 세트(조정·보류), 목걸이·단일 기준선·보안 시험 원자료, 정책 v2, 재실행 명령. 상세는 process.md 5절입니다.

공개 스냅샷 계약 확정(PM 05:4x 요청, 성장·유통 초안 기준, process.md 3절)
- 경로 `gateway-data/necklaces/necklaces.json`, 쓰는 쪽은 워크플로우 jobs 작업 `necklace_judge` 하나
- slug: `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, 3~40자, 과제 이름, 바꾸지도 다시 쓰지도 않음. 표면 이름은 `/necklaces/<slug>`, `necklace-<slug>`, `necklace_<slug>`(MCP 접두는 성장·유통 확인 중)
- held 판단은 워크플로우. 운영·SRE 재시험은 입력이고, 긴급할 때는 운영·SRE가 approvals.json을 held·revoked로 바꿉니다(두 열쇠: approved 항목의 version·digest가 같을 때만 live).
- 더한 필드: `version`, `definition_digest`, `gate_passed_at`(성장·유통 요청: 메뉴 오른 시각), `replaces_templates`·`replaced_at`(옛 template_id 안내용), 품질 하한·유의 여부, held_reason 코드, retired·replaced_by

---

## 4. 생산량과 일정

| 기간 | 워크플로우 | 검색과 RAG | 운영·SRE | 성장·유통 |
|---|---|---|---|---|
| 11-14~16 | 역할 계약(1~5에 필요한 9개), 정의 파일 5개, 정답 세트 생성기와 고정 스냅샷(1·2 먼저), 자리 자격 시험 스크립트 | 역할 도구 실행 시험(후보 31개 + 이 문서 1~5의 새 후보) | 도구 정의 지문 설계 | 계약 확정본으로 표면 1주 차 틀 |
| 11-16~19 | 정책 v2·자리별 다중 시도·웨이브 병렬 실행(기존 순차 워크플로우 무변경 시험 포함, SQLite·PG 둘 다), AgentValCon fallback 7개 | 진주 판정 갱신, Neo4j 같은 역할 묶음·장애 영역 | 재시험 형식 맞춤 | 동의 문구 검토 |
| 11-19~22 | 1·2 자체 시험 → 넘김 묶음 제출, `necklace_judge` | — | 1·2 출시 관문, 켜는 절차(shadow → canary) | 1·2 메뉴·페이지 |
| 11-22~26 | 3·4 자체 시험·제출, 1·2 첫 교체(기존 40·46·47·55·62) | — | 3·4 관문 | 홍보 시작 |
| 11-26~28 | 5(또는 trip-brief) 제출 | — | 5 관문 | — |
| 11-29~12-26 | 주당 후보 8 → 조립 5 → 제출 4, 누적 20. 6~10번과 수요 조사 15개 과제군에서 보충 | 역할별 진주 확대(12-26 진주 1,000) | 매일 재시험 20개 | 목걸이 단위 홍보 |

- 하루 생산량: 자리 자격 시험 2목걸이, 정답 세트 시험 1목걸이(같은 호스트 동시 1, 60초 간격, 2~3일에 나눔)
- 통과율 기록: 조립한 목걸이 중 관문 통과 비율. 50% 아래면 수요 선정·자리 설계 기준을 다시 봅니다.
- 11-28에 5개가 안 되면 숫자를 맞추려고 관문을 낮추지 않고, 통과한 수와 막힌 이유를 그대로 보고합니다.

## 5. 기존 예제 대체 정책 요약 — 상세는 existing-workflows.md
- ① 대체 16개(공개 15): 같은 수요의 목걸이가 메뉴에 오른 날, 그 목걸이가 대체하는 것만 하나씩 내립니다(is_active=0, 삭제 없음, 되돌리기 기록). 대체 전후 품질을 `replacements/<id>.md`에 남깁니다.
- ② 대체 없이 내림 14개: 꺼진 4개(27·28·35·36)는 첫 목걸이가 메뉴에 오르는 날 정리합니다(PM 승인, 사용자 보고는 PM). 공개 10개는 안내할 목걸이가 생긴 뒤 PM에 다시 승인을 받습니다.
- ③ 예제 유지 3개(41·42·43): 엔진·대체 실행 회귀 예제입니다.
- 옛 링크(성장·유통과 맞춤): 지금 공개 화면에는 워크플로우별 주소가 없어(workflows.html 한 장, 카드는 template_id만), 대체된 카드에 "Replaced by necklace <name>" 링크를 30일 동안 붙입니다. 옛 template_id로 run_workflow·workflow_details를 부르면 실행하지 않고 `replaced_by {slug, url, until}`과 "no longer runs; use necklace <slug>"를 돌려줍니다(스냅샷의 `replaces_templates`·`replaced_at`). 폐기된 목걸이 주소는 replaced_by로 301합니다.
- 11-04 뒤 공개 실행 0건, 예약 실행 0건입니다.

## 6. 팀 의존 (맞춘 상태, 11-14)
| 팀 | 맡는 일 | 맞춘 내용 | 상태 |
|---|---|---|---|
| 검색과 RAG | 진주 판정·진주 표, 역할 도구 실행 시험, Neo4j 같은 역할 묶음·장애 영역 | 후보 31개 전달. 그 팀 확인: 수집기 시험 도구가 역할 도구와 달라(예: 47151 openalex_resolve_name) 지금 배치로는 역할을 증명하지 못함 → **역할 도구 직접 실행 시험**을 만들기로 함(하루 3회·60초 간격·429면 중지). 등록 도메인 장애 영역을 묶음에 붙임 | 진행(그 팀) |
| 운영·SRE | 매일 재시험 인프라, 도구 정의 지문, 켜는 절차, 출시 관문 검수·메뉴 적용, 배포 | 재시험 결과 JSONL 형식과 경로 전달. 넘김 묶음 형식(process.md 5절), 관문 기록 파일 `gate/<slug>-v<n>.json` | 확인 요청(현황판) |
| 성장·유통 | 공개 표면(MCP·A2A·웹), 홍보, 옛 링크 안내 | 계약 확정안 전달(경로·slug·held·gate_passed_at). MCP 도구 이름 접두 `necklace_` 확인 요청, 동의 문구 검토 요청 | 답 대기 |

## 7. PM 확인 요청
1. ~~첫 5개 순서~~ → PM 승인, 예비 website-ai-readiness 확정
2. ~~품질 주장 방식~~ → PM 07:5x 승인. 관문은 보류 60건을 4시간 간격 30건씩 두 번, 합계 57/60 이상·각 회 28/30 이상. "검증된 95%"는 누적 110건 중 실패 1건 이하일 때만, 그 전에는 실제 수치("29/30 passed on 11-20")만
3. ~~동의 문구~~ → PM 07:5x 승인("in parallel"은 병렬 그래프에만). 보존 문장은 아래 5번이 해결돼야 씁니다
4. ~~AgentValCon fallback 10개~~ → PM 07:5x 승인. 조건: 공개 원천 이용 규칙 준수(SEC EDGAR User-Agent에 공개 연락 메일 contact@agentconcierge.biz, Wikipedia·arXiv·NVD 권장 호출 간격), 결과에 출처·라이선스 표기, 키·유료·개인정보 없음, 진주처럼 시험 보고서를 남기고 AgentValCon fallback 사용률 기록 → **헌장 956c74b3: 개발 주체는 에이전트 팀으로 바뀜**(목걸이 단계 1~4 대응, 워크플로우는 2단계 그날 보고)
5. ~~실행 본문 정리~~ → PM 08:0x: 운영·SRE에 배정(처리방침 보관 약속 감사·정리 작업 켜기 안, 기존 데이터 삭제는 사용자 승인 뒤). 원래 발견: **실행 본문 정리 작업이 운영에서 돌지 않음**: 코드는 14일(`workflow_maintenance.py:18`)인데, 14일 지난 실행 135건 중 127건에 결과가 남아 있음(11-14 읽기 전용 확인). 목걸이 공개 전에 운영·SRE가 정리 작업을 켜는지, 실제 보존 기간을 문구에 쓸지 결정 필요
