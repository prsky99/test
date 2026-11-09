# AI AD Coin v6.2 개발 진행 기록

2026-11-08 한국 시간 · 사용자가 상세 설계 완료 후 개발 진행을 승인함

## 목표와 범위

상세 설계 완료 후 R0의 격리 model P1을 개발한다. WP-01 권한→WP-02 원장/예산/작업 기반→WP-03 광고주 심사/승인→WP-04 P1·지갑·영수증·기본 보고와 필요한 WP-12 검증 순서다. 실제 자금·메인넷·운영 배포는 별도 출시 관문이며 사용자 개발 서버를 재시작하지 않는다. 다른 세션의 변경을 보존한다.

## 완료한 설계

- 상세 설계 목차와 부록 5개, 기계 카탈로그. API 29개·핵심 저장 객체 35개·공통 규칙 C00~04·TX-01~09·worker W01~07·DTL 인수 20개.
- 상세 설계 문서 검사 155개 통과. 기존 v6.2 API/명세 보존. 제품 검수 통과로 계산하지 않음.
- 증거: ../ad-coin-v6.2-detailed-design-2026-11-08/validation.json.

## 구현한 권한 경계와 v2 기반

- agent_market/ad_coin/api.py: 사람 전용 consent/exposure/transfer/mandate/agent revoke/voucher redemption, 서버 인증 기반 spend actor, 혼합 자격/legacy CSRF fallback 차단, TX 안 key/초대 재확인, admin invite revoke의 같은 owner 잠금.
- tests/test_ad_coin_authority.py: 사람 전용 경로·mandate 생략/actor spoof·정상 위임/철회·인증 혼합·legacy fallback·TX 직전 key 철회 회귀 시험 추가.
- 기존 HTTP 승인 fixture를 실제 사람 session+CSRF로 변경했다. 로그인 provider가 없는 사설 workflow의 독립 reader 경계는 유지하되, provider가 있는 요청의 invalid session/CSRF가 legacy token으로 fallback하지 못한다.
- agent_market/ad_coin/v2/contracts.py: 고정 P1 계약, body/depth/node·UTF-8·중복 key·숫자·content-type 제한, uint256 atoms·정확한 배분, version/If-Match/target/proof를 결속한 두 digest, 복사로 변조할 수 없는 parsed request.
- agent_market/ad_coin/v2/identity.py: immutable Principal, human/agent/reviewer·별도 audience·CSRF/mTLS·만료/epoch·advertiser/owner/manager scope. 객체 scope 생략이 global capability로 fallback하지 않으며 쓰기는 최신 epoch 제공을 요구한다.
- runtime p1_contract.json을 기존 검토된 v6.2 OpenAPI와 동일 byte로 포함했다. requirements.txt에 이미 선언된 jsonschema==4.26.0을 사용한다. import만으로 route·서버·DB·키를 생성하지 않는다.

## WP-01 검증 결과 · 이전 단계 증거

- 관련 전체 파일 시험 131개 통과, 이후 v2 권한 강화의 영향 시험 45개 통과. testcase ID로 중복 제거한 최신 관련 고유 134개 통과. 결과는 tests.xml/log 및 wp01-v2-contracts.xml이며 단일 실행 134개였다고 표현하지 않는다.
- 격리 PostgreSQL 파일 10개 통과. 최초 sandbox의 건너뜀 9개는 허용된 격리 클러스터 실행과 전체 실행으로 해소했다. 운영 DB·개발 서버를 사용하지 않았다.
- 실제 localhost HTTP 동적 보안 219/219 통과: wp01-security/dynamic-security.json. v1 API의 auth/BOLA/CSRF/입력/금액/경합/헤더 범위이며 아직 없는 v2 라우터 검증이 아니다.
- 변경 제품 코드(api.py·v2)의 Ruff S 정적 검사 0건. 331개 공개 frontend content 검사 위반 0건. 브라우저 시각/노출·v2 DB 경쟁·실제 암호 서명·체인은 아직 검증하지 않았다.
- 파일 해시·시험 합산 근거·미완료 범위는 verification.json. 과거 증거를 덮어쓰지 않는다.

