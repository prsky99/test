# 02 데이터·원장·트랜잭션 상세 설계

2026-11-08 · [목차](../AD_COIN_V6_2_DETAILED_DESIGN.md) · 아래 SQL은 구현 패턴이며 운영 migration이 아님

**2026-11-09 구현 갱신:** 모델 schema는 현재 4이며 38개 표를 유지한다. `performance_schema.py`의 여섯 인덱스는 미완료 journal/멱등 명령, 승인·배정된 활성 campaign의 부분 인덱스와 advertiser별 campaign, owner별 wallet, active membership의 범위 인덱스다. 명시적 `migrate_model()`이 1/2/3→4를 처리하고 재실행해도 원장/잔액을 변경하지 않는다. 전역 미완료 정합성 검사를 생략하지 않고 대상 행 접근만 개선한다. UI 목록은 최대 10개와 다음 cursor 확인 1개를 한 고정 조회로 읽고 서버가 advertiser 권한을 재검사한다. [화면·성능 검증](../../reports/ad-coin-v6.2-ui-performance-2026-11-09/README.md)의 단일 로컬 PG 비교는 운영/다지역 처리 용량의 증거가 아니다. 아래 날짜별 구현 설명은 해당 단계의 이력이다.

## 1 물리 타입과 경계

기본 PK는 UUID, 생성/변경 시각은 `timestamptz`, version/epoch/generation은 `bigint CHECK >= 1`, SHA-256은 32-byte `bytea` 또는 64자리 lowercase hex 중 하나로 repository 전체에서 통일한다. R0 기준은 DB bytea·API hex다. canonical payload는 schema 검증 후 JSONB로 보관하며 승인된 revision은 수정하지 않는다.

저장 계층과 모든 DB 시험은 PostgreSQL 전용이다. atoms는 scale을 지정하지 않은 `NUMERIC`에 `amount = trunc(amount)`와 `0 <= amount <= 2^256-1`을 함께 CHECK한다. `numeric(78,0)`의 입력 단계 소수 반올림을 피하고 소수 금액을 거부하기 위한 선택이다. signed posting만 같은 절댓값 범위의 음수를 허용한다. 문자열 prefix를 근거로 잔액 음수를 허용하지 않는다. 외부 clearing account만 명시적 account_class에 따라 음수 가능하며 beneficial=false다. treasury가 확인한 실제 수탁 총량보다 큰 claim을 생성하지 않는다.

commercial_tenant_id와 beneficial_owner_id는 서로 다른 축이다. 사용자 offer는 광고주 campaign과 사용자 owner를 합법적으로 연결하므로 모든 FK에 ‘동일 tenant’를 기계적으로 요구하지 않는다. campaign→revision·review→campaign은 commercial 복합 FK로, consent/session→offer는 owner 복합 FK로 검증한다. journal은 같은 asset의 합법적 여러 owner 계정을 포함할 수 있으며 일반 사용자에게 전체 journal을 공개하지 않는다.

기본 읽기/짧은 쓰기는 READ COMMITTED에 명시적 행 잠금·조건부 UPDATE·유일 제약을 결합한다. 집계 한도를 검사하는 모든 경로가 같은 guard row를 잠가야 한다. reporting snapshot은 읽기 전용 REPEATABLE READ로 manifest를 고정한다. `SKIP LOCKED`는 작업 큐 획득에만 사용하며 잔액·사용자 한도·캠페인 예산의 ‘없는 값’ 판정에 쓰지 않는다.

### 1.1 WP-02 모델 기반 구현 상태 · 2026-11-08

실행 코드의 고정된 SQL은 `agent_market/ad_coin/v2/sql.py`, 명시적 migration은 `schema.py`와 `ModelStore.migrate_model()`이다. PostgreSQL 연결 factory를 직접 주입하며 환경 DSN을 추측하거나 자동으로 DB를 만들지 않는다. import·서비스 시작만으로 migration하지 않으며 기존 v1 원화 잔액을 읽거나 이전하지 않는다. SQLite 구현·fallback·시험은 없다.

