# AI AD Coin v2 운영 연결 준비와 승인 요청 목록

- **작성:** 2026-11-10, AI AD Coin 팀
- **목적:** v2를 운영에 연결하는 데 필요한 것을 한곳에 모은다. **아직 아무것도 실행하지 않았다.** 운영 DB 변경은 총괄 PM을 거쳐 사용자 승인을 받은 뒤에만 한다.
- **연결하면 열리는 범위:** 무상 활동 포인트 모드(`docs/AD_COIN_POINTS_MODE.md`)와 Sponsored 영역(`docs/AD_COIN_SPONSORED_SLOT.md`). 실가치 경로(`AD_COIN_REAL_VALUE_ENABLED`)는 계속 꺼 둔다.

## 0. 2026-11-10 장애와 바뀐 점 (먼저 읽을 것)

- **장애:** 05:38에 첫 migrate가 v2 표와 트리거를 애플리케이션의 `public` 스키마에 만들었다. 애플리케이션 저장소는 연결할 때마다 `public`의 트리거가 자기 것 5개와 정확히 같은지 검사한다(`_validate_native_invariants`). 그래서 공개 사이트 전체가 500을 냈고 jobs도 멈췄다. 트리거 12개를 지워 05:40에 복구됐다.
- **바뀐 점:** v2는 이제 **자기 스키마 `ad_coin_v2`**에만 표, 함수, 트리거를 만든다. 모든 v2 연결은 `search_path`를 `ad_coin_v2`로 고정한다. 애플리케이션 검사는 그대로 엄격하게 둔다.
- **migrate 안전장치:** 실행 전후에 애플리케이션 저장소 검사를 직접 돌린다. 실행 전 검사에 실패하면 아무것도 하지 않고 멈춘다. 실행 뒤 검사에 실패하면 오류를 내서 바로 알 수 있게 한다.
  - 시험: `tests/test_ad_coin_v2_app_store_coexistence.py`
    - 마이그레이션 뒤 애플리케이션 저장소가 열린다.
    - `public`에 v2 표·트리거가 0개다.
    - 장애 상태를 재현하고 정리한 뒤 복구된다.
    - 데이터가 있으면 정리를 거부한다.
- **운영에 남은 것:**
  - `public`에 빈 v2 표 54개와 함수 5개가 남아 있다.
  - 첫 migrate가 넣은 기본 행 3개(schema, assets, commercial_control)도 있다.
  - 트리거는 지워졌다. 애플리케이션 검사는 트리거만 보므로 지금 장애는 없다.

**다시 연결하는 순서(승인 뒤, PM 실행):**

```bash
.venv/bin/python -m scripts.ad_coin_v2_migrate public-status --dsn-file <dsn 파일> --key-file <workflow 키 파일>
```

```bash
.venv/bin/python -m scripts.ad_coin_v2_migrate drop-public --dsn-file <dsn 파일> --key-file <workflow 키 파일> --i-have-approval
```

```bash
.venv/bin/python -m scripts.ad_coin_v2_migrate migrate --dsn-file <dsn 파일> --key-file <workflow 키 파일> --i-have-approval
```

- `public-status`는 읽기만 한다. 기대값: 표 54개, 함수 5개, `data_tables` 빈 목록
- `drop-public`은 기본 행 말고 데이터가 하나라도 있으면 거부한다. 지운 뒤 애플리케이션 검사를 돌린다.
- `migrate`는 `ad_coin_v2` 스키마에 만들고 전후로 검사한다. 트리거를 다시 만드는 SQL을 손으로 돌릴 필요는 없다.

## 0-1. 운영 DB 구조 변경은 사본 리허설부터 (2026-11-10 운영·SRE, 4c371fb5)

v2 migrate 같은 운영 DB 구조 변경은 운영에서 실행하기 전에 사본 리허설을 거친다. 리허설은 운영 버전 코드로 앱 연결(트리거 불변 검사)까지 통과해야 한다. 05:38 장애와 같은 트리거 변경은 이 리허설에서 실패로 잡힌다. 운영 실행 직전에는 같은 명령으로 `check`를 한 번 더 돌린다. 절차는 `deploy/DATABASE_OPERATIONS.md`의 "운영 DB 구조 변경" 절에 있다.

```bash
.venv/bin/python -m scripts.db_change_rehearsal run --command "python -m scripts.ad_coin_v2_migrate migrate --dsn-file {dsn_file} --key-file {key_file} --i-have-approval"
```

## 0-2. v2 켜기 (A2): 운영 설정 파일은 `gateway-data/agentcon.env`

- 세 줄을 넣는다.
  - `AD_COIN_V2_ENABLED=1`
  - `AD_COIN_V2_POOL_MAXIMUM=2`
  - `AD_COIN_V2_KEY_DIR=/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/ad_coin_v2_keys`