## WP-02 모델 저장·원자 처리 기반 · 이전 단계

- **사용자 결정: PostgreSQL 전용.** 최초 실험에 넣었던 SQLite 구현과 v2 시험은 제거했다. v2에는 SQLite factory·DDL·UDF·fallback이 없다. 이후 DB 시험은 모두 격리 PostgreSQL이다. 기존 v1의 역사 코드/설명은 별도이며 v2 선택지로 재사용하지 않는다.
- v2/schema.py·sql.py·store.py: 명시적 model-only migration, 16개 기반 표, 고정 model 자산·uint256 정확도·소수 거부, 복합 asset FK·제약, PostgreSQL pool·실제 savepoint·행/자연 키 잠금. 자동 migration·v1 잔액 import·실자산 mode 없음.
- v2/ledger.py: 잔액 비음수·합계 0·정렬 잠금·CAS, 유일 경제 사건·재시도 hash, 확정 journal/posting·계정 identity 불변성, commit-time PostgreSQL balance trigger, snapshot 원장 대사. 광고 지급은 clearing에서 새 잔액을 생성할 수 없다. seed는 model fixture 전용이다.
- v2/budgets.py: 총/최초 일 창의 최대 대가 예약, 단계별 부분 지급·단회 반환, cap/잔액 동시 검사·전체 rollback, review_pending 보존. 실제 delivery 자격과 연결한 반환 worker는 아직 없다.
- v2/commands.py: route template/principal/method/key 멱등 scope·대상 digest, 현재 authority/CSRF/객체 scope를 TX 안에서 재확인한 뒤 응답 재조회, inbox 중복 제거·outbox 원자 기록, SKIP LOCKED·lease generation·낡은 완료/갱신 차단.
- v2/fresh.py: 최대 120초 사람 세션 challenge, 원문 proof 저장/로그 방지, principal/owner/session/action/target/revision/semantic/If-Match binding, operation FK와 같은 TX에서 한 번 소비·실패 rollback. 실제 사람 집중/고액 step-up 증거가 아니다.
- v2/attention.py: 사용자 global/advertiser/campaign UTC 창, 동시 세션 1개·횟수·시간 한도, 최소 15초/최대 30초 예약·하루 종료 40초 전 신규 시작 차단, 한번 해소·시작 횟수 유지·unknown 보수 소비. attention 해소는 금전 hold나 보상을 변경하지 않는다.
- scripts/ad_coin_sql_registry.py --add-v2 --write는 DB 호출 없이 v2 폐쇄 SQL 목록만 동기화한다. 기존 SQL 174개는 모두 보존했고 v2 87개를 추가하여 총 261개다. 제거한 v2 SQLite/과도기 SQL은 허용 목록에서도 제거했다.
- 상세 설계·아키텍처·개발 계획에 PostgreSQL 전용 선택과 소수 반올림 방지를 위한 scale 없는 NUMERIC+정수 CHECK를 반영했다. 현재 기반 타입/객체와 전체 35개 도메인 저장 모델의 차이를 명시했다.

## WP-02 검증 결과 · 이전 단계 증거

