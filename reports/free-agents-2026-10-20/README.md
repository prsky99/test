# 무료로 자체 에이전트 개발에 쓸 수 있는 등록 에이전트

조회 시각: 2026-10-20. 운영 DB(`gateway-data/collector.sqlite3`)를 읽기 전용으로 조회했습니다.

## 선정 기준

아래 조건을 **모두** 만족하는 A2A 에이전트·MCP 서버만 골랐습니다. x402는 호출마다 결제가 필요해 제외했습니다.

- 활성 상태이며 최근 헬스체크 결과가 healthy
- 계정·API 키 없이 연결됨 (`auth_observed`/`auth_declared` = 0)
- 결제 없이 실제 도구 호출이 성공함 (`trial_ok` = 1)
- 품질 등급 A 또는 B, 보안 평가 `ok` (격리·검토 대상 제외)

## 규모

| 구분 | 엔드포인트 | 제공자(호스트) |
|---|---:|---:|
| MCP 서버 | 14,518 | 8,791 |
| A2A 에이전트 | 2,255 | 1,437 |
| 합계(호스트·종류별 중복 제거) | 16,659 | **10,128** |

같은 호스트가 수천 개 엔드포인트를 등록한 경우가 있습니다(예: 토큰마다 주소가 있는 암호화폐 정보 서버 2곳이 약 4,700건). 그래서 제공자 단위로 묶어 가장 좋은 엔드포인트 하나만 남겼습니다. 전체 목록은 [free-agents.csv](free-agents.csv)에 있습니다.

## 자체 에이전트의 부품으로 쓸 만한 추천 목록

점수 순위만으로는 업체 홍보용 서버가 많이 섞입니다. 그래서 범용 기능을 기준으로 직접 골랐습니다. 모두 최근 24시간 가용성 95% 이상입니다.

