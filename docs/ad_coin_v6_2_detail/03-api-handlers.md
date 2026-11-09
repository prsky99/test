# 03 API 29개 상세 처리 명세

2026-11-08 · [목차](../AD_COIN_V6_2_DETAILED_DESIGN.md) · [고정 OpenAPI](../ad_coin_platform_p1_v6_2.openapi.json)

모든 API는 01의 C00~04와 02의 잠금 규약을 따른다. path/query/body 타입·required·HTTP 응답 schema는 OpenAPI가 기준이다. 아래 TX는 내부 처리 단위이며 같은 command의 하위 함수가 별도 커밋하지 않는다. GET은 금전·동의·시간을 변경하지 않는다. JSON Schema 통과 후에도 아래 의미·권한 검사를 수행한다.

구현 재검수(2026-11-08): `v2/http.py`의 operation 집합은 고정 계약의 29개와 일치하며 모델 처리·응답 검증을 구현했다. 세 가지 human challenge 목적도 모델에서 처리한다. API-14/21/22의 비동기 응답은 계약대로 202다. 실제 로그인/IdP·TLS 검증을 대신하는 것이 아닌 in-process 모델 credential registry와 주입한 인증 검증 callback을 사용하며, 운영 앱에는 mount하지 않았다. `revise_campaign`은 HTTP 계약의 operation이 아닌 내부 모델 보조 함수다. 승인/재원 배정 후 조건 수정은 허용하지 않으며 새 draft가 필요하다. UI·운영 인증·키/role·복구/성능/브라우저 인수는 미완료다. 아래는 완성 목표이며 모델 코드와 시험만으로 R0 출시 완료를 주장하지 않는다. [재검수 근거](../../reports/ad-coin-v6.2-development-2026-11-08/wp04-review/README.md)를 따른다.

## 1 공개·사람 설정

### API-01 getCapabilities

`GET /capabilities` → Capabilities. 공개·읽기 전용. 활성화 manifest에서 policy=v6.1, contract=v6.2, model, real_value=false, P1·platform_text_v1, 외부 adapter 목록 공백·외부 모델 비활성·보고/영수증 profile을 반환한다. 내부 DSN·키 경로·모델·운영 profile 원문을 노출하지 않는다. 실제 환경이 계약과 다르면 model이라고 거짓 표시하지 않고 해당 v6.2 R0 router를 열지 않는다.

### API-02 getAsset

`GET /asset` → AssetView. 공개·읽기 전용. R0 asset_id·namespace=model·decimals=6·redeemable=false만 반환한다. 최초 공급 0이라는 자산 설계와 fixture의 시험 잔액을 구분한다. 비활성 실제 자산 주소를 임의 채우지 않는다.

### API-03 createHumanChallenge

`POST /human-challenges` ChallengeRequest → ChallengeView. 사람 session+CSRF만 허용한다. action registry로 destination method/path·target 종류를 결정하고 target_revision_hash·session·현재 인가를 확인한다. semantic request digest는 실행 시 다시 계산한다. 무작위 일회 proof를 생성해 hash·기한만 저장한다. target이 own preferences/offer/승인 가능한 campaign이 아니면 거부한다. 이 POST는 승인·광고 노출·예산 소비를 실행하지 않는다. 같은 key 재조회는 같은 challenge를 기한 안에 반환하며 만료됐다면 새 의도를 새 key로 요청한다.

### API-04 getAdPreferences

`GET /ad-preferences` → PreferencesView. 사람 자신의 provisioning된 설정만 조회한다. id·revision_hash·version/ETag·수신 여부·전체/캠페인 횟수·시간을 반환한다. GET에서 기본 허용 설정을 만들지 않는다. 설정이 없으면 계정 provisioning 미완료 오류로 처리하고 운영/온보딩 절차로 복구한다.

### API-05 setAdPreferences

`PUT /ad-preferences` PreferencesRequest → PreferencesView. 사람 전용, fresh set_ad_preferences와 If-Match 필수. 목적·context allowlist·상한을 검사하며 receive_offers=false를 맥락 공유·지출 허락으로 해석하지 않는다. authority/preference/fresh를 잠가 설정·revision_hash/version·owner epoch·audit·멱등 결과를 커밋한다. 철회는 신규 offer/start를 즉시 막고 기존 세션 수집 종료를 outbox로 알린다. 이미 취득한 보상은 보존한다. 세션 작업자가 늦게 통지를 받아도 새 start는 최신 epoch 검사로 거부한다.

## 2 광고주·심사·집행

### API-06 createCampaign