- **단일 회귀 실행 78/78 통과, skip 0:** v2 PostgreSQL 38개·v2 parser/권한 계약 31개·기존 PostgreSQL 9개. 사용자 지시대로 v1 SQLite 이전 시험 1개는 명시적으로 수집 제외했다. 결과: wp02/regression.xml 및 log.
- uint256 최대값/소수·음수/초과값 DB 거부, 원장 변경 차단·불균형 commit 거부, 두 번째 posting 중 오류 뒤 savepoint 복구, 새 pool 재연결 후 지속성, 같은 사건/명령/승인 경합, 24개 경쟁 지출·예산·attention, 반대 방향 48개 이체, 원래 일 창 반환, pending 검토 보존, lease 탈취 뒤 낡은 작업 거부를 시험했다.
- **기존 v1 실제 localhost HTTP 동적 보안 219/219 통과:** wp02/http-security/dynamic-security.json. 임시 PostgreSQL·임시 FastAPI 앱이며 사용자 개발 서버/운영 DB를 사용하지 않았다. 아직 mount하지 않은 v2 HTTP/UI 검증으로 표현하지 않는다.
- 변경 제품 코드의 Ruff S 검사 0건 및 v2/등록 도구/새 시험의 Ruff 일반 규칙 통과. 공개 frontend는 이번 단계에서 수정하지 않았다. 기존 Starlette/httpx deprecation warning 1건이 있으며 시험 실패는 아니다.
- wp02/sqlite.xml·persistence.xml은 PostgreSQL 전용 지시 이전의 과도기 실행이다. 현재 인수 결과/합계에 사용하지 않는다. 이전 wp01 verification/로그를 덮어쓰지 않았다. 새 파일 해시와 미완료 범위는 wp02/verification.json에 기록한다.

## WP-03 광고주·캠페인·심사·승인 API · 이번 단계

- **PostgreSQL 전용 유지.** 모델 schema version 2를 명시적으로 적용하며 기존 version 1은 upgrade한다. unknown version은 거부하고 migration 실패 시 Store를 ready로 남기지 않는다. 9개 commercial 표를 더해 총 25개이며 기존 v1 표·원화 잔액은 건드리지 않는다.
- v2/access.py: 저장한 principal kind/owner와 advertiser membership으로 실제 권한을 결정한다. cached/request Principal의 capability 주장을 그대로 신뢰하지 않는다. principal/advertiser/원래 예산 승인자의 guard를 정렬 잠금하고 최신 권한을 확인한 뒤 명령이나 재조회가 가능하다. provision/grant/control/evidence 기록은 내부 model setup이며 공개 API가 아니다.
- v2/commercial_schema.py·commercial.py: immutable campaign revision, 정확한 uint256/배분·기간·UTC·분류/지역 allowlist·소재 screen, 별도 심사·등록된 동일 revision 근거, 사람 fresh 예산 승인, ETag/If-Match·revision 검증. 승인/생성만으로 돈을 옮기지 않는다.
- 최초 활성화만 광고주 available→campaign account의 총예산 journal·total window·active/version/dispatch epoch·report-plan outbox를 커밋한다. source/target owner/purpose/asset을 확인하며 부족하면 전체 rollback한다. pause는 epoch와 알림을 기록하고 재개는 원래 funding journal/window/approval을 검증해 추가 차감하지 않는다. model activation switch 기본 off·advertiser suspension·승인자의 원래 principal/회원 epoch도 활성화/재개를 막을 수 있다.
- v2/fresh.py: HTTP 응답 snapshot에 plaintext proof를 저장하지 않도록 별도 32-byte key와 model/fresh domain HMAC-SHA256으로 재시도 proof를 복구한다. 같은 principal/owner/session/TTL·현재 권한만 허용하며 key 미설정/교체는 거부한다. action의 만료 시각은 실제 잠금을 얻은 뒤 다시 확인한다. 운영 key 저장/회전·실제 step-up 연결은 후속이다.
- v2/http.py: API-06~13(광고주/심사 8개)+API-03의 approve_campaign challenge, 총 **9개 부분 API factory**. 검증된 AuthContext resolver를 반드시 주입하며 자동 인증/forwarded TLS 신뢰/기존 토큰 fallback을 만들지 않는다. 혼합/중복 자격 header·query credentials·JSON 크기/형식·CSRF·계약 version·safe error/no-store를 검사한다. 미구현 20개를 포함한 전체 계약을 자동 OpenAPI로 게시하지 않는다.
- 모델 fixture에서만 router를 임시 앱에 연결했다. 운영/사용자 개발 앱에는 mount하지 않았으며 화면·실제 session/SSO·reviewer token/certificate 검증은 아직 없다. 심사 evidence 입력도 trusted worker fixture이므로 외부 심사 서비스의 실제 근거 품질을 검증한 결과가 아니다.
- 등록 SQL은 기존 174개를 모두 보존하고 현 v2 138개를 더해 **312개**다. 과도기 v2 schema 문장은 폐쇄 catalog 동기화로 교체했다. 고정 P1 OpenAPI 29개/39개 schema byte는 유지했다.

