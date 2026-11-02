# 개선사항 20개 운영 재확인 — 2026-10-29

현재 활성 릴리스 `qa7-repair-frontend-20261029-r4`의 소스, 공개 서비스와 브라우저 동작을 확인했다. 이번 요청은 적용 여부 확인이며, **제품 소스·설정·운영 프로세스는 변경하지 않았다.**

## 결론

이전 평가의 문제 중 상당수는 개선됐다. 특히 정적 자산 캐시·압축, 색 대비, 포커스 링, 오류 JSON 파싱, MCP 발견 경로가 바뀌었다. 그러나 20개 복합 항목 전체를 완료로 볼 수 없다.

- 정적 자산 9개 모두 버전 해시 URL, `public, max-age=31536000, immutable`, Cloudflare `HIT`, gzip 또는 br 압축이었다. 예전의 ‘정적 파일 모두 no-store·BYPASS·압축 없음’은 현재 상태와 다르다.
- 10개 화면 × 4조건에서 색 대비 0건, 이름 없는 select 0건, serious/critical 0건, 포커스 링 누락 0/986회였다.
- 가로 넘침은 0/40조건이었다. 단, 작은 요소의 원시 합계는 76개이며 이를 전부 접근성 위반으로 계산할 수는 없다.
- 아직 쿠키 배너가 실제 포커스 요소를 가린다. 고정 헤더가 주원인이라는 과거 추측은 현재 구조와 맞지 않는다.
- 초기 빈 Chat의 CLS가 0이어도 결과 표시 후에는 모바일 0.1168·데스크톱 0.1005였다. Workflows 초기 측정도 최대 0.104였다. CLS 완료 판정은 이르다.
- Test 캐시·시각 표시에는 재현되는 결함이 있다. 실제 캐시 응답인데 캐시 조회시각이 KPI에 없고, 게이트웨이 지연을 agent 지연으로 표시한다.
- WebMCP, Web Bot Auth, 실제 AP2 mandate 수용, Chat 비교·고유 공유 URL은 확인되지 않았다. 사람 과업·스크린리더 사용자 시험도 별도 증거가 필요하다.

복합 항목별 요약은 개선 확인 2, 부분 개선 13, 미구현/미확인 4, 실사용자 검증 필요 1이다. 이 개수는 작업 완료율이나 원 평가 점수를 뜻하지 않는다. 9번의 readOnlyHint 요구는 실제 동작에 맞게 조정해 판정했다.

## 먼저 남은 문제

1. **쿠키 배너의 포커스 가림:** 새 방문자 상태에서 Explore 검색 버튼·필터와 Workflows 실행 버튼 등이 배너 뒤에 들어간다. 대표 화면 증거는 `focus-covered-mobile-explore.png`다. 자동 측정의 중앙점 가림은 총 85회였지만 동일 요소·화면 조건의 반복을 포함하므로 고유 위반 85개로 세지 않는다. 쿠키 배너의 실제 높이에 맞는 스크롤 여백·포커스 노출을 설계해야 한다. 현재 헤더는 relative이고 `scroll-padding-top`은 24px다.
2. **결과 도착 시 Chat 이동:** 실제 응답으로 추천 카드가 나타날 때 `chatForm`이 이동한다. 높이 예약·대화 영역 구조를 결과가 없는 시작 상태와 실제 카드 상태 모두에서 맞춰야 한다.
3. **Test 캐시·시간 표시:** 두 번 실행한 뉴스 예제의 두 번째 응답은 `fresh_cache`, 원본 조회시각 `2026-10-29T06:07:07.902293Z`였다. 화면은 새 시험 시각인 06:07:09 UTC만 표시했다. `output`은 JSON 문자열인데 KPI 코드가 객체만 읽는 것이 원인이다. `405.6 ms agent · total 906 ms`에서 405.6ms는 실제 응답의 `gateway_latency_ms`이고, 브라우저에서 관측한 응답은 약 931ms였다. 전체시간을 함께 표시한 점은 좋아졌지만 지연 구간 라벨은 아직 잘못됐다.
4. **미완성 문맥·오류 계약:** `the second one`은 상세를 반환했지만 `it`은 다시 과업 설명을 요구했다. 워크플로우 REST 오류 일부는 일반 JSON이고 `retryable`도 없다.

## 항목별 판정

### 1. 정적 파일 캐시·압축 — 부분 개선

확인: 자산 9개 모두 해시 URL, 1년 immutable, Cloudflare HIT, gzip/br.

남음/주의: HTML과 API는 no-store이며 Home TTFB는 0.813~1.176초. HTML의 nonce·세션 분리 후 재검증 정책 검토 필요.

근거: `assets.json, uiux.json`.

### 2. 라이트·다크 색 대비 — 개선 확인

