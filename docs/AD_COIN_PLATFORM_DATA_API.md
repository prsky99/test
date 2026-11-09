# AI AD Coin 데이터와 API 개발 계약 v6.2

> 최신 조사에 따른 [v6.2 보강 설계](AD_COIN_PLATFORM_DESIGN_UPGRADE.md)의 DEC-08~13·DES-01~10을 함께 적용한다. 최상위 사업 정책은 v6.1을 유지하며 이전 기계 계약은 역사본으로 보존한다.

2026-11-07 · [플랫폼 개발 설계](AD_COIN_PLATFORM_ARCHITECTURE.md)의 구체 계약 · 모든 표·v2 경로는 신규 개발 대상

## 1 공통 데이터 규칙

PostgreSQL의 명시적 migration으로 `adc2_` 표를 추가한다. 아래는 논리 스키마이며 실행용 DDL이 아니다. 실제 migration에는 NOT NULL·FK·CHECK·유일 키·권한·인덱스·다운그레이드 영향을 모두 포함해야 한다. 초기 버전은 하나의 쓰기 DB에서 원장·예산·승인·업무 상태를 원자적으로 조정한다.

모든 객체는 UUID ID, environment, 생성 시각, version을 가진다. 고객 자료에는 tenant/owner 경계를 명시하고 복합 FK와 조회 조건으로 경계를 강제한다. 다른 tenant의 객체 ID를 알고 있어도 접근할 수 없다. 조직에 속하지 않는 사용자 자산에는 별도 개인 owner가 있으며 광고주 tenant와 소유자를 혼동하지 않는다. 관계가 필요한 경우 share grant에 목적·필드·기한을 명시한다.

시각은 DB `timestamptz`와 API UTC RFC3339다. 캠페인의 예산 시간대·하루 시작은 계약 revision에 고정한다. 금액은 asset_id와 `NUMERIC(78,0)` 최소 단위 정수로 저장하고 API에는 10진 정수 문자열을 쓴다. 비음수 uint256 상한은 별도 CHECK와 애플리케이션 검증으로 제한한다. 소수·지수 표기·선행 0·bool·float·암묵적 KRW 환산을 거부한다. 분개 delta만 부호를 허용하며 beneficial account의 잔액은 0 이상이다.

자산 식별 `(environment, chain_id, token_contract)`은 불변이다. 가상 모형 자산은 `model` namespace로 분리하고 chain_id·계약을 null로 명시한다. 실제 체인 자산과 같은 asset_id를 공유하지 않는다. policy revision은 자산 식별자가 아니다. 모든 금전 FK는 같은 asset_id를 보장하며 서로 다른 자산을 상계하지 않는다.

계약 revision은 canonical JSON hash를 가진 불변 객체다. 문자열 정규화·허용 필드·정렬·숫자 표현을 스키마 버전에 고정한다. 광고 문구를 의미가 달라지는 방식으로 정규화하지 않는다. 금액·권한·승인 경계에는 검증 전 원시 JSON을 재사용하지 않는다.

fresh action의 request digest는 동작·대상·version과 의미 있는 본문 필드만 결속하고 `fresh_action_id/fresh_action_proof`는 제외한다. 그래야 아직 발급하지 않은 challenge를 해시에 넣는 순환이 생기지 않는다. HTTP 멱등용 hash는 실제 전송된 검증 본문 전체를 대상으로 한다. 같은 키의 재조회는 이전 fresh proof를 다시 소비하지 않지만 현재 principal·객체 접근은 재확인한다.

## 2 주체·광고주·공급 스키마