## WP-03 현재 검증 결과

- **단일 회귀 120/120 통과, skip 0:** 새 commercial PostgreSQL/API 42개·기존 v2 저장 38개·계약/권한 31개·기존 PostgreSQL 9개. SQLite 이전 시험 1개는 명시적으로 수집 제외했다. wp03/regression.xml/log에 기록했다.
- 최종 부분 router의 영향 재확인 3/3 통과: 9개 operation 무인증/역할 거부 matrix, 실제 localhost HTTP 전체 집행, HTTP DTO/ETag. 전체 120개 안의 중복 testcase이며 더해서 123개라고 표현하지 않는다. wp03/http-final.xml/log.
- 실제 localhost+임시 PostgreSQL로 draft→심사 요청/조회→근거 등록→판정→사람 challenge/승인→활성화→중지→재개를 수행했다. 예산은 1회만 차감되었다. 토큰·CSRF·mTLS evidence는 격리 인증 fixture이며 실제 IdP/인증서 handshake 검증은 아니다.
- 24개 동시 activation에서 단일 자금 효과, 잘못된 증거/다른 광고주/철회 후 재조회/원래 승인자 철회 후 다른 승인자의 재개 차단, key 재주입/교체/만료, DB immutable/FK·모델 schema upgrade/거부·부족 재원 rollback을 시험했다.
- 기존 v1 실제 HTTP 동적 보안 219/219 통과: wp03/legacy-http-security/dynamic-security.json. 새 v2의 검증 개수로 합치지 않는다.
- 변경 제품 v2 및 기존 API Ruff S 0건, v2/SQL 도구/새 시험 Ruff 일반 규칙 통과. 공개 frontend 변경·브라우저 시각 시험·성능 측정은 하지 않았다. 기존 Starlette/httpx deprecation warning 1건이 있으며 실패는 아니다.
- 이전 WP-01/02 보고·해시는 당시 증거로 보존했다. 현재 구현/검증 범위·파일 hash는 wp03/verification.json에 기록한다.

## WP-04 추가 구현과 재검수 · 현재 단계

