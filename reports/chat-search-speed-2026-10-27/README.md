# Chat 검색 속도 개선 릴리스 (chat-search-speed-20261027-r1)

2026-10-27. frontend에만 배포했다(slot a). 이전 릴리스 `rag-sql-hardening-20261027-r3`은 slot b에 보존되어 있어 `./agentcon rollback frontend`로 되돌릴 수 있다.

## 패키지 구성

작업 트리에는 다른 작업자의 미배포 프론트엔드 변경이 있었다(`front.py`, `extracted_html.txt`, `new/` 자산). 특히 `operating.js`에는 r3에 들어간 Explore 로딩 표시 복구가 빠져 있었다. 그래서 작업 트리 전체를 패키징하지 않고, **r3 릴리스를 그대로 복사한 뒤 아래 8개 파일만 얹고** SQL 카탈로그를 다시 생성했다. 새 릴리스와 r3의 차이는 이 9개 파일과 `release.json`뿐이다.

| 파일 | 변경 |
|---|---|
| `agent_market/concierge/selection.py` | Chat 검색에 요청 단위 명세 파싱 캐시(`contract_reads`) 적용, 후보 순위는 요약 정보만 사용(`ranking_only`) |
| `agent_market/concierge/discovery.py` | `ranking_only`: 순위 계산에 필요한 열(`RANKING_COLUMNS`)만 읽고 전체 명세는 읽지 않음 |
| `agent_market/application_store_resource_batches.py` | 지정 열만 읽는 `columns` 옵션(카탈로그 열만 허용), 크기 확인을 `row_to_json` 대신 열별 `octet_length` 합으로 |
| `agent_market/gateway/constraints.py` | 푸에르토리코·카리브해를 latam 지역으로 인식(서울 날씨 질의에 푸에르토리코 전용 도구가 나오던 문제) |
| `agent_market/gateway/rag.py` | 임베딩 요청 `keep_alive: -1`(쉬는 동안 모델을 내리지 않음) |
| `agent_market/service_host.py` | frontend 시작 시 임베딩·gemma4 예열, 4분마다 재예열, 준비 상태에 `generation_warmup` |
| `agent_market/concierge/llm.py` | 1토큰 예열 호출 `ping()`(실패해도 번역 기능을 멈추지 않음) |
| `agent_market/gateway/server.py` | 번역 요청 동시 처리 2 → 8 |

## 측정

- 운영 카탈로그 읽기 전용 29개 질의: 평균 2.23초 → 0.99초(−56%), 29건 결과 모두 동일.
- 배포 후 공개 `/chat` 표본 5건: 새 프로세스의 첫 요청 1.7~3.5초, 같은 질의 반복 0.89초.
- 이전 방식은 전체 명세 읽기 바이트 한도 때문에 후보 일부를 조용히 빠뜨렸다(날씨 질의에서 587개 중 205개).

## 검증

- 스테이징 트리(= 배포 내용)에서 관련 테스트 1,897 통과 / 2 실패. 실패 2건(`test_discovery_workflow_upgrade::test_offline_runner_reports_failed_meaning_check...`, `test_front_security::test_client_context_id_cannot_be_hijacked`)은 순수 r3에서도 똑같이 실패한다(테스트가 r3에 없는 코드에 맞춰 수정됨).
- 테스트 중 서비스 PID 변화 없음.

## 운영 DB 인덱스 (2026-10-27 07:20~07:40, 사용자 승인)

