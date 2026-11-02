# 개선 설계서 2.0 — 소스 변경 영향 검토

2026-10-26 KST · 설계 원문은 보존 · 운영 적용 여부를 새로 검증한 보고서 아님

## 결론

**2.1 현행화가 필요하다. 사업 방향과 기존 IMP-01~08의 전체 재설계는 필요하지 않다.** 일부 구현된 기능을 미구현으로 남겨두면 중복 개발이 발생하고, 합성 검증·운영 반영·실제 업무 성공을 섞으면 완료 범위를 과장하게 된다.

[설계서 2.0](../../docs/AGENT_CONCIERGE_BUSINESS_PRODUCT_IMPROVEMENT_2026-10-25.md)의 기준 소스 21개를 내용 hash로 비교했다. **변경 6개, 동일 15개**다. 이는 저장소 전체의 변경 파일 수가 아니다. 추가로 관련 모듈 13개를 검토에 포함했다. 이 추가 파일들은 원래 21개 비교 대상이 아니므로 모두 설계 작성 후 새로 생긴 파일이라고 단정하지 않는다.

기존 위험 14개의 재분류는 **부분 구현 6개 / 현황 설명 보완 1개 / 유지 7개**다. 완전 해결·운영 검증 완료로 종결한 항목은 없다. 아래 ‘부분 구현’은 남은 검증을 없애라는 뜻이 아니라 **구현을 재사용하고 잔여 조건을 좁히라**는 뜻이다.

## 수정해야 하는 내용

### 1. 검색 구현 상태: SR01·SR02 / IMP-02

- [postgres_ann.configure_scan](../../agent_market/postgres_ann.py)은 pgvector 버전을 확인하고 0.8 이상에서 제한된 `strict_order` iterative scan을 사용한다. 5,000개 탐색·메모리 배수 1·`SET LOCAL` 경계가 생겼다. 설계서의 ‘도입 후보’를 **구현됨, filtered recall 검증 필요**로 바꾼다.
- [discovery.candidates](../../agent_market/concierge/discovery.py)는 원문/긍정 목적/제외 조건을 분리하고, 정확한 이름의 최신 검증 shortcut을 제공한다. 다만 shortcut은 초기 lexical 후보를 이용하며, `last_ok_at` 순 `LIMIT 300`과 ANN 후보 상한도 남아 있다. 전문 agent가 초기 후보 밖에 있는 경우까지 해결됐다고 종결하지 않는다.
- [capability_retrieval](../../agent_market/concierge/capability_retrieval.py)에 내용 hash 기반의 불변 Tool projection cache가 있다. 후보·query·사용자·권한 결과 cache와 구분해 재사용한다.
- [retrieval_policy](../../agent_market/concierge/retrieval_policy.py)는 상위 40개·30ms 예산의 구조적 재정렬을 제공한다. 기본값은 **Shadow**이고 cross-encoder가 아니다. 새 모델 도입이나 전체 순위 교체를 이미 완료한 것으로 쓰지 않는다.

잔여: exact eligible 기준 recall, 선택도·실제 규모별 지연, 후보 절단, 현재 자격·권한 검사 보존. 기존 EX01을 ‘도구 새로 개발’에서 ‘현재 구현과 exact 기준 비교’로 바꾼다.

### 2. 실제 Chat 경로 설명: SR03 / IMP-04

[FastConcierge](../../agent_market/concierge/fast_chat.py)는 그대로다. bounded query intent 처리·검색 관측·compact adapter가 추가로 연결돼 있다. ‘일반 RAG 답변 함수를 바꾸면 공개 Chat이 개선된다’는 접근은 여전히 적절하지 않다.

설계서에는 현재 Fast 경로·query 해석·compact/REST/MCP/A2A의 공유 경계를 그린다. 생성 모델 기반 요구 추출은 **선택적 후속 실험**으로 남기고 현재 모든 요청에 모델을 호출한다고 설명하지 않는다.

### 3. 품질 관측: SR06·SR11 / IMP-01·03·06