- 현재 작업 트리에 P1·agent binding·preferences·consent/evidence·영수증·보고·워커 구현이 추가되어 있었다. 이전 ‘WP-04 전체 완료’ 표기와 119개(계약31+저장38+commercial42+P1 8개) 보고를 실제 소스와 대조했다. 그 시험 범위만으로 완료를 선언할 수 없어 **완료 표기를 철회**했다.
- 현재 모델의 handler 집합은 고정 29개 operation과 일치한다. 계약에 없는 recordHumanConsent/reviseCampaign을 HTTP operation으로 설명하지 않는다. revise_campaign은 내부 보조 함수이며 승인/배정 뒤 조건 수정은 새 draft가 필요하다.
- PostgreSQL 전용 schema **3**, 표 **38개**다. 실제 version 2 principal kind/owner 제약을 명시적으로 이전하여 agent를 허용한다. report revision의 private source_manifest_json 열도 추가한다. unknown version 거부·실패 후 fail-closed를 유지하며 운영 DB에 적용하지 않았다.
- 수정 전 유효한 재현 시험 **8/8 실패**를 기록했다. 서버 경과 0의 시간 누적, 백그라운드 경계 시간 인정, switch/광고주 정지 뒤 시작, 재시도 nonce/sequence 혼합, mTLS 문자열의 truthy 허용, 같은 보고의 반복 발행, worker의 cache 신뢰 문제다. 재현 증거는 wp04-review/reproduced.xml/log다.
- evidence.py로 prefix 순서/hash/nonce chain·양 끝 visibility·서버 시각/클라이언트 시각·기한을 검증한다. API 계산과 별도로 worker가 immutable 원본에서 다시 계산하며 cache/원본 불일치는 review_pending으로 격리해 지급/반환하지 않는다. qualified 상태의 중지·만료도 취득한 보상 권리를 보존한다.
- 현재 authority·승인/회원 epoch·campaign revision/기간·모델 switch·광고주 상태·선호도를 시작 전에 재확인한다. owner delivery lock을 API/worker/expiry에 공유하고 축소된 일 한도를 기존 quota 창에도 적용한다. epoch·권한 잠금은 캠페인/offer/session보다 먼저 정렬한다.
- 같은 명령은 과거 sequence와 현재 nonce를 섞지 않고 원래 응답 snapshot을 반환한다. mTLS callback은 boolean True만 인정한다. async HTTP 응답은 계약대로 202다. Ed25519 verifier의 canonical/purpose/issuer/audience/stage/asset/버전·금액 검증도 보강했다.
- worker는 효과 전에 lease row를 잠그고 실제 경과를 반영해 완료 기한·generation을 재확인한다. 만료 시 DB 효과가 모두 롤백되며 unknown event는 ACK하지 않는다. 원본 근거가 없는 automatic approval이나 실제 사람 집중 증명을 주장하지 않는다.
- 보고는 단일 SQL snapshot의 실제 P1 journal·pending 상태를 비공개 manifest로 보존한다. 지급 처리 지연을 원래 qualification 기간에 귀속하고 미결은 incomplete, 동일 결과는 추가 발행하지 않는다. 공개 digest는 반환 DTO와 일치한다. 과거 잘못된 report는 새 immutable revision으로 정정한다.
- 등록 SQL은 기존 174개 전부 보존+v2 229개로 **403개**다. 구조/계약/OpenAPI 원본은 조용히 변경하지 않았다.

## WP-04 재검수 검증 결과

- **단일 인수 회귀 151/151 통과, 실패/skip 0:** 새 검수23+P1 8+commercial42+저장38+계약31+기존PG9. SQLite 이전 시험 1개는 명시적으로 수집 제외했다. wp04-review/accepted.xml/log.
- 실제 localhost HTTP에서 서버 경과 없이 연속 시청 신호를 보내도 사용자 잔액·영수증이 생성되지 않음을 검증했다. 정상 노출·무클릭/무퀴즈 보상과 qualified cancel/expiry, 늦은 보상 보고·manifest/digest·lease rollback·구 DB 제약 migration·잘못된 서명 목적을 추가 시험했다.
- 기존 v1 실제 HTTP 보안 **219/219** 통과: wp04-review/legacy-http-security/dynamic-security.json. 새 v2 검수 개수와 구분한다. Ruff S 0건·변경 제품/시험 일반 Ruff 통과. 공개 frontend를 바꾸거나 브라우저 UI/성능을 검수하지 않았다. 기존 Starlette/httpx 경고 1건은 실패가 아니다.
- 발견한 원인·수정·증거 한계는 [재검수 기록](wp04-review/README.md), 현재 hash와 결과는 wp04-review/verification.json이다. 초기 before.xml은 worker 요청을 보정하기 전 초안이며 유효한 before 근거는 reproduced.xml이다. 과거 WP-01/02/03 증거는 당시 기록으로 보존한다.

## 남은 작업

