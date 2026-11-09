# 05 화면·운영·검수·이전 상세 설계

2026-11-08 · [목차](../AD_COIN_V6_2_DETAILED_DESIGN.md)

### 구현 추적 · 2026-11-09

`v2/workspace.py`와 `v2/web/`에 별도 영어 화면을 구현했다. 기본 미등록이며 `router_for(..., include_workspace=True)`인 격리 앱에서만 검증했다. 정적 shell은 계정 조회 없이 먼저 표시한다. 인증된 사람의 명시적 동작 뒤 session projection·10개씩 keyset 캠페인 목록을 조회하고, 기존 29개 P1 계약을 사용한다. 조회용 UI 두 경로는 계약 OpenAPI를 변경하지 않는 별도 BFF다. 세션 쿠키/CSRF는 신뢰할 인증 adapter가 공급해야 하며 화면은 자격 증명을 발급하거나 입력받지 않는다.

승인 전 소재 조회를 하지 않는다. 메뉴 이동으로 승인 의도를 취소하며 challenge/consent/start/creative 각각의 지연 응답이 숨겨진 광고를 시작하지 못하게 한다. 광고 DOM을 즉시 숨긴 후 서버 취소를 요청하고, 가로·세로 가시 영역이 양수인지와 focus/foreground를 검사한다. 클라이언트 진행은 추정치이며 최종 시간·보상은 기존 서버 verifier만 결정한다. 권한 철회 시 개인 DOM/메모리를 지우고 epoch로 늦은 응답을 거부한다.

화면은 model 잔액·무현금가치를 명시하며 실제 AI 결제·외부 출고·거래소·운영 심사자 UI를 제공한다고 표시하지 않는다. Chromium 실시간 보상/중지/역할별 캠페인·모바일/dark/reduced-motion·키보드/일부 대비·XSS·철회/지연응답·이동 경합의 자동 검증과 PostgreSQL 인덱스 비교는 [증거 기록](../../reports/ad-coin-v6.2-ui-performance-2026-11-09/README.md)에 둔다. 이는 전체 접근성 인증·실제 IdP·전지역 성능 인수를 대체하지 않는다.

## 1 사용자 화면 상태

전용 광고/보상 화면은 로그인한 사용자가 자신의 offer·wallet·consent만 확인하게 한다. Chat·일반 추천에 raw wallet·가격·token·JSON·stack을 넣지 않는다. 사용자에게 필요한 광고 조건은 별도 승인 화면에서 제공한다. 공개 UI는 영어, Lucide/local SVG, 키보드 focus·screen reader·light/dark·reduced motion·모바일 접근성을 유지한다.

수신 설정은 기본 비활성이다. `Receive sponsored offers`와 공유할 task category/language/coarse region, 전체/캠페인별 횟수·시간을 각각 설명한다. 수신·맥락 공유·작업 알림·브라우저 알림·spend를 한 checkbox에 묶지 않는다. 선택하지 않은 맥락을 광고 매칭에 전송하지 않는다.

제안 화면은 광고주 신원, `Sponsored offer`, 정확한 사용자 보상·총 배분·시간·모형 사용 조건·지갑 관리 주체·기한·추가 조건·거절을 먼저 보여 준다. 소재 본문·브랜드 홍보 이미지·외부 tracking request는 동의 전 표시하지 않는다. 실제 paid AI를 충당한다는 설명은 해당 단계에 유효 task quote·검증 근거·전체 비용 충당이 있을 때만 한다. R0에는 `Test balance. No cash redemption.`을 표시한다.

동의 버튼의 참조 문구는 `Allow this ad`이며 거절은 `Not now`다. 동의 후 session을 만들고 `Advertisement` 표시와 승인 소재·취소·진행 시간을 제공한다. count/시간 quota 부족·day closing은 광고를 시작하지 않고 다음 가능 시점/조건을 알린다. 과도한 반복 요청을 유도하지 않는다.

active는 실제 인정 시간과 15초 조건을 설명하고, 화면이 숨겨진 시간은 진행으로 표시하지 않는다. 최대 30초·사용자 남은 한도에 따라 소재를 종료한다. complete 이후 `Checking eligibility` 또는 `Review pending`을 표시하고 현재 보상이 확정됐다고 먼저 말하지 않는다. 정상 확정 뒤에는 `Reward issued`; 서명이 늦으면 `Receipt pending`을 추가한다. 코인 지급과 영수증 파일 발급 상태를 분리한다.

