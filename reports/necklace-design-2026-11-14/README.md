# 진주 목걸이 생성·관리 설계안 (워크플로우 팀, 옛 이름 백앤드, 2026-11-14)

PM 첫 과제: (a) 데이터 모델·수명주기, (b) 대체 사슬과 기존 fallback 확장, (c) 첫 목걸이 후보 5개.
근거: 운영 DB 읽기 전용 조사(11-14 03:4x~04:1x, 집계·후보 표만), 코드 조사, 검색과 RAG 진주 33개(reports/pearls-2026-11-14/pearls.json), 성장·유통 표면 계약(reports/growth-plan-2026-11-14/necklace-contract.md).

## 0. 지금 상태 (실측)

| 항목 | 값 | 뜻 |
|---|---|---|
| 워크플로우 | 33개(공개 28 = id 38~65, 꺼짐 5 = 27·28·34·35·36) | 공개 28개는 자체 에이전트 6개(133018~133023)만 쓰고, 외부는 Paper Finder(34807) 1개가 41~43에 들어감 |
| 실행 | workflow_runs 141건. 공개 117건(성공 92), 마지막 공개 실행 11-04 | 11-04 뒤 외부 실행 0 |
| 그래프 모양 | 공개 28개 모두 **순차 사슬**(trigger → A → B…), 앞 노드 출력을 뒤 노드 입력에 씀 | 전략의 "병렬 조회 뒤 합성" 모양이 아님 |
| 실행기 | `workflows.py:961` 위상 정렬 순서로 **한 노드씩** 실행, 전체 마감 25초 | 그래프로 fan-out을 그려도 실제로는 순차. 5초 목표에 병렬 실행이 필요 |
| 대체 실행 | 전역 스위치 `workflow_fallback_control.enabled=1`(10-24 22:15부터) / 정책 3개(41·42·43, mode active, 133019↔34807) 모두 **10-25 20:28 만료** / 라우팅 시도 44건 모두 10-24 | 스위치는 켜져 있지만 유효 정책 0 → 실질적으로 꺼짐 |
| 대체 한계 | 계약 2개(news.search.v1·docs.search.v1), 노드당 대체 1개, **실행 전체에서 대체 시도 1회**(`workflow_fallback.py:372`), 주 12초·대체 8초 | 목걸이의 "자리마다 여러 대체"를 못 함 |
| 독립성 검사 | 같은 호스트·같은 상위 의존성 거부(`fallback_independence.py:80`) | Agentcon 대체 2개는 둘 다 agentconcierge.biz라 지금 규칙으론 서로 거부됨 |
| 품질 평가 | 워크플로우와 단일 에이전트를 정답 세트로 비교하는 장치 없음 | Δ 측정 틀을 새로 만들어야 함 |
| 공개 노출 | MCP `search_workflows`·`workflow_details`·`run_workflow`(template_id+definition_hash), A2A는 `find_workflows`(발견만) | MCP 실행은 재사용 가능, A2A 실행 기술은 없음(성장·유통 몫) |
| 진주 33개 | 일 도구 25, 모두 MCP, 분야가 흩어짐(같은 역할 2개 이상인 묶음 거의 없음) | 진주 표만으로는 자리별 대체 사슬을 못 채움 → 역할별 후보를 넓은 카탈로그에서 뽑아 실행 시험을 맡겨야 함 |

자체 에이전트의 원천(대체 사슬의 "Agentcon 대체"가 됨): 133018 기술 뉴스 = HN Algolia, 133019 논문 = Crossref, 133020 국가 = World Bank, 133021 패키지 = npm, 133022 경제 지표 = World Bank, 133023 보안 권고 = OSV.

---

## (a) 데이터 모델과 수명주기