- **키 폴더는 반드시 이 절대 경로여야 한다.** 상대 경로면 배포 버전마다 키가 달라진다.
- 설정 검사: `.venv/bin/python scripts/agentcon_config.py --check --env-file gateway-data/agentcon.env`
- 설정은 프로세스가 시작할 때 읽는다.
- **`./agentcon restart frontend`는 쓰지 않는다.** 이 명령은 작업본(다른 세션의 미커밋 변경 포함)으로 새 버전을 만든다.
- 설정만 다시 읽히려면 활성 버전을 그대로 복제한 버전(파일 변경 0)을 `--base`로 패키징해 배포한다.
  - 11-10 켤 때 쓴 버전: `adcoin-v2-on-frontend-20261110-r1`
  - 원본 설정 백업: `gateway-data/agentcon.env.before-adcoin-v2-20261110`
- **11-10 운영 결과:**
  - `/ad-coin/v2` 200
  - `/api/ad-coin/v2/sponsored` 200(Sponsored 표시)
  - `/real/deposits` 404
  - `schema_invariants_mismatch` 새로 0건
  - 키 폴더 0700
  - DB 연결 17
- 되돌리기: `AD_COIN_V2_ENABLED=0`으로 바꾸고 재시작한다. 표는 그대로 둔다.

## 0-3. 사이트 로그인 연결과 포인트 교환 (2026-11-10, PM 승인)

- **전에는:** v2 인증이 `adc2_human_sessions`만 봤다. 운영에는 그 표에 세션을 넣는 경로가 없어서, 로그인한 사이트 사용자도 `/ad-coin/v2`에서 401을 받았다.
- **바뀐 점:** `__Host-ac_customer_session` 쿠키가 있으면 사이트 고객 인증(`customer_identity.actor`)으로 요청마다 다시 확인한다(`live_auth.site_customer`).
  - 다른 출처 요청은 거부한다(`same_origin`). 쓰기는 사이트 CSRF(`X-CSRF-Token` = `identity.csrf(token)`)가 필요하다.
  - 같은 쿠키가 두 개 오면 거부한다.
  - 로그아웃·폐기·만료는 다음 요청부터 바로 401이다(캐시 없음).
- **v2 id:** 고객 id를 서버 비밀 키로 HMAC-SHA256한 값을 uuid로 바꿔 쓴다(owner, principal, wallet). 고객 id만 알아서는 v2 id를 계산할 수 없다.
  - 키 파일: `<AD_COIN_V2_KEY_DIR>/owner-link.key`(0600, 처음 한 번 생성, git 제외)
  - **이 키를 잃거나 바꾸면 모든 사람이 새 v2 계정으로 보인다.** 백업 대상이다. 키가 고정되지 않으면(무작위 키) 연결을 켜지 않고 시작을 거부한다.
- **처음 열 때** 일반 사람 권한(`HUMAN_CAPABILITIES`)의 주체, 광고 설정, 지갑을 만든다. 광고주·운영자 권한은 주지 않는다. 고객 id·이메일·이름은 저장하지 않는다.
- **포인트 교환:** `POST /api/ad-coin/v2/points-exchanges` `{"credits": 1~10}`
  - 로그인, 사이트 CSRF, Idempotency-Key(교환 id)가 필요하다. 고객 id는 본문이 아니라 세션에서 가져온다.
  - 같은 키로 다시 보내면 한 번만 차감한다. 이미 환불된 교환이면 `refunded`를 돌려준다.
  - 크레딧 지급은 작업자 데몬이 한다. **데몬 재설치 필요.**
- **남은 한계(리뷰 11-10)**
  - 교환 작업(outbox)에 고객 id가 v2 owner와 함께 남는다. 작업자가 크레딧을 주는 데 필요하다. DB를 읽을 수 있는 사람은 연결할 수 있다.
  - 사람별 교환 속도 제한이 없다. 월 50크레딧 상한은 크레딧 쪽에서 막고 포인트는 환불된다.
- 시험: `tests/test_ad_coin_v2_site_session.py`

## 1. 승인이 필요한 일 (사용자 결정)

