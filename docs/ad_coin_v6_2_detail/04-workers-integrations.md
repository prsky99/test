# 04 작업자·외부 연동·확장 명령 상세 설계

2026-11-08 · [목차](../AD_COIN_V6_2_DETAILED_DESIGN.md)

## 1 사건 envelope와 작업 획득

내부 event envelope는 event_id UUID, event_type, schema_version, aggregate_type/id/version, command_id, causation_id, audience, occurred_at, payload_ref, payload_hash를 가진다. 외부 송신에서는 허용한 필드만 투영하고 내부 owner·credential·원장 row를 그대로 내보내지 않는다. payload/schema가 같다는 것과 실행 권한이 있다는 것은 다르다.

outbox lease 기본값은 15초, 긴 작업은 현재 generation 조건으로 갱신한다. 초기 batch 상한 50, 동일 상대에 대한 병렬 호출·회로 차단을 별도로 제한한다. 세부 수치는 부하·키 서비스·파트너 한도 검증 전 개발 참조값이다.

```sql
-- 획득 패턴만 제시한다. 실제 상태 enum·권한·SQL 등록은 WP-02에서 작성한다.
WITH picked AS (
  SELECT id FROM adc2_outbox
  WHERE available_at <= clock_timestamp()
    AND (state IN ('pending','retry')
         OR (state = 'leased' AND lease_until < clock_timestamp()))
  ORDER BY available_at, id
  FOR UPDATE SKIP LOCKED LIMIT 50
)
UPDATE adc2_outbox AS job
SET state = 'leased', lease_owner = :worker_id,
    lease_until = clock_timestamp() + interval '15 seconds',
    lease_generation = lease_generation + 1
FROM picked WHERE job.id = picked.id
RETURNING job.id, job.lease_generation;
```

작업 획득 TX는 짧게 종료한다. 실제 업무 TX는 최신 authority→business→accounts 순서로 다시 잠그고 generation/lease/aggregate revision을 검사한다. 외부 호출 뒤 stale worker가 DB 결과를 확정하지 못하게 한다. 그러나 실제 외부 결과가 사라지지 않도록 별도 검증된 inbox observation으로 기록하고 현재 worker가 대사한다.

retry는 네트워크 일시 실패에만 exponential backoff+jitter, 참조 1초~300초·자동 8회로 제한한다. 더 긴 체인/파트너 조회는 별도 reconciliation schedule이다. dead letter는 금전 잠금 해제가 아니며 운영 담당자에게 안전한 reason/operation ref를 제공한다.

## 2 W01 EvidenceVerifier

입력은 ExposureEvidenceClosed(session_id, manifest_hash, cutoff, verifier_profile)다. 원문 chunk를 arbitrary client 목록에서 읽지 않고 서버에 저장한 immutable prefix/manifest로 조회한다. nonce·순번·서버 시간·가시성·세션·consent cutoff·startup/active 한도·위험 판정을 검증한다.

조건 충족은 qualified_at을 고정하고 TX-09 Award를 같은 논리 stage key로 호출한다. 정상 미달은 rejected/cancelled로 기록하고 자금/attention을 각자의 규칙으로 해소한다. 불명확·심사 필요는 review_pending으로 전환하고 deadline·근거 ref를 유지한다. 민감한 탐지 규칙 전체를 사용자 오류 응답에 출력하지 않는다.

review_max 참조 24시간이 지나면 운영 case로 에스컬레이션한다. deadline 도달이 자동 부정 판정·자동 허위 증거·hold 몰수 사유가 아니다. 결정은 근거와 version을 보존하고 이미 지급한 기본 보상에 대한 단순 성과 부진·부정 평가를 환수하지 않는다. 플랫폼 과실 보상은 별도 운영 재원·경제 key로 처리하며 원래 stage를 두 번 지급하지 않는다.

## 3 W02 ReceiptSigner

입력은 ReceiptRequested(receipt_id, journal_id, payload_hash)다. worker는 실제 확정 journal·award·고정 payload와 현재 서명 권한을 검증한다. DB에 private key를 보관하지 않으며 독립 key service에는 허용 issuer/typ/payload hash/receipt_id만 전달한다. 무제한 임의 메시지 서명 API로 쓰지 않는다.