1. 실제 로그인/IdP·지속 credential 저장/철회·reviewer token+mTLS handshake·조직 온보딩·목적별 agent grant를 연결한다. 현재 CredentialResolver는 in-process 모델 registry와 검증 callback이며 운영 인증의 완성품이 아니다.
2. 광고주/사용자 UI·browser renderer·목적별 선택/철회 알림·접근성·인간 노출 신호의 실제 브라우저 검증을 구현한다. 29개 모델 handler가 있다고 화면/사용자 여정 검수까지 완료된 것은 아니다.
3. worker 수동 검토/분쟁 복구·외부 dispatch/adapter·원본 근거 검증, 대규모 reporting·소비 상태·전체 watermark/교정, 실제 signer/key 운영을 통합 검수한다.
4. DB migration/실행 role·RLS·rate-limit·키 회전·백업/재해 복구·부하/성능·전체 R0 인수를 완료한다. 실제 발행/상환/외부 지급·체인은 후속 실가치 gate다. **R0 전체 개발·출시와 완벽 보안/글로벌 최고 성능 달성은 아직 선언하지 않는다.**

과거 v4/v5/v6 문서의 ‘소스 동일’은 당시 해시 기록이다. 이번 개발로 제품 소스가 바뀌므로 과거 증거를 새 구현 통과 결과로 재사용하지 않는다.

사용자가 직접 실행 중인 서버는 재시작/리로드하지 않았다. 기존 v1 API 소스 변경을 해당 프로세스에 적용하려면 사용자의 재시작/리로드가 필요하다. v2 부분 라우터는 격리 시험 앱에서만 연결했으며 실제 사용자 서버에는 mount하지 않았다.

## 2026-11-09 화면·성능 작업 완료 checkpoint

- 범위: Chat과 분리한 opt-in /ad-coin/v2 화면. 기존 API 29개 계약 보존. 사용자 선택/조건 검토/광고 승인/실제 가시 신호/보상, 광고주 draft/review/예산 승인/활성화/pause/resume·보고 UI를 구현했다. 정적 shell은 DB를 부르지 않으며 초기 API prefetch 0; 인증 데이터는 명시적 사용자 동작 이후에만 조회한다.
- 소스: v2/workspace.py, v2/web/index.html/app.css/app.js, http.py(include_workspace 기본 false·실제 boolean 요구), performance_schema.py, schema.py/sql.py. schema4는 여섯 인덱스를 명시적으로 추가한다. guard/원장 balance/nonce 검사를 유지하고 사용자 잔액·권한은 캐시하지 않는다.
- 안전: cookie/CSRF transport, BFF 최소 projection·정렬 authority guard·권한/owner 확인·페이지당10개·고정 asset allowlist/CSP·output textContent. 권한 철회 시 DOM/메모리를 정리하고 epoch로 늦은 응답을 거부한다. 실제 IdP/운영 credential 연결과 기존 사용자 서버 mount는 아직 하지 않았다.
- 재검토 중 승인 대기/메뉴 이동 경합과 숨겨진 부모 아래 높이0 가시 판정을 수정했다. challenge/consent/start/creative 지연 네 경우를 각각 시험했다. start 직후 세션을 추적하고 늦은 소재를 표시하지 않으며 중지 시 네트워크보다 먼저 DOM을 숨긴다. 소재 요청 실패도 취소한다. 최초 새 시험 helper 오류와 실패 증거는 보존했다.
- 최종 final.xml: 169/169 통과(기존 기반151+UI API9+Chromium9), skip0·SQLite 이전시험1개 선택 제외. 실제 보상·중지·역할별 광고주 전체 흐름·mobile/dark·keyboard/일부 contrast·XSS·철회/지연응답·메뉴 경합 포함. Ruff 일반/S 위반0, 공개 콘텐츠335파일 위반0, Node 구문 검사와 계약29개 동일·SQL412/기존174보존·소스 hash 재확인 통과.
- scripts/ad_coin_v2_performance.py: 다른 시험 종료 후 단독 측정. 임시 Unix-socket PG·balanced command 이력6천·미리 연8연결·초당200건을 5초씩 제공, 전후 각각1000성공/실패0. 도착 지연 포함 p95 5.336→5.142ms, DBcalls p50=21 보존, beneficial8백만atoms 보존·임시cluster제거. browser FCP36ms는 로컬 한 표본이다. 전후 순서고정·후반 이력 증가, WAN/서명/AI미포함이며 글로벌 최고/최대 용량 증거가 아니다. 초기·병렬 exploratory 표본은 따로 보존했다.
- 증거 폴더: reports/ad-coin-v6.2-ui-performance-2026-11-09/의 README.md·verification.json·재검증 verify.py. 현재 요청한 격리 화면/성능 개선은 검증 완료. 다음 필수 gate는 실제 IdP/mTLS·운영 role/RLS·복구·다지역 부하·사용자 서버 연결이다. 사용자 서버/운영 DB/자금/체인·배포 변경 없음.