이번 기반은 schema/asset·account/journal/posting·budget window/hold/event·idempotency·outbox/inbox·authority guard·fresh action·attention window/session/reservation의 16개 표다. UUID 값은 정규화한 문자열, 시각은 안전 범위 정수 milliseconds, hash는 lowercase hex, 제한된 응답 snapshot은 canonical JSON text로 저장한다. 위의 UUID/시각/bytea/JSONB 전체 도메인 모델 35개가 이미 구현됐다는 뜻이 아니다. campaign/revision·membership/agent binding·consent/evidence·receipt/report 연결과 타입 확정은 후속 handler migration에서 완성하며 기존 API 계약은 보존한다.

`ledger.py`는 고정 model 자산만 허용하고, 계정을 정렬하여 `FOR UPDATE` 잠금한 뒤 journal·posting·캐시 잔액을 같은 TX에 넣는다. 분개 합계 0은 PostgreSQL deferred constraint trigger가 커밋 시 다시 검사하며, 확정 분개·posting과 계정 identity의 변경을 차단한다. 광고 지급은 clearing을 사용해 새 잔액을 만들 수 없으며 `model_seed`만 격리 fixture 경로에서 사용한다. 계정별 원장 재계산은 읽기 전용 REPEATABLE READ에서 DB 집계로 수행한다.

`budgets.py`는 최초 예약의 총/일 창에 최대 지급량을 예약하고, 지급은 reserved→spent, 적격 반환은 최초 창의 reserved 해소로 처리한다. review_pending은 타이머 반환에서 제외한다. 반환 primitive만으로 실제 노출의 미충족을 판정하지 않으며 delivery 상태를 잠그고 지급 권리/미결 검토 여부를 확인하는 상위 명령과 자동 만료 worker는 아직 미구현이다.

`commands.py`는 route template·principal·method·key scope와 대상/본문 digest를 구분한다. 권한 확인 wrapper가 현재 guard·CSRF·객체 scope를 같은 TX에서 확인한 뒤 재조회나 실행을 허용한다. 원장·작업 outbox·응답 snapshot은 함께 커밋한다. outbox는 SKIP LOCKED와 lease owner/generation/기한으로 낡은 완료·갱신을 거부한다. 외부 수신자의 중복 효과·실제 서명/체인 dispatch는 별도 통합 검증 대상이다.

`fresh.py`는 120초 이하의 무작위 proof를 hash로만 저장하고 principal/owner/session/action/target/revision/semantic digest/If-Match에 묶어 operation과 원자적으로 소비한다. `attention.py`는 UTC global/advertiser/campaign 세 창, 동시 세션 1개, 최소 15초·최대 30초 예약, 하루 종료 40초 전 시작 차단을 구현한다. 시작 횟수는 중지 후 복구하지 않으며 미확인 증거는 시간 quota를 보수적으로 소비한다. attention 해소는 금전 hold·보상·유효 노출 매출을 변경하지 않는다.

서버 인증 adapter·DB 실행 role 제한·29개 handler·UI·실제 노출 검증·서명 통합·장애 복구/성능 인수는 아직 남아 있다. 최신 범위와 시험 증거는 [개발 기록](../../reports/ad-coin-v6.2-development-2026-11-08/PROGRESS.md)에 남긴다.

### 1.2 WP-03 모델 commercial 구현 · 2026-11-08

명시적 모델 schema 1→2 업그레이드로 principals·advertisers·memberships·campaigns·campaign_revisions·reviews·review_evidence·approvals·commercial_control의 9개 표를 추가하여 현재 기반 표는 25개다. 기존 계정/원장과 v1 표를 삭제/변환하지 않는다. 알 수 없는 schema version은 거부하고 migration 실패 후에는 해당 Store를 ready로 유지하지 않는다. 실제 데이터 migration/실행 role 분리와 운영 복구 검수는 별도다.

상업 권한은 request/cached Principal의 capability 주장을 무시하고 DB membership으로 결정한다. principal·advertiser·예산 승인자의 guard를 먼저 정렬 잠금하고, 최신 grant를 확인한 뒤 멱등 응답 재조회나 업무를 허용한다. 활성화는 approval의 원래 principal/회원 epoch·기한·revision도 확인한다. 원래 승인 권한이 철회/변경되면 다른 담당자가 그 승인으로 재개하지 못한다. R0는 revision 편집/재승인 endpoint가 없으므로 오래된 승인/조건을 교체하려면 새 draft를 사용한다. 광고주 중지·모델 activation switch도 신규 활성화를 거부하며 switch 기본값은 off다.

