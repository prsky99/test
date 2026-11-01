# Chat 503(쓰기 잠금 대기 초과) 조사 (2026-11-01 밤)

## 현상
- 18:51:41 `POST /chat`가 503(`SERVICE_BUSY`)을 냈다. frontend 재시작 직후 약 50초 뒤였다.
- 같은 순간 PostgreSQL에서 `canceling statement due to lock timeout`이 2건 났다.
  - backend 70885: execution 작업자
  - backend 95494: frontend의 Chat 요청
- 그 뒤 같은 질의는 연달아 200이었다.
- 오늘 Chat 5xx는 이 1건과 14:31~14:32 배포 사고 3건(500)뿐이다.

## 구조
- **전역 쓰기 잠금 하나**
  - PostgreSQL 저장소의 모든 쓰기 트랜잭션은 시작할 때 `pg_advisory_xact_lock(WRITER_LOCK)`을 잡는다(`application_store_postgres._begin_direct`).
  - frontend 두 슬롯, admin, jobs, execution의 쓰기가 모두 한 줄로 선다.
  - 대기 한도는 `SET LOCAL lock_timeout TO '1000ms'`다. 누군가 1초 넘게 쥐면 그동안 들어온 쓰기는 `statement_failed`로 실패한다.
- **Chat 한 번에 쓰기 트랜잭션 5개 이상**
  - `VisitorBook`의 touch/create, add_message(요청), save_results, remember_interest, add_message(답변)이 각자 따로 잡는다.
  - 그중 하나만 1초를 넘겨도 `chat` 처리기가 503을 돌려준다. 추천은 이미 계산해 둔 상태여도 그렇다.
- **잠금 대기 초과 집계 (오늘 PG 로그 32건)**
  - 25건은 execution 연결(70885)이다. 실패한 라운드는 다음 차례로 미루므로 사용자에게는 보이지 않는다.
  - 시간대별: 14시 5, 16시 7, 17시 11, 18시 5, 19시 3.

## 누가 오래 쥐는가 (20:01~20:03 표본, 0.25초 간격, 읽기 전용 연결 1개)
| 연결 | 가장 오래 본 트랜잭션 | 내용 |
|---|---|---|
| 42882 (jobs, 16:36 시작) | 0.91초 | `DELETE FROM legacy_vector_jobs ... LIMIT 500` |
| 70885 (execution) | 0.11초 | `workflow_result_outbox` 조회 |
| 그 밖 | 0.04초 이하 | |

- 벡터 대기열 정리(`legacy_vector_index.py` 534행)가 원인이다.
  - 일주일 지난 작업을 한 번에 500건씩 지우는데, 대기열 claim 트랜잭션 안에서, 즉 전역 쓰기 잠금을 쥔 채로 지운다.
  - 지울 것이 가득 남아 있으면 쉬지 않고 반복한다.
  - 0.9초는 1초 한도에 거의 붙어 있다. 조금만 길어져도 그 순간의 Chat 쓰기가 실패한다.
- 이 표본은 2분 24초뿐이다. 백엔드 세션의 PG 재시작(max_connections 24→48) 안내가 와서 중단했다.

## 개선 방향 (아직 적용 전)
1. **jobs: 정리 묶음 줄이기**
   - `LIMIT 500`을 100 정도로 줄여 한 번에 0.2초 안팎이 되게 한다.
   - 대상은 `legacy_vector_index.py`이고 정책 해시 파일이 아니다. 배포는 jobs만 하면 된다.
2. **Chat: 잠금을 잡지 못했을 때만 다시 시도하기**
   - 잠금을 기다리다 실패한 쓰기는 아직 아무것도 쓰지 않은 상태라, 다시 시도해도 안전하다.
   - 지금은 이 실패가 일반 `statement_failed`로만 올라와 다른 실패와 구별할 수 없다.
   - 그래서 저장소가 잠금 대기 초과를 따로 알려 주게 하고, 방문자 기록 쓰기는 짧게 1~2번 다시 시도하게 한다.
   - 저장소는 모든 서비스가 같이 쓰는 핵심 코드라서, 범위를 좁게 잡아야 한다.
3. **Chat: 쓰기 묶기**
   - 답변 뒤에 하는 쓰기 3개(결과 저장, 관심사 저장, 답변 기록)를 한 트랜잭션으로 묶어 잠금을 기다리는 횟수를 줄인다.

## 적용 (21시)
- **jobs `vector-retention-jobs-20261101-r1`(21:09 배포)**
  - 만료 작업 검색을 읽기 스냅샷으로 옮겼다(`PostgresVectorIndex._expired_jobs`).
  - 쓰기 트랜잭션에서는 찾은 id만 다시 확인해 지운다(`_delete_expired`). 지울 것이 없으면 쓰기 트랜잭션 안의 검색을 아예 하지 않는다.