[retrieval_metrics](../../agent_market/concierge/retrieval_metrics.py)와 [search_quality](../../agent_market/search_quality.py)가 단계별 처리시간·후보 수·cache/재정렬/보정 건수와 역할별 snapshot을 제공한다. 어드민에는 ‘탐색·생성 품질’ 화면이 구현됐다.

이를 신규 관측 플랫폼 구축 과제에서 제외한다. 대신 현재 프로세스 세대·최대 2,048개 지연 표본·최대 30초 저장 간격·best-effort 전달을 명시한다. 이 값은 24시간 네트워크 SLA, 독립 업무 품질, 실제 고객 만족을 뜻하지 않는다. 생성·embedding·DB·외부 provider의 전역 입장 예산과 혼합 부하 검증은 계속 필요하다.

### 4. Workflow query 보정: SR08·SR12 / IMP-02·06

[workflow_plan_repair](../../agent_market/workflow_plan_repair.py)는 지원되는 명확한 공개 영어 목적에서 검색 주제 누락이 생긴 경우, 원래 목적에서 query를 한 번 재구성하고 엄격한 compiler 검사를 다시 수행한다. 추가 모델 호출이나 임의 graph 수정을 하는 기능이 아니다.

이 한정 보정은 기존 자산으로 반영한다. 전체 edge 의미·최종 업무 목적의 검증과는 구분한다. 기존 순차 계획의 `items[0].title → 다음 query` 바인딩이 보편적인 조사·종합 작업을 완성한 것으로 처리하지 않는다.

### 5. 기계용 접점과 승인·변경 추적: 4·6.4·9장 보완

2.0의 자산 설명은 현재 기능을 충분히 담지 못한다. [agent_access/service](../../agent_market/agent_access/service.py), [catalog](../../agent_market/agent_access/catalog.py), [tasks](../../agent_market/agent_access/tasks.py), [events](../../agent_market/agent_access/events.py) 및 [별도 상세 설계](../../docs/AUTONOMOUS_AGENT_ADOPTION_DESIGN.md)를 연결해야 한다.

- `/mcp/compact` 고정 5개 도구와 작은 공개 OpenAPI.
- 호출 없는 입력 준비, 고객의 정확한 입력 공유 승인, 제한된 단일 실행 grant.
- 현재 상태를 재검증하는 변경 ledger/feed와 별도 동의 기반 의존성 watch.
- 얇은 client와 배포 metadata, 제한된 불변 schema cache.

이 기능들을 새 master router·두 번째 SDK·새 event DB로 다시 설계하지 않는다. 기존 보고서는 사용자 운영 반영 후 **읽기 스모크 37건**을 기록하지만, 이번 검토에서 현재 서버를 재점검한 것은 아니다. 이 기록은 외부 host 설치, Registry 게시, 실제 고객/provider 실행·발송의 완료 증거가 아니다. [개발·검증 기록](../agent-adoption-development-2026-10-25/README.md)

## 계속 유지해야 하는 항목

- **SR04:** 유효한 형식과 업무 goal/source 성공을 구분. 해당 helper·계약 소스는 동일하다.
- **SR05:** OAuth 만료·재연결·선택 refresh 수명주기. 해당 연결 모듈은 동일하다.
- **SR07:** 현재 provenance·model/source/generation·권한 gate를 보존. 새 cache를 권한 원본으로 사용하지 않음.
- **SR09:** 처리시간/오류 관측과 독립 평가자·source 검증을 구분. 어드민 품질 화면 추가만으로 독립 검증이 완성되지 않음.
- **SR10:** 내부 HMAC과 공개 Ed25519의 역할·제한·동의를 유지.
- **SR13:** provider OAuth/API 키 저장과 범용 인증 workflow 실행을 구분. compact의 고객 실행 grant는 provider credential 연동 완료와 다름.
- **SR14:** `QualityRecommender.search` 자동/Any 분기의 선택 조건 전달 누락이 남아 있다. 관측 decorator를 우회한 격리 method-spy에서 `category`, `auth_pref`, `hint`가 다음 메서드에 전달되지 않음을 재확인했다. 이 결과를 공개 화면 전체의 필터 장애나 실행 권한 우회로 확대하지 않는다. [확인 결과](selection-probe.json)

