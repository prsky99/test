# 01 도메인·권한·공통 처리

2026-11-08 · [상세 설계 목차](../AD_COIN_V6_2_DETAILED_DESIGN.md)

## 1 모듈 간 명령 계약

M01 identity는 `resolve_principal`, `authorize_object`, `lock_authority_guard`, `verify_fresh_action`을 제공한다. M02 commercial은 `create_campaign`, `submit_review`, `decide_review`, `approve_revision`, `activate_campaign`, `pause_campaign`을 소유한다. M03 delivery는 `reserve_offer`, `consent_offer`, `start_exposure`, `append_evidence`, `close_evidence`, `cancel_exposure`를 소유한다. M04 economy만 `post_journal`, `reserve_budget`, `consume_stage`, `release_hold`를 호출할 수 있다.

M05 fulfillment는 `authorize_payment`, `bind_execution`, `settle_execution`, `refund_case`; M06 treasury는 `authorize_funding`, `project_finalized_event`, `request_withdrawal`, `request_redemption`, `reconcile_checkpoint`; M07 measurement는 `append_fact`, `publish_report_revision`, `record_consumption`; M08 intelligence는 `query_approved_aggregate`; M09 operations는 `set_pause`, `resolve_case`, `approve_activation`을 소유한다.

command 입력은 principal의 서버 생성 참조, command_id, contract_version, target revision, typed payload, idempotency context다. 결과는 domain result 또는 고정된 error code이며 ORM row·예외 stack·개인 토큰을 직접 반환하지 않는다. 외부 payload가 principal·권한·판정·분개를 직접 만들 수 없다.

repository는 명시적 `UnitOfWork`만 받는다. command가 transaction을 시작하고 내부 ledger가 별도 커밋하지 않는다. read-only projector와 worker도 원장 쓰기 우회 메서드를 갖지 않는다. ledger의 unit test 성공이 호출자의 인가 성공을 의미하지 않는다.

## 2 Principal과 권리자

Principal은 `principal_id`, kind, subject_owner_id, organization_memberships, agent_binding_id, audience, capabilities, credential_epoch, expires_at을 가진 불변 요청 객체다. 사람·agent·buyer/publisher/merchant/measurement service·reviewer/ops 종류를 인증 계층에서 고정한다. credential 자체는 로그·DB 업무 row에 저장하지 않는다.

scope는 가능한 동작의 상한이다. 최종 판정은 객체 소유·조직 역할·권리자의 grant·금액/횟수·기한·철회·기능 중지까지 포함한다. viewer는 read, editor는 draft/심사 요청, budget approver는 승인·활성화, reviewer는 별도 review service에서 심사 판정을 수행한다. 대행사 조직 owner가 모든 광고주 예산을 쓸 수 없다.

사용자 지갑의 owner는 사람/조직 권리자이며 agent는 manager다. 직접 이용자 기본 지갑과 owner+agent 관리 하위 지갑은 다른 account ID지만 같은 사용자의 권리다. 수신 agent가 철회되면 견적에 고지한 같은 owner의 기본 지갑 fallback만 허용한다. 사용자 변경·operator 귀속은 금지한다.

계약 이행을 위한 이미 획득한 보상 크레딧과 새로운 agent 지출 권한을 구분한다. agent 철회는 미확정 사용자 권리를 operator 자산으로 바꾸거나 확정 지급을 취소하지 않는다. 확정 보상 조회는 사용자 소유권으로 허용하고, 철회된 agent 자격은 과거 operation 재조회에도 사용할 수 없다.

## 3 HTTP 공통 파이프라인 C00

