# SQLite maintenance

The gateway and public frontend share the configured `GATEWAY_DB`. Do not run
another collector or gateway against an unintended database while investigating
an incident. Confirm the database opened by the listening process; a recovered
file with a different filename does not change an existing connection.

## Safe startup

The gateway reserves both configured listening ports before opening storage or
starting collectors. A port collision exits with an explicit error and releases
all reservations. It does not silently start the frontend on a different port.
Stop the existing gateway gracefully before restarting with the same settings.

On macOS, the command-line entry point checks Python's linked SQLite version.
If it predates the WAL-reset fix and a patched Homebrew SQLite is installed,
the entry point probes it in a child process and re-executes Python with that
library selected. Existing application settings are preserved. This does not
replace Python packages or install software. Other platforms should use a
distribution build containing the upstream WAL-reset fix.

The fix is available in SQLite 3.51.3 and later, and the 3.44.6 and 3.50.7
backports. See [SQLite WAL-reset documentation](https://www.sqlite.org/wal.html#walreset).

## Permission and lock safety

SQLite owns the descriptors for an existing database, WAL, and shared-memory
file. Never open and close these files merely to change permissions: on POSIX,
closing an unrelated database descriptor can release the process's SQLite locks.
The permission helper uses a no-follow metadata operation and retains mode 600.
Only initial creation uses an exclusive raw descriptor, before SQLite connects.
See [SQLite's POSIX lock explanation](https://www.sqlite.org/howtocorrupt.html#posix_advisory_locks_canceled_by_a_separate_thread_doing_close_).

## Preservation and validation

- Use SQLite's online backup API for a live database. Restrict the destination
  directory to mode 700 and backup files to mode 600.
- A raw filesystem snapshot requires all writers to be stopped; preserve the
  database and its matching WAL together. Never delete or mix WAL files to make
  an error disappear, and never replace a database held open by a process.
- Run `PRAGMA quick_check` on a consistent snapshot, then `integrity_check`
  when checking index consistency. Large databases may take several minutes.
- Verify the affected record, schemas, row counts, and application reads before
  considering a recovered copy usable. A successful backup operation alone does
  not prove that the source was healthy.
- Keep damaged originals. Recovery can lose records or constraints; restore to
  a separate file and validate it before a controlled, offline replacement.

References: [safe backup methods](https://www.sqlite.org/howtocorrupt.html#backup_or_restore_while_a_transaction_is_active)
and [SQLite recovery guidance](https://www.sqlite.org/recovery.html).

## Workflow execution snapshots (R-05)

Use the explicit `agent_market.workflow_backup` CLI for an online snapshot and
restoration to a **new** path. It verifies integrity/checksums and preserves a
local encryption key in private storage (environment-managed keys stay outside
the export). Restoration quarantines unfinished/pending outcomes, pauses runtime
controls/schedules, invalidates old deployment/delivery/destination/event/session
and active task-update authorization, and never automatically replays old work.
Do not replace a live database or run the source and restored clone as active
executors. See [the implementation contract](../docs/DURABLE_WORKFLOWS.md).


## v1.10 bounded retention and restored inventory

Use the explicit workflow maintenance CLI in [operations hardening](../docs/WORKFLOW_OPERATIONS_HARDENING.md) after current schema initialization. Preview is read-only and does not recover or poll the execution queue; apply compacts at most twenty old known-terminal runs and preserves replay/unknown evidence. Do not expect immediate SQLite file shrinking or automatic VACUUM. A new-path restore writes `<database>.restored-inventory.json` at 0600 with limited prior IDs/states and reapproval steps; it never reenables old keys or pending deliveries. Latest execution/routing/operations PostgreSQL rehearsal is 27 tables, including budget/reconciliation/manual delivery/retention state. Complete Store/FTS/auth/collector adaptation and production cutover remain unimplemented.

## 운영 DB 구조 변경 (PostgreSQL, 2026-11-10)
11-10 05:38에 AD Coin v2 마이그레이션이 public 스키마에 트리거 12개를 만들었다. 앱은 DB에 붙을 때마다 public 트리거 목록이 정해진 5개와 같은지 검사(`_validate_native_invariants`)한다. 그래서 모든 요청이 거부됐고, 공개 사이트가 2분 동안 500이었다. 마이그레이션 시험은 빈 DB에서만 돌았다. 앞으로 운영 DB 구조를 바꾸는 일(표·열·인덱스·트리거·함수·스키마 추가·변경·삭제, 마이그레이션 도구 실행)은 아래 순서를 따른다.

1. **복구 SQL을 먼저 파일로 만든다.** 변경을 되돌리는 SQL(예: `DROP TRIGGER …`, `DROP TABLE …`)을 실행 전에 준비해 둔다. 데이터를 지우는 복구는 따로 승인을 받는다.
2. **사본에서 리허설한다(운영 DB에는 연결하지 않음).**
   ```bash
   .venv/bin/python -m scripts.db_change_rehearsal run --sql change.sql
   .venv/bin/python -m scripts.db_change_rehearsal run --command "python -m scripts.ad_coin_v2_migrate migrate --dsn-file {dsn_file} --key-file {key_file} --i-have-approval"
   ```
   - 최신 일일 백업(`gateway-data/backups/daily/snapshot-*/database.dump`)을 일회용 사설 PostgreSQL에 복원한다.
     - 스키마는 전부 복원한다. 데이터는 큰 표 16개만 빼고 복원한다(약 170MB, 15초 안팎). `--data full`이면 전부 복원한다(수십 분).
     - 사본에서는 원래 DB 신원에 묶인 제어 스키마(`agent_migration_control`, `agent_restore_control`)만 지운다.
   - 운영 중인 frontend·jobs 버전(`state.json`)의 코드와 환경으로, 변경 전과 변경 후에 각각 다음을 확인한다.
     - 앱 연결: 스키마 프로필과 트리거 불변 검사
     - 쓰기 트랜잭션(쓰기 잠금·배포 게이트)
     - 탐색 검색 한 번
   - `--command`에는 `{dsn_file}`·`{key_file}`·`{socket}`·`{port}`가 사본 값으로 바뀌어 들어간다. 운영 DB 표시(포트 55432, `gateway-data/postgres18`, `application.dsn`, 운영 DB 이름)가 들어 있으면 실행하지 않는다.
   - 결과는 `logs/ops/db-rehearsal/rehearsal-*.json`에 남는다. 판정(`verdict`)은 다음 중 하나다.
     - `passed`
     - `change_failed`: 변경 자체가 실패
     - `application_refuses_changed_database`: 변경 뒤 앱이 붙지 못함. 05:38 같은 경우다
     - `copy_unusable_before_change`: 사본이나 도구 문제
     - `restore_failed`
   - 통과하면 변경의 지문(SQL 파일 내용, 또는 명령 문자열의 sha256)이 `logs/ops/db-rehearsal/passed.json`에 기록된다.
3. **승인을 받는다.** 리허설 보고서, 복구 SQL, 예상 영향(잠금 시간, 재시작 여부)을 붙여 사용자 승인을 받는다(총괄 PM 경유).
4. **운영 실행 직전에 확인한다.**
   ```bash
   .venv/bin/python -m scripts.db_change_rehearsal check --sql change.sql   # 0이 아니면 실행하지 않는다
   ```
   - 같은 변경이 24시간 안에, 지금 운영 중인 frontend·jobs 버전으로 통과했을 때만 0을 돌려준다. 버전이 바뀌었으면 다시 리허설한다.
5. **운영에 실행한다.** 사람이 정한 한 번의 실행으로 한다. 다른 세션의 배포·시험과 겹치지 않게 한다.
6. **바로 확인한다.**
   - 홈(`/`), `/llms.txt`, `/api/explore?q=…`, `/mcp`가 200인지 본다.
   - frontend·jobs 로그에서 `schema_invariants_mismatch`, `schema_profile_mismatch`, ERROR가 새로 생기지 않았는지 본다.
   - 문제가 보이면 1의 복구 SQL을 바로 실행한다. 복구 SQL은 복구 목적이라 리허설 없이 실행할 수 있게 미리 승인받아 둔다.

- 시험: `tests/test_db_change_rehearsal.py`
- 11-10 실측(백업 snapshot-20261110-043005, frontend adcoin-credit-terms r2, jobs growth-md-jobs r5)
  - 표 주석 변경: `passed`, 14.7초
  - 05:38과 같은 종류의 변경(public 표 + 트리거): `application_refuses_changed_database`(두 버전 모두 `schema_invariants_mismatch`), 11.3초
  - 이 변경은 `check`도 거부했다.