### a-1. 저장 방식: 1단계는 파일, DB 구조 변경 없음
- **목걸이 정의**: `agent_market/necklaces/definitions/<slug>.json` (git, 리뷰 대상). 사람이 고치는 원본.
- **역할 계약**: `agent_market/necklaces/contracts/<role>.v1.json` (입출력 스키마·검증 규칙·시험 입력 3개).
- **실행 그래프**: 정의에서 만든 **템플릿 워크플로우 1개**(기존 `agent_workflows`, is_template=1). 정의 버전이 바뀌면 새 그래프 → 새 `workflow_versions` digest. 실행·체크포인트·노드 기록·공개 MCP `run_workflow`는 그대로 재사용.
- **대체 사슬**: 기존 `workflow_fallback_policies.payload`(TEXT, 서명)에 v2 형식으로 넣음. `workflow_routing_attempts`의 PK(run_id, node_id, ordinal)는 이미 N개 시도를 담을 수 있음 → **표 변경 없음**.
- **판정 결과(공개 스냅샷)**: `gateway-data/necklaces/necklaces.json` — 성장·유통 계약 형식 그대로. 쓰는 쪽은 백앤드의 jobs 작업(판정), 재시험 결과를 받은 뒤 갱신.
- **재시험·채점 원자료**: `gateway-data/necklaces/results/<slug>/<date>.jsonl`(원자료 먼저 저장), 요약은 스냅샷에.
- 이유: 목걸이 20개 규모에선 파일이면 충분하고, 운영 DB 구조 변경(리허설·승인·4역할 확인)을 1단계에서 피함. 2단계(목걸이 20개 이후·외부 실행이 생긴 뒤)에 필요하면 자기 스키마(`necklace`)에 표를 만드는 안을 따로 올림(public 트리거 불변식 때문에 public에는 만들지 않음).
- 새 조회 SQL은 `application_store_sql.json` 등록이 필요함(구조 변경 아님, frontend+jobs 함께 배포).

### a-2. 정의 형식 (요약)
```json
{
  "slug": "package-risk-audit", "version": 1, "status": "candidate",
  "name": "Package risk audit",
  "summary": "Known vulnerabilities, release health and maintenance signals for one npm or PyPI package, cross-checked across independent sources.",
  "input_schema": {"type":"object","properties":{"package":{"type":"string"},"ecosystem":{"enum":["npm","PyPI"]},"version":{"type":"string"}},"required":["package","ecosystem"]},
  "slots": [
    {"slot":"advisories","contract":"package.advisories.v1","required":true,"fanout":2,
     "chain":[
       {"resource_id":47161,"tool":"osv_query_package","kind":"external","upstream":["osv"],"io_profile":null},
       {"resource_id":286623,"tool":"search_vulnerabilities","kind":"external","upstream":["threatist"]},
       {"resource_id":130453,"tool":"scan_package_cve_advisories","kind":"external","upstream":["unknown"]},
       {"resource_id":133023,"tool":"check_package_advisories","kind":"agentcon","upstream":["osv"]}
     ]},
    {"slot":"release","contract":"package.metadata.v1","required":true,"fanout":1,"chain":[ ... ]}
  ],
  "synthesis": {"kind":"merge-v1","rules":["dedupe_by_id","agreement_mark","conflict_flag"]},
  "budget_ms": {"total": 5000, "slot": 3500},
  "answer_set": "package-risk-audit-v1",
  "baselines": "every external chain member as a single agent"
}
```
- `fanout`: 같은 역할에서 동시에 부를 진주 수(1이면 대체만, 2이면 두 출처를 함께 불러 대조). 같은 역할 fan-out은 "두 출처가 일치" 표시와 놓친 항목 보완(recall)이라는, 단일 진주에 없는 가치를 만듦.
- `required:false` 자리는 끝까지 실패해도 목걸이를 완주로 칩니다(답에 "이 부분 없음" 표시). 완주율에는 필수 자리만 셈.

### a-3. 수명주기

```
candidate → qualifying → trial → live ⇄ held → retired
                                 └→ (새 version) → qualifying
```