1. reverse proxy와 애플리케이션에서 최대 비압축 body 32,768 bytes를 제한한다. stream 중 상한을 확인하고 과도한 압축·깊이·수신 시간을 중단한다. JSON UTF-8·허용 content type·중복 key·비정규 숫자·허용 field를 검증한다.
2. 계약을 선택한다. R0 쓰기는 `X-AIAC-Contract: v6.2`가 필수다. 같은 header의 중복·상충 값은 거부한다. 공개 capability 조회만으로 영업 계정·금융 권한이 생기지 않는다.
3. 인증 수단을 해석한다. human cookie와 machine credential의 혼합은 거부하며 header 우선순위로 더 높은 권한을 고르지 않는다. 사람 cookie 쓰기는 CSRF·Origin·세션 만료를 검사한다. review route는 지정 audience의 token과 mTLS를 모두 요구한다.
4. UUID path·query·본문을 타입화하고 다른 tenant/owner 객체는 404로 처리한다. 단순 입력 오류를 타 객체 존재 여부의 신호로 사용하지 않는다.
5. 현재 인가와 rate/body 한도를 검사한 뒤 멱등 기록을 조회/확보한다. 동시 같은 key는 unique 제약을 통해 한 소유 operation으로 수렴한다. 409 충돌은 새 key로 금전 재시도를 지시하는 응답이 아니다.
6. 해당 TX의 고정 잠금 순서로 객체를 읽고 최신 권한·grant epoch·중지·ETag·fresh action을 확인한다. commit 직전 필요한 상태를 다시 비교한다. 외부 HTTP·모델·키 서비스 호출은 잠금 중에 하지 않는다.
7. 업무 상태·분개·카운터·fresh 소비·operation·outbox·idempotency 응답 snapshot을 함께 커밋한다. read projection은 권한에 맞는 DTO만 만든다.
8. HTTP 응답에는 안전한 error/request_id와 `no-store`를 반환한다. campaign/review/preferences는 ETag를 반환한다. `Idempotency-Replayed: true` header가 있으면 과거 결과이며 화면은 필요 시 GET으로 최신 상태를 다시 읽는다.

외부 공개 실패 응답에는 원문 body·SQL·운영 주소·모델·키 경로·stack을 포함하지 않는다. 내부 감사도 최소 actor ID·target ID·event/code·revision·근거 참조만 기록한다. 보안 로그에 세션·proof·JWS 원문·사용자 맥락을 출력하지 않는다.

## 4 두 가지 digest와 fresh action C01

canonical form은 계약 버전이 고정한 RFC 8785 JCS를 사용한다. 금액은 문자열이고 sequence/version/시간 정수는 안전한 정수 범위로 제한한다. 잘못된 Unicode surrogate·중복 JSON key를 canonicalization 전에 거부한다. 광고 텍스트를 임의 NFC 변환·번역해 원래 계약 hash를 바꾸지 않는다.

semantic digest는 `contract_version, action, method, canonical_target, target_revision_hash, preconditions, semantic_body`의 JCS SHA-256이다. semantic_body는 실제 command body에서 `fresh_action_id/fresh_action_proof`만 제외한다. preconditions에 If-Match를 넣는다. target_revision_hash는 campaign의 business revision, offer의 quote hash, preferences의 현재 설정 hash로 해석한다.

idempotency digest는 `contract_version, method, canonical_target, preconditions, validated_body` 전체를 결속한다. scope는 `(environment, principal_id, method, route_template, Idempotency-Key)`이며 target/body/계약이 달라지면 409다. 계약 version을 scope에 추가해 같은 key를 새 금전 사건으로 재실행하지 않는다.

fresh challenge는 목적·owner·session binding·target hash·semantic digest·If-Match·expires_at·challenge_hash를 저장한다. plaintext proof는 해당 사람 세션에만 전달한다. 참조 TTL은 120초이며 승인된 노출 시간/토큰 증거가 아니다. 사람의 실제 생물학적 존재·집중을 nonce echo로 증명했다고 표현하지 않는다.

challenge 생성은 행위 실행이 아니다. 승인 command의 TX가 challenge row를 잠가 현재 principal/session·동작·target·digest·기한을 비교하고 `consumed_by_operation`을 기록한다. challenge는 다른 operation으로 재사용할 수 없다. 같은 key·같은 요청의 응답 재조회는 proof를 다시 소비하지 않지만 현재 접근 권한을 확인한다.