- **원인:** 흔한 단어를 OR로 묶은 전문 검색이 일치 행을 최근순으로 정렬할 때, 도구 명세가 들어 있어 넓은 resources 본문(430MB)을 읽었다. `shared_buffers`가 128MB라 매번 디스크나 OS 캐시에서 읽었다.
- **추가한 인덱스:** 부분 커버링 인덱스 `resources_search_lookup ON resources (id) INCLUDE (kind, category, last_ok_at) WHERE active=1 AND health_status IN ('healthy','reachable') AND COALESCE(eval_security,'') NOT IN ('quarantine','review')`, 약 11MB. `CREATE INDEX CONCURRENTLY`로 2.56초 만에 생성했고, 서비스 중단이나 행 변경은 없었다.
- **resources 테이블 autovacuum 조정:** `autovacuum_vacuum_scale_factor=0.01`, `autovacuum_vacuum_threshold=1000`. 헬스체크가 분당 약 1,500행을 갱신해서, 기본값(20%)이면 vacuum 사이에 visibility map이 59%까지 떨어진다. 그러면 계획기가 인덱스만 읽는 경로를 포기하고 테이블 전체를 읽는다. 조정 후 VACUUM 1회(3.3초)로 visibility map이 99.97%가 됐고, autovacuum이 몇 분 간격으로 돌며 약 99.8%를 유지한다.
- **되돌리는 방법:** `DROP INDEX CONCURRENTLY resources_search_lookup;`, `ALTER TABLE resources RESET (autovacuum_vacuum_scale_factor, autovacuum_vacuum_threshold);`
- **도구:** `scripts/search_indexes.py`(기본은 확인만, `--apply`일 때 생성·설정·VACUUM). 정의는 `agent_market/admin_query_indexes.py`의 `SEARCH_INDEXES`와 `SEARCH_TABLE_SETTINGS`에 있다. 새로 설치하는 DB에는 `ensure_postgres`가 같이 적용한다. 테스트는 `tests/test_search_indexes.py`이며, 쿼리 조건과 부분 인덱스 조건이 어긋나지 않는지도 검사한다.
- **효과:** 운영 DB에서 읽기 전용으로 전문 검색 쿼리 24건(질의 8개 × MCP·A2A·전체)을 측정했다. 합계 **3.84초 → 1.00초(−74%)**, 결과는 24/24 동일하다. 앱 코드 변경과 배포는 필요 없었다.
- **검토 후 채택하지 않은 것:** 최근순 정렬 인덱스는 오히려 2.7배 느려졌다. 계획기가 행마다 전문 검색 일치를 다시 계산하기 때문이다. 함수 `COST` 조정은 SQL 함수가 인라인되어 효과가 없었다. GIN 일치 행을 먼저 구하는 쿼리(MATERIALIZED)는 임시 DB에서는 이득이 있었지만 운영에서는 1.00초 대 1.06초로 차이가 없어 넣지 않았다.
- **검증:** 운영 테이블의 복사본(pg_dump, 읽기 전용)을 임시 포트의 격리된 PostgreSQL에 올려 후보를 비교했고, 끝난 뒤 삭제했다. PostgreSQL 관련 테스트 500건 통과. 테스트 중 운영 서비스 PID 변화는 없었다.

### shared_buffers 128MB → 1GB (2026-10-27 07:44~07:46, 사용자 요청으로 실행)

- **절차:**
  - 백업 `gateway-data/postgres18/data/postgresql.conf.bak-20261027`
  - 프로젝트 블록 897번째 줄 `shared_buffers = '1GB'`로 변경
  - `./agentcon stop` → `pg_ctl -m fast restart` → `./agentcon start`
  - 공개 서비스 중단 약 80초
- **로케일 오류:** 첫 재시작은 `postmaster became multithreaded during startup` 오류로 실패했다. `LC_ALL=en_US.UTF-8 pg_ctl ... start`로 다시 시작해 정상 기동했다.
- **결과:** 29개 질의 평균 1.99초 → 0.97초(첫 회차), 1.56초 → 0.80초(두 번째 회차). 벡터 검색 2회 합계 517ms → 57ms. 시스템 여유 메모리 56%. 서비스는 같은 릴리스로 다시 떴다.
- **슬롯 상태:** 재시작 후 대기 슬롯(frontend a, admin b)은 실행되지 않는다(phase `stable`).
- **되돌리기:** 백업 파일을 복원한 뒤 같은 절차로 재시작한다.

### PostgreSQL launchd 등록 (2026-10-27 07:52~07:54, 사용자 요청)

- **등록 정보:** LaunchAgent `biz.agentconcierge.postgres18`. 원본 `deploy/launchd/biz.agentconcierge.postgres18.plist`를 `~/Library/LaunchAgents`에 설치했다. 레이블은 agentcon이 관리하는 범위(`biz.agentconcierge.498590e0b3.*`)와 겹치지 않는다.
- **동작 설정:**
  - `RunAtLoad`: 로그인·재부팅 시 자동으로 시작한다.
  - `KeepAlive SuccessfulExit=false`: 비정상 종료 때만 다시 시작한다. 그래서 `pg_ctl stop`으로 정상 종료하면 점검을 위해 꺼진 상태로 남는다.
  - `LC_ALL=en_US.UTF-8`, 로그는 `gateway-data/postgres18/server.log`에 이어서 기록, `ExitTimeOut=120`.
- **전환 절차:** `./agentcon stop` → `pg_ctl -m fast stop` → `launchctl bootstrap` → `./agentcon start`. 공개 서비스는 약 100초 중단됐다. 전환 후 `shared_buffers=1GB`가 유지되고 Chat 응답도 정상이다.
- **운영 명령:**
  - 점검용 중지: `pg_ctl -D gateway-data/postgres18/data -m fast stop`
  - 다시 시작: `launchctl kickstart gui/$(id -u)/biz.agentconcierge.postgres18`
  - 등록 해제: `launchctl bootout gui/$(id -u)/biz.agentconcierge.postgres18`
  - DB를 재시작할 때는 앞뒤로 `./agentcon stop`과 `./agentcon start`를 한다.