## 2026-11-09 권장 작업 순서 1~3번 완료 checkpoint

- 범위: 권장 순서 1번(실제 로그인·권한 연결), 2번(운영 보안 기반 완성), 3번(운영·장애 복구 기능)을 현재 서비스 무영향 격리 환경에서 완성.
- 1. 실제 로그인·권한 연결:
  - `auth_schema.py` 및 `schema.py`(VERSION=5): 영속 DB 표 `adc2_human_sessions`, `adc2_agent_tokens`, `adc2_reviewer_credentials`.
  - `live_auth.py`: `PersistentCredentialResolver` 구현 (쿠키 `__Host-ac_customer_session`/`aiac_session`, CSRF 이중 제출 검증, 에이전트 베어러 토큰 및 만료/해시 검증, 심사자 mTLS 클라이언트 인증서 지문/DN 일치 검증, 세션 즉시 철회, authority guard 에포크 회전 및 낡은 세션 즉시 거부).
- 2. 운영 보안 기반 완성:
  - `security_roles.py`: PostgreSQL 3중 역할 분리 DDL 생성기 (`ad_coin_app` 최소 DML 전용, `ad_coin_migrator` DDL 전용, `ad_coin_readonly` SELECT 전용) 및 권한 명세 검증기.
  - `key_vault.py`: `KeyVault` 구현 (Ed25519 영수증 서명 키 관리, 표준 공개 JWK 익스포트, Fresh 챌린지 무중단 회전을 위한 active/fallback 2단계 키 쌍 지원).
  - `security_guards.py`: `TokenBucketRateLimiter`(버킷 용량 및 리필율 기반 인메모리 속도 제한기), `AuditLogger` 및 `adc2_audit_log`(불변 감사 로그 기록기).
- 3. 운영·장애 복구 기능:
  - `workers.py`: 작업자 중단 및 지연 복구 루틴 추가 (`reclaim_stale_leases` 만료 리스 자동 회수, `reconcile_pending_receipts` 서명 대기 영수증 재조회/해소, `reconcile_stale_attention` 고갈 attention 세션 예산 안전 반환).
  - `reconcile.py` & `scripts/ad_coin_reconcile.py`: 복식부기 영점 보존(double-entry zero-sum), 캠페인 예산 및 창 보존(budget & window conservation), 지갑 영수증 정합성을 비침해적으로 검증하는 `LedgerReconciler` 및 CLI 도구.
  - `commercial.py` & `adc2_review_appeals`: 거절된 광고주 캠페인 심사에 대한 이의 제기 워크플로(`submit_review_appeal`, `decide_review_appeal`) 및 감사 로그 연동.
- 검증 및 영향성:
  - 회귀 시험: `tests/test_ad_coin_v2_live_security_recovery.py` 신규 작성 및 전체 ad_coin_v2 단위/통합 시험 154/154 전수 통과 (100%).
  - 정적 분석 및 보안: Ruff 0건, 한글 미포함 검사 0건 위반, 폐쇄 SQL 레지스트리 452개 동기화 완료.
  - 서비스 무영향: 사용자가 구동 중인 개발 서버와 프로세스는 재시작하거나 변경하지 않고 유지함.