| 상태 | 들어가는 조건 | 하는 일 | 나가는 조건 |
|---|---|---|---|
| candidate | 백앤드가 정의 파일 작성 | 자리·계약·사슬 후보 | 계약 파일·정답 세트 준비 |
| qualifying | — | **자리 자격 시험**: 사슬의 각 멤버를 계약 시험 입력 3개로 읽기 전용 호출(실제 경로), 출력이 계약 검증 통과·지연 기록. io_profile 서명(24시간) | 필수 자리마다 외부 멤버 2개 이상 + Agentcon 멤버 1개 이상 통과 |
| trial | — | 정답 세트 90건(조정 30 + 보류 60)으로 목걸이 실행 + 사슬의 외부 멤버 각각을 단일로 실행, 채점 | **종단 성공률 95% 이상**(PM 06:2x·06:3x), Δ > 0, 완주율 95% 이상, 외부만 완주 70% 이상, p95 ≤ 5초(공개 주소·새 연결), 보안 시험 통과. 세부는 reports/necklace-production-2026-11-14/process.md 4절 |
| live | trial 통과 → 운영·SRE 95% 출시 관문 검수 통과(메뉴 적용) | necklaces.json `status: live`, 공개 표면 노출, 매일 재시험 | 아래 보류 조건 |
| held | 자동: 아래 조건 하나 | 표면은 200으로 남기고 실행만 막음(계약 3절) | 원인 해소 뒤 재시험 통과 |
| retired | 대체 목걸이가 live가 되거나 3주 연속 held | 표면에서 내림, 정의는 남김 | — |

**자동 보류 조건(백앤드 판정, 매일 재시험 뒤)**
1. 필수 자리에서 쓸 수 있는 멤버 0개
2. 매일 재시험 Δ ≤ 0 이 2일 연속
3. 완주율이 기준 아래 2일 연속
4. 보안 시험 실패(도구 설명·출력의 지시문 주입 패턴, 쓰기·결제 도구로 바뀜)
5. 재시험 결과가 48시간 넘게 없음(표면 계약의 tested_at 48시간과 같음)

**사슬 정비(보류 아님, 자동)**
- 멤버의 도구 정의 지문이 바뀜(운영·SRE ①) → 그 멤버를 사슬에서 즉시 빼고 다음 순위가 올라감. 백앤드가 새 정의를 검토·재자격 시험 뒤 복귀.
- 멤버가 이틀 연속 재시험 실패 → 빼기. 7일 연속 통과하면 원래 순위로 복귀.
- 자리별 외부 멤버가 2개 아래 → 경보(운영·SRE) + 백앤드가 검색과 RAG에 그 역할의 진주 시험을 요청.
- Agentcon 대체 사용률이 한 자리에서 30% 넘음(7일) → 그 자리 외부 진주를 다시 찾음.

**버전 규칙**: 사슬 순서·멤버 교체는 같은 version(정책 revision만 올림, 재시험으로 확인). 자리·계약·합성 규칙·입력 스키마가 바뀌면 version+1 → qualifying부터.

### a-4. 품질 지표 정의
| 지표 | 정의 |
|---|---|
| 목걸이 성공률 | 정답 세트 30건 중 채점 통과 비율 |
| 최고 단일 성공률 | 사슬에 든 외부 진주 각각을 같은 정답 세트로 단독 실행(같은 채점기)한 성공률의 최댓값 |
| **Δ** | 목걸이 성공률 − 최고 단일 성공률(%p). 과제 유형별로 나눠 함께 보고: ① 여러 측면 과제(구조적으로 단일이 불리), ② 같은 역할 과제(단일 대 fan-out 대조). ②의 Δ도 0보다 커야 공개 |
| 완주율 | 필수 자리가 모두 채워져 유효한 최종 답이 나온 실행 / 실행 |
| 외부만 완주율 | Agentcon 대체를 한 번도 쓰지 않고 완주한 비율 |
| 단계별 성공률·대체 발생률 | 자리별: 1순위로 끝남 / 2순위 이상으로 넘어감 |
| Agentcon 대체 사용률 | 자리 출력 중 Agentcon 멤버가 낸 비율 |
| 1회 비용·지연 | 호출 수, USDC(지금 0), p50·p95(공개 주소·새 연결·처음 보는 입력, 표본 제외 없음) |
| 보안 시험 | 도구 설명 지문 고정 확인, 출력에 든 지시문 패턴은 데이터로만 다룸(합성은 결정적 규칙), 자격 증명·사설 주소 차단(check_public_url) |