revision·review evidence·approval·principal identity는 DB에서 UPDATE/DELETE를 막는다. campaign의 current revision은 defer 가능한 복합 FK로 같은 campaign/advertiser에 묶고, review evidence도 실제 review/revision/advertiser에 결속한다. 심사 판정은 별도 reviewer kind/audience·creative.review·검증된 mTLS가 필요하다. 입력 UUID만으로 근거를 등록하지 않으며 trusted model review worker의 내부 record_evidence가 선행한다. 실제 reviewer token/certificate 검증과 근거 수집 서비스는 아직 운영 연결하지 않았다.

광고주 가용→캠페인 가용 계정의 owner/purpose/asset을 검증하고 최초 activation TX에서만 총예산 journal·total window·active/version/dispatch epoch·보고 계획 outbox를 함께 커밋한다. 부족/오류는 전부 롤백한다. pause는 신규 dispatch epoch를 바꾸며 hold/원장을 지우지 않는다. resume은 확정 funding journal·원래 총예산 창·승인을 확인하고 재충전하지 않는다. 실제 제안/노출 worker의 epoch 소비는 WP-04 이후에 연결한다.

HTTP challenge의 응답 snapshot에는 proof를 넣지 않는다. 별도로 주입한 32-byte secret과 model/fresh purpose로 구분한 HMAC-SHA256에서 같은 proof를 복구하고, DB에는 challenge hash와 binding만 저장한다. 같은 사람 세션·현재 권한·TTL에서만 응답 재시도를 허용하며 secret 교체/미설정 시 거부한다. secret의 운영 저장/회전·TLS는 배포 인수 대상이다. 만료 판정은 DB 잠금을 얻은 후의 서버 시각으로 수행한다.

### 1.3 WP-04 추가 구현 재검수 · 2026-11-08

현재 model schema 3·38개 표다. P1의 13개 표와 agent kind를 CREATE IF NOT EXISTS만으로 추가했던 코드의 이전 DB 제약 갱신 누락을 보완했다. 실제 WP-03형 human/ops 제약을 가진 DB에서 migration한 뒤 agent provision이 가능한지 시험한다. 기존 report revision에는 source_manifest_json 열을 명시적으로 추가한다. 운영 DB에는 적용하지 않았다.

`evidence.py`는 immutable evidence prefix의 순서·nonce chain·canonical hash·서버/클라이언트 시각 단조성·양 끝 visible/foreground·3초 이하 간격·startup/최대 노출/cutoff를 재검증한다. 서버 경과 0은 0ms이며, 백그라운드→포그라운드 경계 구간은 누적하지 않는다. API와 보상 worker가 같은 검증 함수를 사용하되 worker는 저장된 합계/자격 cache를 신뢰하지 않고 원본에서 독립 계산한다. 불일치는 review_pending으로 격리하고 보상과 hold 반환을 실행하지 않는다. 이는 실제 사람 집중의 완전한 증명이 아니다.

광고주·원래 승인자 authority guard를 먼저 정렬 잠금하고, owner 단위 delivery lock 이후 campaign/offer/session을 잠근다. 최신 switch·advertiser suspension·승인 grant epoch·campaign revision/기간·선호도를 노출 전 다시 검증한다. 일 한도 축소는 기존 attention 창에도 신규 시작/예약 상한으로 적용한다. worker와 expiry는 같은 owner 잠금을 사용하며 여러 owner 잠금을 한 expiry TX에 누적하지 않는다.

재시도 응답은 과거 sequence와 현재 nonce를 섞지 않고 원래 nonce/sequence 응답 snapshot을 반환한다. nonce는 이미 session/chunk에 저장되는 일회성 프로토콜 값이며 fresh human proof와 구분한다. fresh proof는 여전히 snapshot에 넣지 않는다. worker는 효과 전에 lease row를 잠그고 generation/소유자/기한을 확인하며, 실제 경과를 반영한 완료 검사 실패 시 효과를 롤백한다. 미지원 event는 완료 ACK하지 않는다.