- `adc2_principals`: id, kind, owner_id/organization_id, issuer, external_subject, status, revocation_epoch. UNIQUE(issuer, external_subject, environment). 사람과 서비스 종류를 요청에서 바꾸지 못한다.
- `adc2_memberships`: organization_id, principal_id, capability, status, version. 광고주별 finance·editor·approver 범위를 기록한다. owner가 자동으로 사람 동의 권한을 얻지 않는다.
- `adc2_agent_bindings`: agent_id, operator_id, owner_id, key_id, audience, scopes, status, epoch. 키 비밀은 해시/전용 credential 저장소로 분리하고 조회 API는 재출력하지 않는다.
- `adc2_grants`: grantor_id, grantee_id, purpose, object_scope, field_allowlist, limits, expires_at, revoked_at, version. 사용자 수신·맥락 공유와 대행사 집행 권한은 purpose를 구분한다.
- `adc2_fresh_actions`: principal_id, action, target_id, request_digest, challenge_digest, expires_at, consumed_by_operation. 원시 challenge는 제한된 일회 전달만 한다. UNIQUE(challenge_digest).
- `adc2_advertisers`: organization_id, legal_party_ref, brand_verification_ref, jurisdiction_profile, status. 개인 신원 원문은 외부 KYC/보호 저장소에 두고 범용 보고에 포함하지 않는다.
- `adc2_publishers`·`adc2_inventory`: operator_id, property_id, authorization_version, renderer_profile, protocols, locale/region, allowed_products, capability_status. 도메인 소유와 광고 판매 위임을 각각 검증한다.
- `adc2_agent_capability_checks`: agent/property, protocol_version, checks_digest, checked_at, expires_at, evidence_ref. 등록과 실행·표시 검증 결과를 구분한다.

행 보안을 추가할 경우 서비스 계정은 테이블 owner/BYPASSRLS와 분리하고 transaction-local tenant context만 설정한다. 풀 커넥션의 이전 tenant가 남지 않게 한다. RLS 유무와 별개로 repository는 명시적 tenant·owner 조건과 인가를 수행한다. cross-tenant FK와 조합 unique index 없이 서비스의 문자열 필터에만 의존하지 않는다.

## 3 상품·계획·캠페인·소재

- `adc2_product_packs`: advertiser_id, revision, product_id, factual_payload, claim_evidence_refs, price_timestamp, validity, rights_ref, canonical_hash. UNIQUE(advertiser_id, product_id, revision).
- `adc2_creative_revisions`: advertiser_id, product_pack_revision, locale, immutable_content_ref, content_hash, disclosure_profile, renderer_profile, validity. 심사 후 본문 덮어쓰기 금지.
- `adc2_reviews`: target_revision, reviewer_principal, verdict, limitations, reason_code, evidence_ref, expires_at. 심사·이의 제기·판정 정정은 append-only 이력으로 보관한다.
- `adc2_plan_revisions`: advertiser_id, objective, outcome_definition, channels, regions, dates, forecast_ref, budget_contract, policy_version, canonical_hash.
- `adc2_approvals`: plan/campaign_revision, approver_principal, grant_id, approval_digest, approved_at, expiry. 승인한 내용과 집행 내용이 해시로 같아야 한다.
- `adc2_campaigns`: advertiser_id, current_revision, status, lock_version. `adc2_campaign_revisions`: plan_revision, approved_creative_revision, supported_asset_id, start/end, timezone, budget_policy, reward_contract, targeting_fields, frequency_policy, hash.
- `adc2_reward_stage_contracts`: campaign_revision, stage_key, event_type, prerequisites, max_count, gross_atoms, exact_split_atoms, qualification_deadline, review_deadline. UNIQUE(campaign_revision, stage_key). 단계 최대 gross의 합이 offer 전체 hold와 같다.

첫 버전의 P1은 텍스트 소재·플랫폼 렌더러만 지원한다. 별도 자료·HTML·동영상·외부 추적 URL은 renderer profile의 적합성 검증 없이 끼워 넣지 않는다. campaign status 변경과 revision 변경은 다른 작업이다. active 상태의 수정은 새 심사·승인과 기존 offer 보존을 요구한다.

## 4 자산·원장·예산