| # | 일 | 바뀌는 것 | 되돌리기 |
|---|---|---|---|
| A1 | 운영 PostgreSQL에 v2 표 만들기 | **`ad_coin_v2` 스키마에** `adc2_` 표 54개(코인 경제의 Sponsored 예약 표 `adc2_sponsored_bookings` 포함), 색인 32개, 함수 5개, 트리거(원장 불변성 검사), 스키마 행 1개(`real_value=0`). 기존 표는 건드리지 않는다. 지우는 문장이 없다(`drops_or_deletes_data: false`) | 표를 지우는 것은 데이터 삭제라 별도 승인이 필요하다. 쓰지 않으면 비어 있을 뿐이다 |
| A2 | v2 켜기 | frontend 설정에 `AD_COIN_V2_ENABLED=1`을 넣고, 처음에는 `AD_COIN_V2_POOL_MAXIMUM=2`로 시작한다 | 설정을 지우고 다시 배포 |
| A3 | 운영 설정 허용 목록 바꾸기 | `scripts/agentcon_config.ALLOWED_KEYS`에 `AD_COIN_V2_ENABLED`, `AD_COIN_V2_POOL_MAXIMUM`, `AD_COIN_V2_KEY_DIR`를 추가한다(공용 파일이라 운영·SRE와 조율) | 코드 되돌리기 |

**실행 명령**(A1, 승인 뒤에만):

```bash
.venv/bin/python -m scripts.ad_coin_v2_migrate plan
```

```bash
.venv/bin/python -m scripts.ad_coin_v2_migrate status --dsn-file <dsn 파일> --key-file <workflow 키 파일>
```

```bash
.venv/bin/python -m scripts.ad_coin_v2_migrate migrate --dsn-file <dsn 파일> --key-file <workflow 키 파일> --i-have-approval
```

- `plan`은 DB에 연결하지 않고 만들 것만 보여 준다.
- `migrate`는 `--i-have-approval`이 없으면 거부한다. 여러 번 실행해도 결과가 같다. 연결은 하나만 쓴다.
- 시험: `tests/test_ad_coin_v2_migrate_script.py`. 빈 DB에서 상태 확인 → 두 번 migrate → 표 54개, 스키마 10, `real_value=0`.

## 2. 연결 예산 (운영 DB `max_connections` 48)

- v2는 프로세스마다 전용 세션 풀을 쓴다. 기본 최대 4개, 처음에는 2개를 권장한다.
- frontend 슬롯 2개에서 최대 **4개**(2×2), 기본값이면 8개가 늘어난다. v1 AD Coin은 꺼져 있어 지금 쓰는 세션은 0이다.
- 켜기 전에 운영 연결 수를 확인하고, 여유가 10개보다 적으면 1개로 시작한다.

## 3. 이번에 고친 연결 결함 (운영 연결 전 필수)

1. **v2를 켜면 서버가 시작하지 못했다.**
   - `front.py`가 `create_live_ad_coin_v2_router()`를 저장소 없이 불렀고, 그러면 `ModelStore()`를 인자 없이 만들다 오류가 났다.
   - **고침:** `front.py`가 애플리케이션 저장소를 넘긴다(`app_store=front.store`). v2는 v1처럼 같은 DB에 작은 전용 풀을 만든다(`store_from_application`). 저장소 없이 부르면 분명한 오류를 낸다.
2. **서명 키가 프로세스마다 달랐다.**
   - 키 환경 변수가 없으면 프로세스마다 임의 키를 만들었다.
   - 그래서 한 슬롯에서 받은 확인(fresh challenge)이 다른 슬롯에서 실패하고, 재시작하면 이전 영수증을 검증할 수 없었다.
   - **고침:** 운영 경로는 `gateway-data/ad_coin_v2_keys/`의 키 파일(소유자만 읽기, 0600)을 쓴다. 파일은 처음 한 번만 만들고, 동시에 시작해도 한 파일을 함께 쓴다. 이 폴더는 git에 넣지 않는다.
   - 시험: `test_v2_keys_persist_in_owner_only_files`

## 4. SQL 등록

- v2는 이름 붙인 SQL 목록(`agent_market/ad_coin/v2/sql.py`)만 실행한다. 모든 문장은 AD Coin 등록 목록(`agent_market/ad_coin/sql_registry.json`, 현재 543개 모양)을 통과해야 DB에 닿는다.
- 운영 애플리케이션 저장소의 등록 목록(`application_store_sql.json`)과는 따로 있다. v2는 자기 풀에서 자기 목록만 쓴다.
- 새 문장을 더하면 `.venv-tests/bin/python -m scripts.ad_coin_sql_registry --add-v2 --write`로 다시 만든다.

## 5. 배포 순서 (승인 뒤)

1. A3 허용 목록 → 운영·SRE와 함께 배포
2. A1 `plan` → `status` → `migrate --i-have-approval` → `status`로 확인
3. 활성 frontend 판 위에 v2 파일을 겹친다. 기준 판은 `--base`로 기록한다. `front.py`는 활성 판 사본에 v2 마운트 한 줄만 바꾼다.
4. 게이트(`scripts.release_gate`)를 통과한 뒤 A2 설정으로 배포하고, `/api/ad-coin/v2/sponsored`와 `/ad-coin/v2`를 확인한다.
5. 문제가 있으면 `AD_COIN_V2_ENABLED`를 지우고 다시 배포한다. 표는 그대로 둔다.