보고서의 원천은 하나의 PostgreSQL SELECT snapshot에서 읽은 확정 P1 원장 사건과 미결 session이다. 광고 대가는 현재 catalog 가격이 아닌 실제 소비 journal의 금액을 사용하고, 기간은 늦은 지급 시각이 아닌 qualification 시각에 귀속한다. private manifest에 원천 참조·금액·시각을 보존하고 미결 증거가 있으면 complete=false다. 같은 manifest/집계/cutoff는 revision을 추가하지 않는다. 공개 content_digest는 반환하는 DTO에서 content_digest만 제외한 canonical JSON의 hash다. 기존 잘못된 digest/manifest의 역사 revision은 수정하지 않고 다음 발행에서 새 revision으로 정정한다. 전체 전역 watermark/외부 통계·수신 사업자 인수는 후속이다.

Ed25519 JWS verifier는 canonical JSON/base64url·중복 key/크기·고정 model issuer/audience/stage/asset/버전·양의 원자량·키의 발행 시각 범위를 검증한다. 키 운영/회전, 실제 renderer와 인간 행동 검증, role/RLS, 장애 복구·부하·실가치 검수는 이 모델 시험으로 대체하지 않는다.

## 2 R0 표의 필수 필드·키

모든 표에는 environment를 포함한다. 금전 객체는 asset_id를 필수로 갖는다. 아래 필드 외 공통 생성/감사 필드는 repository 계약으로 보완한다. catalog.json은 주요 필드·키·원자 경계를 기계적으로 추적하며 실행용 DDL은 후속 WP-02에서 작성한다.

### 2.1 권한과 설정

- **principals:** id PK, kind text CHECK enum, credential_epoch bigint, status, subject_owner_id UUID 선택, expires_at. UNIQUE(environment, issuer, external_subject). 직접적인 업무 호출 kind와 실제 owner를 분리한다.
- **authority_guards:** guard_type, guard_id 복합 PK, epoch, status. principal·grant·organization·owner별 철회 선형화 지점이다. 단순 수익 수취자까지 모두 authority guard로 잠그지 않아 전역 platform 병목을 만들지 않는다.
- **memberships:** commercial_tenant_id, principal_id, capability, grant_epoch, revoked_at. UNIQUE(tenant, principal, capability). 활성 membership만 인가에 사용한다.
- **agent_bindings:** id, owner_id, agent_principal_id, operator_id, credential_epoch, audience, capabilities, revoked_at. UNIQUE(id, owner_id). key secret은 해시/별도 credential store이며 업무 row에 plaintext로 두지 않는다.
- **ad_preferences:** id, owner_id, purpose, receive_offers, context_fields, max_offers/day, max_ads/day, max_ads/campaign/day, max_ad_ms/day, version, revision_hash. UNIQUE(owner_id, purpose). 기본은 수신 비활성·공유 없음이다.
- **fresh_actions:** id, principal_id, session_binding_hash, action, target_id, target_revision_hash, semantic_digest, challenge_hash UNIQUE, expires_at, consumed_by_operation 선택. challenge 소비는 수신 command의 커밋과 원자적이다.

### 2.2 광고주와 캠페인

- **advertisers:** id, commercial_tenant_id UNIQUE, verification_status, brand_rights_ref, jurisdiction_profile, status. KYC 원문은 별도 보호 저장소 참조다.
- **campaigns:** id, advertiser_id, current_revision_id, state, approval_status, version. UNIQUE(id, advertiser_id). workflow 상태 변경마다 version 증가.
- **campaign_revisions:** id, campaign_id, advertiser_id, revision_no, content_hash, asset_id, total_budget_atoms, daily_budget_atoms, timezone, starts_at, ends_at, product=P1, gross_p1_atoms, split_bps, exact_split_atoms, min_exposure_ms, creative_hash/text_ref, renderer_profile. UNIQUE(campaign_id, revision_no), UNIQUE(id, advertiser_id), CHECK daily<=total·ends>starts·사용자 보상>0.
- **reviews:** id, advertiser_id, campaign_id, campaign_revision_id, state, version, reviewer_principal 선택, evidence_ref 선택, reason. 같은 campaign/revision의 활성 pending 심사 하나에 partial unique index.
- **approvals:** id, campaign_revision_id, content_hash, approver_principal, fresh_action_id UNIQUE, approved_at, expires_at, grant_epoch. UNIQUE(revision, approver, approval_purpose). 승인한 revision과 실제 활성 revision이 같아야 한다.

### 2.3 원장과 예산

