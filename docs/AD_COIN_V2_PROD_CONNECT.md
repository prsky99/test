# AI AD Coin v2 운영 연결 준비와 승인 요청 목록

- **작성:** 2026-11-10, AI AD Coin 팀
- **목적:** v2를 운영에 연결하는 데 필요한 것을 한곳에 모은다. **아직 아무것도 실행하지 않았다.** 운영 DB 변경은 총괄 PM을 거쳐 사용자 승인을 받은 뒤에만 한다.
- **연결하면 열리는 범위:** 무상 활동 포인트 모드(`docs/AD_COIN_POINTS_MODE.md`)와 Sponsored 영역(`docs/AD_COIN_SPONSORED_SLOT.md`). 실가치 경로(`AD_COIN_REAL_VALUE_ENABLED`)는 계속 꺼 둔다.

## 1. 승인이 필요한 일 (사용자 결정)

| # | 일 | 바뀌는 것 | 되돌리기 |
|---|---|---|---|
| A1 | 운영 PostgreSQL에 v2 표 만들기 | `adc2_` 표 53개, 색인 31개, 함수 5개, 트리거(원장 불변성 검사), 스키마 행 1개(`real_value=0`). 기존 표는 건드리지 않는다. 지우는 문장이 없다(`drops_or_deletes_data: false`) | 표를 지우는 것은 데이터 삭제라 별도 승인이 필요하다. 쓰지 않으면 비어 있을 뿐이다 |
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
- 시험: `tests/test_ad_coin_v2_migrate_script.py`. 빈 DB에서 상태 확인 → 두 번 migrate → 표 53개, 스키마 9, `real_value=0`.

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
