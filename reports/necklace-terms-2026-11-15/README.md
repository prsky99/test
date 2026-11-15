# 목걸이 외부 멤버 약관 확인 1차 (에이전트 팀, 2026-11-15)

PM 12:28 지시를 따랐습니다. 11-17 관문 후보 3개(quakes-near-address, book-author-brief, website-trust-brief)와 company-due-diligence의 외부 멤버 8개를 먼저 봤습니다.

## 확인 방법

- 제공자 홈페이지에서 약관 링크를 찾고 그 페이지를 읽었습니다. 링크가 없으면 `/terms`와 공개 문서 페이지를 읽었습니다.
- 모두 읽기 전용 GET이고, 공용 장부 'adhoc' 몫 안(도메인당 2번)입니다. 제공자에게 문의나 연락은 하지 않았습니다.
- 남의 약관 문장은 옮기지 않고, 근거 위치(조항·문단 이름)만 `basis`에 적었습니다. 읽은 원문은 팀 scratchpad에만 두었습니다.
- 판정 기준(PM)
  - `allowed`: 자동 호출이나 재사용을 허용하거나, 공개 API라고 밝힘
  - `silent`: 약관에 그에 대한 말이 없거나, 약관 페이지가 없음을 확인함
  - `prohibits`: 자동 호출, 상업적 재사용, 중계를 금지함. 애매하면 이쪽으로 둡니다.

## 결과

| 멤버 | 목걸이·자리 | 판정 | 근거 |
|---|---|---|---|
| 37322 Datakoot 날씨·지리 | quakes-near-address location·quakes | allowed | datakoot.com/terms 3절 Acceptable use: 요금제 한도 안의 에이전트 자동 접근을 환영함, 경쟁 데이터셋으로 재판매 금지 |
| 264482 DMV Transit | quakes-near-address location | allowed | dmvtransit.com/mcp-server Limits: 모든 MCP 앱용 키 없는 공개 서버, 망당 분당 120·하루 3,000 |
| 52559 Presend | website-trust-brief registration, company-due-diligence domain | allowed | presend.pages.dev/api: 키·가입 없는 무료 공개 엔드포인트, 공정 사용, 과도한 자동 호출은 속도가 제한될 수 있음 |
| 38608 Invokera Book Search | book-author-brief book | silent | 홈페이지에 약관 링크가 없고 /terms는 404(11-15). Open Library API를 가져다 올린 것이라 데이터에는 Open Library 조건이 적용됨 |
| 178542 A.U.G.U.R Foresight | quakes-near-address quakes | silent | 홈페이지에 약관 링크가 없고 /terms는 404(11-15). 지진 자료는 USGS 공공 영역 |
| 241601 web2mcp | book-author-brief author, company-due-diligence background | silent | 개인 workers.dev 주소의 시연 서버라 약관 페이지가 없음. 코드는 MIT. 돌려주는 Wikipedia 글은 CC BY-SA 4.0이라 출처 표시가 필요 |
| 58997 filings.tools | company-due-diligence filings | **prohibits** | filings.tools/terms의 무료 사용 문단: 무료 도구·키 없는 API·무료 키는 운영 환경, 팀, 사업에 쓸 수 없고 유료 플랜이 필요함(지출 0이라 불가) |
| 132732 xfix | website-trust-brief crawlers | **prohibits** | xfix.ai/terms의 What you may not do: 이 서비스로 경쟁하는 감사 제품을 만들거나 보고서를 재게시하는 것을 금지. 사이트 신뢰 목걸이가 여기에 걸린다고 봄(애매하면 prohibits) |

allowed와 silent 6개는 정의 파일의 멤버 `terms`에 넣었습니다(같은 커밋).

## 워크플로우가 정할 것(prohibits 2건)

prohibits 2건은 정의에 넣지 않았습니다. 넣으면 그 멤버가 모든 사슬에서 빠집니다(watch.runtime_chain). 그 결과가 아래처럼 정의 구조를 바꾸기 때문에 워크플로우가 정하고 반영합니다.

- **company-due-diligence filings 자리**: 멤버가 58997 하나뿐이라 자리가 비게 됩니다.
  - 정할 것: 다른 멤버로 바꿀지, 자리를 선택으로 돌릴지, 이 자리를 뺄지.
  - 참고: 자체 대체 sec-edgar는 registry 자리에서 회사 식별자만 돌려주고, 공시 목록은 주지 않습니다.
- **website-trust-brief crawlers 자리**: 132732가 빠지면 자체 대체 site-readiness가 선두가 됩니다.
- 영향받는 시험(그대로 두면 실패): tests/test_necklace_gate_check.py 3개, tests/test_necklace_website_trust_brief.py::test_run_sends_the_url_and_the_domain. 둘 다 이 두 멤버가 실행된다고 가정합니다.
- 넣을 값

```json
{"58997": {"status": "prohibits", "source": "https://filings.tools/terms", "checked_at": "2026-11-15",
           "basis": "paragraph on free use: the free tool, the API without a key and a free key may not be used in production, for a team or for a business; that needs a paid plan"},
 "132732": {"status": "prohibits", "source": "https://xfix.ai/terms/", "checked_at": "2026-11-15",
            "basis": "section What you may not do: using the service to build a competing audit product and republishing reports; a site-trust necklace is close enough to count (PM rule: unclear means prohibits)"}}
```

## 남은 것

- 카탈로그 밖 자체 에이전트 133018·133019·133023(topic-evidence-brief, package-risk-audit)
  - 지금 `model.terms_status`는 agentcon 종류를 자체 대체 카탈로그(SPECS)로만 판정해서, 멤버 `terms`를 넣어도 unknown으로 남습니다. 워크플로우가 이 경우에 멤버 `terms`를 읽도록 바꿔야 합니다.
  - 원천 약관은 R16과 같은 기준으로 공개 차례가 올 때 봅니다.
- 나머지 외부 멤버 23개(cve-incident-brief, package-risk-audit, topic-evidence-brief)도 공개 차례가 올 때 봅니다.
- silent 3개(38608·178542·241601)는 도메인당 하루 읽기 몫을 다 써서 /legal 같은 다른 주소는 아직 못 봤습니다. 다음 날 한 번 더 확인합니다.