취소·실패·검토는 원인에 맞는 안전한 설명과 이의 제기 경로를 제공한다. fraud score·탐지 우회 방법·다른 사용자의 상태는 표시하지 않는다. 확정 보상은 철회/거절로 없어지지 않는다. 추가 구매/구독을 숨은 기본 보상 조건으로 바꾸지 않는다.

## 2 광고주·대행사·검토자 화면

광고주 흐름은 draft 작성→검증 오류→심사 요청→pending/eligible/rejected→예산 승인→활성화→pause→명세/보고다. editor와 approver 버튼은 실제 capability로 제한하며 서버도 재검사한다. UI의 disabled 상태만 권한 통제로 인정하지 않는다.

예산 승인 화면에는 고정 revision·총/일 예산·asset/model·split·최대 보상·지원 지역·기간·소재를 표시한다. 더미 충전을 실제 입금처럼 표시하지 않는다. activation 충돌·ETag 변경은 현재 상태를 다시 읽어 사용자에게 재확인할 변화만 설명한다. stale approval을 자동 재승인하지 않는다.

보고 목록은 obligation waiting/delayed/action_required와 revision·정정 연결·기간·data_through·method·first_party를 보여 준다. 0·미측정·비공개·추정을 구분한다. `unique_owners`는 계정 권리자 기준으로 표시한다. consumption ACK는 `Mark report received` 등 보고 수신 의미로 표현하고 `Approve payment`로 번역하지 않는다.

검토 서비스는 별도 관리 경계를 쓴다. review target revision·근거·결정·reason·판정자·시점을 감사한다. 일반 광고주 cookie나 범용 운영 super-token으로 review service를 흉내 내지 못한다. 고객 지원 화면은 개인정보를 최소로 투영하며 승인/지출·임의 원장 쓰기를 제공하지 않는다.

## 3 운영 상태와 runbook

중지는 new_campaign/new_offer/new_exposure/reward_verification/internal_spend/external_withdrawal/mint/redeem/statistics_publish로 구분한다. source credential·권한·DB·담보·서명 문제가 발생하면 영향받는 쓰기를 먼저 닫고 사용자 권리/증거/원장을 보존한다. 어떤 문제든 일반 검색 전체를 광고 서비스와 함께 중단하는 구조로 결합하지 않는다.

**DB 장애:** 미커밋 요청은 경제 효과 없음, 커밋 여부 불명은 operation/idem으로 조회한다. DB 복구 후 원장·업무 state·outbox/inbox·nonce·체인과 대사 전 외부 지급을 재개하지 않는다. 백업에 있던 옛 balance를 신뢰해 신규 지급하지 않는다.

**키 서비스 장애/침해:** 원장 확정과 영수증 서명 지연을 구분한다. 신규 서명 중지·key status/발급 이력 보호·교체 인수를 수행한다. key가 폐기됐다고 정상 journal을 삭제하지 않는다. 공격자가 만든 서명을 기존 지급으로 인정하기 전에 authoritative 발급/journal과 대사한다.

**worker lease/서버 종료:** 새 generation이 상태를 인수하고 stale generation의 쓰기를 거부한다. already dispatching인 외부 효과는 조회·대사하며 timeout만으로 새 ID 재지급/hold 해제를 하지 않는다. prepared에서 안전하게 중단된 요청과 구분한다.

**RPC/최종성/담보 불일치:** v5의 동일 체크포인트 R/S/C/B를 검사하고 관련 mint/출고/상환을 개별 중지한다. 원시 잔액이 커도 동결된 USDC를 실제 지급 가능 담보로 정상 표시하지 않는다. 수탁/준비금 부족을 고객 잔액 삭감이나 가상 credit으로 숨기지 않는다.

**외부 partner 장애:** 등록 profile·nonce·webhook·업무 idempotency·원본거래 조회가 가능한지 확인한다. 신뢰 범위 밖 auth fallback이나 무제한 retries로 우회하지 않는다. partner에서 처리된 지급/전환을 단순 내부 타임아웃으로 취소하지 않는다.

