# 제공자 소유 확인 셀프서비스 설계 (에이전트 팀, 2026-11-15, PM 검토용)

- 근거: 매출 전면 조사 `reports/revenue-review-2026-11-15/README.md` 3.3절("제공자가 들어올 입구가 없다")·5.1절(설계 11-17).
- 이 문서는 설계만 담습니다. 구현은 PM이 본 뒤 정합니다.
- 기존 운영자 전용 확인(`docs/PROVIDER_CLAIMS.md`, `provider-https-control-v1`)은 그대로 둡니다.

## 0. 무엇을 하고, 무엇을 하지 않나

- 한다: 고객 로그인을 한 사람이, 자기가 그 에이전트의 주소를 통제한다는 것을 스스로 증명합니다. 증명되면 그 에이전트의 시험 기록을 보고, 설명 정정을 요청할 수 있습니다.
- 증명하는 것은 "확인 시각에 그 주소의 특정 위치를 바꿀 수 있었다"는 사실뿐입니다. 법적 소유, 품질, 상업 권리를 뜻하지 않습니다. 화면 문구에도 그렇게 씁니다.
- 하지 않는다
  - 제공자에게 먼저 연락하지 않습니다(메일·DM·이슈 없음).
  - 메일 주소를 모으지 않습니다. 고객 로그인 표는 지금처럼 발급자와 주체 해시만 저장합니다(`customer_identities`).
  - 확인 여부가 등급·순위·추천·시험 결과에 영향을 주지 않습니다(코드 불변식 + 시험으로 고정).
  - 확인된 제공자도 등급·순위·시험 결과를 바꿀 수 없습니다.

## 1. 확인 방법

| 방법 | 증명 범위 | 우리가 하는 요청 | 권장 |
|---|---|---|---|
| A. well-known 파일 | origin(스킴+호스트+포트) | `GET https://<origin>/.well-known/agentvalcon-claim.json` 한 번 | **1단계** |
| B. DNS TXT | 호스트 | `_agentvalcon-claim.<host>` TXT 조회 한 번 | 2단계(의존성 필요) |
| C. 프로토콜 안 표시 | 그 자원 하나(정확한 URL) | MCP는 `initialize` 한 번, A2A는 카드 GET 한 번 | **1단계** |

- **A. well-known 파일**
  - 본문: `{"profile":"agentvalcon-provider-claim-v1","claim":"<claim_id>","nonce":"<nonce>"}`
  - 정확히 일치해야 통과합니다. 중복 키, 다른 필드, 200이 아닌 응답, 4KiB 초과, 리다이렉트는 모두 실패입니다(운영자용 v1과 같은 엄격함).
  - 경로를 운영자용 `/.well-known/agent-concierge-claim.json`(옛 이름)과 나눠, 두 체계가 섞이지 않게 합니다.
- **B. DNS TXT**
  - 레코드: `_agentvalcon-claim.<host> TXT "agentvalcon-claim=<nonce>"`
  - 지금 운영 `.venv`에 DNS 라이브러리가 없습니다(dnspython 미설치). 의존성 절차(버전·해시 고정, 라이선스, pip-audit, 운영·SRE lock 반영)를 거쳐 2단계에 넣습니다.
  - 공개 DoH(Cloudflare·Google)로 묻는 방식은 쓰지 않습니다. 제3자 서비스에 의존하고 그 이용 조건을 따로 확인해야 하기 때문입니다.
- **C. 프로토콜 안 표시**: 경로로 여러 고객을 받는 공유 호스트에서는 A·B로 개별 고객을 가를 수 없어서 필요합니다.
  - MCP: 서버의 `initialize` 응답 `instructions` 문자열이나 `_meta`에 `agentvalcon-claim=<nonce>`를 넣습니다. 도구 설명에는 넣지 않게 안내합니다. 도구 설명은 우리가 저장하고 공개 화면에 보여 주므로 값이 퍼집니다.
  - A2A: 에이전트 카드 `capabilities.extensions`에 `{"uri":"https://agentconcierge.biz/ext/provider-claim/v1","params":{"nonce":"<nonce>"}}`를 넣습니다.
  - 확인할 때 이 값을 읽고 버립니다. 수집기가 저장하는 카드·도구 정보에서도 이 확장과 문자열은 지웁니다.