확인: 40개 화면 조건에서 color-contrast 0건, serious/critical 0건.

남음/주의: 자동 검사 범위의 확인이다. 실제 사용자·저시력 시험을 대체하지 않는다.

근거: `uiux.json`.

### 3. 포커스 링·가림·스크롤 여백 — 부분 개선

확인: 포커스 링 누락 0/986회. scroll-padding-top은 24px. 헤더는 현재 relative.

남음/주의: 가림 중앙점 85회 관측. 대표 실제 원인은 하단 쿠키 배너이며 헤더 높이만큼 여백을 넣는 조치만으로 해결되지 않는다.

근거: `browser-details.json, focus-covered-mobile-explore.png`.

### 4. CLS와 비동기 결과 공간 — 부분 개선

확인: 초기 Explore CLS 0~0.005, 실제 검색 결과까지 0~0.008.

남음/주의: 추천 응답 후 Chat CLS 모바일 0.1168·데스크톱 0.1005, 초기 Workflows 최대 0.104. 아직 0.1 초과.

근거: `uiux.json, dynamic-cls.json`.

### 5. 라벨·랜드마크·작은 타깃 — 부분 개선

확인: select-name/aria-allowed-role 0건. 로그인 select가 없고 Learn은 DIV tablist. 기존 템플릿 aside는 role=region.

남음/주의: 홈의 daily-catalog-statistics complementary 경고와 제목 순서 경고가 4조건씩 남음. 작은 요소 원시 76개는 숨긴 미러·skip link 등을 포함한다. 체크박스 라벨은 30px여서 입력 22px만으로 실패 판정하면 안 된다.

근거: `uiux.json, labels-structure.json`.

### 6. RFC 9457 오류 계약 — 부분 개선

확인: 깨진 JSON 400, limit=1000은 422와 읽을 수 있는 문장. 해당 응답은 problem+json.

남음/주의: 워크플로우 REST 오류 400은 일반 JSON. retryable 없음. 모든 type URI가 상세 error_code와 대응하지 않음. MCP/A2A는 JSON-RPC 계약을 유지해야 한다.

근거: `api.json`.

### 7. 한도·목록 캐시·멱등성 — 부분 개선

확인: Explore next_cursor/o3, ETag/304 확인. 일반 조회 RateLimit-Policy 있음. 비실행 워크플로우 입력의 Idempotency 재생 확인.

남음/주의: 샘플의 RateLimit 잔량 헤더는 없고 목록 전체에 ETag가 있지 않다. API no-store. 실제 등록·결제·장애 시 정확히 한 번 보장은 이번에 미검증. Retry-After를 정상 200에 일괄 붙일 필요는 없다.

근거: `api.json`.

### 8. 결제 실패 이유 코드 — 부분 개선

확인: 잘못된 payload·버전·네트워크·수취인·금액·시각·서명 등의 구분 코드가 구현됨. 관련 격리 회귀 59개 통과.

남음/주의: 공개 x402는 inspection_only. 실제 잔액·settle 실패와 실결제 성공은 검증하지 않았으며 구현 범위를 넘어서는 사유를 꾸며내지 않는다.

근거: `payment-source-matches.json, payment-tests.log`.

### 9. MCP·발견 문서 — 개선 확인

확인: server.json, 명시적 Markdown 협상, 일간 통계와 llms.txt의 196,335건 일치 확인.

남음/주의: search/find_agents/whats_new는 세션 기록을 변경해 readOnlyHint=false가 정확하다. 요청한 true를 일괄 강제하면 실제 동작을 잘못 설명한다.

근거: `api.json, search-documents.json`.

### 10. 서비스 상태 JSON — 부분 개선

확인: /status.json이 operational, 점검 시각, 카탈로그 스냅샷·한도를 제공.

남음/주의: 기간별 실측 가동률, 최근 장애 목록은 없다. operational 응답만으로 SLA·가동률을 판단할 수 없다.

근거: `api.json`.

### 11. Chat 문맥·피드백·중단 — 부분 개선

확인: the second one → details 동작. Worked/Did not work UI, 브라우저 Stop 및 입력 보존 확인.

남음/주의: it → clarify여서 문맥 처리가 완전하지 않다. 피드백 이유 입력은 없다. Stop은 브라우저 요청 중단이며 서버 작업 취소 보장은 아니다.

근거: `browser-details.json, chat-stop-390.png`.

### 12. 자동완성·오타 제안 — 부분 개선

확인: translte → translate, gihtub → github 제안 필드가 반환됨.

남음/주의: 두 글자 gi 입력 후 combobox/option/aria-activedescendant 없음. 무의미 검색도 10개 결과가 나와 0건 처리·관련성 기준을 추가 확인해야 한다.

근거: `search-documents.json, browser-details.json`.

### 13. 품질 설명·제공자 문구 구분 — 부분 개선