- **assets:** id text PK, namespace, chain_id 선택, token_contract 선택, decimals=6, activation_manifest_ref 선택. model은 체인 identity가 null이며 정식 자산과 ID를 공유하지 않는다.
- **accounts:** id, owner_id, manager_binding_id 선택, asset_id, purpose, beneficial, account_class, balance_atoms. UNIQUE(id, asset_id). manager null/non-null 두 partial unique index로 owner/asset/purpose/manager의 중복을 막는다. campaign/hold 등 목적 계정에는 object_ref를 포함한다.
- **journals:** id, asset_id, economic_event_key, operation_id, kind, committed_at. UNIQUE(environment, asset_id, economic_event_key), UNIQUE(id, asset_id). 확정 후 UPDATE/DELETE 금지.
- **postings:** journal_id, line_no, asset_id, account_id, signed_delta. PK(journal_id, line_no), 복합 FK(journal_id,asset_id)·(account_id,asset_id). 같은 journal의 delta 합 0을 command와 commit-time DB 검증으로 강제한다.
- **budget_windows:** id, campaign_id, asset_id, window_kind(total/day), window_start/end, limit_atoms, reserved_atoms, spent_atoms, version. UNIQUE(campaign, kind, start), CHECK reserved>=0·spent>=0·reserved+spent<=limit.
- **budget_holds:** id, offer_id UNIQUE, asset_id, total_window_id, day_window_id, hold_account_id, initial_atoms, remaining_atoms, state, qualification_deadline, review_deadline. remaining은 실제 hold 계정 잔액과 대사한다. 같은 금액을 B에 두 번 합산하지 않는다.
- **stage_awards:** id, offer_id, stage_key, occurrence, evidence_verdict_id, journal_id UNIQUE, receipt_id UNIQUE. UNIQUE(offer,stage,occurrence), 단계별 동일 원본 evidence 재사용 제한.

### 2.4 제안과 노출

- **offers:** id, campaign_revision_id, advertiser_id, owner_id, agent_binding_id 선택, wallet_id, fallback_wallet_id, quote_hash, quote_snapshot, hold_id, state, version, expires_at. UNIQUE(id,owner_id). quote에는 asset·정확한 split·기한·관리 철회 fallback·검토 조건을 포함한다.
- **human_consents:** id, offer_id, owner_id, quote_hash, fresh_action_id UNIQUE, version, created_at, revoked_at. 복합 FK(offer,owner), UNIQUE(offer,owner,quote_hash). 소비와 취소 이력은 보존한다.
- **exposure_sessions:** id, offer_id, owner_id, consent_id/version, state, nonce_sequence, next_nonce_hash, startup_deadline, first_signal_at 선택, active_deadline 선택, evidence_deadline, cutoff_at 선택, collected_valid_ms, max_view_ms, version. 같은 offer의 활성 세션 하나에 partial unique index.
- **evidence_chunks:** session_id, sequence, nonce_hash, server_received_at, client_elapsed_ms, visible, foreground, canonical_hash. PK(session,sequence), UNIQUE(session,nonce_hash). 원본은 append-only, 동일 sequence·다른 내용은 거부.
- **evidence_verdicts:** id, session_id, stage, verifier_version, evidence_manifest_hash, decision, qualified_at 선택, reason, review_deadline. 최종 판정 정정은 새 이력으로 기록하며 stage award 유일성은 유지한다.
- **attention_windows:** owner_id, scope_kind(global/advertiser/campaign), scope_id, day_start, reserved_sessions, started_sessions, reserved_ms, observed_ms, limits, version. UNIQUE(owner,scope,scope_id,day). 시작 횟수와 지급 가능한 유효 노출 수를 구분한다.
- **attention_reservations:** id, session_id, window_id, reserved_ms, consumed_ms, count_consumed, state. UNIQUE(session,window). 세션 종료마다 정확히 한 번 해소한다.

### 2.5 작업·영수증·보고