## 2. 범위 단위와 묶음

- A·B로 증명한 origin은 같은 origin의 활성 자원 전부를 덮습니다. 덮는 범위는 읽을 때마다 계산하고(자원 URL의 origin이 일치하는지), 표에 자원 목록을 저장하지 않습니다.
  - 운영 실측(11-15 읽기 전용 조회): A2A 활성 231,216개가 3,889개 호스트에, MCP 43,053개가 30,278개 호스트에 있습니다. A2A는 호스트당 평균 약 60개라, 호스트 단위 한 번 확인이 요청 수를 크게 줄입니다.
- **공유 호스트 예외**: 한 origin에서 여러 고객의 에이전트를 경로로 나눠 서비스하는 곳(호스팅 플랫폼)은 A·B로 확인할 수 없고 C만 받습니다.
  - 목록은 운영·SRE가 관리합니다. 첫 후보는 `provider_budget.SHARED_SUFFIXES`와, 한 origin에 서로 다른 카드 제공자 이름이 여러 개인 곳입니다.
  - 테넌트 서브도메인(`x.vercel.app`)은 그 서브도메인이 origin이므로 A를 받을 수 있습니다. 플랫폼 루트(`vercel.app`)는 받지 않습니다.
- 한 origin을 여러 계정이 각자 증명할 수 있습니다(같은 팀). 계정마다 자기 일회용 값을 따로 올립니다.

## 3. 신청자와 흐름

- 신청자는 기존 고객 로그인(OIDC, Google·GitHub, `customer_identity.py`)을 한 사람입니다. 지금 운영 계정은 2개입니다.
- 저장하는 것은 계정(customer_id)과 origin 또는 자원의 연결뿐입니다.

1. **준비** (바깥 호출 없음): 자원 페이지에서 "이 에이전트의 제공자입니까"를 누르면 방법(A 또는 C)을 고릅니다.
   - 서버가 claim_id와 32바이트 일회용 값(nonce)을 만들어 한 번만 보여 줍니다. 저장은 해시만 합니다.
   - 대기 유효 시간은 24시간입니다. 운영자용 v1의 10분은 파일 배포에 짧습니다.
2. **게시**: 제공자가 파일이나 표시를 올립니다.
3. **확인**: 사용자가 "확인" 버튼을 눌렀을 때만 GET을 정확히 한 번 합니다. 자동 재시도는 하지 않습니다. 실패하면 사유 코드만 보여 주고, 다시 누를 수 있습니다(한도 안에서).
4. **확인됨**: 30일 동안 유효합니다. 혜택이 열립니다.
5. **다시 확인**: jobs가 만료 3일 전에 origin마다 GET 한 번을 합니다(측정 시간 :55~:10과 03:50~05:10은 피함).
   - 성공하면 30일 연장합니다.
   - 실패하면 24시간 뒤 한 번 더 봅니다. 두 번 연속 실패하면 `lapsed`가 되고 혜택이 닫힙니다. 기록은 남깁니다.
   - 자원 URL의 origin이 바뀌면, 다시 확인을 기다리지 않고 그 자원은 즉시 범위에서 빠집니다.
6. **철회**: 사용자가 언제든 철회할 수 있습니다. 표에서 지우지 않고 `withdrawn`으로 남깁니다.

## 4. 안전