| 기능 | 이름 (종류·등급) | 주소 | 주요 도구 |
|---|---|---|---|
| 웹 검색·수집 | Exa (MCP·A) | https://mcp.exa.ai/mcp | web_search_exa, web_fetch_exa |
| 웹 검색·수집 | agentsearch-mcp (MCP·A) | https://agentsearch-mcp.vercel.app/mcp | web_search, instant_answer, fetch_url |
| 웹 검색·수집 | search-mcp (MCP·A) | https://search.ioconnex.dev/mcp | search_web, fetch_url |
| 웹 페이지 → 마크다운 | PageWire (MCP·A) | https://pagewire.dev/mcp | page_to_markdown, page_metadata, crawl_site |
| 웹 페이지 → 마크다운 | AgentMD (MCP·A) | https://www.getagentmd.com/api/mcp | convert_url_to_markdown, convert_document_to_markdown |
| 뉴스 | Glitchwire News (MCP·A) | https://glitchwire.com/mcp | search_news, latest_news, get_article |
| 개발 문서 검색 | Context7 (MCP·A) | https://mcp.context7.com/mcp | resolve-library-id, query-docs |
| 위키백과 | wikipedia-mcp (MCP·A) | https://wikipedia.caseyjhand.com/mcp | 검색, 요약, 본문 |
| 위키데이터 | wikidata-mcp (MCP·A) | https://wikidata.caseyjhand.com/mcp | 엔티티 검색·조회 |
| 논문 | arxiv-mcp (MCP·A) | https://arxiv.caseyjhand.com/mcp | 논문 검색, 메타데이터, 본문 읽기 |
| 공개 데이터 묶음 | Open Data Tools for Agents (A2A·A) | https://agent-data-tools.grit-77.workers.dev | Hacker News, arXiv, OpenAlex, SEC EDGAR, 지진 등 15개 |
| 날씨·지도 | Weather & Geo Intel (MCP·A) | https://weather.datakoot.com/mcp | geocode, 예보, 현재 날씨, 경보, 지진, 고도 |
| 지오코딩 | Pinloft Batch Geocoder (MCP·A) | https://pinloft.cybermax-tools.workers.dev/mcp | 주소↔좌표 |
| 계산 | Math MCP Learning (MCP·A) | https://math-mcp.fastmcp.app/mcp | 수식, 통계, 단위, 행렬 등 17개 |
| 날짜·시간 | Plumbkit (MCP·A) | https://plumbkit.dev/mcp | 현재 시각, 시간대 변환, 날짜 계산, 영업일 등 16개 |
| 날짜·시간 | Timezone Truth (MCP·A) | https://timezone-truth.gumballtools.com/api/mcp | convert_time |
| 데이터 검증 | Payload Validator (MCP·A) | https://payload-validator.gumballtools.com/api/mcp | JSON·YAML·XML·CSV 검증 |
| cron 해석 | Cron Translator (MCP·A) | https://crontoenglish.com/api/mcp | cron 설명, 다음 실행 시각, 생성 |
| 파일 변환·번역 | ChangeThisFile (MCP·A) | https://changethisfile.com/mcp | 파일 변환, 번역, 표 추출, 압축 |
| PDF 생성 | MintPDF (MCP·A) | https://mintpdf.dev/mcp | generate_pdf, pdf_from_url |
| PDF 생성 | url-to-pdf (MCP·A) | https://url-pdf.hammbox.com/mcp | URL→PDF·스크린샷·마크다운 |
| LaTeX → PDF | Pressa (MCP·A) | https://api.pressa.dev/mcp | compile, 템플릿 렌더링 |
| OCR·문서 추출 | Frenchie (MCP·A) | https://mcp.getfrenchie.dev | OCR, 음성→마크다운, 추출 |
| 인도 언어 | Bhasini (MCP·A) | https://mcp.bhasini.com/mcp | 문자 변환, 음역 |
| IP 정보 | IPinfo (MCP·A) | https://mcp.ipinfo.io/ | IP 조회, 프록시·VPN 판별, 위치 |
| 도메인·DNS | Domain & Company Intel (MCP·A) | https://domain.datakoot.com/mcp | 도메인 리포트, DNS, 메일 전달성, 기술 스택 |
| WHOIS | wwhois.ru (MCP·A) | https://wwhois.ru/backend/mcp | whois, IP 위치, punycode |
| 한국 주식 | aikstockdata (MCP·A) | https://mcp.aikstockdata.com/mcp | 종목 검색·조회, 순위, 시장 요약 등 12개 |
| 미 의회 주식 거래 | Coldpine (MCP·A) | https://coldpine.io/api/mcp | 의원 주식 공시 11개 |
| 프론트엔드 점검 | Front-End Checklist (MCP·A) | https://mcp.frontendchecklist.io | 코드 리뷰, URL 감사 등 11개 |
| 에이전트 탐색 | AgentsJunction (A2A·A) | https://www.agentsjunction.com | 에이전트·MCP 서버 탐색 |
| 에이전트 탐색 | ANP2 Network Relay (A2A·A) | https://anp2.com/api/a2a | 이벤트 발행·조회, 에이전트 탐색, 작업 수명주기 |

## 유의 사항

- **무료의 의미:** 계정·키·결제 없이 실제 도구 호출 1건이 성공했다는 뜻입니다. 서버의 모든 도구가 무료라는 보장은 아닙니다. 일부는 무료 체험 범위나 정보 조회 도구만 공개하고, 나머지는 API 키나 유료 플랜을 요구합니다(예: `get_pricing`, `get_api_key` 도구가 있는 서버).
- **호출 제한:** 무료 공개 서버는 대부분 속도 제한이 있습니다. 운영용으로 쓰기 전에 각 제공자의 제한과 이용약관(상업적 이용 허용 여부)을 확인해야 합니다.
- **안정성:** 개인이 운영하는 서버(vercel.app, workers.dev 등)는 예고 없이 중단될 수 있습니다. 같은 기능을 가진 대안을 하나 이상 함께 두는 것을 권합니다. CSV에서 같은 분류의 다른 후보를 찾을 수 있습니다.
- **수치 기준 시각:** 헬스체크와 시험 호출 결과는 조회 시점 기준입니다.