**보고/통계 오류:** obligation은 유지하고 delayed/incomplete·정정 revision을 게시한다. report 재생이 reward command를 다시 호출하지 않는다. 개인정보/작은 집단 누출이면 조회·cache·외부 목적지의 해당 snapshot을 중지하고 lineage로 영향 범위를 확인한다.

재개 기록은 incident_id·영향 기능·근거·대사 checkpoint·승인자·복구/재실행 범위·검증 결과를 포함한다. 일반 지원자가 보안 중지를 해제하거나 financial unknown을 실패 처리할 수 없다.

## 4 상세 인수 시나리오 DTL-01~20

다음은 **향후 실제 제품에서 실행할 검수**다. 이번 문서 validator의 통과 항목이 아니다. GROW 28개·DES 10개·v5 43개와 함께 출시 범위별로 적용한다.

- **DTL-01:** 다른 owner/advertiser의 UUID·scope·path 조합, 혼합 cookie/key, reviewer token without mTLS를 모두 거부한다. WP-01; SEC-01·03, GROW-07, DES-01·09.
- **DTL-02:** fresh action의 action/target/quote·If-Match·body·contract·session을 각각 바꿔 거부한다. 같은 HTTP replay만 원래 응답을 반환하고 현재 접근은 재검사한다. WP-01·04; SEC-04, DES-09·10.
- **DTL-03:** 중복 JSON key·대소문자 alias·oversize·잘못된 Unicode·비정규 금액·uint overflow를 파서/schema/의미 경계에서 거부한다. WP-01·02; ECON-01, DES-09.
- **DTL-04:** draft 생성 무이동, 최초 activation 단회 배정, pause/resume 재차감 없음, stale review/approval·budget 부족의 전체 rollback을 PG에서 확인한다. WP-02·03; GROW-01·06·14.
- **DTL-05:** 같은 캠페인/다른 owner의 동시 offer와 같은 owner/다른 캠페인의 동시 offer를 실행해 일/총 한도·잔액·동시 제안 수를 지킨다. WP-02·04; ECON-09, GROW-06.
- **DTL-06:** 기본+추가 단계 최대 reserve·부분 award·추가 기한 종료·다음 날 release에서 원래 window와 user 권리를 보존한다. WP-02·04·08; ECON-10, GROW-05.
- **DTL-07:** 같은 사람의 여러 agent/campaign 동시 start에서 전체/캠페인 count/time 한도를 지키고 UTC day closing·최소 15초 부족을 거부한다. WP-02·04·07; DES-03.
- **DTL-08:** first signal·nonce/sequence·서버 간격·hidden/background·gap·30초 상한·600초 제출 기한·증거 재전송을 실제 브라우저/API로 검증한다. WP-04; SEC-12, GROW-08, DES-09.
- **DTL-09:** 15초 충족 후 cancel/withdraw/pause/verifier 지연이 확정 권리를 잃게 하지 않고, 미충족·불명확·review_pending을 구분한다. WP-01·04; AD-02, GROW-05, DES-07.
- **DTL-10:** 같은 stage를 다른 key/동시 worker/재시작으로 제출해도 단일 journal·award·receipt만 만든다. 서명 장애로 재지급하지 않는다. WP-02·04; ECON-08, DES-08.
- **DTL-11:** agent manager 철회·휴면·wallet fallback·내부 이전·locked/unknown 자금을 검사하고 다른 owner/operator로 귀속되지 않게 한다. WP-01·04·05; PAY-01, GROW-13.
- **DTL-12:** JWS alg/type/kid/issuer/audience·payload/표시·서명 위조·키 회전/폐기·원격 jku/x5u를 실제 암호 검증한다. WP-01·04·06; DES-08.
- **DTL-13:** lease 만료·stale generation·철회와 dispatching commit·I/O 전후 종료·원격 성공/응답 유실에서 unknown·중복 방지를 검증한다. WP-02·06·12; SEC-10·11, DES-07.
- **DTL-14:** 보고 0건·미도착·억제·관측 지연·out-of-order commit·정정·exact revision 복구·ACK digest mismatch가 과금/보상과 섞이지 않는다. WP-04·09·11; DES-05·06.
- **DTL-15:** 실제 AI run의 definition/provider/node/owner/version을 바꾸거나 재사용해 정산할 수 없고 부분 성공·미실행·지급 후 환불 재원이 맞는다. WP-05; PAY-02~05, ECON-11.
- **DTL-16:** 실입금 단회 mint·동결/전송 실패 rollback·확정 전 credit 금지·동일 checkpoint 대사·unknown 출고·원자 상환을 로컬 체인/격리 PG에서 검증한다. WP-06; INV-01~06, SEC-05~11.
- **DTL-17:** 매체 판매 권한·schema/auth profile·beta·hop/loop·표시/배분·A2A/MCP·B1과 사람 노출을 구분한다. WP-07; GROW-02·20, DES-01·02.
- **DTL-18:** 브랜드 상담·클릭/재생/가입·구매 단계·도구 retry/재귀·비용 상한·중립적 피드백·임의 구매/구독 차단을 검증한다. WP-08·10; GROW-05·21·26, DES-04.
- **DTL-19:** CRM 원본 주문 중복·환불/정정·귀속 version·실험 권리·통계 suppression/차분·자료 라이선스·삭제 lineage를 검사한다. WP-09·11; GROW-09·10·15·22·25.
- **DTL-20:** 격리 부하·복구·영어/접근성·CSP/escaping·CSRF·기존 추천·v1 분리·실가치 gate·release overlay와 rollback을 인수한다. WP-12; OPS/PERF, GROW-18·27·28, DES-10.