- **남은 공백:** DB가 비정상 종료되면 launchd가 DB는 다시 띄우지만, 앱 서비스는 끊긴 DB 연결을 다시 만들지 않는다(`connection_unusable`). 그래서 `./agentcon restart`가 필요하다. 운영 DB를 강제 종료하는 시험은 앱 연결을 끊게 되므로 하지 않았다.

### 앱 DB 재연결 (2026-10-27 08:15~08:17 배포 완료)

- **배포 방식:** 서비스별 현재 릴리스 위에 같은 패치(5개 파일)를 얹어 패키지를 만들었다. 카탈로그에서 바뀐 것은 `application_runtime.py` 소스 해시뿐이다.

  | 서비스 | 기반 릴리스 | 새 릴리스 | 방식 |
  |---|---|---|---|
  | frontend | `autonomous-agent-interop-20261027-r2` | `db-reconnect-frontend-20261027-r1` | 무중단 전환 |
  | admin | `chat-remediation-20261027-r4` | `db-reconnect-admin-20261027-r1` | 무중단 전환 |
  | jobs | `dependency-security-20261026-r3` | `db-reconnect-jobs-20261027-r1` | worker-deploy |
  | execution | `weather-news-contracts-20261026-r1` | `db-reconnect-execution-20261027-r1` | worker-deploy |

  frontend와 admin의 이전 슬롯은 롤백용으로 남겨 두었다.
- **배포 전 검증:** 서비스별 스테이징 트리에서 재연결 테스트 8/8 통과. 패치 전 기반과 비교해 새로 생긴 실패는 0건이다(최신 테스트와 예전 코드의 차이로 나는 기존 실패는 양쪽이 같다).
- **배포 후 확인:** 모든 서비스가 정상 실행 중이고 Chat 응답도 정상이다. admin의 `report existence check rejected: result_limit` 경고는 이전 admin에서도 01:05부터 5,990건 나온 기존 문제다.

- **저장소** `PostgresApplicationStore`(`application_store_postgres.py`): 트랜잭션을 시작할 때 세션이 끊겨 있으면 다시 연결한다. 미리 끊긴 것으로 표시된 경우뿐 아니라, `BEGIN`이 실패하고 연결이 끊긴 것으로 확인된 경우에도 그렇다. 앱 코드가 아직 실행되기 전이라 안전하다. 트랜잭션 도중에 끊기면 그 요청은 실패하고 다시 실행하지 않으며, 다음 요청부터 새 세션을 쓴다. DB가 아직 내려가 있으면 다시 연결하는 시도는 1초에 최대 1번이다. 연결 팩토리를 설정한 런타임 세션만 다시 연결하고, 세션 잠금을 쓰는 운영자 도구(마이그레이션·복원)는 이전처럼 실패 상태를 유지한다.
- **런타임** `application_runtime.py`: 주 저장소, 관리자 읽기 세션(다시 연결한 뒤 `default_transaction_read_only=on`을 다시 적용), Chat 대화형 세션에 연결 팩토리를 넣었다. 종료할 때는 새로 만든 세션까지 닫는다.
- **풀** `admin_postgres_pool.py`: 다시 연결한 저장소의 현재 세션을 추적한다. 죽은 세션은 닫고 새 세션은 계속 쓴다.
- **서비스 제어** `service_runtime.py`·`service_host.py`:
  - frontend와 admin의 `ServiceControl`은 다시 연결한다.
  - jobs와 execution은 소유 advisory lock이 세션과 함께 사라지므로 다시 연결하지 않는다. 대신 heartbeat가 실패하면 non-zero로 종료하고, launchd가 재시작해 소유권을 다시 얻는다.
  - 이전에는 종료 시 heartbeat가 성공하면 exit 0으로 끝나 재시작되지 않을 수 있었다.
- **테스트:**
  - 일회용 PostgreSQL에서 `pg_terminate_backend`로 세션을 끊는 `tests/test_postgres_reconnect.py` 8건을 추가했다: 쉬는 세션 자동 재연결, 진행 중 작업 재실행 안 함, 팩토리 없는 저장소는 실패 유지, 백오프, 풀, 런타임 세션 설정 재적용, frontend·admin 재연결과 소유 워커 재연결 금지, 소유권 상실 시 non-zero 종료.
  - 관련 회귀 500건 통과, 운영 서비스 PID 변화 없음.