header는 typ=aiac-receipt+jwt, alg=EdDSA, 승인된 Ed25519 kid다. payload는 ReceiptClaims schema·JCS를 따르고 base64url compact JWS를 만든다. signer 결과를 issuer 공개키로 다시 검증한 후 receipt signed·key_id·JWS와 outbox 완료를 원자적으로 기록한다. 재호출이 원장 command를 실행하지 않는다. 다른 header/payload의 서명이 도착하면 격리한다.

issued_at/iat는 receipt payload를 준비해 발급한 업무 시각이며 journal committed_at과 별도 보존한다. 비동기 서명 완료 시각 signed_at은 내부 감사에 기록한다. iat 자체를 암호학적으로 신뢰할 수 있는 서명 시각 증명으로 판매하지 않는다. 회전 후 과거 사건을 증명할 수 있는 key 사용·검증 조건을 명시하고 key의 현재 서명 권한/issue_until을 검사한다. 그 시각을 증명할 필요가 있으면 별도 타임스탬프/발급 로그 검증을 추가해야 한다.

서명 미확정이면 API는 pending·key_id/JWS=null이다. 폐기 key로 새 서명을 만들지 않는다. 서명 응답 유실 시 동일 receipt/payload를 조회·재요청할 수 있지만 서명만 다시 받으며 보상은 다시 지급하지 않는다. revoked key의 JWT iat만으로 ‘침해 전 서명’이라고 주장하지 않는다. authoritative 발급 기록·기존 journal과 대사하고 필요하면 같은 권리를 새 receipt 증명 버전으로 재인증하는 후속 계약을 심사한다.

## 4 W03 ExpiryAndAttention

작업은 due 대상 ID를 읽은 후 각각의 업무 TX에서 state/version·현재 시간·원본 창을 잠근다. reserved/미시작 consented offer의 기한 종료만 TX-05로 해소한다. started/evidence_pending/review_pending/unknown 자금은 일반 expiry 대상에서 제외한다.

session startup/active deadline은 수집 종료와 verifier 요청을 만들고 attention 예약을 한 번 해소한다. 이후 자금 자격은 W01이 판단한다. 소유자의 전체 시간 quota 해소를 offer 환불로 연결하지 않는다. 모든 release는 hold_id/reason/terminal_version 유일 key와 잔액 검사로 보호한다.

## 5 W04 ReportingPlannerAndPublisher

activation 및 매일 UTC scheduler가 campaign flight에 맞는 obligation을 UNIQUE key로 만든다. 일정 누락은 planner replay로 보충하며 보고 미생성 자체가 obligation을 없애지 않는다. R0의 expected_at은 해당 UTC day 종료 후 15분, 자동 복구 창은 60분 참조다. 이 수치는 실운영 SLA 약정이 아니며 판매 계약 때 version 고정한다.

publisher는 read-only REPEATABLE READ로 유효 P1 award·금전 journal·계정 권리자의 snapshot을 만든다. fact manifest·방법·cutoff·unit·first_party·completeness를 고정하고 report revision·digest·obligation available을 커밋한다. 0건은 measured 0이며 미도착·미측정·억제를 0으로 대체하지 않는다.

late event/정정/환불의 보고 반영은 새 revision과 supersedes를 만든다. 기존 content_digest·행을 수정하지 않는다. report 결과를 입력으로 보상을 다시 지급하지 않는다. 지연된 사실의 원래 노출일·원장 인식일을 구분한다. R0 unique_owners는 계정 owner 수로 한정한다.

후속 report callback은 obligation/revision/digest/operation/audience를 결속하고 수신자가 정확한 같은 revision을 GET으로 복구할 수 있게 한다. consumption received는 digest 일치, missing/unreadable은 복구 절차, content_mismatch는 dispute로 연결한다. 어느 상태도 결제 승인이나 invoice settlement가 아니다.

## 6 W05 ExternalDispatcher와 철회