- 주소는 `broker.discovery.check_public_url`(ip.is_global, 100.64/10 차단)을 통과해야 합니다. 연결은 `public_client`로 해서 연결 순간 주소를 다시 검사합니다(DNS 재바인딩 방지).
- 요청은 HTTPS GET 한 번(C의 MCP는 `initialize` POST 한 번)입니다. 포트 443, 리다이렉트 없음, 8초, 응답 4KiB입니다. 자격 증명이나 쿠키는 보내지 않습니다.
  - User-Agent는 `AgentValCon-claim-check/1.0 (+https://agentconcierge.biz/; contact@agentconcierge.biz)`입니다. 제공자가 우리 요청을 알아볼 수 있습니다.
- 공용 장부(`agent_market/provider_budget.py`)에 새 몫 `provider_claims`를 둡니다(도메인당 하루 6회 제안, 합계 60은 그대로). 429를 받으면 그날 그 도메인은 모두 멈춥니다.
- 한도: 계정당 활성 신청 20건, 확인 버튼 하루 10회, 같은 origin에 1분에 1회입니다. 계정 없는 요청은 받지 않습니다.
- nonce는 화면에 한 번만 보이고 로그에 남기지 않습니다. 실패 사유는 코드로만 저장합니다(원문 응답·헤더는 저장하지 않음).

## 5. 확인된 제공자가 얻는 것 (무료, 읽기 전용)

| 혜택 | 내용 | 바꿀 수 없는 것 |
|---|---|---|
| 시험 기록 | 자기 자원의 헬스 상태·최근 오류 코드, 마지막 시험 호출 결과, 시험 보고서 v2 판·점수·실패 사유(`exports/pearls/reports`) | 등급, 순위, 점수 |
| 설명 정정 요청 | 필드(이름·설명·분류)와 고칠 문장 1,000자, 근거 URL 하나. 운영자 검토 대기열로만 가고 자동 반영은 없음. 상태(접수·반영·반려)를 볼 수 있음 | 직접 수정 |
| 재시험 대기열 위치 | `report_v2`의 재시험 대기열에서의 순서와 예상 시각 | 순서 앞당기기 |

- 다른 고객의 실행 기록이나 사용자 질의는 보여 주지 않습니다. 제공자 자원의 공개 시험 결과만 보여 줍니다.
- 공개 페이지의 "제공자 확인됨" 표시는 두지 않습니다(PM 결정 3). 확인 여부는 제공자 본인 화면과 운영 화면에만 보입니다.
- 유료 이용권(알림·분석, AI AD Coin 설계)은 이 확인을 전제로 나중에 붙습니다.

## 6. 표와 등록 SQL

**구현에서 바뀐 점(11-15): public이 아니라 자기 스키마 `provider_claims`에 둡니다.**
- 이유: 애플리케이션 저장소는 시작할 때 공용 카탈로그(`application_store_sql.json`)에 적힌 모든 표가 운영에 있는지 검사합니다. 새 표를 카탈로그에 먼저 올리면, 표를 만들기 전까지 frontend가 시작하지 못합니다(schema_profile_mismatch). AD Coin v2와 같은 방식입니다.
- 앱은 표를 만들지 않습니다. 처음 쓸 때 `provider_claim_schema` 버전을 읽어 붙고, 없으면 기능이 꺼진 채(목록은 빈 값, 쓰기는 409)로 5분마다 다시 봅니다.
- 연결은 이 기능 전용으로 프로세스당 1개입니다. 스키마를 `provider_claims`로 고정하고, 문장마다 2초 제한을 겁니다. 모듈의 이름 붙은 SQL(`SQL`)만 보냅니다.
- 트리거와 함수는 만들지 않습니다. 운영 DB 구조 변경이므로 절차 대상입니다: `scripts.db_change_rehearsal run --sql deploy/db-changes/provider-claims-v1.sql` → 복구 SQL `deploy/db-changes/provider-claims-v1-rollback.sql` → 사용자 승인 → `check` 0 확인 뒤 실행. 애플리케이션의 DB 역할로 실행해야 앱이 스키마와 표를 소유합니다.
- 아래 표 정의는 설계 때 초안입니다. 실제 정의는 `agent_market/provider_self_claims.py`의 `DDL`과 위 SQL 파일입니다(시험이 둘을 대조함).