확인: Why these matches?에서 품질 6축 배점과 추천 순서를 설명. 설명이 제공자 작성임을 알리는 문장도 있음.

남음/주의: 품질 숫자 자체의 클릭 상세·방법론 링크와 Provider description 개별 라벨·별도 배경은 확인되지 않음.

근거: `browser-details.json; operating.js 3794~3797`.

### 14. 추천 공유 URL·항목 비교 — 미구현/미확인

확인: 일반 페이지 URL·Explore 검색 URL은 존재.

남음/주의: Chat 추천·상세의 고유 공유 URL, 2~4개 비교 UI는 확인되지 않음. 일반 #chat이나 호출 명령 복사는 이 기능과 다르다.

근거: `browser-details.json; 활성 operating.js`.

### 15. Chat AI·보관 안내 — 부분 개선

확인: 입력창 아래 자동 추천, 사람 사전 검토 없음, 최근 질문 저장과 Privacy 링크 안내가 있음.

남음/주의: 정확한 보관일수 N은 입력창 아래에 없다. 실제 보관 정책과 맞춰야 한다. AI Act 50조가 보관일수를 정하는 것은 아니므로 법적 준수 전체를 판정하지 않는다.

근거: `browser-details.json`.

### 16. Test 캐시·시간·지연 표시 — 부분 개선

확인: 실제 실행 성공과 전체 응답시간을 표시. 원본 응답에 fresh_cache/retrieved_at이 존재.

남음/주의: output이 문자열인데 KPI는 객체로만 읽어 캐시 조회시각을 놓친다. gateway latency 405.6ms가 agent로 표시됨. 전체 약 0.9초와 원본 시각을 구분해야 한다.

근거: `test-cache.json, test-cached-390.png`.

### 17. WebMCP 검색·추천 도구 — 미구현/미확인

확인: 공개 MCP 서버는 존재.

남음/주의: navigator.modelContext 도구 등록 구현을 찾지 못함. 시험 Chromium에서도 modelContext=false. MCP HTTP 엔드포인트와 WebMCP는 별개다.

근거: `labels-structure.json; 활성 소스 검색`.

### 18. Web Bot Auth 서명·차등 한도 — 미구현/미확인

확인: 일반 요청 한도와 방문 토큰은 존재.

남음/주의: RFC 9421 Web Bot Auth 검증 후 높은 한도를 부여하는 구현·운영 증적을 찾지 못함.

근거: `활성 소스 검색`.

### 19. AP2 mandate·A2A x402 확장 — 미구현/미확인

확인: x402 검사 경로와 로컬 quote-bound 시험 fixture는 존재.

남음/주의: 실제 AP2 SD-JWT mandate 수용은 코드가 명시적으로 미지원. 공개 A2A 카드에도 해당 확장 선언 없음.

근거: `search-documents.json; workspace_protocol_conformance.py`.

### 20. 실사용자·스크린리더 시험 — 실사용자 검증 필요

확인: 자동 브라우저·키보드·axe 검사는 실시.

남음/주의: 5명×6과업, 스크린리더 사용자 1~2명 및 분기별 반복 실시에 대한 증적은 확인하지 못함. 자동 시험으로 해당 점수를 대신 확정하지 않는다.

근거: `이번 점검 범위 및 제공된 이전 평가 한계`.

## 접근성 판정의 보정

현재 axe의 남은 규칙은 홈 `.necklace-center > h3`의 heading-order 4회, `#daily-catalog-statistics`의 보조 랜드마크 중첩 4회다. 이전 `#pearlWorkflowTemplates` 경고와 Learning topics의 역할 경고를 그대로 현재 결함으로 옮겨 적지 않았다. 템플릿 노드는 ASIDE이지만 `role=region`으로 동작하고 Learn은 DIV tablist다. 로그인 화면에는 현재 select 자체가 없다.

원시 작은 요소 목록에는 다음이 포함된다.

- 포커스 전에는 1×1px로 숨기는 skip link.
- `aria-hidden=true`, `tabIndex=-1`, opacity 0인 미러 select.
- 문장 안 Privacy 링크.
- 입력 자체는 24×22px지만 클릭 가능한 라벨이 높이 30px인 Explore 체크박스.

따라서 76이라는 원시 합계는 76개 수정 대상을 의미하지 않는다. WCAG의 간격·동등 타깃·인라인 예외와 실제 라벨 클릭 영역을 적용해 판단해야 한다. 포커스 링 누락이 0이어도 쿠키 배너에 가려지는 문제는 별도로 남는다.

## API·결제 요구에서 조정할 기준