**정직성 장치**: 여러 측면 과제만 쓰면 Δ가 저절로 커집니다. 그래서 정답 세트의 절반 이상은 같은 역할 대조 과제로 채우고, 지금 자체 에이전트만 쓰는 워크플로우(28개 중 대응되는 것)의 성공률도 함께 적습니다("외부 진주를 넣어 나아졌나").

---

## (b) 대체 사슬과 기존 fallback 확장

### b-1. 지금 구현에서 그대로 쓰는 것
- pin 조건(`workflow_fallback.py:147-178`): 연결 버전 고정, 도구 승인, 계약 스키마 일치 또는 서명된 io_profile, readOnly·비파괴·멱등 표시, 최근 실행·계약 증거
- 확실한 실패(invalid output·definitive·preflight)일 때만 전환, 불확실하면 전환 안 함(중복 실행 방지)
- 자격 증명 감지 입력은 대체로 보내지 않음, 쓰기·결제·A2A 세션·x402 제외
- 전역 스위치 + 워크플로우별 서명 정책, shadow·canary 단계(켜는 절차는 운영·SRE)

### b-2. 바꾸는 것
| # | 바꿀 곳 | 지금 | 목걸이용 | DB 영향 |
|---|---|---|---|---|
| 1 | 정책 형식 | `pairs[{node, primary, alternate}]` 최대 6쌍 | `workflow-fallback-policy-v2`: `slots[{node, chain:[pin…]}]`. 외부 멤버 최대 6, Agentcon 최대 2(맨 뒤), 순서 검증 | 없음(payload TEXT) |
| 2 | 시도 제한 | 실행 전체 대체 1회(`attempt()` ordinal==2 검사) | 자리별 사슬 길이까지, 실행 전체 대체 시도 상한 = 필수 자리 수 × 3 | 없음. 새 조회 SQL 등록 필요 |
| 3 | 시간 예산 | 주 12초 + 대체 8초 | 마감 기반: 자리 3.5초 안에서 1순위 2초, 남은 시간을 다음 순위가 나눠 씀. 남은 시간 < 0.6초면 중단 | 없음 |
| 4 | 병렬 실행 | 위상 순서로 한 노드씩 | 정의에 `parallel: true`인 그래프만 **웨이브 실행**(부모가 끝난 노드들을 스레드 풀에서 동시에). 체크포인트·fence는 노드 단위 그대로. 기존 워크플로우는 순차 유지 | 없음 |
| 5 | 독립성 | 쌍 단위 같은 호스트·의존성 거부 | 사슬 전체 쌍별 검사. 단 Agentcon 멤버끼리는 호스트 검사 면제, 대신 `upstream`이 서로 달라야 함. 외부와 Agentcon이 upstream을 공유하면(예: osv-advisory ↔ 133023 OSV) 허용하되 "같은 원천" 표시, 그 자리 사슬에 원천이 다른 멤버가 하나 이상 있어야 함. 등록 도메인이 같으면(*.caseyjhand.com, *.openkrill.app) 한 장애 영역으로 셈 | 없음 |
| 6 | 계약 | news.search.v1·docs.search.v1 | 역할 계약 추가(아래 c의 9개). 검증기는 `capability_contracts.validate` 방식(HTTPS 출처, 중복, 최신성 + 역할별 필수 칸) | 없음 |
| 7 | io_profile | 24시간 만료, 수동 시험 | 매일 재시험이 실제 호출로 다시 서명(만료 = 재시험 누락 경보) | 없음 |
| 8 | 제품 승인 | `Products.accept` "정확히 2회 시도" 장애 드릴 | 자리마다 1순위 강제 실패(preflight 모의) → 다음 멤버가 계약 통과하는지 확인, 사슬 깊이만큼 | 없음 |
| 9 | 동의 문구 | `readonly-fallback-v1`: "같은 입력이 다른 검증된 에이전트 1곳으로 갈 수 있음" | `necklace-v1`: "입력이 이 목걸이에 표시된 검증된 에이전트들(대체 포함)로 보내짐". 목걸이 페이지·MCP 도구 설명에 멤버 목록 공개. 동의는 실행마다, 저장 안 함 | 없음 |