- `adc2_assets`: asset_id, namespace/environment, chain_id, token_contract, decimals, collateral_profile, activation_manifest. model과 chain 자산 identity에 각각 유일 제약.
- `adc2_accounts`: owner_id, managed_by_agent_id(선택), asset_id, purpose, beneficial, status, balance_atoms. purpose는 advertiser_available, campaign_available, offer_hold, user_available, user_locked, provider_payable, operator_payable, direct_cost, platform_revenue, external_clearing 등 enum이다. 임의 문자열 접두사로 음수를 허용하지 않는다. 관리 에이전트는 소유자가 아니며 owner와 agent binding의 결속을 검증한다.
- `adc2_journals`: asset_id, economic_event_type, economic_event_key, operation_id, posted_at, audit_ref. UNIQUE(environment, asset_id, economic_event_key). 금전 사건의 생애주기에 걸쳐 중복 키를 보존한다.
- `adc2_postings`: journal_id, line_no, account_id, asset_id, signed_delta_atoms. PK(journal_id, line_no). 동일 asset의 합계 0은 posting command와 commit 전 검증으로 강제하며 migration에서 deferred trigger 등 DB 보강을 검토한다. 애플리케이션 검증만 완료했다고 DB 제약 완료로 표시하지 않는다.
- `adc2_budget_windows`: campaign_id, revision/timezone, start_at, end_at, limit_atoms, committed_atoms, spent_atoms. `committed_atoms = spent_atoms + live_reserved_atoms`, 둘을 합해 일 한도 이하로 유지한다. 총 캠페인 한도도 별도 동일 원리로 검사한다.
- `adc2_budget_holds`: offer_id, campaign_revision, budget_window_id, account_id, initial_atoms, remaining_atoms, state, earliest_release_at. hold 값은 분개의 메타데이터이며 B에 별도 채무로 중복 합산하지 않는다.
- `adc2_stage_awards`: offer_id, stage_key, occurrence, accepted_evidence_id, journal_id, receipt_id, awarded_at. UNIQUE(offer_id, stage_key, occurrence)와 accepted evidence 사건의 재사용 제약을 함께 둔다.

계정 잔액을 변경하는 유일 경로는 PostingCommand다. 커밋 절차는 권한·철회 확인 → 고정 순서 잠금 → 사건 유일 키 확인 → 분개 합 0·비음수·자산 일치 → 잔액·원장·업무 상태·outbox 반영이다. 같은 사건을 다른 HTTP idempotency key로 보내도 경제 사건 유일 키가 중복 지급을 막는다.

순수 내부 이동은 beneficial B 총량을 보존한다. 외부 입금·출고는 v5의 R/S/C/B delta를 따른다. 외부 clearing 등 기술적 상대 계정은 beneficial=false로 고정하고 B 계산에서 제외한다. 내부 claim을 늘리는 명령은 확정 담보·수탁 사건이나 기존 소유자의 차변과 반드시 연결한다. 은행 웹훅·관리자 입력·광고 사건만으로 돈을 만든다는 journal kind는 없다.

에이전트를 통해 받은 광고 보상의 기본 수취 계정은 **사용자 소유·해당 에이전트 관리 하위 지갑**이다. 직접 이용자는 사용자 기본 지갑을 쓴다. offer에 wallet_id와 관리 주체를 고정하고 지급 시 소유 결속·철회 상태를 다시 확인한다. 관리 철회 시 미확정 지급은 같은 사용자의 기본 지갑으로 귀속할 수 있지만 다른 사용자나 운영자에게 돌리지 않는다. 확정 지급 뒤 내부 이전·AI 사용은 별도 권한을 따른다. 휴면/철회 회수는 v5의 14일 참조 정책과 기존 약정을 따르며 가용액만 사용자 기본 지갑으로 옮긴다. 작업·검토·출고 잠금은 해소 전까지 보존하고 외부 자기보관 지갑을 임의 회수하지 않는다.

**예산 예시:** 캠페인 가용 100에서 기본 단계 10+선택 추가 단계 10을 제안하면 hold 20, 가용 80이다. 기본 단계 확정 시 hold 10이 계약 배분으로 이동하고 선택 단계 10은 잠긴다. 추가 단계 기한이 끝나면 그 10을 캠페인 가용으로 반환한다. 사용자에게 지급한 기본 몫은 유지된다. 일 한도는 제안 발급의 원래 budget window에 귀속하며, 다음 날 해제된 예약을 오늘의 추가 지출 여력처럼 중복 사용하지 않는다. 회계 일자와 보고할 실제 노출 일자는 별도다.

재생·구매 등 늦은 조건부 단계의 hold는 약정한 최대 기한까지 충당한다. 추가 보상을 열 때 그 단계의 최대 재원을 새로 예약하는 대안은 사용자에게 새 견적·승인을 받는 상품에만 적용한다. 이미 승인한 보상을 향후 입금에 의존하게 바꾸지 않는다.