- **operations:** id, principal_id, owner/tenant scope, command_type, target_id, state, result_ref, error_code, version. state는 API 계약과 같으며 금전 unknown은 별도 업무 객체 상태에 보존한다.
- **idempotency_records:** 환경/주체/method/route/key 복합 유일 키, request_digest, operation_id, http_status, safe_response_ref, state. 경제 dedup보다 짧은 캐시 수명은 허용해도 경제 사건 tombstone은 유지한다.
- **outbox:** id, aggregate_type/id/version, event_type/schema, payload_ref/hash, audience, available_at, state, lease_owner, lease_until, lease_generation, principal_epoch, grant_epoch, auth_snapshot_hash, dispatch_intent_id 선택, attempts. INDEX(state,available_at), INDEX(aggregate,id).
- **inbox:** source_id, audience, event_id 복합 유일 키, payload_hash, received_at, processed_operation. 같은 ID·다른 hash는 격리.
- **dispatch_intents:** id, logical_effect_id UNIQUE, operation_id, target_profile, payload_hash, authority_epochs, lease_generation, state, remote_ref 선택. committed intent와 실제 송신 결과를 분리한다.
- **receipts:** id, journal_id UNIQUE, offer_id, payload_bytes/hash, policy/contract version, issued_at, signature_state, key_id 선택, jws 선택. signed일 때 key/JWS 필수, pending일 때 둘 다 null. payload는 서명 전에 고정한다.
- **receipt_key_metadata:** kid PK, public_jwk, status, not_before, issue_until, verify_until, key_service_ref. private key는 DB/catalog에 저장하지 않는다.
- **reporting_obligations:** id, advertiser/campaign, period_start/end, timezone, expected_at, recovery_deadline, metric_contract_hash, state, current_report/revision 선택. UNIQUE(campaign,period,metric_contract_hash). available은 유효 revision을 요구한다.
- **report_revisions:** report_id, revision 복합 PK, obligation_id, content_digest, fact_manifest_ref, generated_at, data_through, method_version, vendor_relation, supersedes_revision 선택, completeness. revision 불변.
- **report_consumption:** id, tenant/principal, report_id, revision, state, observed_digest 선택, recorded_at. received는 저장된 content_digest와 일치해야 한다. 이 표를 원장 지급 트리거로 사용하지 않는다.

## 3 transaction 잠금 규약

모든 쓰기는 먼저 HTTP idempotency/내부 command ownership을 확정한다. 이후 (1) 필요한 authority guard를 type/ID 순서로, (2) business row를 type/ID 순서로, (3) asset/account row를 ID 순서로 잠근다. account 잠금 후 앞 단계 row를 추가 획득하지 않는다. ID를 사전 읽었지만 실제 관계가 달라졌으면 전체 TX를 중단하고 새 lock set으로 재시도한다.

guard/window가 없으면 `INSERT ... ON CONFLICT DO NOTHING` 후 동일 유일 키의 row를 `FOR UPDATE`로 읽는다. 다른 TX의 미커밋 insert를 무시하고 별도 한도를 만들지 않는다. platform 수익처럼 단순 credit의 beneficiary authority guard까지 전역 잠그지 않는다. source debit·campaign 한도·대상 계정의 회계 제약은 항상 검사한다.

READ COMMITTED에서 관련 guard를 읽기만 하면 write skew가 남는다. 모든 경로의 잠금 규약을 회귀 검증한다. 교착/serialization 실패는 rollback 후 같은 논리 key로 최대 3회 jitter 재시도한다. 한도를 늘려 실패를 숨기지 않으며 외부 송신을 TX 재시도 함수에 넣지 않는다.

## 4 TX-01~05 캠페인과 제안

**TX-01 CreateCampaign:** tenant/capability 확인 → draft+불변 revision+version=1+operation 생성. 예산 한도는 계약 값이며 아직 돈을 이동하지 않는다. gross 배분을 계산해 사용자 몫이 0이면 422. R0 region/taxonomy·UTC·P1·텍스트·15초·기본 split 외 요청은 거부한다.

**TX-02 Review/Approve:** 현재 version·revision을 잠금 아래 재확인한다. review verdict의 evidence_ref는 같은 revision의 접근 가능한 근거를 가리켜야 한다. approval은 fresh action 소비와 승인 row·campaign approval_status/version을 함께 기록한다. 자기 조직의 편집자 자격으로 review service를 가장하지 못한다.

**TX-03 Activate:** 최신 approval·review·기간·중지·asset를 검사한다. 최초 활성화는 광고주 available에서 total_budget만큼 campaign_available로 한 번 이전한다. 경제 키 `campaign_funding:{campaign_id}:{asset_id}`. pause 이후 resume은 기존 배정·한도·승인을 검증하고 추가 funding을 만들지 않는다. 금액 변경은 새 revision/계약이다.