- **배포 뒤 5분 측정(21:11~21:16)**
  - 옛 in-lock 정리가 21:15에 한 번 1.07초 동안 돌았다.
  - 원인: 정리할 때가 됐는지를 트랜잭션 앞(`start`)과 안(`now`)에서 두 번 판정했다. 그 사이에 일시정지가 끝나면 옛 경로로 갔다.
  - 고친 것: 판정을 한 번만 하게 했다(`due`). 이를 담은 `vector-retention-jobs-20261101-r2`는 패키징·검증까지 했고, 배포 승인을 기다린다.
- **같은 측정에서 본 다른 긴 보유:** jobs의 통계 `SELECT COUNT(*) ... eval_score` 1.07초, ERC-8004 토큰 UPDATE 0.57~0.82초. 정리만 고쳐서는 1초 근처 보유가 남으므로 Chat 재시도가 필요하다.
- **frontend `writer-retry-frontend-20261101-r2`**
  - 구성: 활성 `edit-revision-frontend-20261101-r1` 위에 `memory.py`와 `application_store_postgres.py`의 WriterBusy 부분만 문자열로 얹었다. 작업본의 다른 세션 hunk(`statement_timeout 120s`)는 빼고 넣었다.
  - 비교 시험이 진행 중이다.

## 배포 (22:58~22:59)
- jobs `vector-retention-jobs-20261101-r2`를 22:58에 배포했다.
- frontend `writer-retry-frontend-20261101-r3`를 22:59에 배포했다(활성 a, b=centre-progress-r3).
  - 구성: 그 시점 활성 `centre-progress-frontend-20261101-r3` 위에 2개 파일만 얹었다.
  - 배포 직후 Chat·진행 스트림·탐색은 모두 200이었다.
- **배포 뒤 5분 측정(23:00~23:05, 0.25초 간격)**
  - 옛 in-lock 정리는 0회였고, 새 id 삭제만 쓰였다.
  - 0.5초 이상 보유한 표본은 2개다(배포 전 12개). 1.07초 정리, 1.07초 통계, 0.82초 ERC-8004 갱신은 보이지 않았다.
  - 가장 긴 보유는 0.81초였다. `DELETE FROM agentcon_search.capability_text ... NOT EXISTS`(capability_text Refresher의 정리)이고, 다음 후보다.
  - 배포 뒤 잠금 대기 초과 0건, frontend 5xx 0건이다.

## 스냅샷 이중 실행 (11-02 0시)
- **현상:** frontend 두 슬롯이 모두 'Recorded reports' 스냅샷(170~205초)을 10분마다 만들었다. DB 부하가 두 배였다. 대기 슬롯이 스냅샷을 만드는 중이면 배포가 timeout으로 멈췄다(11-01 19:49). 프론트엔드 세션이 알려 왔다.
- **변경:** `report_snapshot.keep_fresh(serving=...)`
  - 시작할 때는 늘 한 번 만든다. 곧 활성이 될 새 슬롯이 스냅샷을 가진 채 트래픽을 받게 하려는 것이다.
  - 그 뒤에는 30초마다 확인한다. 이 프로세스의 릴리스가 `state.json`의 활성 슬롯 릴리스일 때만, 스냅샷이 10분을 넘었으면 다시 만든다.
  - 상태 파일을 읽지 못하면 예전처럼 갱신한다.
  - `service_host.serving_slot(role, release)`가 판단하고, 상태 디렉터리는 `AGENTCON_SERVICE_STATE_DIR`로 받는다.
- **릴리스:** `standby-snapshot-frontend-20261102-r1`
  - 구성: 활성 `writer-retry-frontend-20261101-r3` 위에 2개 파일을 얹었다. `service_host.py`는 작업본이 활성보다 오래된 부분이 있어 문자열 패치로 얹었다.
  - 시험: 관련 10개 파일(108건)을 돌렸고, 기준 사본에서만 실패한 2건은 이번에 새로 넣은 시험이다.
- **배포 (11-02 07:03:47):**
  - 프론트엔드 세션이 07:01에 `batch-reads-frontend-20261101-r5`를 배포했다.
  - 그래서 그 위에 2개 파일만 다시 얹은 `standby-snapshot-frontend-20261102-r2`를 배포했다(활성 a, 대기 b=r5).
  - r5 사본과 비교한 시험 108건이 통과했다.
  - 배포 뒤 Chat·스트림·탐색은 200, 5xx 0건, 잠금 대기 초과 0건이다.
  - 배포는 대기 슬롯 a의 스냅샷이 끝난 06:59:44 직후에 해서 timeout이 없었다.
- **같은 시각 다른 세션이 발견한 장애:** r5의 `customer_batch.py`가 하위 요청에 Accept-Encoding을 그대로 넘긴다. 그래서 gzip 바이트가 JSON 안에 들어가 고객 워크스페이스 첫 화면이 "Workspace access could not be loaded"로 깨진다. 이 릴리스에도 들어 있다. 프론트엔드 세션이 이 위에 수정만 얹은 r6을 준비한다.