### b-3. 실행 흐름(한 자리)
1. 자리 시작: 사슬에서 지금 쓸 수 있는 멤버만 남김(재시험 결과·지문·회로 상태, 요청 경로에서 DB 재확인 추가 없이 정책에 서명된 값 사용 — 속도 원칙)
2. `fanout` 수만큼 앞 순위 멤버를 동시에 호출
3. 확실한 실패면 다음 순위로, 불확실하면 그 멤버는 끝으로 처리(재호출 안 함)
4. fan-out 결과가 하나 이상 계약 통과면 자리 성공. 모두 실패하고 남은 외부가 없으면 Agentcon 멤버(최대 2)
5. 각 시도는 `workflow_routing_attempts`(ordinal 1..N), 자리 결과는 `workflow_routing_decisions`에 기록 → 지표 계산 원천

### b-4. 남의 서버 부하
- 목걸이 1회 = 자리 수 × fanout 호출 + 실패 시 대체. 헤지(자리 p95가 지나면 다음 순위를 함께 호출, Tail at Scale: p99.9 1,800→74ms, 추가 요청 2%)는 1단계에서 하지 않음. 자리별 p95를 2주 잰 뒤, 추가 호출 5% 이하일 때만 2단계에서 켬.
- 매일 재시험은 운영·SRE 인프라가 멤버당 하루 계약 시험 3건 + 정답 세트 실행. 같은 호스트 동시 1, 호출 사이 간격 둠.

### b-5. 역할 나눔
- 워크플로우: 정의·계약·사슬 순위·판정(보류·교체), 정책 v2·웨이브 실행·채점기·necklaces.json 작성기
- 운영·SRE: 매일 재시험 실행, 도구 정의 지문, 켜는 절차(꺼짐 → shadow → canary → 전면), 배포. **넘길 형식**: 재시험 결과는 멤버마다 `{slug, version, slot, resource_id, tool, at, ok, contract_valid, latency_ms, fingerprint, fingerprint_changed, error_class}` 한 줄 JSONL을 `gateway-data/necklaces/retest/<date>.jsonl`에
- 검색과 RAG: 역할별 진주 판정·실행 시험(아래 c-2 목록 우선), Neo4j "같은 역할" 묶음 → 사슬 후보 순위 입력
- 성장·유통: necklaces.json을 읽는 표면(MCP 도구·A2A 기술·페이지)

---

## (c) 첫 목걸이 후보 5개

모두 "여러 출처를 병렬로 조회한 뒤 합성" 모양이고, 자리 사이 순차 의존이 없습니다(입력은 모두 사용자 입력에서 바로 옴). 후보 멤버는 운영 DB에서 MCP·활성·healthy·trial_ok·등급 A인 것 중 도구 이름·필수 입력이 역할에 맞는 것을 골랐고, 도구 표시는 모두 readOnlyHint=true입니다(예외는 따로 적음). **아직 자리 자격 시험 전**이라 순위는 잠정입니다.