`POST /advertisers/{advertiser_id}/campaigns` CampaignRequest → CampaignView. 사람 campaign.edit와 해당 advertiser membership을 검사한다. taxonomy/region·기간·UTC·total/day 한도·텍스트 길이·renderer·split·사용자 0 보상 거부를 의미 검증한다. TX-01로 draft와 revision을 만들고 approval_status=unapproved를 반환한다. advertiser 잔액은 아직 옮기지 않는다. 서버가 만들지 않은 account·review·판정 필드는 받지 않는다.

### API-07 getCampaign

`GET /advertisers/{advertiser_id}/campaigns/{campaign_id}` → CampaignView. campaign.read와 두 path 객체의 실제 관계를 검사한다. 현재 state·approval_status·content revision hash·version/ETag를 반환한다. operator의 상태 변경도 version에 반영한다. 다른 advertiser의 ID 조합은 404이며 잘못 연결된 campaign 이름을 오류에 포함하지 않는다.

### API-08 requestReview

`POST .../campaigns/{campaign_id}/review-request` ReviewRequest → ReviewView. campaign.edit·If-Match·현재 content hash를 확인한다. TX-02로 허용된 draft/rejected 상태를 잠가 in_review, review pending/version을 기록하고 심사 작업 outbox를 만든다. 같은 revision의 pending 요청은 유일 제약으로 합친다. R0는 수정용 숨은 endpoint가 없으므로 다른 소재로 바꾸려면 새 draft가 필요하다. 사람-facing response에 review 서비스 자격·운영 증거 원문을 넣지 않는다.

### API-09 decideReview

`POST /reviews/{review_id}/decisions` ReviewDecision → ReviewView. reviewer token+mTLS·creative.review·review audience와 If-Match가 필수다. evidence_ref가 현재 revision의 허용된 검토 자료를 가리키는지 확인한다. TX-02로 review와 campaign을 잠가 verdict/근거/reviewer·campaign eligible 또는 rejected·version을 함께 반영한다. R0 입력 verdict는 eligible/rejected만 허용하며 미래 eligible_limited를 임의 실행하지 않는다. 이미 종료된 판정을 다른 HTTP key로 바꾸면 409이며 정정·이의 제기는 별도 감사 명령이다.

### API-10 getReview

`GET /reviews/{review_id}` → ReviewView. 동일 reviewer service 경계로 현재 revision·state·version/ETag만 조회한다. 공개/사람 advertiser가 이 경로에 우회 접근하지 않는다. advertiser는 자기 campaign GET으로 집행 가능 상태를 확인한다.

### API-11 approveCampaign

`POST .../campaigns/{campaign_id}/approvals` ApprovalRequest → CampaignView. 사람 budget.approve·fresh approve_campaign·If-Match·현재 review eligible·기간·소재/예산 hash를 검사한다. TX-02에서 fresh 소비·approval·approval_status=approved·version을 함께 기록한다. editor 자격만으로 승인하지 못한다. stale hash/ETag는 409로 현재 campaign 재조회·새 승인을 요구한다. 승인은 활성화/입금/노출 그 자체가 아니다.

### API-12 activateCampaign

`POST .../campaigns/{campaign_id}/activation` RevisionRequest → CampaignView. budget.approve·If-Match·content hash·현재 승인/심사·환경·asset·기간·안전 중지를 확인한다. TX-03으로 최초 총예산 배정을 한 번 수행한다. 부족한 예산은 409 insufficient_budget이며 active도 journal도 남기지 않는다. 허용된 resume은 기존 배정 상태를 재사용한다. activation은 report obligation 계획도 outbox에 넣고 campaign version을 올린다. R0는 starts_at 전 사전 활성화를 허용하지만 실제 offer 제공은 starts_at<=now<ends_at을 반드시 검사한다.

### API-13 pauseCampaign

`POST .../campaigns/{campaign_id}/pause` PauseRequest → CampaignView. 사람 campaign.pause와 If-Match를 확인한다. campaign을 잠가 paused·version·신규 dispatch 차단 epoch와 통지를 기록한다. 기존 hold는 일괄 반환하지 않는다. 아직 노출 전인 offer는 정리 작업으로, 이미 수집/검증 중인 것은 권리 보존 규칙으로 처리한다. pause가 영수증·확정 원장·보고 기록을 삭제하지 않는다.

## 3 제안·동의·노출

### API-14 requestOffer

`POST /offers` OfferRequest → 202 OperationView. 사람 또는 owner와 결속된 agent의 offers.request를 허용한다. 입력은 허용 taxonomy·language·coarse region·일반 추천 selection digest뿐이며 원문 대화나 client가 정한 user/operator ID를 받지 않는다. 최신 preference/grant와 실제 지원 범위를 확인하고 읽기 후보 선택 후 TX-04에서 재확인·예약한다. operation이 succeeded일 때 own offer resource_id로 조회한다. no_offer는 빈 결과이며 조회 권한 밖 campaign·재원 부족자의 신원을 드러내지 않는다.