### admin `report existence check rejected: result_limit` 경고 (2026-10-27 08:34 admin 배포 완료)

- **배포 후 확인:** `report-pages-admin-20261027-r1`이 admin 슬롯 a에서 실행 중이고, 이전 릴리스는 슬롯 b에 보존되어 있다. 배포된 것과 같은 `find_existing`을 운영 DB에 읽기 전용으로 실행했다. a2a·mcp의 기존 대상은 2~5ms 만에 찾았고, 없는 대상은 2,001건을 모두 확인한 뒤 None을 돌려줬다(38~53ms). `result_limit`는 발생하지 않았다.

- **원인:** `report_creation.find_existing`이 중복 확인을 위해 같은 프로토콜의 리포트를 한 번에 모두 읽었다. 운영 데이터는 a2a 2,001건, mcp 2,001건으로 PostgreSQL 저장소의 쿼리당 한도(2,000행)를 넘는다. 그래서 a2a·mcp의 중복 확인 API(`/admin/api/test-reports/existing`)가 매번 400을 돌려줬고, 같은 함수를 쓰는 리포트 생성도 실패했을 것으로 보인다. x402(532건)는 영향이 없다.
- **수정:** 비교 규칙(정규화한 주소 비교)은 그대로 두고, 같은 쿼리를 id 기준으로 1,000행씩 나눠 읽는다(`... AND id>? ORDER BY id LIMIT 1000`). SQL 카탈로그 문장 수는 3,801개 그대로다(기존 쿼리를 대체).
- **검증:**
  - `tests/test_report_existence_pages.py`: 일회용 PostgreSQL에 리포트 2,101건을 넣고 마지막 페이지의 표기만 다른 주소(대소문자·기본 포트·끝의 점)도 찾는지, 없는 대상은 None인지, admin 확인 경로가 동작하는지 확인했다. 3건 통과.
  - 리포트·PostgreSQL 회귀 677건 통과. 실패 1건(`test_reported_frontend_defects`의 HTML 메타데이터 테스트)은 기존 실패다.
  - 스테이징에서 리포트 관련 테스트 69건 통과.
- **패키지:** `report-pages-admin-20261027-r1`(기반 `db-reconnect-admin-20261027-r1` + `report_creation.py` + 카탈로그). 배포 명령: `./agentcon deploy admin report-pages-admin-20261027-r1`.

### (적용 전 기록) 남은 DB 병목

- 운영 DB의 캐시 적중률이 **70.5%**다. 검색에 쓰이는 데이터는 HNSW 인덱스 712MB, resources 본문 430MB, 전문 검색 테이블과 GIN 인덱스를 합쳐 약 1.3GB인데, `shared_buffers`는 128MB이고 호스트(RAM 16GB)의 남은 메모리는 약 200MB다. 그래서 벡터 검색이 데워져 있으면 4ms지만, 캐시에서 밀려나면 약 250ms 걸린다.
- 이 때문에 Chat 검색 평균은 아직 약 1.6~2.0초다(29개 질의, 머신 load average 약 7).
- 권장: `shared_buffers`를 1GB 안팎으로 올리고 `effective_cache_size`를 조정한다(PostgreSQL 재시작 필요, 운영자가 수행). 메모리가 부족한 상태라면 같은 머신의 다른 상주 프로세스 메모리부터 확인한다.

## 남은 한계

- **비영어 질문 번역 약 1초:** 모델 서버의 요청당 생성 속도(초당 약 25~30토큰)에 묶여 있다. 원문 커버리지 검증용 `source` 반복은 안전장치라 유지했다. 키 이름만 줄이는 형식은 1.26초가 1.21초가 되는 데 그쳤고, 형식이 깨지는 사례가 있어 채택하지 않았다.
- **처음 보는 주제 1.5~2초:** 흔한 단어를 OR로 묶은 전문 검색이 수만 건과 일치하면, PostgreSQL이 넓은 resources 테이블을 훑어 최근순으로 정렬한다(약 300~380ms, 디스크 5만 페이지). MATERIALIZED CTE로도 개선되지 않았다(결과 24/24 동일, 시간 비슷). → 위 "운영 DB 인덱스" 절에서 커버링 인덱스와 autovacuum 조정으로 해결했다(−74%). 남은 병목은 DB 캐시 크기다.
- 벡터 검색은 `hnsw.ef_search=40`, iterative scan off 상태에서 필터 때문에 LIMIT 100 중 10건 정도만 돌려주는 경우가 있다. 속도 문제는 아니고 재현율 문제여서 이번 범위에서는 제외했다.