```sql
CREATE TABLE IF NOT EXISTS provider_self_claims(
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
  method TEXT NOT NULL CHECK (method IN ('well_known','dns_txt','protocol')),
  origin TEXT NOT NULL, resource_id BIGINT,            -- protocol 방법일 때만 자원 하나
  nonce_hash TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN
    ('pending','checking','verified','failed','lapsed','withdrawn','expired')),
  revision INTEGER NOT NULL, created DOUBLE PRECISION NOT NULL, expires DOUBLE PRECISION NOT NULL,
  verified_at DOUBLE PRECISION, next_check DOUBLE PRECISION, fail_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS provider_self_claims_live ON provider_self_claims(customer_id, origin, COALESCE(resource_id, 0))
  WHERE status IN ('pending','checking','verified');
CREATE INDEX IF NOT EXISTS provider_self_claims_origin ON provider_self_claims(origin) WHERE status='verified';
CREATE INDEX IF NOT EXISTS provider_self_claims_due ON provider_self_claims(next_check) WHERE status='verified';

CREATE TABLE IF NOT EXISTS provider_self_claim_checks(   -- 확인 요청마다 한 줄(감사)
  claim_id TEXT NOT NULL, at DOUBLE PRECISION NOT NULL, started_by TEXT NOT NULL,   -- user | recheck
  outcome TEXT NOT NULL, http_status INTEGER, ms INTEGER, PRIMARY KEY(claim_id, at));

CREATE TABLE IF NOT EXISTS provider_correction_requests(
  id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, resource_id BIGINT NOT NULL,
  field TEXT NOT NULL CHECK (field IN ('name','description','category')),
  proposed TEXT NOT NULL, evidence_url TEXT, status TEXT NOT NULL CHECK (status IN ('open','applied','declined','held')),
  created DOUBLE PRECISION NOT NULL, decided_at DOUBLE PRECISION, decided_by TEXT);
```

- 질의는 공용 카탈로그에 넣지 않고 모듈의 이름 붙은 `SQL` 목록(21개)만 씁니다. 자원 조회는 이미 등록된 `store.resource(rid)` 하나만 씁니다.
- 정정 요청의 결정(채택·반려·보류)은 운영 DB 쓰기입니다. 팀 세션은 운영 DB에 직접 쓰지 않으므로, 검토 화면(직원 로그인)이나 PM이 정하는 경로로 기록합니다(열린 문제).
- 운영자용 `provider_control_claims`(0건)를 넓혀 쓰지 않는 이유가 있습니다. 그 표는 직원 세션·워크스페이스 개정·HMAC 묶음에 맞춰져 있어, 고객 주체를 섞으면 검증 경로가 둘로 갈립니다. 확인 전송 코드(엄격한 JSON 대조, 4KiB, 리다이렉트 없음)는 같은 함수로 공유합니다.

## 7. 나눌 경계

| 팀 | 맡을 것 |
|---|---|
| 에이전트 팀 | 백엔드 모듈(`agent_market/provider_self_claims.py`), 고객 API(`/api/customer/provider-claims` 준비·확인·철회·목록·혜택 조회·정정 요청), 확인 전송(A·C, 2단계 B), 범위 계산, 시험, **정정 요청 검토(48시간 안에 채택·반려·보류)** |
| 성장·유통 | 에이전트 페이지의 "이 에이전트의 제공자입니까" 입구(11-19 묶음), 계정 화면 "내 에이전트"(안내문·확인 버튼·혜택 화면). 공개 문구는 영어. 디자인 시스템과 화면 정책(영역별 로딩, 팝업 없음)을 따름 |
| 운영·SRE | `provider_budget`의 `provider_claims` 몫, jobs의 다시 확인 단계, 공유 호스트 목록, DB 변경 리허설과 실행 준비, 정정 요청 대기 건수를 깔때기 줄에 |
| 검색과 RAG | 재시험 대기열 위치 조회 함수(읽기 전용), 수집기가 저장하는 카드·도구 정보에서 확인 표시 지우기 |
| AI AD Coin | 나중에 유료 이용권이 이 확인을 전제로 붙음 |