### API-15 getOffer

`GET /offers/{offer_id}` → OfferSummary. 사람 owner 또는 현재 binding에 허용된 agent의 offers.read를 검사한다. 광고주 식별·정확한 split·user wallet·기한·노출 기준·모형 사용 조건·광고 표시를 반환한다. 승인 전 소재/원격 추적 URL/쿠키 요청을 포함하지 않는다. expires_at이 지났더라도 GET이 원장을 정리하지 않는다. UI는 기한을 보고 승인 버튼을 끄고, 최종 상태 전이는 정리 command가 담당한다.

### API-16 declineOffer

`POST /offers/{offer_id}/decline` DeclineRequest → OfferSummary. owner/binding의 offers.decline과 현재 state를 검사한다. TX-05로 reserved/아직 미시작 consented 제안을 종료·hold 반환·거절 빈도 기록한다. 이미 exposing 이후면 세션 cancel 경로를 안내하는 state conflict다. 원래 key 재조회는 같은 결과이며 새로운 key가 추가 환불을 만들 수 없다. 거절 사유로 일반 추천 품질을 낮추지 않는다.

### API-17 approveOffer

`POST /human-consents` ConsentRequest → ConsentView. 사람 owner의 fresh approve_offer·quote hash·기한·최신 preference·campaign 새 노출 자격을 검사한다. TX-06에서 해당 offer/owner/fresh를 결속한다. agent key·reviewer·광고주 owner·브랜드 service는 사람을 대신해 이 API를 수행하지 못한다. 성공 뒤에도 사용자가 start를 하지 않으면 소재를 표시하거나 보상을 지급하지 않는다.

### API-18 startExposure

`POST /exposure-sessions` ExposureRequest → ExposureView. 사람 owner·consent/version·quote·기한·현재 철회/중지·동시 세션·전체/캠페인 quota를 검사한다. TX-07에서 세션·시간/횟수 예약·초기 nonce·startup/evidence deadline을 생성한다. min 15초를 충당할 시간 또는 당일 창이 없으면 409로 거부한다. 계정별 시작 횟수는 유효 사람 노출 매출 지표가 아니다.

### API-19 getApprovedCreative

`GET /exposure-sessions/{session_id}/creative` → CreativeView. 같은 사람 owner·활성 consent/session·renderer·기한을 확인한다. 승인한 creative revision/hash의 plain text와 Advertisement 표시만 반환한다. 같은 origin HTML 실행·외부 픽셀은 없다. GET 자체로 시간·보상·attention 소비를 갱신하지 않는다. 클라이언트가 URL만 알아도 다른 사람의 소재를 열 수 없고 token을 URL query에 넣지 않는다.

### API-20 submitEvidence

`POST /exposure-sessions/{session_id}/evidence` EvidenceRequest → ExposureView. 사람 session·owner·현재 수집 허용·nonce·sequence·size/rate·30초 active 상한을 검사한다. TX-08로 immutable chunk·다음 nonce·보수적 시간 상태를 반영한다. client elapsed/visible/foreground는 claim이며 판정 필드를 받지 않는다. 동일 sequence/hash replay에서 nonce를 또 회전하지 않는다. nonce/내용 불일치 409, 미지원 자료 422, 제한 초과 429다.

### API-21 completeExposure

`POST .../{session_id}/complete` CompleteRequest → 202 OperationView. owner·last_sequence와 실제 저장 prefix를 확인한다. TX-08로 수집 cutoff/manifest를 고정하고 evidence_pending·verifier 작업을 만든다. last_sequence 뒤 자료를 슬쩍 끼워 판정 결과를 바꾸지 못한다. 요청 수락은 지급 확정이 아니며 operation 조회가 succeeded/review_pending/failed를 반환한다. 반복 완료가 새 verifier 경제 사건을 만들지 않는다.

### API-22 cancelExposure

`POST .../{session_id}/cancel` CancelExposureRequest → 202 OperationView. 사람 owner가 명시적 중지를 요청한다. 같은 session을 잠가 수집 종료 cutoff·현재 evidence prefix를 고정한다. 이미 qualified면 판정/지급 절차를 보존하고, 미달이면 취소·attention 해소·안전한 hold 해제로 진행한다. 불명확하면 review_pending이다. cancel을 검증 중 권리나 확정 지급을 강제 취소하는 API로 쓰지 않는다.

## 4 비동기 결과·지갑·영수증

### API-23 getOperation

