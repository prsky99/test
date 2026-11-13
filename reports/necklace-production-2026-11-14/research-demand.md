# 수요 근거: 여러 출처를 병렬로 읽어 합치는 과제 15가지 (워크플로우 팀 11-14, 하위 조사 결과 정리)

조사 방법: 웹 검색과 공개 API 조회만 했습니다(게시·쓰기 없음).
- n8n: `api.n8n.io/api/templates/search` 누적 조회수입니다. 실행 수가 아닙니다.
- Smithery: `registry.smithery.ai/servers` 기본 정렬 앞 262개(전체 20,750)의 useCount입니다. 정의는 공개돼 있지 않습니다.
- [업체]는 업체 스스로의 주장입니다.

| 순위 | 과제군 | 수요 근거 | 여러 출처가 나은 이유 | 목걸이 후보 |
|---|---|---|---|---|
| 1 | 주제 브리프·딥리서치 | 리서치 24.4%(LangChain 2025-12), 정보 찾기 24%(NBER w34255), n8n research 템플릿 226개(딥리서치 47,644, Perplexity 리서치 45,170·34,934) | 교차 확인, 최신성과 깊이 | topic-evidence-brief |
| 2 | 회사·거래상대 실사 | 영국 실사 60,881, 기업 신원 16,045, Zapier "Lead Background Research"[업체], Relevance "Atlas" 407회[업체], Gumloop "Research a startup"[업체] | 등기만으로는 평판·최근 사건을 모름 | company-due-diligence |
| 3 | 상장사·주식 스냅샷 | n8n 주식 분석 36,976·27,894(관련 112개), SEC 40,620, Edgar Tools 290k/주[업체 집계], 금융 직군 47%(Comet) | 숫자와 맥락 | 보류(투자 조언 경계) |
| 4 | 학술 문헌 교차 검색 | 논문 검색 59,106, PubMed 42,137·13,948, Semantic Scholar 10,296, n8n arXiv 알림 9,074 | 분야마다 색인이 다름, 중복 제거 | paper-cross-search |
| 5 | 뉴스·브랜드 모니터링 | n8n news 템플릿 385개, Agent News 43,392, Gumloop "가장 인기"[업체] | 매체 치우침 상쇄, 중복 묶기 | news-digest |
| 6 | 경쟁사 인텔리전스 | n8n "Competitor Research with Exa.ai" 22,060(관련 171개), Google 보고서 분석가 에이전트 | 가격·뉴스·리뷰·순위를 합침 | 12-26 뒤 후보(가격 페이지 읽기 진주 필요) |
| 7 | 웹사이트·SEO 진단(읽기만) | n8n SEO 템플릿 266개(온페이지 감사 36,255, 키워드 22,715) | 페이지·검색 결과·기술 점검을 합쳐야 진단 | website-ai-readiness |
| 8 | 패키지 공급망 보안 | CISA 2025-09-23 Shai-Hulud 경보, NPM Sentinel 13,278 | DB마다 수록 범위·속도가 다름 | package-risk-audit |
| 9 | CVE 브리프 | NVD 12,481, CVSS+KEV+EPSS 결합 연구(2502.11070). n8n CVE 템플릿은 11개(최고 949)로 얇음 | 결정적 정답 | cve-incident-brief |
| 10 | 예측시장·암호화폐 스냅샷(조회만) | Polymarket 39,483·10,102, n8n crypto 207개 | — | 보류(거래 경계) |
| 11 | 라이브러리 업그레이드 브리프 | Context7 1m/주[업체 집계], mcp.directory 1위(2026-02), 코딩 36~44%(Anthropic Economic Index 2025-09) | 문서·변경 이력·패키지 정보 합침 | library-upgrade-brief |
| 12 | 상품 구매 리서치 | Comet 하위 주제 1·2위(강의·쇼핑 합 22%) | 사양·리뷰·가격 비교 | 공개 가격 진주 부족, 뒤로 |
| 13 | 여행·도시 브리프 | 미국 소비자 29%(Adobe), 날씨 17,177, NYC 지하철 16,873, 도시 비교 12,406. n8n 여행 31개 | 날씨·환율·행사·교통 묶음 | trip-brief |
| 14 | 국가·거시 스냅샷 | SEC·거시 40,620, 정부 통계 노출(중간) | 출처 교차 | country-economy-snapshot |
| 15 | 회의 전 인물·회사 브리프(공개만) | Lindy 템플릿[업체] | LinkedIn은 로그인 필요라 일부만 | company-due-diligence에 흡수 |

맞지 않는 큰 수요(쓰기·계정·결제): 영상 생성·SNS 게시(n8n 조회 1위 214.9K), 메일함 관리(29.1K), 사내 문서 RAG(47.0K), 리드→CRM 기록(Zapier 분석 1위[업체]), 브라우저 조작(Playwright 5.5m/주), 결제.

주요 링크
- LangChain https://www.langchain.com/state-of-agent-engineering
- NBER https://www.nber.org/papers/w34255
- Perplexity Comet https://www.perplexity.ai/hub/blog/how-people-use-ai-agents , https://arxiv.org/abs/2512.07828
- Google Cloud AI Agent Trends 2026 https://services.google.com/fh/files/misc/google_cloud_ai_agent_trends_2026_report.pdf
- Anthropic Economic Index 2025-09 https://www.anthropic.com/research/anthropic-economic-index-september-2025-report
- Smithery https://registry.smithery.ai/servers , PulseMCP https://www.pulsemcp.com/servers
- CISA https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem
- Zapier Agents 템플릿 https://zapier.com/agents/templates , Gumloop https://gumloop.com/templates/research-a-startup-get-a-comprehensive-email-report
- Adobe 여행 https://business.adobe.com/au/blog/consumers-embrace-generative-ai-for-trip-planning
- n8n 순위 https://n8n-pulse.gui.do/templates

한계: n8n 조회수와 Smithery useCount는 실행 수가 아닙니다. Reddit 원글은 직접 열지 못했고, HN Ask 글은 15점 이하가 대부분이라 근거로 쓰지 않았습니다. Make.com·Gumloop·Lindy는 공개 사용량 순위를 찾지 못했습니다.