effect는 prepared → dispatching → observed/completed 또는 unknown/failed로 추적한다. prepared row의 생성만으로 외부 실행 권한이 생기지 않는다. 최신 principal/grant epoch·pause·조건을 검사해 **dispatching을 커밋하는 TX가 실행 인가의 선형화 지점**이다. 이 단계가 상위 설계의 ‘dispatch intent 승인 커밋’에 해당한다.

철회가 먼저 커밋되면 prepared→dispatching이 실패하며 새 송신을 하지 않는다. dispatching 이후에는 이미 송신 중일 수 있어 무조건 회수됐다고 주장하지 않는다. worker가 실제 I/O 전에 죽어도 상태는 보수적으로 unknown으로 다루고 원격의 논리 key/거래 조회·취소 결과로 확인한다. 단순 lease timeout·철회·작업자 재시작으로 hold를 해제하지 않는다.

원격이 idempotency를 지원하면 같은 logical_effect_id와 payload hash를 유지한다. 지원하지 않거나 조회할 수 없는 partner는 자동 금전 재시도를 비활성으로 두고 제한된 수동 해결만 허용한다. 세대가 바뀐 worker도 새 effect ID로 지급을 재생성하지 않는다. 원본 요청·원격 결과의 자산/금액/수취인을 대사한다.

## 7 W06 TreasuryIndexer와 W07 Reconciler

v5의 단일 EVM/ERC-20·USDC 담보 참조안을 따른다. 실제 주소·관할·발행/수탁 주체·최종성은 미정 활성화 항목이다. indexer는 지원 chain/contract/event·RPC quorum·finalized checkpoint를 확인하고 chain_id/block_hash/tx_hash/log_index/contract와 논리 nonce를 함께 기록한다.

최종성 전에는 내부 가용 잔액을 만들지 않는다. 확정된 mint/deposit/withdraw/redeem을 같은 DB checkpoint의 R/S/C/B 투영과 journal에 한 번 반영한다. 다른 asset·주소·입금 목적 미지정은 quarantine이며 사용자 임의 credit이나 플랫폼 수익이 아니다. 최종 블록 재구성·RPC 불일치·USDC 동결은 관련 발행/이동을 닫고 incident로 전환한다.

Reconciler는 원장 전체 분개/잔액·hold·지급/환불·chain checkpoint·수탁 잔액·서명 nonce를 독립 읽기로 계산한다. 원장 누락을 임의 credit으로 맞추지 않는다. 비교 시점·범위·미확정 이동·동결 자산·한계를 기록하며 R>=S, C>=B를 서로 다른 시점으로 조합하지 않는다. 복구 뒤 이 검증 전에는 관련 자금 쓰기를 재개하지 않는다.

## 8 R1 실제 AI 작업·가맹점 명령

**CreatePaymentIntent:** merchant_service가 자기 order_id·asset·정수 금액·provider·고정 execution definition hash·expiry·정산/환불 조건을 등록한다. UNIQUE(merchant,order,business_revision). 가맹점의 요청은 사용자의 지출 승인이 아니다.

**AuthorizePayment:** 사람의 정확한 금액/작업 승인 또는 현재 agent mandate를 검사한다. mandate에는 owner·agent·provider/recipient·action·asset·누적/단건 한도·기간·revocation epoch를 고정한다. mandate 소비·wallet available→locked·payment 상태·실행 outbox를 같은 TX에 넣는다. body actor 생략으로 사용자 직접 지출 모드에 진입하지 않는다.

**BindExecution:** payment_intent_id·execution_id·workflow version/hash·provider/node/call·owner 권한을 결속한다. 이 정의와 다른 최신 workflow를 실행해 같은 이름이라고 정산하지 않는다. run_id를 client 성공 주장만으로 가져오지 않고 허용된 실행 reader로 조회한다. UNIQUE(provider_execution_source,run_id,node/call)로 재사용을 막는다.

**SettleExecution:** 실제 성공/실패/미실행 line을 확정하고 검증한 부분만 locked→provider_payable로 이전한다. 실패/미실행분은 owner 가용으로 반환한다. paid와 fulfilled는 다른 상태다. 이미 provider에게 확정 지급한 뒤의 분쟁 환불은 약정된 provider 환불 자본/플랫폼 운영 재원에서 처리하며 USDC 준비금이나 다른 사용자의 코인을 차감하지 않는다.