잠금 순서는 v5와 맞춰 `(권리자 ID 정렬) → (캠페인·offer 등 업무 객체의 type/ID 정렬) → (asset/account ID 정렬)`이다. 작업자는 이미 잠근 account 뒤에 campaign을 새로 잠그지 않는다. 교착·serialization 실패는 전체 트랜잭션을 제한된 횟수 재시도하고 외부 호출은 트랜잭션 안에 넣지 않는다.

## 5 승인·전달·증거·중계

- `adc2_offer_requests`: authenticated principal, bound owner, minimized_context_ref, selection_digest, request_hash. 원문 대화 전체 저장 금지.
- `adc2_offers`: campaign_revision, owner_id, agent_binding_id, quote_hash, disclosure_profile, reward_snapshot, budget_hold_id, expires_at, evidence_deadline, state, version.
- `adc2_ad_preferences`: owner_id, purpose, allowed_context_fields, frequency/time_limits, effective_at, revoked_at, version. 광고 수신·맥락 공유·spend를 다른 purpose로 취급한다.
- `adc2_human_consents`: owner_id, offer_id, quote_hash, fresh_action_id, scope, created_at, revoked_at, version. UNIQUE(owner_id, offer_id, quote_hash). 사람 전용 경로에서만 쓴다.
- `adc2_exposure_sessions`: offer_id, consent_id/version, renderer_profile, challenge_id, issued_at, started_at, evidence_deadline, state. 한 offer의 기본 단계에 동시에 유효한 세션 하나만 허용하는 partial unique index.
- `adc2_evidence_chunks`: session_id, sequence, nonce_digest, server_received_at, elapsed_claim_ms, visibility_claim, artifact_ref, content_digest. UNIQUE(session_id, sequence), UNIQUE(session_id, nonce_digest). 불일치 replay는 거부한다.
- `adc2_evidence_verdicts`: session/stage, verifier_version, accepted/rejected/review_pending, basis_ref, decision_at, review_deadline. 외부 principal은 판정 행을 직접 쓰지 못한다.
- `adc2_delivery_hops`: offer_id, original_hash, parent_hop_id, sender/recipient principal, authorization_version, endorsement_ref, hop_count. 루프·수취인·전체 대가·기한 검증.
- `adc2_brand_sessions`: offer/context grant, advertiser, owner, product_pack_revision, shared_field_manifest, budget_cap, consumed_atoms, state. 원래 대화의 범용 read 권한을 주지 않는다.

단순 시간 합은 유효 노출 판정이 아니다. 서버 수신 시간·순번·nonce·가시성·정상 렌더러·중복 세션·등록 매체 신호를 함께 검사하며 network gap은 약정 범위로 제한한다. 증거 수집 실패와 실제 부정행위는 다른 사유로 기록한다. 검토 기한이 지나도 자동으로 증거를 조작해 지급하지 않으며 계약된 재심·운영 보상 절차로 연결한다. 검토 중인 hold를 일반 만료 작업이 반환하지 못한다.

## 6 결제·체인·측정·통계·공통 작업

M05·M06은 v5 테이블 후보를 `adc2_` namespace로 구현한다. `payment_intents`는 owner·merchant·asset·amount·order·execution_definition_hash·expiry·grant를, `execution_bindings`는 고정 workflow version·provider·node/call·run/execution을 결속한다. 한 run이 다른 결제에 재사용되지 않게 유일 키를 둔다. `refund_cases`는 미사용 잠금 반환과 제공자 지급 후 환불 재원을 구분한다.

`funding_intents`, `chain_events`, `chain_checkpoints`, `signing_requests`, `withdrawals`, `redemptions`, `reconciliation_reports`는 동일 확정 시점·nonce·계약 주소·논리 지급 ID를 보존한다. `unknown`인 출고의 hold는 타임아웃으로 풀지 않는다. 웹훅·모형 seed는 chain-backed balance를 생성할 수 없다.