fixture는 서로 다른 owner A/B·agent A1/A2/B1·광고주 X/Y·editor/approver/reviewer·비활성/철회 자격·model asset와 다른 asset·캠페인/보고 기간을 분리한다. 실제 고객·운영 계정·체인 키를 복사하지 않는다. 실패·건너뜀·미실행은 숨기지 않는다.

## 5 성능 검수

원장 command 처리량, API 요청 수, posting 행 수, 외부 작업 완료를 별도 단위로 잰다. seed/초기 fixture 행을 측정 구간 처리량에 합치지 않는다. open-loop 부하에서 보내지 못한 요청도 실패로 기록한다. 읽기 p99 20ms·금전 쓰기 50ms·정산 200ms와 200 command/s 관문·1,000/s 도전은 목표이며 실제 증거가 필요하다.

일반 분산 사용자와 hot owner/campaign/account를 나눠 시험하고 동시 철회·expiry·report·signer 지연을 포함한다. 별도 API cohort별 p99 판정에는 참조 10,000개 이상 표본, 실패율·최대값·CPU/DB wait·실제 config를 남긴다. 표본이 부족하면 더 빠르다고 결론 내리지 않는다. 실제 사용자 15초 노출·체인 최종성·은행/파트너 대기는 내부 TX 시간과 구분한다.

처리량 때문에 auth·원장·DB 제약·fresh·한도·대사를 끄지 않는다. 플랫폼 수익 credit의 hot row가 문제이면 deterministic event hash 기반 stripe 계정과 대사를 검토할 수 있지만 R0 기본 회계 정확성을 먼저 통과한다. 일반 추천과 광고의 자원 경합을 측정하고 광고 장애가 검색 전체를 지연시키지 않게 bulkhead·pool·rate를 설정한다.

## 6 migration·배포·운영 인수

실행 전 실제 DB 버전·권한·현재 schema·active release·변경 파일을 확인한다. expand migration은 adc2 표/제약/인덱스·명시적 role·등록 SQL을 추가하고 v1 원화 row를 변환하지 않는다. 모형에서 migration 전/후·다시 실행·부분 실패·복구·옛 코드 공존을 검증한다.

배포, migration, 기능 공개, 실가치 활성화는 네 단계다. 사용자가 직접 실행 중인 개발 서버를 재시작/대체하지 않는다. 실제 배포 시 활성 release 기반의 리뷰된 overlay만 구성하며 shared working tree 전체를 패키징하지 않는다.

rollback은 신규 진입·위험 기능을 닫고 권리·원장·pending/unknown을 보존한다. 이미 지급/발행된 사실을 DROP/DELETE로 되돌리지 않는다. R2는 발행/수탁 주체·관할·담보·상환·주소·키 분리·독립 감사·복구·전체 출시 검수 증거가 모두 있어야 한다. 메인넷 주소나 법적 미정 항목을 developer 임의 값으로 채워 활성화하지 않는다.
