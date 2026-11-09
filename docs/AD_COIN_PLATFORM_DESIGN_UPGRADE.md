# AI AD Coin 최신 조사 기반 설계 보강 v6.2

2026-11-07 · 정책 기준은 v6.1 유지 · 추가 개발 설계이며 구현 완료가 아님

## 1 개정 범위와 근거

[플랫폼 아키텍처](AD_COIN_PLATFORM_ARCHITECTURE.md), [데이터·API](AD_COIN_PLATFORM_DATA_API.md), [개발 작업](AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md)을 보강한다. 초기 공급 0·실입금 기반 발행·승인 노출 독립 보상·사용자 귀속 지갑·담보/수탁 불변식은 바꾸지 않는다. [v6.2 기계 명세](ad_coin_platform_v6_2_spec.json)와 [P1 계약](ad_coin_platform_p1_v6_2.openapi.json)이 현재 개발 계약이며 이전 v6.1 기계 파일·검증 기록은 보존한다.

핵심 변화는 광고 정보를 통한 판단 유도에 대한 근거 검증, 프로토콜·인증 버전 고정, 매체 전반의 사용자 한도, 원본 보고·정정·누락 구분, 실행 비용 상한, 철회와 대기 작업의 경쟁 처리, 검증 가능한 영수증이다. 상세 출처와 접근 한계는 [조사 기록](../reports/ad-coin-design-upgrade-v6.2-2026-11-07/README.md)에 둔다.