측정 표는 `measurement_sources`, `fact_events`, `conversion_claims`, `attribution_runs`, `attribution_adjustments`, `experiment_assignments`, `cohort_snapshots`, `report_disputes`다. 원본 사건 유일 키는 `(source_id, source_event_id)`이며 주문 전환은 `(advertiser_id, integration_id, order_id, event_type, business_revision)`도 검사한다. 원본과 correction을 분리하고 귀속 결과의 재계산이 과거 원장을 다시 지급하지 못하게 한다.

통계 표는 `aggregate_snapshots`, `query_policies`, `query_budgets`, `query_audits`다. 셀의 원시 contributor 수·집계 lineage는 보호된 내부 자료다. 외부 응답은 공개 기준을 통과한 지연·집계 결과와 기간·단위·분류·추정 여부만 담는다. 집계 대상·이용권·철회·삭제 변경 시 새 snapshot을 만들고 허용되지 않은 옛 캐시를 무효화한다.

공통 표는 `operations`, `idempotency_records`, `outbox`, `inbox`, `receipts`, `audit_events`, `activation_manifests`다. idempotency 범위는 `(environment, principal_id, HTTP method, route template, key)`이며 정규화한 대상 ID와 본문 hash를 기록한다. 동일 key·다른 대상/본문은 409다. 과거 응답을 반환하기 전에도 현재 객체 접근·철회를 확인한다. 증명 nonce의 사용 여부와 HTTP 재조회 멱등은 다른 계층이다.

outbox는 aggregate_id/version, event_id, event_type, schema_version, audience, available_at, lease_until, attempts, delivery_state를 갖는다. inbox는 source/audience/event_id 유일 키와 digest를 갖고 같은 event_id의 다른 payload는 격리한다. 정해진 상태 전이만 version CAS로 반영하며 전역 사건 순서를 가정하지 않는다. 영수증 서명 전 원장 커밋이 완료될 수 있으므로 `receipt_pending`을 허용하고 서명 재시도로 분개를 다시 만들지 않는다.

초기 필수 인덱스는 tenant/status/created_at, campaign/status/validity, owner/offer/state, expiry가 있는 live hold, owner/campaign/frequency window, economic_event_key, outbox(state, available_at), inbox dedup, chain checkpoint와 미확정 operation이다. 원장·과금 dedup을 단순 날짜 partition TTL로 삭제하지 않는다. 실제 쿼리·용량으로 인덱스와 파티션을 검증하고 통계 용도로 원장 실시간 full scan을 하지 않는다.

## 7 첫 개발 범위의 OpenAPI

[ad_coin_platform_p1_v6_2.openapi.json](ad_coin_platform_p1_v6_2.openapi.json)은 OpenAPI 3.1.1로 작성한 **플랫폼 렌더러 P1의 첫 계약**이다. 자산 발행·외부 출고·CRM·브랜드 대화의 완성된 OpenAPI라고 표현하지 않는다. 인증·객체 인가·fresh action·멱등·state transition은 operation의 `x-*` 규칙과 이 문서를 함께 구현한다. 스키마가 맞는 요청이라고 실행 권한이 생기지 않는다.

공개 capability는 지원 환경·상품·렌더러·정책 버전을 밝힌다. 운영 DSN·키·내부 처리량·모델·서명 인프라 경로는 반환하지 않는다. 아직 미지원 기능은 명시적으로 false다. 원화 v1과 v2를 자동 혼합하지 않는다.

첫 계약은 광고주 캠페인 생성·심사 요청·심사 판정·집행 승인·활성/중지, 사람 challenge·수신 설정, 제안·건별 승인·노출·소재 조회·증거 제출·완료, operation·지갑·영수증 조회를 포함한다. 자금은 격리 모형 fixture 또는 v5의 검증된 funding 경로로만 공급한다. 공개 test credit API를 실제 가치 환경에 만들지 않는다.

R0의 초대 사용자·광고주 조직/역할·scope가 있는 agent binding·가상 재원은 테스트 fixture로 구성한다. 기존 v1 키를 자동으로 v2 scope로 승격시키지 않는다. 계정 초기화에서 기본 거절 상태의 ad preference와 model wallet을 만들고, GET preferences/campaign으로 현재 version·revision을 조회한 뒤 challenge·If-Match를 사용한다. 응답이 version을 바꾸는 쓰기에는 새 ETag를 반환해야 한다. 제안 거절 API도 제공해 거절·hold 해제·반복 제안 제한을 기록한다.