**TX-04 ReserveOffer:** owner의 수신·맥락 grant·동시 제안 2개/일 제안 10개 상한, campaign·총/일 예산·가용액을 잠근다. 최신 적격 계약 Q의 최대 단계 총액을 campaign_available(-Q), offer_hold(+Q)로 옮긴다. 두 budget window의 reserved를 Q 늘리고 offer·quote·operation 결과를 만든다. 실패 시 후보를 무한 순회하지 않으며 최대 후보 수를 참조값 20으로 제한한다. 관련 결과가 없으면 202 operation no_offer이며 소재/가짜 보상은 없다.

**TX-05 Decline/Expiry:** 아직 시작하지 않은 offer만 종료한다. hold 잔액 H를 캠페인으로 반환하고 원래 total/day window의 reserved를 H 줄인다. day가 바뀌었다고 현재 day window에 credit하지 않는다. active session·evidence_pending·review_pending은 이 경로로 해제하지 않는다.

## 5 TX-06~09 승인·노출·보상

**TX-06 Consent:** owner/session/fresh action·quote hash·expires_at·최신 preference를 확인한다. consent·offer consented/version·fresh 소비·멱등 결과를 같은 TX에서 만든다. 동의는 소재 표시만 허용하고 spend·구독·지갑 이전은 허용하지 않는다.

**TX-07 Start:** 최신 consent/version·철회·campaign 새 노출 허용·quote를 검사한다. owner global→advertiser→campaign attention window를 정렬해 잠근다. 참조 max_view=30,000ms, 남은 사용자 시간과의 최소값을 예약하되 최소 15,000ms를 충당하지 못하면 거부한다. count도 동시에 검사한다. 새 세션·초기 nonce·시작 횟수 예약·startup deadline을 커밋한다.

R0 attention day는 UTC로 고정한다. `day_end - now < startup_allowance(10초)+max_view_ms`면 start를 `attention_window_closing`으로 거부하고 다음 UTC day 재시도를 안내한다. 이는 하루 경계를 넘기는 예약 분할을 R0에서 피하는 구현 규칙이다. 돈이 새로 청구되거나 승인 조건이 바뀌지 않으며 offer가 유효하면 다음 창에서 다시 시작할 수 있다.

**TX-08 Evidence/Close:** session·nonce·sequence를 잠근다. 동일 sequence/hash의 replay는 이전 결과, 다른 hash는 409다. 서버 수신 시각을 저장하고 next nonce를 한 번 회전한다. complete는 evidence manifest/cutoff를 고정하고 verifier outbox를 생성한다. cancel은 수집을 멈추고 기존 prefix의 판정을 예약한다. GET 소재/조회는 시간·금액·동의를 변경하지 않는다.

**TX-09 Award:** verifier가 채택한 manifest와 qualified_at, stage contract, 아직 미지급 유일 키를 검사한다. offer/hold/budget/account를 잠그고 Q를 hold에서 꺼내 사용자·operator·direct·platform으로 정확히 배분한다. 두 window에서 reserved-=Q, spent+=Q를 적용한다. stage_award·journal·offer awarded·receipt pending·서명 outbox·사실 사건·operation을 함께 커밋한다. signature 호출이나 HTTP callback을 여기서 수행하지 않는다.

배분은 사용자/운영자/직접비를 `floor(Q*bps/10000)`으로 계산하고 잔여 최소 단위는 고지한 platform 몫에 넣는다. 계약 bps 하한과 반올림 후 실제 수량을 구분해 표시한다. user=0은 거부한다. 추가 단계는 별도 key/hold/판정이며 P1이 awarded여도 미결 추가 단계의 예약은 유지한다.

## 6 ledger commit 검증

PostingCommand는 source/destination account의 asset·purpose·소유 근거·금전 사건을 타입으로 받는다. 한 command에서 같은 account의 delta를 먼저 합치고 정렬 잠금한다. delta 합 0, beneficial 비음수, uint 범위, source 가용, event 유일성을 확인한다. journal·postings·잔액을 같은 TX에 넣는다.

```sql
-- 후보 패턴: 모든 account를 이미 고정 순서로 잠근 상태
UPDATE adc2_accounts
SET balance_atoms = balance_atoms + :delta
WHERE id = :account_id AND asset_id = :asset_id
  AND balance_atoms + :delta BETWEEN 0 AND :uint256_max;
-- 실제 구현은 영향 행 수 1을 확인하고, 하나라도 실패하면 TX 전체 rollback
```