R0는 challenge를 세 동작에만 발급한다: set_ad_preferences, approve_offer, approve_campaign. 고위험 외부 금전 행위에는 별도 step-up 인증 검증 결과·수취인·자산·금액·기한을 결속하며 단순 approve_offer proof를 재사용하지 않는다.

## 5 불변 revision과 변경 가능 version C02

campaign business revision은 소재·보상·배분·기간·지역·asset·renderer·예산 조건의 hash다. entity version은 심사 요청·심사 판정·승인·활성화·중지 때 증가하는 integer다. ETag는 type/id/version을 결속한 opaque 값으로 만들고 서버가 검증한다. 클라이언트가 ETag를 해석해 권한을 얻지 않는다.

예: revision H인 campaign v1 draft → v2 in_review → v3 eligible → v4 approved → v5 active. H는 같고 ETag만 바뀐다. 소재를 바꾸면 H2의 새 revision·심사·승인이 필요하다. R0 공개 29개 API에는 편집 revision 생성이 없으므로 rejected 소재 수정은 새 draft campaign으로 진행하며, 숨은 update 경로를 만들지 않는다. 후속 revision API는 별도 계약을 추가한다.

read·정확한 멱등 replay는 version을 올리지 않는다. DB에 영향을 주는 operator/worker의 상태 변경도 version을 올린다. 임의로 version을 되돌려 stale approval을 유효하게 만들 수 없다.

## 6 철회·pause·이미 발생한 권리 C03

새 제안/새 노출/새 지출은 최신 preference/grant/campaign state로 허용한다. offer approval 시점의 정보를 근거로 지금 철회된 권한을 재사용하지 않는다. 노출 중 중지는 수집 종료 cutoff와 현재 증거를 원자적으로 기록하며 이미 충족한 단계의 자격은 보존한다.

qualified_at은 고정 verifier가 서버에 수신된 검증 가능 구간으로 산출한 최초 충족 시각이다. client timestamp 하나로 철회 전 자격을 주장할 수 없다. cutoff 이전 증거로 조건을 충족하면 후속 verifier 지연에도 지급한다. 조건 미달은 중단·미지급이며, 수신 지연 등으로 판정이 불명확하면 review_pending으로 보존하고 약정 검토 기한을 적용한다. 검토 중 hold를 만료 처리하지 않는다.

pause는 새 dispatch/offer/start를 막는다. 시스템 보안 사고로 검증기를 중지할 때 기존 증거·hold·권리를 보존하며 대체 판정을 임의 생성하지 않는다. 과거 분개를 수정하는 대신 사유가 있는 조정 분개와 운영 책임 재원으로 분쟁을 해결한다.

## 7 오류·재시도 C04

인증 없음 401, 권한·목적 위반 403, 타인 객체 404, stale version/idempotency/state/예산 충돌 409, schema·보상 조건 위반 422, 크기 413, 한도 429, 안전 중지·의존 장애 503을 쓴다. recovery.action은 reauthenticate, refresh_resource, poll_operation, wait, contact_support, do_not_retry 중 하나다.

poll_operation은 소유자가 조회 가능한 operation_id를 필수로 반환한다. retry_after_seconds는 최소 1초이며 실제 재시도는 같은 key·같은 본문을 유지한다. `unknown` 금전 요청은 새로운 operation 생성으로 ‘재시도’하지 않는다. 정정·수동 해결은 원본 논리 요청 ID와 근거를 보존한다.

안전한 권한 없는 문법 오류·인가 실패·DB 미커밋 실패는 경제 효과가 없다. 커밋 후 응답 유실은 idempotency/operation 조회로 복구한다. replay 캐시만 남기고 economic event tombstone을 삭제하는 정책은 금지한다.