R0의 제안에는 정확한 기본 배분과 시험 전용·상환 불가를 표시한다. 아직 연결하지 않은 유료 AI를 사용할 수 있다고 약속하지 않는다. 실제 작업 후원은 R1/R2에서 유효한 task quote·검증 근거·가격 기한·부족액·별도 실행 위임을 추가한 계약으로 확장한다.

오류는 `error.code`, 안전한 message, request_id, retryable을 반환한다. 401 인증 없음, 403 권한·scope·인간 전용 위반, 다른 소유자의 객체 404, revision/멱등/상태 충돌 409, 자료 형식·계약 위반 422, 크기 413, 한도 429, 자금 안전 중지·의존 장애 503이다. 잔액 부족은 409 `insufficient_budget/balance`로 구분한다. API·서버 stack trace와 원시 요청·토큰은 노출하지 않는다.

모든 쓰기는 Idempotency-Key를 필수로 받고 대상 변경은 If-Match 또는 고정 revision hash를 검사한다. 사람의 cookie 쓰기는 CSRF와 Origin 검사를 추가한다. 최초 PoC의 기계 인증은 기존 키의 서버 결속·scope를 강화하는 방식으로 시작하되 외부 서비스의 장기 자격·서명은 별도 검증된 프로필로 확장한다.

완료 API의 202는 증거 검증 요청 수락이다. operation 조회에서 성공·실패·검토 중과 wallet/receipt ref를 확인한다. API에 클라이언트가 `accepted`, `reward_paid`, `journal_id`, `actor`를 지정하는 필드는 없다. 원장은 내부 보상 명령만 쓴다.

명시적 노출 중지는 `/exposure-sessions/{id}/cancel`로 요청한다. 새 증거 수집을 중단하고, 이미 충족한 조건·확정 보상이 있으면 보존한다. 중지 요청이 검증 중인 권리를 임의 취소하거나 hold를 먼저 풀게 하지 않는다. 단순 offer decline은 노출 전 제안에만 적용하고 노출 시작 후에는 이 중지 절차를 쓴다.

## 8 후속 API의 기능 계약

아래 경로는 전체 플랫폼의 **예정 계약**이다. 요청 필드는 필수 의미를 설명하며 개별 구현 작업에서 OpenAPI를 완성해야 한다. 실제 구현된 엔드포인트가 아니다.

- `POST /plans`, `POST /plans/{id}/revisions`, `POST /plans/{id}/approvals`: 광고주·대행사 planner/approver. 목표·기간·성과 정의·매체·예산·예측 근거·revision hash를 결속한다.
- `POST /inventory`, `GET /inventory`, `POST /media-proposals`, `POST /media-bookings`: 적격 매체와 광고주 역할. property 판매 권한·지원 버전·상품·가격·유효기간·예약 재원을 검증한다. GET은 권한에 맞는 공개/계약 정보를 분리한다.
- `POST /product-packs`, `POST /creatives`, `POST /appeals`: advertiser editor. 사실 근거·가격 시점·권리·지원 renderer·locale·심사 대상 revision을 고정한다.
- `POST /deliveries/{id}/relay`, `POST /offer-acks`: publisher_service의 제한 capability. 원본 envelope·audience·허용 hop·중계 대가·nonce를 검사하며 사람 노출과 구분한다.
- `POST /brand-sessions`, `POST /brand-sessions/{id}/messages`, `POST /brand-sessions/{id}/end`: 사람/허용된 사용자 에이전트·brand service를 동작별 분리한다. 별도 시작 동의·공유 필드·대화 비용·적격 사건을 결속한다.
- `POST /mandates`, `POST /mandates/{id}/revoke`, `POST /payment-intents`, `POST /payment-intents/{id}/authorize`, `POST /captures`, `POST /refunds`: M05 권한. 사용자 신규 위임·가맹점 주문·실행 정의·실제 run·환불 재원을 결속한다. body의 agent_ref로 주체를 선택하지 않는다.
- `POST /funding-intents`, `POST /transfers`, `POST /withdrawals`, `POST /redemptions`: M04·M06 권한. 자산·체인·금액·수취인·승인·nonce와 위험 한도를 검사하고 비동기 체인 확정을 operation으로 반환한다. 상세 계약은 v5를 따른다.
- `POST /measurement-integrations`, `POST /conversion-events`, `POST /report-disputes`: advertiser finance/measurement_service. 동의한 사건·source identity·business revision·귀속·취소·환불을 검증한다. 전환 송신은 지갑 송금 권한이 아니다.
- `POST /experiments`, `POST /optimization-plans`, `POST /optimization-plans/{id}/apply`: 승인된 계획 범위. 실험 배정과 실행 권한, 원본 예산/철회 version을 확인한다.
- `GET /reports`, `POST /market-queries`: 인가된 광고주·대행사·분석 서비스. 측정·귀속 버전·기간·분모·개인정보 억제·질의 예산·자료 사용권을 검사한다. 외부 agent의 통계 조회가 고객 원장 조회를 허용하지 않는다.