### N1. `topic-evidence-brief` — 주제 하나의 논문·배경·최신 뉴스
- 입력: `{topic}` / 출력: 논문 목록(DOI·arXiv id), 백과 요약, 최근 뉴스, 출처 일치 표시
| 자리 | 계약 | fanout | 사슬(순서) | Agentcon |
|---|---|---|---|---|
| papers | papers.search.v1 | 2 | 47151 OpenAlex `openalex_search_entities` → 39577 NobleBlocks `search_papers` → 34550 CutGPT `search_papers` → 34807 Paper Finder `search_papers` → 130450 arXiv digest | 133019(Crossref) |
| background | encyclopedia.summary.v1 | 1 | 47189 Wikipedia `wikipedia_get_summary` → 143970 Faceabot `wiki_summary` | 새로 만듦: Wikipedia REST 요약(키 없음) |
| news (선택) | news.search.v1 | 1 | 147960 Galactic `search_news` → 41195 TechSnif `search_articles`(표시 없음, 검토 필요) | 133018(HN) |
- 정답 세트(30): 기술·과학 주제 30개. 채점: 논문 ≥3건 중 DOI/arXiv id가 실제로 풀리고 주제 관련(관련성은 LLM 채점 + 20% 사람 확인), 백과 요약 제목이 주제와 맞음, 뉴스는 30일 안·HTTPS. 같은 역할 과제 15건: "이 주제의 대표 논문 5개" — 단일 논문 진주 대 fan-out 2개 병합의 정답 재현율 비교(정답은 OpenAlex 인용 상위 + Crossref로 고정 스냅샷).
- 대체하는 기존 워크플로우: 34·38(가장 많이 쓰인 둘, 33+21회), 41·42·43·48·53·54·57·60·61·64

### N2. `package-risk-audit` — 패키지 하나의 취약점·릴리스 상태
- 입력: `{package, ecosystem, version?}`
| 자리 | 계약 | fanout | 사슬 | Agentcon |
|---|---|---|---|---|
| advisories | package.advisories.v1 | 2 | 47161 OSV advisory `osv_query_package` → 286623 Threatist `search_vulnerabilities` → 130453 AgentDiet CVE `scan_package_cve_advisories` → 367249 Fixlane `check_software`(진주) | 133023(OSV), 새로 만듦: GitHub Advisory DB(키 없는 REST) |
| release | package.metadata.v1 | 1 | 50709 Commit 공급망 `lookup_npm_package`/`lookup_pypi_package`(B 등급·표시 없음, 검토 필요) → 40897 Velora `get_package_profile`(확인 필요) | 133021(npm), PyPI JSON 확장 |
- 정답 세트(30): npm·PyPI 패키지@버전 30개(알려진 취약 버전 15, 깨끗한 버전 15). 정답은 OSV·GitHub Advisory를 만든 날 직접 받아 고정. 채점: 권고 id 재현율 ≥ 0.9, 취약한데 "깨끗함" 답이면 실패, 최신 버전 일치.
- 주의: 47161(OSV)과 133023(OSV)은 원천이 같음 → 같은 원천 표시, 원천이 다른 286623·GitHub Advisory가 사슬에 있어야 함.
- 대체: 40·46·47·55·56·62·65 (꺼진 27·35는 정리)

### N3. `country-economy-snapshot` — 국가 하나(또는 둘)의 핵심 지표·환율
- 입력: `{country, compare_with?}`
| 자리 | 계약 | fanout | 사슬 | Agentcon |
|---|---|---|---|---|
| indicators | country.indicator.v1 | 2 | 47130 IMF `imf_query_dataset` → 34791 Country Stats `get_country_indicator` → 37316 Economy Intel `country_indicator` → 33130 dsght `get_country_indicator` | 133022(World Bank 지표), 133020(World Bank 국가) |
| fx | fx.rate.v1 | 2 | 48762 Frankfurter `convert` → 47112 exchange-rates `fx_get_rate` → 226724 FXHUB → 36306 AllRatesToday `get_exchange_rate` | 새로 만듦: ECB 기준환율(키 없음) |
- 정답 세트(30): 국가 30개 × GDP·인플레이션·인구 중 하나(World Bank·IMF 값 고정 스냅샷, 같은 연도·±2%), 환율은 ECB 같은 날 기준 ±0.5%. 같은 역할 과제: 두 출처 값이 어긋나면 "불일치" 표시가 맞는지.
- 주의: 34791(openkrill.app)은 Paper Finder와 같은 등록 도메인. 47130·47112는 caseyjhand.com(같은 발행자) → 같은 사슬에서 한 장애 영역.
- 대체: 39·44·45·52·58·59·63