## 검증 자료의 해석도 수정해야 함

[품질 후속 개발 보고서](../discovery-quality-phase2-2026-10-26/README.ko.md)와 [최종 검증 요약](../discovery-quality-phase2-2026-10-26/validation-summary.json)에 기록된 변경 소스 **20개 모두 현재 hash와 일치**했다. 기록에는 별도 PostgreSQL 18의 GIN/HNSW 검사, 합성 300개 사례의 Off/On 비교 600건 통과, 기능/API/보안 회귀 473개 및 브라우저 6개 통과가 있다. 이 숫자는 기존 기록이며 이번에 모두 다시 실행한 결과가 아니다.

주의할 차이:

1. [평가 스크립트](../../scripts/evaluate_search_workflow_quality.py)는 9개 검색 family·40개 기초 prompt의 표현 변형과 workflow 조건 변형을 포함한다. ‘독립적인 실제 업무 300개’ 또는 ‘실제 provider 600회 성공’으로 재해석하지 않는다.
2. 기본 검색 합격 조건은 기대 family의 agent가 상위 3개에 포함되는지 등이다. 이것만으로 exact ANN Recall@k, 전체 순위의 nDCG, 출처 사실성, 사용자 업무 완료까지 입증하지 않는다.
3. 기록의 작은 합성 카탈로그에서 Chat p95는 Off 27.2ms, On 50.2ms다. 운영 성능 차이나 통계적으로 확정된 인과 효과는 아니지만, ‘On이 무조건 빠르고 좋다’고 쓸 근거도 없다. Shadow 유지 결정과 추가 품질·지연 검증 조건을 보존한다.
4. query 보정의 실제 모델 표본 4개는 서버 schema 지원 전수 검사나 운영 성공률이 아니다.
5. 보고서는 당시 `discovery-quality-20261026-r1` 패키지 준비와 미전환을 기록한다. 이번 검토로 현재 운영 배포 상태까지 확인한 것은 아니다. 문서에는 **구현 / 격리 검증 / 패키지 준비 / 운영 반영 확인 / 실제 업무 수용**을 나눠 적는다.

이번 추가 확인은 기존 영향 검사 **15개 통과, 1개 선택 제외**다. 캐시·버전별 ANN 설정·Shadow 순서 보존·제한 보정·개인정보 없는 관측·관측 실패 격리를 다뤘다. 실제 DB 색인 부하·브라우저·운영 요청은 다시 수행하지 않았다. [로그](targeted-regressions.log), [JUnit](targeted-regressions.xml)

## 2.1에 반영할 권장 범위

1. **4·6.4·9장:** compact/준비·grant/feed/watch/client와 기존 자율형 상세 설계의 연결.
2. **10·19·20장:** ANN·Tool projection·Shadow 재정렬·실제 검색 경로의 현황과 잔여 위험.
3. **7·13·22장:** 관측 범위·합성 표본의 상관·실제 업무/출처/성능 수용 기준의 분리.
4. **19·21장:** bounded query repair의 재사용과 전체 workflow 의미·provider credential 실행의 잔여.
5. **14·23·24·27장:** IMP/EX별 구현·증거·잔여·운영 반영 상태와 source snapshot 갱신.

사업 포지션·초기 세 업무·BYOK 우선·조건부 결제·기존 보류를 이번 소스 검토로 변경할 이유는 확인되지 않았다. 결제·수익화 전체 코드나 저장소 전체의 무관한 변경을 전수 재감사했다는 뜻은 아니다.

**권장 후속 순서:** 현재 자산·상태 현행화 → SR14 선택 조건 보존 → filtered recall/후보 절단 → 전체 업무 의미/인증 실행 profile → 운영 수용 증거. 기존 완료 기능을 다시 만드는 계획은 제외한다.

## 이번 검토의 범위

2.0 원문과 기존 기준 hash는 그대로 보존했다. 이 문서는 **수정 필요 여부와 구체적인 수정 범위의 검토 결과**다. 제품 소스·DB·배포·서버·기존 승인/보류는 변경하지 않았다. 원장과 source hash는 [review.json](review.json)에 있다.