`GET /operations/{operation_id}` → OperationView. 현재 사람/agent의 operations.read와 operation의 owner/원래 binding·grant를 확인한다. pending/running/review_pending/succeeded/failed/no_offer와 허용된 result/receipt ref를 반환한다. 다른 주체의 key를 추측해 operation을 조회할 수 없다. 에러가 생겼다고 원래 effect를 새로운 operation으로 자동 실행하지 않는다.

### API-24 getWallet

`GET /wallets/{wallet_id}` → WalletView. 사람 owner 또는 wallet.read가 허용된 agent의 해당 관리 범위를 확인한다. asset별 available/locked atoms, user_owned, model을 반환한다. agent가 다른 manager 하위 지갑까지 일괄 볼 수 있는지는 별도 grant가 필요하다. 임시 보관을 operator 매출로 보이게 하지 않는다. R0는 외부 출금/AI 결제 기능을 이미 제공한다고 표시하지 않는다.

### API-25 getReceipt

`GET /receipts/{receipt_id}` → ReceiptView. owner/binding의 receipts.read와 원래 award 관계를 검사한다. 원장 확정 후 signature pending이면 key_id/JWS=null을 반환한다. signed면 고정된 JWS·key_id·issuer/audience·정확한 보상·quote·시점을 반환한다. 영수증 조회가 서명 재생성이나 지급 재시도를 유발하지 않는다. 서명 key가 침해됐어도 사용자 확정 journal을 지우지 않고 검증 상태/분쟁 절차를 운영한다.

### API-26 getReceiptKeys

`GET /receipt-keys` → ReceiptKeySet. 공개 읽기 전용. 지정 issuer의 Ed25519 공개 JWK·kid·active/verify_only/revoked·검증 기간만 반환한다. private d·key-service 경로·원시 키 저장 정보를 노출하지 않는다. API가 반환한 JSON 자체가 서명의 신뢰 루트는 아니며 HTTPS의 고정 서비스 경로와 배포된 신뢰 설정을 따른다. 영수증의 임의 URL을 따라 키를 수집하지 않는다.

## 5 광고주 보고

### API-27 getReportingStatus

`GET /advertisers/{advertiser_id}/reporting-status` → ReportingStatus. 사람 advertiser reports.read와 cursor 범위를 확인한다. 등록된 obligation을 period/id 기준 keyset pagination으로 반환한다. limit<=200, cursor는 tenant·필터·최종 key·기한을 결속한 opaque 값이다. waiting/available/delayed/action_required와 정확한 immutable report ref를 제공하고 미도착 보고를 0으로 숨기지 않는다. GET이 report generation이나 billing을 실행하지 않는다.

### API-28 getReportRevision

`GET /advertisers/{advertiser_id}/reports/{report_id}/revisions/{revision}` → ReportRevision. reports.read·tenant·report/obligation 연결을 검사하고 정확히 그 revision을 반환한다. 최신 revision으로 몰래 치환하지 않는다. content digest·supersedes·data_through·method·first_party·complete·metrics의 상태/단위를 표시한다. R0 unique_owners는 계정 권리자 수이며 고유한 사람 수로 표현하지 않는다. 이미 만료/삭제된 content의 tombstone은 유지해 ‘새 보고 없음’과 구별한다.

### API-29 recordReportConsumption

`POST /advertisers/{advertiser_id}/reports/{report_id}/consumption` ReportConsumptionRequest → ReportConsumptionView. 사람 reports.acknowledge·CSRF·같은 tenant/revision 접근을 검사한다. received/content_mismatch는 observed_digest가 필요하고 received는 원본 digest와 같아야 한다. missing/unreadable은 null을 허용한다. consumption 이력·operation·멱등 결과만 기록하며 journal·campaign 예산·보상·보고 원문을 변경하지 않는다. 서로 다른 소비자의 상태를 하나로 덮어쓰지 않는다.

## 6 계약 오류와 후속 API

상세 카탈로그는 operationId와 이 API 번호를 일대일로 연결한다. 같은 거래를 위한 client 호출을 무조건 다시 보내는 SDK retry를 만들지 않는다. 429/503은 recovery 지시·동일 key·기한을 따른다. 불명 결과는 GET operation/report 조회로 확인하고 자기 권한 밖 상세 오류를 노출하지 않는다.

funding·transfers·payments·brand sessions·CRM·market queries·revision 편집·관리 복구 명령은 04의 확장 계약을 따른다. R0에 없는 endpoint를 29개 계약에 있는 것처럼 호출하거나 mock 성공을 실제 성공으로 반환하지 않는다. 확장마다 목적별 인증·OpenAPI·migration·부정/복구 검수를 함께 추가한다.