### N4. `trip-brief` — 도시 하나의 날씨·환율·행사 (성장·유통 계약 예시와 같은 이름)
- 입력: `{city, home_currency?, date_from?}`
| 자리 | 계약 | fanout | 사슬 | Agentcon |
|---|---|---|---|---|
| weather | weather.forecast.v1 | 1 | 37322 Weather & Geo `weather_forecast` → 56036 MET Norway `get_forecast`(표시 없음, 검토) → 38062 get4agent `weather` | 새로 만듦: Open-Meteo(키 없음, 지오코딩 포함) |
| fx | fx.rate.v1 | 1 | N3와 같은 사슬 | ECB(새로 만듦) |
| events (선택) | events.search.v1 | 2 | 115024 Things To Do API `search_events`(진주) → 47538 FestivalFinder(진주, 연도 단위) → 38634 NUM `num_search_places`(진주, 장소) | 없음(선택 자리) |
- 위치 입력(lat/lon)이 필요한 날씨 멤버가 있어 자리 안에 지오코딩 변환(37322 `geocode` 또는 Open-Meteo 지오코딩)을 둠 — 자리 안의 순차라 자리 사이 의존은 없음.
- 정답 세트(30): 대륙별 도시 30개. 날씨는 같은 시각 Open-Meteo 값 ±3°C, 환율 ECB ±0.5%, 행사는 그 도시·기간 안 행사 1건 이상 또는 해당 출처의 coverage에 도시가 없으면 "없음"이 정답.
- 대체: 28(꺼짐)·49·50·51

### N5. `cve-incident-brief` — CVE 하나의 심각도·악용 여부·영향 패키지 (새 목걸이)
- 입력: `{cve_id}`
| 자리 | 계약 | fanout | 사슬 | Agentcon |
|---|---|---|---|---|
| cve | cve.lookup.v1 | 2 | 37259 CVE Security `get_cve` → 286623 Threatist `get_vulnerability` → 47161 OSV `osv_get_vulnerability` | 새로 만듦: NVD API(키 없음, 속도 제한 지킴) |
| exploited | kev.status.v1 | 1 | 55398 CyberMax `cve_kev_lookup` → 286623 Threatist `list_exploited` | 새로 만듦: CISA KEV JSON |
- 정답 세트(30): CVE 30개(KEV 등재 15, 미등재 15). 정답은 NVD·KEV 고정 스냅샷. 채점: CVSS 점수·KEV 여부 정확, 영향 제품 1개 이상, HTTPS 참고 링크.

### c-1. 필요한 역할 계약 11개
papers.search.v1(docs.search.v1 확장), encyclopedia.summary.v1, news.search.v1(기존), package.advisories.v1, package.metadata.v1, country.indicator.v1, fx.rate.v1, weather.forecast.v1, events.search.v1, cve.lookup.v1, kev.status.v1 — 11개 중 기존 1개 재사용, 새로 10개.

### c-2. 검색과 RAG에 요청할 실행 시험(진주 판정 우선순위)
위 사슬의 외부 멤버 31개: 47151, 39577, 34550, 34807, 130450, 47189, 143970, 147960, 41195, 47161, 286623, 130453, 367249, 50709, 40897, 47130, 34791, 37316, 33130, 48762, 47112, 226724, 36306, 37322, 56036, 38062, 115024, 47538, 38634, 37259, 55398. 각 멤버의 "일 도구"(표의 도구 이름)로 실행 보고서를 만들어 주면 진주 판정과 자리 자격 시험을 함께 씁니다. 지금 진주 33개에 든 것은 367249·115024·47538·38634 4개뿐입니다.

