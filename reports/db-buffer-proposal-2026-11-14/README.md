# 운영 DB 메모리 버퍼 안 (검색과 RAG, 2026-11-14)

PM 16:2x 지시 ③의 안입니다. **아직 아무것도 바꾸지 않았습니다.** 운영 DB에는 읽기 전용으로만 붙어 숫자를 읽었습니다.

## 목적

처음 보는 질의의 추천·탐색에서 ann(벡터 그래프 읽기)과 projection(후보 행 읽기)이 0.1~0.9초를 씁니다(F07 기록 `reports/f07-latency-2026-11-14/README.md`). 같은 질의를 다시 보내면 0.04~0.5초로 줄어드는데, 질의 결과 캐시가 아니라 DB 페이지가 메모리에 있느냐의 차이입니다.

## 지금 값 (11-14 16:3x, 읽기 전용 조회)

| 항목 | 값 |
|---|---|
| PostgreSQL | 18.6 (Homebrew), launchd `biz.agentconcierge.postgres18`, 포트 55432 |
| shared_buffers | 2GB (`gateway-data/postgres18/data/postgresql.auto.conf`, ALTER SYSTEM 값. postgresql.conf의 1GB보다 우선) |
| effective_cache_size | 6GB (같은 파일) |
| work_mem / maintenance_work_mem | 48MB / 128MB |
| max_connections | 48 |
| shared_preload_libraries | 없음 |
| pg_prewarm 확장 | 설치 가능(available), 만들어져 있지 않음 |
| DB 크기 | 16GB |
| 버퍼 적중률(누적) | 90.3% |

검색이 읽는 관계와 크기:

| 관계 | 크기 | 3분 동안 검색 횟수 | 3분 동안 읽은 블록(적중/디스크) |
|---|---|---|---|
| embeddings_half_a2a (A2A 그래프) | 457MB | 29 | 69,886 / 22,257 (적중 75.8%) |
| embeddings_half_mcp (MCP 그래프) | 85MB | 22 | 53,794 / 6,395 (89.4%) |
| embeddings_half_x402 | 254MB | 0 | 0 / 0 |
| **embeddings_cosine_hnsw (공용 그래프)** | **1,647MB** | **0** | **7,314 / 6,528** |
| resources (표) | 773MB | - | 누적 적중 82.8% |
| explore_documents (표) | 362MB | - | 누적 적중 99.3% |

- 검색은 종류별 반정밀도 그래프(a2a·mcp)만 씁니다. 두 개를 합쳐 542MB입니다.
- **공용 그래프는 3분 동안 검색에 한 번도 쓰이지 않았는데 블록 13,842개(약 108MB)를 건드렸습니다.** 새 벡터가 들어올 때 이 색인도 함께 고쳐지기 때문으로 봅니다. 쓰지 않는 1.6GB 색인이 버퍼를 밀어내고 쓰기 비용을 늘리는 셈입니다(누적 검색 564,508회는 11-12 종류별 그래프 도입 전의 값으로 봄. 하루 더 재서 확인).

## 맥 메모리 여유 (16GB, 16:3x)

- 스왑 6GB 중 **4.7GB 사용**(여유 1.4GB). 시스템 여유 36%(비활성 포함), 고정(wired) 약 3.7GB, 빈 페이지 거의 0.
- 큰 프로세스(상주 메모리 합): Claude 앱 계열 약 1.7GB, Chrome 0.8GB, postgres 0.66GB(공유 버퍼는 따로), frontend 0.55GB, Ollama 0.43GB, Codex 0.32GB.
- **결론: 지금 shared_buffers를 늘리면 스왑이 더 늘어 오히려 느려질 위험이 큽니다.**

## 안