**RefundCase:** 원래 결제·line·수량·사유·책임 재원·결정자·refund economic key를 결속한다. 재시도는 한 번의 환불이며 새 광고 발행이 아니다. 정상 부정 피드백·광고 철회를 이유로 사용자의 획득 보상을 빼앗지 않는다.

## 9 R2 발행·이전·상환 명령

**AuthorizeFunding:** 광고주/적격 파트너, 실제 순입금, asset/chain, 정해진 수취 수탁 주소, nonce·기한·한도를 결속한다. 달러 입금 알림만으로 mint하지 않는다. USDC 실제 collateral transfer와 mint는 CollateralVault의 원자적 경로만 사용한다. 중복 입금 claim은 원본 funding intent와 계약 nonce로 막는다.

**RequestTransfer:** 내부 owner→owner/agent 하위 계정 이전은 별도 권한/수취인·자산·한도를 검사하고 B 내부 분개로 처리한다. 새/고위험 수취인은 step-up 결과를 정확한 intent hash에 결속한다. agent는 미등록 수취인·무한 approve로 권한을 확대하지 못한다.

**RequestWithdrawal:** source available→withdraw_locked, 독립 execution/risk 승인, nonce·chain·contract·recipient·amount·deadline을 고정한다. 외부 finalized event 전에 잠금을 반환하지 않는다. outcome unknown은 원래 nonce·대체/취소 거래를 조회하며 새 지급을 만들지 않는다. 확정 시 C/B를 같은 checkpoint에서 줄인다.

**RequestRedemption:** 보유권·상환 자격·공식 USDC 수취인·수수료를 검사하고 토큰 소각+USDC 지급을 같은 계약 TX로 실행한다. 지급 실패/동결이면 소각도 되돌린다. 수탁 상환과 자기보관 상환의 R/S/C/B delta를 구분한다. 사용을 내부 AI에 강제하기 위해 적격 출고·상환을 막지 않는다.

관리 quorum·Guardian·일반 변경 지연·immutable 주소 결속·임의 minter 금지·key 분리는 v5를 따른다. 직접 발행/허가된 발행 파트너·담보 적격성·관할·KYC/AML·상환·파산 권리는 실가치 전에 별도 확정한다. 위 명령 작성 자체가 법적 적합성을 승인하지 않는다.

## 10 R3 외부 광고·중계·브랜드·CRM

**RegisterAdapterProfile:** protocol exact version, schema/build digest, supported/experimental features, signing/key-resolution profile, audience, byte/depth/time bounds, 시험 증거·만료를 승인한다. main/SDK 버전 하나만으로 wire를 추론하지 않는다. 발견 요청은 계정 개설·금전 권한을 만들지 않는다. x402는 명시적으로 선택한 결제 경로에만 연결한다.

**PlanCampaign/MediaProposal:** advertiser 목표·상품 팩·적격 전환 정의·매체/지역·기간·일/총 예산·최대 단가·허용 자동화·측정/운영 비용을 고정한다. 판매 권한이 검증된 inventory에서 지원 상품·renderer·언어·공급·가격·유효기간·보고 계약을 비교한다. 예측은 관측 기간·표본·방법·불확실성을 포함하고 공급량을 보장하지 않는다. proposal은 draft/requested/offered/revised/accepted/rejected/expired로 관리하며 수락한 revision만 booking에 연결한다.

**Reserve/CommitMediaBuy:** 선택 매체·가격·수량/성과·기간·추가 보상·취소/환불·측정 책임을 같은 광고 계약과 자금 한도에 결속한다. 예약/전환 대가는 예산에 이미 포함돼야 하고 같은 인벤토리를 팔았다고 사용자 보상을 이중 발행하지 않는다. 선지급 매체비가 필요하면 고객에게 약속한 hold·준비금이 아닌 확인된 운영/계약 재원을 요구한다. 배분 하한·총비용이 맞지 않으면 매체·단가·상품 범위를 새 사전 견적으로 조정하며 기존 승인 보상을 삭감하지 않는다.