### c-3. 새로 만들 Agentcon 대체 에이전트 (모두 키 없는 공개 원천, 지출 0)
Wikipedia 요약, GitHub Advisory, ECB 환율, Open-Meteo 날씨, NVD CVE, CISA KEV — 6개. 기존 owned_data_agents 틀(`catalog.py` SPECS, 같은 MCP 엔드포인트 형식)로 만들고 자원 등록은 기존 `activation.install`.

---

## (d) 기존 워크플로우 33개 정리안
| 처리 | 대상 | 방법 |
|---|---|---|
| 목걸이로 다시 만듦 | N1: 34·38·41·42·43·48·53·54·57·60·61·64 / N2: 40·46·47·55·56·62·65 / N3: 39·44·45·52·58·59·63 / N4: 49·50·51 | 대응 목걸이가 live가 된 날, 옛 공개 워크플로우를 비공개(is_active=0)로. 삭제하지 않음. 공개 주소는 목걸이로 안내 |
| 내림 | 27(외부 1개 + A2A 물리 작업 GetBody 61333 — 읽기 전용 원칙과 맞지 않음), 28(항공권·환율 순차), 35(Capacitor 같은 진주 2회), 36(Padel 같은 진주 2회) | 이미 꺼짐. 그대로 두고 목록에서 제외 |
| 남김 | 없음(모든 공개 워크플로우가 목걸이 하나에 대응) | — |
- 옛 워크플로우를 비공개로 바꾸는 것은 운영 DB 데이터 변경(구조 변경 아님)이라 PM 확인 뒤 운영·SRE와 함께 실행합니다.

## (e) 일정 (11-28 목걸이 5개)
| 기간 | 백앤드 | 다른 팀 |
|---|---|---|
| 11-14~16 | 역할 계약 10개, 정의 파일 5개, 정답 세트 생성기(고정 스냅샷), 자리 자격 시험 스크립트(읽기 전용) | 검색과 RAG: c-2 실행 시험 |
| 11-16~19 | 정책 v2·자리별 다중 시도·웨이브 병렬 실행(기존 순차 워크플로우 무변경 시험 포함, SQLite·PG 둘 다), Agentcon 대체 6개 | 운영·SRE: 지문 ①, 재시험 형식 맞춤 |
| 11-19~22 | trial: 목걸이 대 단일 채점, necklaces.json 작성기(jobs) | 성장·유통: 표면 시험 |
| 11-22~25 | 판정·보류 자동화 | 운영·SRE: shadow → canary |
| 11-25~28 | live 5개(Δ > 0인 것만), 옛 워크플로우 정리 | 성장·유통: 공개 |
- Δ ≤ 0인 후보는 공개하지 않고 사유를 적습니다. 5개 미달이면 그대로 보고합니다.

## (f) PM 결정 필요
1. **저장 방식**: 1단계 파일(정의·스냅샷) + 기존 표 재사용, DB 구조 변경 없음 — 이대로 진행해도 되는지(권장).
2. **읽기 전용 기준**: 지금 pin은 readOnly·비파괴·멱등 표시 3개를 모두 요구. 후보 대부분은 readOnlyHint만 있음. 목걸이 사슬은 "readOnlyHint=true + destructiveHint≠true"로 받고 멱등은 읽기 전용에서 따른다고 볼지(권장), 아니면 지금 기준 유지(후보 대부분 탈락). 표시 없는 멤버(41195·56036·50709)는 어느 쪽이든 제외.
3. **안정성 관문과의 관계**: 현황판 관문(닫힘)은 "새 기능 동결"인데, 목걸이는 11-14 사용자 전략의 핵심 과제. 관문 뒤로 미루지 않고 진행해도 되는지(개발·시험은 사본에서, 공개는 차선 목표 측정과 겹치지 않게).
4. **옛 공개 워크플로우 비공개 전환**(d 표): 대응 목걸이 live 날 is_active=0, 삭제 없음.
5. **공개 동의 문구 `necklace-v1`**(b-2 #9): 공개 문구라 성장·유통 검토 포함.