| 안 | 내용 | 재시작 | DB 변경 절차 | 기대 효과 | 위험 |
|---|---|---|---|---|---|
| **A (권장 1순위)** | 쓰지 않는 공용 그래프 `embeddings_cosine_hnsw`를 없앰. 먼저 72시간 동안 검색 0회를 확인하고, 앱 코드가 이 색인을 고르는 경로(종류 그래프가 없을 때의 대체)가 남아 있는지 확인 | 필요 없음 | 필요(색인 삭제 = DDL: 사본 리허설 → 복구 SQL → 사용자 승인 → check 0) | 쓰기 때 버퍼 오염과 쓰기 비용 감소, 디스크 1.6GB 확보. 종류 그래프의 적중률이 오르는지 사본에서 잼 | 대체 경로가 남아 있으면 그 경로가 느려짐. 복구는 색인 다시 만들기(사본 실측 시간 필요) |
| B | `pg_prewarm` 확장을 만들고 a2a·mcp 그래프(542MB)를 공유 버퍼에 미리 올림. 매일 1회와 DB 시작 직후 실행 | 필요 없음(자동 preload를 쓰면 필요) | 필요(CREATE EXTENSION = DDL) | 처음 보는 질의의 ann 디스크 읽기 감소. 다른 페이지에 밀려나므로 효과는 일시적 | 공유 버퍼 2GB 중 542MB를 먼저 차지 |
| C (지금은 비권장) | shared_buffers 2GB → 3GB | **필요**(postmaster 설정) | DB 재시작 절차: 앱 먼저 중지(`./agentcon stop`) → DB 재시작 → 앱 시작, 공개 중단 약 80~100초, 사용자 승인 | 적중률 상승 | 스왑 4.7/6GB 사용 중이라 메모리 부족으로 더 느려질 수 있음. 메모리를 비운 뒤에만 고려 |

A의 근거: `agent_market/postgres_ann.py` `kind_graph_search`는 종류를 묻지 않는 검색도 종류별 그래프 세 개(a2a·mcp·x402)를 따로 읽어 거리순으로 합칩니다. 공용 그래프는 종류 그래프가 아직 없거나(`layout()['kind_indexes']`가 거짓) 알 수 없는 종류일 때만 쓰입니다. 코드 주석에도 "공용 그래프는 삽입 때 유지만 되며, 72시간 동안 검색이 없으면 지울 수 있다(별도 승인)"고 적혀 있습니다(11-12 PM A3). 그래서 A는 72시간 검색 0회를 확인한 뒤 신청합니다(11-14 16:30 기준 누적 idx_scan 564,508에서 시작).

권장 순서: A를 먼저(72시간 관찰 → 사본 측정 → 승인), 효과가 모자라면 B. C는 맥 메모리를 확보한 뒤에 다시 봅니다.

## 사본에서 잴 것 (아직 안 함)

- 사본 클러스터(포트 55447)에 운영 백업을 복원하고, 처음 보는 질의 30개(탐색 15·추천 15)를 같은 순서로 보내 ann·projection 구간과 디스크 읽기 블록을 잽니다.
  1. 지금 그대로
  2. A 적용 뒤(공용 그래프 삭제)
  3. A + B(미리 올림) 뒤
- 각 단계 사이에 사본 DB를 재시작해 캐시를 같은 상태로 맞춥니다(사본이라 운영 영향 없음).
- 시간: 사본 복원이 1~1.5시간 걸립니다(11-14 그래프 상한 리허설 실측). 11-15 밤 00:30~03:30은 다른 리허설이 잡혀 있으므로, **11-15 낮(무거운 작업 칸 1개, 측정 시간 :55~:10 피함)이나 11-16 밤 B+C 배포 뒤**를 제안합니다. PM이 시각을 정해 주세요.

## 복구 방법

- A(색인 삭제): 사본에서 실측한 `CREATE INDEX CONCURRENTLY ... USING hnsw (...)` 문장을 복구 SQL로 준비합니다(만들 때 걸리는 시간도 사본에서 잼). 삭제 전 색인 정의(`pg_get_indexdef`)를 파일로 남깁니다.
- B(미리 올림): `DROP EXTENSION pg_prewarm;` 미리 올린 페이지는 그대로 두면 자연히 밀려납니다.
- C(설정): `ALTER SYSTEM SET shared_buffers = '2GB';` 뒤 같은 재시작 절차. 지금 값은 `postgresql.auto.conf`에 있고, 바꾸기 전에 파일을 백업합니다.

## 승인이 필요한 것 (PM이 모아서 사용자에게)

- A: 운영 색인 삭제(DDL), DB 재시작 없음
- B: 운영 확장 만들기(DDL), DB 재시작 없음
- C: 운영 DB 설정 변경과 재시작(공개 중단 약 80~100초)

## 11-14 16:4x PM 결정 뒤 진행 (안 A)

PM 결정: 안 C는 하지 않음. 안 A는 72시간 관찰(11-17 17시경까지) → 11-17 밤 00:30 사본 측정 → 11-18 아침 PM이 모아서 사용자 승인 요청. 안 B는 안 A 결과를 본 뒤 정함.

### 관찰 기준값과 지금까지의 기록

- 기준값: `baseline-1114.json`(11-14 16:4x, 읽기 전용). 공용 그래프 idx_scan 564,508, **last_idx_scan 2026-11-13 09:31:41 KST**. 색인 정의도 같은 파일에 보관(복구용):
  `CREATE INDEX embeddings_cosine_hnsw ON agentcon_search.embeddings USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')`