- [Agent Ads 연구, 2026-10-12](https://arxiv.org/abs/2610.17195)는 겉으로 규칙을 따르는 상품 설명과 외부 자료로 에이전트 선택을 유도하는 공격을 다룬다. 키워드·명령문 탐지 외에 독립 근거 검증을 설계한다. 본문 일부와 초록을 확인했으며 실험을 재현하지 않았다.
- [AdSteer, 2026-11-03](https://arxiv.org/abs/2611.04147)와 [AdsWorldEngine, 2026-08-13](https://arxiv.org/abs/2608.13833)의 생성·대화형 광고 방향을 재검토했다. 광고의 유용성 판단과 비용을 명시적으로 다루되 독립 답변에 숨은 광고 영향을 넣는 방식은 채택하지 않는다.
- [AdCP 3.2 변경 원문](https://github.com/adcontextprotocol/adcp/blob/main/docs/reference/whats-new-in-3-2.mdx)은 통합 빈도·보고 상태·측정 관계를, [버전 규칙](https://github.com/adcontextprotocol/adcp/blob/main/docs/reference/versioning.mdx)은 3.3 beta 및 변경 경계를 설명한다. Reliable Reporting의 실험 상태와 stable/beta를 구분하며 아래 구조는 AI AD Coin 자체 계약이다. 외부 AdCP 적합성 인증이나 표준 완성본이 아니다.
- [PubMatic 2026-08-05 발표](https://pubmatic.com/news/pubmatic-launches-governance-architecture-for-agentic-advertising-on-agenticos/)의 실행 단계 통제와 [11월 4일 업계 보도](https://ppc.land/shelly-palmers-4-questions-sort-real-ai-agents-from-rebranded-chatbots/)·공개 SNS의 승인/책임 논의를 참고했다. 회사 발표·의견을 독립 보안 검증이나 우리 제품 효과로 전용하지 않는다.

## 2 DEC-08 프로토콜 기능과 인증을 각각 고정

`adc2_adapter_profiles`에 protocol_name, exact_wire_version, schema_digest, adapter_build_digest, supported_features, experimental_features, signing_profile, key_resolution_profile, audience_rules, conformance_evidence, approved_at, expires_at을 보관한다. main 브랜치·검색 결과·SDK 버전 하나만으로 상대 프로토콜을 추론하지 않는다. SDK·wire·서명 profile은 다른 버전 축이다.

연결 시 상대 기능을 제한된 크기·깊이·시간으로 조회하고 이미 승인한 profile과 교집합만 사용한다. 처음 보는 기능·버전·서명은 무조건 더 강한 것으로 간주하지 않는다. 인식한 정확한 schema hash와 일치하지 않으면 재검증하거나 그 기능을 닫는다. 인증 실패 후 익명/다른 인증으로 재시도해 자금 집행으로 들어가지 않는다.

Web Bot Auth 관련 RFC·beta 전환은 진행 중인 논의로 취급한다. origin/key를 증명하는 것과 광고주 계정·매체 판매·사용자 지출 권한은 별도다. MCP session ID, A2A task ID, 서명된 origin만으로 광고주 계정을 자동 생성하거나 금융 권한을 부여하지 않는다. 개설은 명시적 account provisioning 명령과 권한을 요구한다.

R0는 외부 어댑터를 비활성으로 선언하고 플랫폼 고유 P1 계약만 제공한다. 추후 외부 연결을 열 때 profile 적합성·키 교체·폐기·양방향 callback·서명 범위·크기 제한·SSRF·계정 인가 시험을 추가한다. 이 문서는 특정 beta·최신 patch가 이미 지원된다고 선언하지 않는다.

## 3 DEC-09 광고 주장과 독립 근거의 경계

`adc2_claim_provenance`는 product_pack_revision, claim_id, claimant_principal, claim_kind, cited_source, source_control_relation, observed_at, expires_at, independent_evidence_ref, verification_state, verifier_version을 갖는다. 광고주·그 계열·중계자가 제공한 문서 여러 개를 독립 출처 여러 개로 세지 않는다. 웹 문서 개수·검색 노출 순위·내용 hash만으로 진실성을 보증하지 않는다.

광고 자료에서 유래한 새로운 위험 주장·경쟁사 비방·생소한 평가 기준은 검증 작업으로 격리한다. 검증하지 않은 주장으로 경쟁사의 일반 추천 등급·안전 등급을 낮추지 않는다. 독립된 검증 자료가 없으면 미확인으로 표시하고, 위험 업종·효능 주장은 해당 심사 규칙에 따라 제한한다. 외부 자료의 검색·요약은 M02 심사 권한이며 원장/지갑 권한이 아니다.

원본 사용자 작업의 품질 평가와 광고 소재의 주장을 다른 입력 채널·모델 호출·저장소 권한으로 분리한다. 일반 추천 adapter는 광고주가 제출한 ‘경쟁사 위험 점수’를 읽지 않는다. 검색 보강 모델이 광고 팩의 지시나 분류 기준을 정책으로 승격시키는지 회귀 시험한다. 이 검사는 표시된 광고의 사실 검증을 강화하는 것이며 광고 수신·브랜드 상담 자체를 금지하는 정책이 아니다.

## 4 DEC-10 전역 사용자 한도와 자동화 비용

`adc2_attention_windows`와 `adc2_attention_reservations`에 owner, scope, budget_window, reserved_sessions, started_sessions, accepted_exposures, reserved_view_ms, observed_view_ms, version을 둔다. scope는 사용자 전체·광고주·캠페인을 포함하고 필요한 행을 고정 순서로 잠근다. 같은 사용자의 여러 에이전트·캠페인도 사용자 전체 상한을 넘지 못한다. 사용자 전체와 캠페인별 상한은 동시에 적용한다.

offer 발급의 짧은 자금 hold와 별도로 노출 시작 시 사용자 횟수·시간을 예약한다. 첫 버전의 활성 광고 화면 상한은 참조값 30초이며 증거 제출 TTL 600초와 구분한다. 완료·취소·기한 종료 때 실제 관측 사용량을 적용하고 남은 예약을 반환한다. 부정확한 신호는 보수적으로 제한하되 실제 사람이 봤다고 청구하거나 보상을 확정하는 근거로 바꾸지 않는다. 세션 시작 횟수와 적격 노출 지표는 별도다.

owner가 확인되지 않는 외부 호출은 사용자 한도 보장·순도달·P1 사람 보상에 포함하지 않는다. B1 등 별도 기계 상품으로 처리하거나 거부한다. 외부 서비스에서 무단 식별자를 수집해 ‘전역 사용자’ 식별을 확대하지 않는다. 삭제·철회 뒤의 개인정보 처리와 사기/금전 dedup 보존 근거도 분리한다.

`adc2_execution_cost_budgets`는 payer_operating_account, accounting_unit, total_limit, committed_cost, actual_cost, tool/token/model_call ceilings, expires_at을 가진다. 도구·모델 호출 전 비용과 횟수를 예약하고 응답 후 실비와 미사용분을 대사한다. 단가가 불명확하거나 도구 재귀·retry가 상한을 넘으면 새 호출을 중지한다. 고객 약정 보상과 준비금으로 운영비 부족을 보충하지 않는다. 이미 약속한 보상을 운영비 증가 때문에 삭감하지 않는다.

R0에서는 외부 모델·유료 도구 호출을 비활성으로 두고 비용을 0으로 표시한다. 실제 소재 생성·브랜드 상담·최적화 도입 시 확인된 운영 재원과 가격 계약을 별도로 요구한다. 토큰 수·긴 상담·호출 수 증가를 광고 성과로 판매하지 않는다.

## 5 DEC-11 보고 의무와 값의 의미

`adc2_reporting_obligations`는 campaign/account, period_start/end, timezone, expected_at, recovery_deadline, metric_contract_hash, state를 가진다. 예정된 보고 창을 먼저 만들기 때문에 누락된 보고가 분모에서 사라지지 않는다. 상태는 waiting, available, delayed, action_required이며 ‘내용이 0’과 다르다.

`adc2_report_revisions`는 obligation_id, revision, content_digest, generated_at, data_through, method_version, vendor_id, vendor_relationship, supersedes_id, rows_ref, completeness를 가진다. first_party/affiliated/third_party/undeclared를 구분한다. 측정 주체와 관계 표시는 독립성·정확성 인증이 아니다. 보고서 정정은 새 revision이며 원래 지급 원장을 다시 실행하지 않는다.

각 metric은 value와 `measured/estimated/not_measured/suppressed` 상태, 단위·분모·방법을 함께 반환한다. 값이 없는 상태를 0으로 채우지 않는다. 관측된 0은 measured+0이며 개인정보 억제는 suppressed+null이다. 순도달과 매체별 도달 합계를 다른 metric으로 둔다. 비율은 필요한 분모가 없거나 0이면 미정의 상태로 반환한다.

`adc2_report_consumption`은 authorized_consumer, revision_id, digest, received/missing/unreadable/content_mismatch, observed_at을 보관한다. webhook은 특정 obligation/revision/operation과 audience에 결속하고 GET으로 같은 revision을 복구할 수 있어야 한다. 수신 ACK·보고 동의는 청구 승인·사용자 노출·가맹점 결제 완료가 아니다.

R0 보고 API는 UTC의 P1 원장/검증 사건만 제공한다. CTR·외부 매출·증분 효과 등 아직 수집하지 않은 지표를 0 또는 실측값으로 만들지 않는다. 캠페인 운영자는 누락·지연·정정 상태와 플랫폼 자체 측정이라는 사실을 확인할 수 있다.

R0의 고유 수 지표는 `unique_owners`로 명명하고 계정 권리자 기준임을 방법에 표시한다. 이를 독립 검증된 고유 사람 도달로 바꾸어 부르지 않는다. 매체 간 사람 도달 추정은 별도 근거·방법·불확실성을 갖춘 후속 지표다.

## 6 DEC-12 대기 작업의 권한과 결과 불명

outbox에 authorization_snapshot_hash, principal_epoch, grant_epoch, aggregate_revision, dispatch_intent_id, lease_generation을 추가한다. 작업자는 lease와 단조 증가 generation을 얻은 뒤 최신 권한·중지·campaign/grant version을 다시 검사한다. DB 변경과 서명 요청은 현재 generation을 제시해야 하며 lease를 잃은 작업자의 후속 쓰기를 거부한다.

철회와 dispatch 승인의 선형화 지점은 **같은 DB에서 최신 epoch를 확인하고 dispatch intent를 커밋하는 시점**이다. 철회 이후에는 새 dispatch intent를 만들지 못한다. 이미 커밋되어 송신 중인 외부 요청은 원격 도착을 완전히 회수할 수 없으므로 in_flight 또는 unknown으로 추적한다. 가능하면 취소를 요청하고, 조회·원본 사건 ID·대사로 결과를 확인한다. timeout이나 철회만으로 재원을 풀고 새 ID로 같은 지급을 보내지 않는다.

원격 시스템이 멱등 키를 지원하면 논리 업무 ID를 그대로 전달한다. 지원하지 않으면 조회·원본 거래 결속·운영 한도를 검증하기 전 자동 재집행을 열지 않는다. generation은 외부 중복 지급 방지의 대체물이 아니다. 유효한 작업이 끝나도 정책·철회 확인이 필요한 다음 단계는 새 검사를 거친다.

## 7 DEC-13 영수증과 사람 승인 계약

첫 P1의 광고 보상 영수증은 버전 고정 JWS compact로 제공한다. header는 승인된 typ·alg·kid만 쓰고 EdDSA를 사용할 때 Ed25519 key로 제한한다. `none`, 대칭 키로의 알고리즘 혼동, 임의 `jku/x5u` 원격 키 조회는 거부한다. issuer·audience·token type은 인증용·fresh action용 토큰과 분리한다. 검증 키는 고정된 신뢰 경로의 `/receipt-keys`에서 해석하며 receipt의 issuer URL을 따라 임의 요청하지 않는다.

서명 payload는 receipt_id, offer_id, stage, asset_id, 지급량, quote hash, 정책/계약 버전, issuer, audience, 발급 시점을 결속한다. 검증자는 서명 payload와 화면/JSON의 표시 필드가 일치하는지도 확인한다. pending은 서명 없음으로 반환하고 signed 상태는 kid·JWS를 필수로 요구한다. 회전·중지·침해된 key의 검증 기간과 상태를 공개하되 과거 권리·분개를 삭제하지 않는다. 폐기 키로 새 영수증을 발급하지 않는다.

fresh action은 서버가 렌더링한 정확한 동작·대상·보상·기한과 semantic digest를 결속한다. 단순 nonce echo나 로그인만으로 사람의 실제 시청/의도를 증명한다고 표현하지 않는다. 사람 세션·CSRF·Origin·권한·일회 challenge를 기본으로 하고 고위험 금전 행위는 독립적인 step-up을 요구한다. 서비스 토큰이나 보상 영수증은 어떤 경우에도 fresh action proof가 아니다. JSON 중복 key·필드 대소문자 혼동·잘못된 content type은 정규화 전에 거부한다.

기술 근거로 [JWT BCP RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html)의 알고리즘·issuer/audience·토큰 용도 분리를 참고한다. 이 표준은 최신 뉴스가 아니며 안전한 구현을 위한 기존 근거다. 실제 서명·보유 키·브라우저 승인 검증은 후속 구현에서 수행한다.

## 8 추가 설계 인수 기준

아래 DES-01~10은 기존 GROW-01~28과 v5 43개에 **추가할 미실행 제품 검수**다. 문서 검사 횟수를 제품 검수 통과로 합산하지 않는다.

- **DES-01:** 프로토콜·schema·기능·서명 profile 고정, beta 거부/격리, discovery 크기·SSRF·인증 fallback·계정 자동 개설 차단. WP-01·07·12; PLAT-04·05·20·30.
- **DES-02:** 광고주 통제 출처의 가짜 독립성·새 평가 기준·경쟁사 위험 주장·검색 보강을 이용한 판단 유도를 심사하며 일반 추천에 섞이지 않는다. WP-03·04·08·10; PLAT-05·08·10·31·32·37.
- **DES-03:** 같은 사용자의 동시 세션·여러 에이전트·캠페인에서 전체/캠페인 횟수·시간을 원자적으로 지키고 unknown owner를 사람 도달로 표시하지 않는다. WP-02·04·07; PLAT-11·13·17·18·37.
- **DES-04:** 모델·도구·retry·재귀 비용 상한과 운영 재원 예약·실비 대사를 검증하고 약정 보상·준비금을 침범하지 않는다. WP-02·08·10; PLAT-14·15·22·24·33.
- **DES-05:** 누락 보고·측정 0·미측정·억제·추정·정정을 구분하고 시간대·방법·측정 관계·순도달을 일관되게 보고한다. WP-09·11; PLAT-13·19·28·34·36.
- **DES-06:** webhook 누락·역순·중복·key 회전·내용 불일치에서 같은 불변 보고 revision을 조회·대사하며 ACK로 결제하지 않는다. WP-09·12; PLAT-13·17·20·29·34.
- **DES-07:** lease 만료·동시 worker·권한 철회·중지·서버 종료 사이에서 stale generation 쓰기·철회 후 새 dispatch·타임아웃 재지급을 차단한다. WP-01·02·06·10·12; PLAT-02·15·23·29·37.
- **DES-08:** 영수증의 alg/kid/issuer/audience/type·payload/표시 불일치·침해 key·pending 서명 상태를 검증하고 영수증을 승인/인증 토큰으로 재사용하지 않는다. WP-01·04·06; PLAT-12·18·20·23·30.
- **DES-09:** 중복 JSON key·인증 혼합·nonce echo·stale digest·CSRF·토큰 용도 혼동을 거부하고 실제 사람 집중에 대한 미증명 한계를 유지한다. WP-01·04·12; PLAT-02·11·17·18·37.
- **DES-10:** 신규 계약의 구버전·기능 상태·정정·R0 비활성을 검증하고 업그레이드가 자산·확정 보상·지갑 소유권을 바꾸지 않는다. WP-02·03·04·07·12; PLAT-02·04·12·23·30·38.