광고 슬롯의 선택은 적격성·사용자 관련성·상품 근거 관문 뒤 고정 버전의 score로 수행한다. 입력 feature·단가 상한·추정 성과·광고 품질·사용자 효용·tie-break를 감사 기록으로 남긴다. 초기에는 결정적 관련성 우선/검증 근거/품질/입찰 tie-break로 시작하고 검증된 실측 뒤 가중치를 개정한다. 이 광고 score를 일반 에이전트 검색/추천에 전달하지 않는다.

**RelayOffer:** original offer/hash·issuer/audience·허용 hop·sender/recipient·parent endorsement·기한·광고 표시를 검증한다. hop 기본 3, cycle/self relay 금지. 중계자의 대가는 승인된 operator pool 안에서 나누고 Q/user 몫을 늘리거나 줄이지 않는다. 잘못된 요약/번역은 거부하며 외부 소재 렌더러가 미검증이면 플랫폼 노출 화면 링크만 전달한다.

**BrandSession:** 사용자 선택 공유 field manifest·상품 팩 revision·상업 역할·대화/도구 비용 cap·기한을 고정한다. 원래 대화 전체 read 권한을 주지 않는다. 활성 대화는 광고 표시·종료·독립 답변 복귀를 제공한다. 긴 대화·토큰 수로 적격 문의·구매를 대신하지 않는다. 추가 보상은 별도 stage 계약을 사전 잠그고 부정 후기에도 동일 약정 지급한다.

**RecordConversion:** measurement service는 tenant/integration·source_event_id·order/business revision·발생/수신 시각·환불/정정·권한 목적을 제출한다. inbox 중복 제거와 원본 주문 유일성으로 다른 event_id를 통한 이중 전환을 차단한다. 서명은 송신자 확인이며 실제 매출의 자동 보증이 아니다. 외부 효과가 원장을 직접 수정하지 않는다.

**Attribute/Experiment:** 원본 fact는 보존하고 attribution rule version·기간·보상 여부·대조군 배정·표본·방법을 고정한다. 정정은 새 투영이다. 약속한 P1 보상을 실험 때문에 거절하지 않으며 제안 전 적격 집단 등 별도 설계를 사용한다. 원래 추천은 광고/실험 점수를 읽지 않는다.

**OptimizeCampaign:** 제안→정책 검사→사람 승인 또는 한정된 mandate→적용 TX로 진행한다. 금액·지역·소재·정보 이용 범위를 넓히면 새 승인이 필요하다. 적용 직전 최신 epoch·pause·budget을 검사한다. 광고주/계열 출처를 독립 근거 여러 개로 세거나 검증 안 된 경쟁사 위험 주장을 일반 추천에 반영하지 않는다.

## 11 R4 시장 정보·개인정보 작업

**MarketQuery:** 허용 tenant/principal·라이선스·목적·정규화된 질의·snapshot·집계 cell·조회 예산을 확인한다. 개발 참조 사용자 50명/광고주 5곳 이상 외에도 지배적 주체·차분 질의·민감 범주·재식별 위험을 억제한다. 이 기준만으로 익명성·DP를 보증하지 않는다. 미공개 미래 입찰·고객 원문·개인 지갑·개인별 프로필은 반환하지 않는다.

**RetentionAndDeletion:** 실제 개인 자료·증거 원문·회계 보존·과거 consent를 구분해 삭제/익명화/접근 제한을 적용한다. snapshot·cache·외부 목적지·분쟁 hold를 추적한다. 작은 집계가 억제돼도 financial/report event tombstone을 임의 삭제하지 않는다. 온체인에 개인 대화·광고 응답 원문을 기록하는 기능은 없다.

모든 외부 callback은 등록된 목적지·TLS·서명 profile·audience·timestamp/nonce·payload hash·재전송/순서 처리를 수행한다. DNS/IP/redirect·크기·동시성·자격 전달 제한을 검사하고 공격자가 제공한 issuer URL로 임의 자격 요청을 하지 않는다.