## 8. PM 결정 (11-15 11:0x)

1. 1단계 방법은 A(well-known 파일) + C(프로토콜 안 표시)입니다. B(DNS TXT)는 2단계입니다.
2. 대기 24시간, 확인 30일, 연속 2회 실패 시 `lapsed`를 그대로 씁니다.
3. 공개 "확인됨" 표시는 1단계에 두지 않습니다. 진주의 '검증'과 섞여 품질 보증처럼 읽힐 수 있기 때문입니다. 확인 여부는 제공자 본인 화면과 운영 화면에만 보입니다.
4. 재시험은 대기열 위치 보기만 줍니다. 요청 기능은 호출 예산과 악용 가능성을 본 뒤 정합니다. **돈을 내면 재시험이 빨라지는 길은 어떤 단계에서도 만들지 않습니다.**
5. 정정 요청은 에이전트 팀이 검토하고, 48시간 안에 채택·반려·보류를 적습니다. 자동 반영은 없습니다. 운영·SRE는 대기 건수만 매일 깔때기 줄에 넣습니다. 상태 값에 보류(`held`)를 더합니다.
   - 기록 경로(PM 11-15 11:2x): 에이전트 팀은 요청마다 권고(채택·반려·보류와 한 줄 이유)를 48시간 안에 git 밖 파일 `gateway-data/provider-claims/recommendations.jsonl`에 적습니다(`scripts/provider_correction_recommend.py`, 요청 목록은 `scripts.prod_ro_sql` 읽기). 운영 DB 기록은 직원 로그인으로 admin 검토 칸에서 누르는 사람(지금은 사용자)이 합니다. 파일을 DB에 자동 반영하는 길은 만들지 않습니다.
   - 요청자 화면에는 `waiting`, `recommendation_ready`(검토 중, 권고 준비됨), `decided`만 보이고 권고 내용은 보이지 않습니다.
   - admin 검토 칸(한국어, 11-19 묶음)은 요청 원문·권고·버튼 세 가지만 둡니다. `ProviderSelfClaims.waiting_corrections()`가 권고를 붙여 줍니다.
   - 운영 PG 연결은 상시 연결 없이 쓸 때 열고 닫으며, 자기 SQL 목록(`agent_market/provider_self_claims_sql.json`)에 있는 문장만 보냅니다(운영·SRE 11-15 검토, 7c76dbe4). 이 목록을 공용 카탈로그 밖에 두는 것은 PM 결정 사항입니다.

구현 순서
- 코드와 시험은 지금 시작합니다. 표가 없으면 기능이 꺼진 채로 둡니다(운영에 실려도 409나 빈 응답). AD Coin의 migrate 전 처리와 같은 방식입니다.
- 표 3개는 11-16 아침 묶음에 넣지 않습니다. 운영·SRE와 리허설을 11-17 밤에 하고, 통과하면 PM이 11-18에 사용자 승인을 요청합니다. 화면은 성장·유통이 11-19 묶음에 맞춥니다.
- 공용 장부의 새 몫 `provider_claims`(도메인당 하루 6회)는 운영·SRE 장부 담당과 맞춥니다.

## 9. 일정 (PM 승인 뒤)

| 일 | 담당 | 기간 |
|---|---|---|
| DB 변경 리허설·복구 SQL·등록 SQL | 에이전트 팀 + 운영·SRE | 1일 |
| 백엔드 모듈·API·A·C 확인·시험 | 에이전트 팀 | 2일 |
| 화면(입구·내 에이전트) | 성장·유통 | 2일(병렬) |
| 다시 확인 jobs 단계·장부 몫 | 운영·SRE | 0.5일 |
| 사용자 승인 뒤 운영 표 생성, frontend·jobs 배포 | 운영·SRE | 반나절 |