- 매시간 기록(`logs/ops/vector-index-usage.jsonl`, `scripts/vector_index_usage.py`, 11-12 13:16부터 53줄): 공용 그래프에 검색이 있었던 마지막 시간은 11-13 10:01 줄(55회). 그 뒤 31시간 동안 검색 0회인데 **유지 비용으로 디스크 블록 8,847,202개(약 72.5GB, 시간당 약 2.3GB)를 읽었습니다.** 같은 시간 종류별 그래프 half_a2a는 시간당 57~107만 블록을 읽었습니다(버퍼 경쟁).
- 72시간 끝: 마지막 검색 기준 11-16 09:31, PM 관찰 기준 11-17 17시. 11-17 17시에 `last_idx_scan`과 매시간 기록을 다시 읽어 0회를 확인합니다.

### 이 색인을 쓸 수 있는 경로 점검 (코드·등록 SQL)

- 벡터 거리 연산자(`<=>`, `<->`, `<#>`)를 쓰는 앱 코드는 두 곳뿐: `agent_market/postgres_ann.py`(`nearest`)와 `agent_market/concierge/discovery.py`(탐색·추천 후보). 둘 다 `kind_graph_search`를 거칩니다.
- Chat·추천(fast_chat → 추천기 → discovery), MCP(find_agents·chat·search), A2A, REST 탐색은 모두 같은 discovery 경로입니다. jobs와 관리 화면에는 벡터 거리 쿼리가 없습니다(evaluation·수집·정리는 벡터를 쓰기만 함).
- 등록 SQL 목록(`agent_market/application_store_sql.json`)에 거리 연산 문장은 0개입니다.
- 평가·리허설 스크립트(`scripts/evaluate_design21_filtered_ann.py`, `scripts/rehearse_quality_native_indexes.py`)는 사본·개인 클러스터 전용이고 운영 DSN을 받지 않습니다.
- `kind_graph_search`가 공용 그래프로 가는 조건은 둘: ① 종류 그래프 셋 중 하나라도 유효하지 않을 때(`layout()['kind_indexes']` 거짓) ② a2a·mcp·x402가 아닌 종류를 물을 때. **②는 이번에 막음**: 벡터의 종류는 셋뿐이라(운영 a2a 227,767·x402 124,740·mcp 42,692) 다른 종류는 빈 결과를 돌려주게 고침(시험 추가). ①은 종류 그래프가 깨졌을 때의 대체 경로라, 삭제 뒤에는 그 경우 전체 훑기(느림)가 됩니다. 삭제 전에 종류 그래프 셋이 유효한지 확인하는 단계를 복구 절차에 넣습니다.

### 11-15 밤 그래프 상한 리허설과의 관계

- 그래프 상한(`scripts/embeddings_graph_cap.py`)은 a2a·x402 행에 표시(in_kind_graph)를 다는 UPDATE를 약 5만 4천 행(a2a 약 7천, x402 약 4만 7천) 합니다. 표시 칸이 새 부분 색인의 조건이라 이 UPDATE는 HOT가 될 수 없고, **바뀐 행마다 공용 그래프(1.6GB)에도 새 항목이 들어갑니다.** 즉 그래프 상한은 공용 그래프를 건드립니다.
- 11-15 00:30 사본 리허설 스크립트에 표시 단계 직전·직후의 색인별 블록 적중·읽기·검색 수를 남기는 단계(`apply_index_io`)를 더했습니다(사본 전용). 아침에 공용 그래프 몫을 이 안의 근거에 더합니다. 안 A를 먼저 하면 그래프 상한의 표시 비용도 줄어듭니다.

### 11-17 밤 00:30 사본 측정 (예약)

1. 사본 복원(복원 한도 5400초, 유지 작업자 1).
2. 종류 그래프 셋 유효 확인, 처음 보는 질의 30개(탐색 15·추천 15)로 ann·projection·디스크 블록 측정.
3. 사본에서 `DROP INDEX CONCURRENTLY agentcon_search.embeddings_cosine_hnsw` → 사본 재시작 → 같은 30개 다시 측정.
4. 복구 시간 실측: 사본에서 위 정의로 `CREATE INDEX CONCURRENTLY` 다시 만들기(걸린 시간, 그동안 검색·쓰기 지연 기록).
5. 네 역할(frontend·jobs·admin·execution) 운영 버전으로 사본 연결 검사(트리거 5개·쓰기·탐색).
결과와 복구 시간은 이 파일에 적고 11-18 아침 PM에 넘깁니다.