- MCP의 `readOnlyHint`는 상태 변경 여부를 알리는 힌트다. 기록을 저장하는 검색·대화 도구에 true를 강제하면 실제 동작을 잘못 설명하게 된다. 현재 false를 결함으로 세지 않았다. [MCP ToolAnnotations](https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations)
- RFC 9457 형식은 REST API에 일관되게 적용하는 방향이 맞지만, MCP/A2A의 JSON-RPC 오류나 사람이 읽는 HTML 404까지 무조건 같은 body로 바꾸면 안 된다. `retryable`은 확장 필드이며 RFC 자체의 필수 필드는 아니다. 이번 제품 요구사항으로는 미완성이다. [RFC 9457](https://www.rfc-editor.org/info/rfc9457/)
- 정상 200 응답 모두에 Retry-After가 필요한 것은 아니다. 제한·일시 장애에서 실제 재시도 시점을 알리고, 정상 응답에서는 정확한 정책·잔량을 제공해야 한다. 이번 샘플에는 RateLimit-Policy가 넓게 붙었지만 RateLimit 잔량은 없었다.
- 공개 게이트웨이의 x402는 inspection_only다. 사유 코드 구현과 오프라인 검증을 실제 결제 정산 검증으로 보고하지 않는다. 관련 결제·멱등 격리 회귀는 59개 통과했고 해당 소스 파일이 운영 패키지와 같은 것도 확인했다. 실제 돈은 사용하지 않았다.
- AI 고지와 개인정보 보관 안내는 구분해야 한다. EU 집행위는 Article 50 적용일을 2026-08-02로 안내하지만, ‘N일 보관’ 자체가 Article 50의 문구는 아니다. 현재 자동 추천·최근 질문 저장 안내는 있고 구체적 보관일수는 정책과 맞춰 보완할 부분이다. 이 점검으로 법적 준수 전체를 확정하지 않는다. [EU 집행위 Article 50 FAQ](https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act)

## 측정 방법·점수 한계

원본 `scripts/uiux_audit.js`를 읽기 전용으로 복제해 같은 10개 경로·4조건을 측정했다. axe-core는 4.10.3이며, Playwright는 이미 설치된 1.64 beta를 사용했다. 로그인·실행 버튼을 임의로 누르지 않도록 ‘각 페이지의 첫 main 버튼 클릭’만 제거했다. 제품 의존성을 설치·변경하지 않았다.

자동 측정 요약은 LCP 표본 p75 384ms, TTFB 중앙값 330ms, 초기 CLS 최대 0.104다. 같은 브라우저 컨텍스트의 캐시가 적용된 페이지 이동이 많고, 네트워크·CPU 제한을 하지 않은 실험실 수치다. 실제 방문자 p75 Web Vitals로 해석하지 않는다. Home의 개별 TTFB는 813~1,176ms로 제시된 800ms 목표를 여전히 넘었다. INP 원시값 0은 유효한 실제 과업 INP 0ms 달성으로 판정하지 않았다.

별도로 실제 Chat/Explore 검색 결과까지 기다려 CLS를 측정했다. 초기 화면만으로 CLS 완료를 선언하지 않았다. 이 결과는 `dynamic-cls.json`에 있다.

제공된 62/62/69, 종합 64점은 과거 평가다. 현재 저장소에 `docs/qa/uiux-evaluation-criteria.md` 세부 기준표가 없고, 사람 과업·스크린리더 사용자 실측도 없으므로 새 종합 점수·등급을 임의 계산하지 않았다. 76개 에이전트 시나리오 전체를 이번에 다시 수행한 것도 아니며, 위 항목의 현재 계약·공개 인터페이스와 관련 동작에 범위를 맞췄다.

## 산출물

- 전체 20개 판정: `items.json`, 필터 가능한 Canvas.
- 자동 40조건: `uiux.json`, 도구 정보 `tool-versions.json`.
- 실제 상호작용·포커스: `browser-details.json`, `labels-structure.json`, `focus-covered-*.png`, `chat-stop-390.png`.
- 결과 표시 CLS: `dynamic-cls.json`, `result-{chat,explore}-{390,1366}.png`.
- 캐시·압축·API: `assets.json`, `api.json`, `search-documents.json`.
- Test 캐시 시각 대조: `test-cache.json`, `test-cached-390.png`.
- 결제 검사: `payment-tests.log`, `payment-source-matches.json`.

[WCAG 최소 타깃 크기와 예외](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [CLS 측정·개선 기준](https://web.dev/articles/optimize-cls)을 판정에 참고했다. 자동 접근성 검사나 가상 브라우저 시험으로 사람 사용자·스크린리더 시험을 대체하지 않았다.

이번 시험에서 만든 QA 방문자 3명·관심사 4건·메시지 12건·전용 방문 집계 1건은 접근 제한 백업 후 정리했다. 실제 사용자나 실제 원본 실행의 검증 이력을 삭제하지 않았다. 정리 증적은 `test-data-cleanup.json`이다.
