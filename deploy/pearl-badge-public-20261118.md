# 공개 화면의 진주 배지 (성장·유통, PM 11-18 07:0x 지시, 원래 11-24 과제를 11-20까지)

## 무엇이 보이나
| 화면 | 내용 | 코드 |
|---|---|---|
| 에이전트 페이지 `/agent/<id>` | 제목 줄에 배지("Final pearl, #1 for <role>" 또는 "Verified pearl"), 맨 위 카드 "Verified role tasks"에 역할별로 "Passed N of M role tasks · confirmed on D different days · last checked <date>"와 /methodology 링크 | `growth_catalog.pearl_blocks`, `pearl_badge.py` |
| Explore 결과 카드 | 작은 배지("Final pearl"/"Verified pearl"). 목록은 `/api/pearls/public`(최대 60초 캐시)에서 페이지당 한 번 읽음 | `pearl-ui.js` `markPearls`, `necklace_surface` 라우트 |
| 홈·About 띠 | 아래 "검토" 참고(이번에는 만들지 않음) | — |
- 진주가 아닌 에이전트 페이지는 바이트까지 그대로다(시험으로 고정).

## 데이터
- 검색과 RAG의 공개 목록 `gateway-data/pearls/public-pearls.json`(schema agentcon-public-pearls-v1, 원자적 교체, 09:12·15:12·20:12 회차 뒤 갱신)만 읽는다. `AGENTCON_PROJECT_ROOT` 아래 절대 경로이고 작업본 상대 경로(reports/…)는 읽지 않는다. 파일이 없거나 깨지면 아무것도 보이지 않고 페이지는 그대로 열린다. 수정 시각 기준 메모라 요청 때 DB를 읽지 않는다.
- 화면에 나오는 것은 level이 final·verified인 행뿐이다. provisional(1일)은 보이지 않는다.
- **terms가 prohibits인 행도 보인다**(PM 11-18 07:2x: 우리 정책은 "중계하지 않는다"이지 "숨긴다"가 아니고, 시험 결과는 사실이다). 대신 배지 옆과 카드 안에 고정 문구 "Connect directly — we don't relay this agent (provider terms)"를 붙인다(에이전트 페이지는 제목 줄 배지와 "Verified role tasks" 카드, Explore 카드는 배지 옆 작은 글). 지금 파일에서 이 문구가 붙는 것은 58997 sec.filings.v1(최종), 132732 website.ai_readiness.v1(최종) 두 에이전트다. 검색과 RAG의 추천 카드도 같은 기준으로 "relayed": false를 낸다(bbe4e5b1). 시험: `test_a_member_whose_terms_prohibit_our_relay_is_shown_with_the_fixed_direct_note`.
- 숫자는 모두 목록의 값이다(통과 수·시도 수·서로 다른 성공 날수·마지막 확인 날짜). 계산하거나 지어내지 않는다. 역할 이름표는 목록의 label, 없으면 역할 id에서 만든다.
- 실제 파일(11-18 07:2x)로 읽어 보니 46행 중 final 20·verified 17이 대상이고 에이전트 34개, 읽은 행 수가 기대와 같다(prohibits 2행 포함).

## 퍼지가 필요한가
- 새 화면 코드는 배포 뒤 곧바로 쓰이지만, 엣지에는 두 가지가 남는다. (1) 에이전트 페이지 HTML은 엣지 6시간이라 진주가 바뀌어도 최대 6시간(+낡은 사본 허용 1일) 옛 모습이 나올 수 있다. (2) Explore 페이지 HTML이 엣지 6시간(11-18 캐시 변경)이라 새 pearl-ui.js 해시를 부르는 HTML이 늦게 갈 수 있다.
- 그래서 첫 배포 직후 한 번 퍼지할 것을 권한다: `deploy/cloudflare-purge-urls-pearl-badge-20261118.txt`(Explore 1 + 진주 에이전트 페이지, 30개씩 나눠 실행, 실행은 PM). 이후 회차마다 바뀌는 진주는 6시간 안에 반영되는 것으로 둔다. 급하면 해당 `/agent/<id>`만 퍼지한다.
- 목록 다시 만들기: 같은 조건(level final·verified)으로 `resource_id`를 모아 `https://agentconcierge.biz/agent/<id>`를 만든다.

## 홈·About 띠 검토(3번)
- 만든다면 고정 HTML 한 줄 띠("Pearls we verified" + 한 문장 + Explore 진주 필터 링크)이고 숫자는 넣지 않는다(회차마다 바뀜). 링크는 검색과 RAG가 만드는 Explore "Verified pearls" 필터 주소가 정해져야 쓸 수 있다.
- 홈 HTML을 바꾸면 첫 화면 CSS를 다시 만들고(`build_critical_css`) 시안과 대조해야 하며(디자인 시안 보존 규칙) 홈 바이트가 매번 같아야 한다는 70230022 조건도 지켜야 한다. 그래서 필터 주소가 나온 뒤 별도 변경으로 한다.