외부 clearing은 별도 제한된 posting command만 사용하며 위 비음수 조건을 문자열로 우회하지 않는다. journal balance는 commit-time 검증도 추가한다. deferred trigger를 구현한다면 관련 journal의 최종 postings 전체와 asset 일치·line 유일성을 확인하고, 권한 없는 사용자가 trigger를 비활성화하거나 posted row를 변경하지 못하게 한다. 검사 함수·role·trigger DDL의 시험은 WP-02에 포함한다.

계약 이행·환불·출고의 ledger kind를 고정 enum으로 제한한다. R0 test seed는 model asset에만 연결되는 별도 fixture 명령이며 HTTP 발행 경로가 아니다. 프로덕션 실행 role에 일반적인 임의 credit/mint 명령을 제공하지 않는다.

## 7 유효 시간·한도 해소

첫 검증된 positive heartbeat는 0ms 시작점이다. 이후 인접 구간에서 nonce/sequence 일치, 양 끝 foreground/visible, 서버 간격<=3,000ms, client elapsed 단조 증가·서버 경과와의 허용 오차를 검사한다. 유효 구간 길이는 서버/클라이언트 경과의 보수적인 최소값으로 누적하며 중복/겹침을 제외한다. 기본 heartbeat 간격은 1,000ms, 과도한 호출은 제한한다.

first positive부터 30초 상한 안의 구간만 합산한다. 15초 충족은 qualified_at을 기록하고 그 이후 cancel/complete·verifier 지연과 분리한다. first signal이 10초 startup 기한을 넘으면 새 유효 노출을 시작하지 않는다. evidence 제출의 600초 TTL은 늦은 제출·검토를 위한 기한이며 600초 시청을 허용하는 값이 아니다.

관측 시간은 보상 자격과 attention 사용량에서 다르게 관리할 수 있다. 세션 시작 시 예약된 count는 광고 피로 제한상 보수적인 시작 횟수이고 사람 노출 매출이 아니다. 증거가 완전히 없거나 불명확하면 시간 quota를 보수적으로 소비할 수 있지만 광고주에게 유효 노출로 청구하지 않는다. 정상 종료 시 남은 시간 예약은 한 번 반환한다.

startup/active session 종료, evidence_pending, review_pending, awarded 상태를 각각 다룬다. 자금 hold 해소와 attention 예약 해소는 다른 명령이다. unknown/검토 중인 금전 hold를 단순 시간 quota 해소에 연동하지 않는다.

## 8 조회·집계·보존

INDEX는 owner/offer/state, advertiser/campaign/state, campaign window unique, expiry가 있는 live hold, outbox state/available_at, report obligation/time을 우선한다. nonce·economic event key·원본 주문 사건의 유일성은 캐시가 아닌 DB 제약이다. 원장 합계를 매 요청 full scan하지 않고 권한 있는 대사 작업에서 독립 재계산한다.

보고 snapshot은 한 REPEATABLE READ 시점의 qualifying facts 목록·방법·cutoff·manifest hash를 보존한다. sequence의 MAX나 최대 UUID가 커밋 순서를 보장한다고 가정하지 않는다. 늦게 커밋된 작은 ID의 사건은 다음 정정 revision으로 포함한다. snapshot이 누락되거나 원본 watermark가 불확실하면 incomplete/delayed를 표시한다.

evidence 원문은 기본 개발 참조 30일, 보안 세부 로그 90일, 회계/계약 핵심 기록 5년 참조로 목적을 분리하되 실제 관할·약정·분쟁 보존 검토 전 확정 보존 정책으로 활성화하지 않는다. 삭제는 원장·청구권을 없애는 수단이 아니다. 개인정보와 연결되는 hash도 접근·보존 대상으로 취급한다.

기술 근거: [PostgreSQL 격리](https://www.postgresql.org/docs/18/transaction-iso.html), [SELECT locking/SKIP LOCKED](https://www.postgresql.org/docs/18/sql-select.html), [JCS RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html). 문서 버전은 의미 확인용이며 현재 운영 PostgreSQL 버전을 확인했다는 뜻이 아니다.