내부 전용 API는 검증 판정·chain projection·대사 결과·금전 서명 요청·run 결과를 별도 audience와 네트워크 정책으로 제한한다. 일반 공개 API의 인증 bearer를 그대로 신뢰하지 않는다. 외부 webhook sender의 임의 URL을 내부 요청 목적지로 사용하지 않는다.

## 9 변경과 검증

v6.2에서는 [보강 설계](AD_COIN_PLATFORM_DESIGN_UPGRADE.md)의 adapter profile·주장 근거·attention quota·실행 비용·보고 의무/불변 revision·수신 상태 표를 추가한다. outbox/dispatch에는 권한 epoch와 lease generation을 붙인다. 이 논리 표와 필드도 후속 migration·인덱스·SQL 허용 목록·동시성 검증 대상이며 현재 DB에 존재한다고 표시하지 않는다.

현재 P1 계약은 capability의 contract_version=`v6.2`를 확인한 뒤 사용한다. 쓰기는 `X-AIAC-Contract: v6.2`를 필수로 보내며 미지원 버전은 거부한다. fresh action의 semantic digest는 method·대상·contract version·의미 본문을, HTTP 멱등 digest는 contract version과 실제 검증 본문을 포함한다. 기존 멱등 key의 계약 버전이 달라지면 409이며 새 금전 사건으로 자동 실행하지 않는다.

수신 설정은 캠페인별 상한 외에 사용자 전체 일일 광고 횟수·시간을 갖는다. exposure 응답의 max_view_ms는 증거 제출 기한과 별개이며 전체 quota reservation과 결속한다. 보고 API는 reporting-status 조회, 불변 report revision 조회, 인가된 소비 상태 기록을 제공한다. 소비 ACK는 `reports.acknowledge` 권한이며 송금·집행 권한이 아니다. R0에는 외부 매출 추정치를 생성하지 않는다.

영수증 v6.2는 예전 signature 필드 대신 key_id와 jws, issuer/audience, 정책/계약 버전을 제공한다. JWS protected header·payload는 ReceiptHeader·ReceiptClaims로 검증하고 서명 검증 뒤 표시 필드와 대응시킨다. signature_state=pending이면 key_id/jws는 null이다. 공개 receipt-keys는 검증용 공개키·상태만 반환한다. 기존 v6.1 JSON은 역사본이며 새 shape로 조용히 해석하지 않는다.

migration 순서는 expand → 새 코드 이중 프로필 검증 → 제한 cohort → 필요 시 별도 승인된 실가치 활성화다. v1 잔액의 자동 backfill은 없다. rollback은 새 트래픽·기능을 닫고 미처리 지급·권리를 보존하는 방식이며 이미 발행된 자산·확정 분개를 삭제하지 않는다. 새 column을 옛 코드가 무시한다고 경제적 rollback이 완료되는 것은 아니다.

개발 검증에는 복합 FK·다른 tenant·agent key→human 차단, 만료·철회·동시 지급, stage 최대량·일 창·예산 경합, uint256 경계·정수 배분·negative claim, 중복 원본 주문·역순 webhook, 차분 통계 질의, 회복 후 nonce·출고 잠금·chain checkpoint를 포함한다. v6.2 저장 계층과 DB 검증은 PostgreSQL 전용이다. SQLite fallback이나 대체 시험을 제공하지 않는다.
