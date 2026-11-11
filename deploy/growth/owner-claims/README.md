# 제공자 소유 증명 표 (성장·유통, 11-11, PM 결정 ②)

운영 PostgreSQL에 소유 증명과 제외 요청을 남길 표 하나를 만드는 변경이다. 사용자 승인 묶음에 넣는다.

## 변경
- `change.sql`: 전용 스키마 `agentcon_owner`와 표 `resource_owner_claims`, 부분 인덱스 하나를 만든다.
  - 열: host(PK), method(well_known·dns_txt), verified_at, last_checked_at, hidden, hidden_at
  - 트리거·함수는 없다. public에는 아무것도 만들지 않는다. 앱이 연결마다 public 트리거가 5개인지 검사하기 때문이다.
  - 개인정보는 없다. 이메일·비밀번호를 받지 않는다.
- `rollback.sql`: 표와 스키마를 지운다. 데이터가 쌓인 뒤라면 소유 증명 기록이 지워지므로 그때는 따로 묻는다.

## 리허설 (사본, 운영 DB에는 연결하지 않음)
| 대상 | 결과 | 시간 | 보고서 |
|---|---|---|---|
| change.sql | passed | 15.8초 | logs/ops/db-rehearsal/rehearsal-20261111-133050.json |
| change.sql + rollback.sql | passed | - | logs/ops/db-rehearsal/rehearsal-20261111-133117.json |

- 확인한 버전: frontend·jobs bundle2-*-20261111-r1(그때 운영 중). 두 버전 모두 변경 뒤 연결·쓰기 트랜잭션·탐색 검색이 정상이었다.
- 운영 버전이 바뀌면 실행 직전에 `run`을 다시 하고 `check`가 0인지 본다(24시간·같은 버전 조건).

## 예상 영향
- 새 스키마와 빈 표 만들기라 잠금은 짧다(기존 표를 잠그지 않음). 재시작은 필요 없다.
- 앱 코드는 아직 이 표를 쓰지 않는다. 표를 쓰는 코드(저장·숨김)는 승인 뒤 켠다.

## 실행 순서 (승인 뒤)
```bash
.venv/bin/python -m scripts.db_change_rehearsal check --sql deploy/growth/owner-claims/change.sql   # 0이 아니면 멈춤
psql "$(cat <DSN 파일>)" -v ON_ERROR_STOP=1 -f deploy/growth/owner-claims/change.sql
```
그 뒤 홈, `/llms.txt`, `/api/explore?q=weather`, `/mcp`가 200인지, 로그에 `schema_invariants_mismatch`가 없는지 본다. 문제가 있으면 `rollback.sql`을 실행한다.
