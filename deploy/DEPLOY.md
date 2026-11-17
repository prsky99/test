# 배포와 운영

이 문서는 두 부분입니다. **현재 운영(맥)**이 지금 쓰는 방식입니다. 맨 아래 **옛 방식(보관)**은 2026-09 무료 서버안으로, 지금은 쓰지 않습니다(정밀 검토 R59, 11-15 운영·SRE).

## 현재 운영(맥) 한눈에 (2026-11-15)

- **서비스**: 운영 맥 한 대에서 launchd로 돕니다. 웹 역할 frontend·admin은 a/b 두 칸을 번갈아 쓰고, jobs·execution은 한 칸(main)입니다. 앞에 caddy 프록시가 있고, 공개는 Cloudflare 터널(cloudflared)입니다. DB는 같은 맥의 PostgreSQL 18(소켓 `gateway-data/postgres18/run`, 포트 55432)입니다.
- **배포 단위**: 커밋 하나로 릴리스를 만들고(`./agentcon package <릴리스> --commit <커밋> --base <활성 릴리스>`), 배포 도구가 확인한 뒤 바꿉니다. 운영 중인 버전·배포 잠금·배포 대기는 `logs/ops/status-board.md`가 기준입니다.
- **실행기 틀**: `deploy/ops/deploy-runner.sh <역할> <릴리스> <커밋> <기준> [시작 시각] [마감]`. 기다리는 동안은 '## 배포 대기'에 [예약] 줄만 쓰고, 배포 순간에만 그 시각으로 잠금 줄을 씁니다(`deploy/ops/runner-lock.sh`).
- **배포 도구가 스스로 막는 것(R54, 11-15)**
  - 운영 버전과 기준 버전이 다르면 거부(`release_base_mismatch`), 다른 팀 잠금이 있거나 자기 잠금 줄이 60분보다 오래되면 거부
  - frontend·jobs의 정책 해시(`explore_documents.policy_hash()`)가 바뀌면 00:30~01:30 밖에서 거부
  - 운영 버전에 있던 등록 SQL이 새 릴리스에서 빠지면 거부(10-30 r14 시작 실패)
  - 네 역할 모두 `scripts.release_gate` 통과가 필요(같은 커밋 24시간 안 통과 기록은 재사용). 실측: frontend 약 277초(Chat 비교 포함), jobs 약 29초
  - `package --commit`은 `--base` 필수(`package_base_required`). 패키징한 릴리스는 배포되거나 48시간이 지날 때까지 자동 정리에서 보호(R60, `PACKAGED_PIN_HOURS`)
  - 계보 검사(11-16): 활성 버전에만 있는 변경이 새 커밋에 빠져 있으면 package 거부(`lineage_base_not_in_commit`, `git cherry`로 판단하므로 쌓인 되돌리기·cherry-pick은 통과). 일부러일 때만 `--allow-lineage "<이유>"`를 붙이고, 이유는 `release.json`과 `logs/ops/lineage-exceptions.jsonl`에 남음. 실패한 package는 만들다 만 릴리스 폴더를 지움
  - `rollback`·`restart`·`stop`도 `--lock-owner <팀>`과 현황판 잠금 줄 필요. 워커 되돌리기는 `./agentcon worker-rollback jobs|execution --lock-owner <팀>`
  - `--force-base`·`--skip-gate`·`--take-stale-lock` 사용은 `logs/ops/deploy-overrides.md`에 남음
- **PM이 실행하는 것(11-15 사용자 결정 "모두 맡김")**: 운영 DB 구조 변경과 DB 재시작(사본 리허설 통과·복구 SQL 준비·실행 직전 `check` 0 뒤), launchd 작업 설치·교체(bootstrap·bootout·설치 스크립트), 예약 작업 변경, Cloudflare 설정. 명령과 되돌리는 방법은 `deploy/ops/user-*.md`에 준비합니다(파일 이름은 예전 그대로 `user-`).
- **계속 사용자가 하는 것**: 지출과 실제 자산 송금, 본인만 할 수 있는 일(계정 생성·약관 동의·비밀번호 입력), 되돌릴 수 없는 운영 데이터 삭제, 게이트를 통과하지 못한 배포, 외부 게시 실행, 시스템 설정.
- **운영 작업 코드**: launchd 운영 작업은 차례로 작업본 대신 커밋으로 만든 `gateway-data/ops-code/current`를 실행하게 옮깁니다(R05, `scripts/ops_code.py`). `deploy/launchd/ops-pinned/`에 plist 10개가 있습니다: 11-15에 옮긴 광고 원장·백업·시험 보고서(`opsauto.housead`·`backup`·`opsauto.testreports`, `deploy/ops/user-launchd-ops-code-20261115.md`)와 11-17에 옮길 7개(`opensearch-sync`, `opsauto.netpath`·`ofac`·`paidreconcile`·`pearltests`·`watch`·`watchstale`). 7개 전환은 `deploy/ops/user-launchd-ops-code-20261117.md`(스크립트 `deploy/ops/launchd-ops-code-switch-20261117.sh`)로 PM이 11-17에 실행합니다. `scripts/ops_code.py`는 데이터 폴더와 함께 `tests/`·`reports/`도 링크합니다(11-16).
- **감시**: 10분 감시(`scripts/ops_watch.py` → `scripts/ops_auto.py`)가 사이트·메모리·스왑·디스크·launchd 작업·백업·핵심 프로세스·DB 연결 수를 봅니다. 같은 경보가 6번 넘게 닫히지 않으면 바탕화면 알림 파일과 `logs/ops/pm-escalations.md`로 격상합니다.

### launchd 작업 목록 (11-15 09:5x 이 맥 기준, driveragent 프로젝트 제외)

| launchd 작업 | 설치 | 주기 | 실행 코드 | 하는 일 |
|---|---|---|---|---|
| `biz.agentconcierge.498590e0b3.adcoin-worker` | 예 | 상시(KeepAlive) | 릴리스 폴더(배포 도구가 씀) | 서비스 adcoin-worker |
| `biz.agentconcierge.498590e0b3.admin.b` | 예 | 상시(KeepAlive) | 릴리스 폴더(배포 도구가 씀) | 서비스 admin.b |
| `biz.agentconcierge.498590e0b3.execution.main` | 예 | 상시(KeepAlive) | 릴리스 폴더(배포 도구가 씀) | 서비스 execution.main |
| `biz.agentconcierge.498590e0b3.frontend.b` | 예 | 상시(KeepAlive) | 릴리스 폴더(배포 도구가 씀) | 서비스 frontend.b |
| `biz.agentconcierge.498590e0b3.jobs.main` | 예 | 상시(KeepAlive) | 릴리스 폴더(배포 도구가 씀) | 서비스 jobs.main |
| `biz.agentconcierge.498590e0b3.proxy.main` | 예 | 상시(KeepAlive) | caddy 실행 파일(설정은 배포 도구가 씀) | 프록시(caddy) |
| `biz.agentconcierge.backup` | 예 | 매일 04:30 | 작업본 | 매일 DB·상태 백업(맥미니 복사) |
| `biz.agentconcierge.opensearch` | 예 | 상시(KeepAlive) | Homebrew 실행 파일(작업 폴더만 저장소) | OpenSearch |
| `biz.agentconcierge.opensearch-sync` | 예 | 상시(KeepAlive) | 작업본 | OpenSearch 동기화 |
| `biz.agentconcierge.opsauto.edgewarm` | 아니오(저장소에만) | 매일 06:50 | 작업본 | 엣지 데우기 |
| `biz.agentconcierge.opsauto.housead` | 예 | 매일 09:10 | 작업본 | 자사 광고 매일 예약(원장 쓰기) |
| `biz.agentconcierge.opsauto.netpath` | 예 | 60초마다 | 작업본 | 1분 경로 측정(net_path) |
| `biz.agentconcierge.opsauto.ofac` | 아니오(저장소에만) | 매일 06:20 | 작업본 | OFAC 제재 주소 갱신(R06) |
| `biz.agentconcierge.opsauto.paidreconcile` | 아니오(저장소에만) | 매일 09:20 | 작업본 | USDC 결제 매일 대조(`deploy/ops/payment-reconcile-daily.sh`: 어제와, 최근 7일 중 결과가 없거나 체인을 읽지 못한 날. `scripts.ad_coin_paid_reconcile --due`, 11-16) |
| `biz.agentconcierge.opsauto.pearltests` | 예 | 매일 09:12 | 작업본 | 진주 매일 시험 |
| `biz.agentconcierge.opsauto.testreports` | 예 | 매일 02:30 | 작업본 | 시험 보고서 배치 |
| `biz.agentconcierge.opsauto.watch` | 예 | 600초마다 | 작업본 | 10분 감시(ops_watch → ops_auto) |
| `biz.agentconcierge.opsauto.watchstale` | 아니오(저장소에만) | 300초마다 | 작업본 | 감시 정지 25분 알림(R53) |
| `biz.agentconcierge.postgres18` | 예 | 상시(KeepAlive) | Homebrew 실행 파일(작업 폴더만 저장소) | 운영 PostgreSQL 18 |

- '실행 코드'가 작업본인 운영 작업은 R05 순서대로 커밋 폴더로 옮깁니다(광고 원장·백업 먼저).
- 저장소에만 있고 설치되지 않은 것(11-15 기준): `opsauto.ofac`·`opsauto.watchstale`·`opsauto.paidreconcile`(11-17 전환 대상, 설치는 PM), `opsauto.edgewarm`(설치 여부를 담당 팀이 확인할 것).
- 현황판 사본(`logs/ops/status-board-history/`)은 10분 감시(`ops_auto.py watch`)가 함께 남긴다. 따로 쓰던 `opsauto.board` plist는 설치하지 않고 지운다(11-17).

## 현재 운영(맥) — 세부 규칙 (날짜순)

## 맥 운영 DB 매일 백업 (agentconcierge.biz)
- launchd 작업 `biz.agentconcierge.backup`(원본 `deploy/launchd/biz.agentconcierge.backup.plist`)이 매일 04:30에 `.venv/bin/python -m scripts.scheduled_backup`을 낮은 우선순위로 실행합니다.
- 결과는 `gateway-data/backups/daily/snapshot-YYYYmmdd-HHMMSS/`에 저장됩니다(0700). 내용은 `scripts/runtime_snapshot.py`와 같습니다: DB 덤프, 소스 압축, `runtime.env`, `workflow.key`, `postgres.dsn`, `manifest.json`.
- 완료된 스냅샷은 최근 7개만 남깁니다. 실패하고 남은 폴더는 다음 성공 뒤에 지웁니다.
- 앱 연결(`agentcon_app`)이 19개를 넘으면 5분 간격으로 6번까지 기다리고, 그래도 많으면 건너뜁니다. `pg_dump`는 연결을 하나만 씁니다.
- 로그: `logs/services/biz.agentconcierge.backup.log` (JSON 한 줄, 실패하면 종료 코드 1, 건너뛰면 2)
- 설치: plist는 템플릿입니다. `__REPO__`를 저장소 절대 경로로, `__BACKUP_COPY_TO__`를 복사할 공유 폴더로 바꿔 설치합니다.
  `sed -e "s#__REPO__#$PWD#g" -e "s#__BACKUP_COPY_TO__#/Volumes/<공유>/agentconcierge-backups#g" deploy/launchd/biz.agentconcierge.backup.plist > ~/Library/LaunchAgents/biz.agentconcierge.backup.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/biz.agentconcierge.backup.plist`
  `deploy/launchd/biz.agentconcierge.postgres18.plist`도 같은 방법으로 `__REPO__`를 바꿔 설치합니다.
- 바로 한 번 실행: `launchctl kickstart gui/$(id -u)/biz.agentconcierge.backup`
- 2026-11-01 실측: DB 10.3GB → 덤프 2.7GB, 소스 0.46GB, 343초, 테이블 데이터 270개, 서비스 영향 없음.
- 다른 기기 복사(2026-11-01 사용자 결정): `--copy-to /Volumes/<공유>/agentconcierge-backups`(다른 Mac mini의 SMB 공유)에도 같은 스냅샷을 복사합니다. 키도 함께 복사됩니다.
  - 먼저 `.partial-` 이름으로 복사하고, 파일 크기를 확인한 뒤 이름을 바꿉니다. 그쪽에도 최근 7개만 남깁니다.
  - 공유가 마운트되어 있지 않으면(`/Volumes/<공유>`가 마운트 지점이 아니면) 복사를 건너뜁니다. 로컬 디스크에 엉뚱한 폴더를 만들지 않습니다.
  - 복사가 실패해도 로컬 스냅샷은 그대로 둡니다. 로그의 `offsite`에서 결과를 확인합니다.
  - 최신 것만 다시 복사: `.venv/bin/python -m scripts.scheduled_backup --copy-only --copy-to /Volumes/<공유>/agentconcierge-backups`
  - 실측: launchd 환경에서 3.2GB를 약 198초에 복사했고, sha256이 원본과 일치했습니다.
  - 재부팅 뒤에는 공유를 다시 마운트해야 복사됩니다. 로그인 항목에 공유 폴더를 넣어 두면 자동으로 마운트됩니다.
- 2026-11-02 자동 백업 실측: 04:30 시작, 덤프 약 17분, 전체 1,102초, Mac mini 복사 성공.
  - 수동 실행(343초)보다 느린 이유는 launchd의 `LowPriorityIO`·`Nice 10` 때문입니다. 새벽 서비스에 부담을 주지 않으려는 설정이라 그대로 둡니다.
- 복원 연습(2026-11-02, `snapshot-20261102-043005`)
  - 운영과 분리된 임시 클러스터에 복원했습니다. TCP를 열지 않고, 짧은 경로의 유닉스 소켓만 썼습니다.
  - 명령: `pg_restore --no-owner --no-privileges -j 2`, `nice -n 15 taskpolicy -b`로 낮은 우선순위 실행.
  - 11분 걸렸고, 오류는 0건입니다.
  - 확인한 것
    - 테이블 272개
    - `resources` 237,585건: manifest의 `catalog_resources_at_baseline`과 같습니다.
    - `explore_documents` 237,585건
    - 확장 기능: vector, unaccent, pg_stat_statements
    - 최신 `first_seen`: 04:29(백업 직전)
    - 복원된 DB 크기: 7.5GB
  - macOS에서 주의할 것
    - 소켓 경로는 103바이트를 넘으면 안 됩니다. 예: `/tmp/claude-501/pgd`
    - Postgres를 시작할 때 `LC_ALL=en_US.UTF-8`을 지정해야 합니다. 없으면 "postmaster became multithreaded" 오류로 시작하지 않습니다.
  - 임시 클러스터는 확인 뒤 지웠습니다.

의존성 프로필과 선택형 Claude SDK/레거시 SQLite 벡터 설치는 [의존성 관리 안내](DEPENDENCY_MAINTENANCE.md)를 참고하세요.

## frontend 릴리스 배포 전 점검 (2026-11-02)
> 11-10 이후 대체됨: 릴리스는 이제 커밋에서 만들고 파일을 얹지 않는다(아래 "배포는 커밋 하나에서"). 사본 점검이 필요한 이유는 같다.

릴리스는 활성 릴리스에 파일을 얹어 만들기 때문에, 작업본에서 시험이 통과해도 릴리스가 맞다는 보장은 없다. 배포 전에 릴리스 사본에서 첫 화면 경로 시험을 돌린다(약 40초(11-02 당시. 11-15 실측은 frontend 약 277초·jobs 약 29초), `nice -n 10`).

```bash
.venv-tests/bin/python -m scripts.release_gate <release>
```

- 마지막 줄이 `passed`일 때만 배포한다.
- 11-02부터 `./agentcon deploy frontend <release>`가 이 점검을 먼저 자동으로 돌린다. 배포 잠금을 잡기 전에 돌고, 실패하면 배포하지 않는다(`release_gate_failed`).
  - 긴급할 때만 `--skip-gate`를 붙인다. 롤백(`./agentcon rollback frontend --lock-owner <팀>`)은 점검하지 않는다.
  - 11-15(R54)부터 admin·jobs·execution 배포도 점검한다. 같은 커밋이 24시간 안에 전체 점검을 통과한 기록(`logs/ops/release-gates/`)이 있으면 다시 돌지 않는다.
- 시험 목록은 `scripts/release_gate.py`의 `TESTS`에 있다.
  - 묶음 읽기, 실행 엔진 선택, 읽기 전용 경로, 공개·워크스페이스 첫 화면 브라우저 시험이 들어 있다.
- 11-02 07:01 장애 버전 `batch-reads-frontend-20261101-r5`는 이 점검에서 실패로 걸린다(gzip 시험).
- 배포 뒤 점검(`verify_web`)은 로그인하지 않으므로 고객 화면의 데이터 읽기를 확인하지 못한다. 그래서 배포 전 점검이 필요하다.
- 시험은 작업본의 `tests/`에서 가져온다. 아직 배포되지 않은 기능의 시험을 `TESTS` 목록의 파일에 넣지 않는다. 넣으면 그 기능이 없는 다른 세션의 릴리스가 점검에서 실패한다. 새 기능의 시험은 별도 파일에 둔다.

## 기준 판 검사 (2026-11-09)
> 11-10 이후 대체됨: 릴리스는 커밋에서 만든다. 기준 판 검사(`release_base_mismatch`)는 그대로 쓰인다.

릴리스는 활성 판에 파일을 얹어 만든다. 그사이 다른 세션이 활성 판을 바꾸면, 낡은 판 위에 만든 릴리스가 그 세션의 작업을 되돌린다(11-09 밤 여러 번 겹침). 그래서 배포 도구가 스스로 막는다.
- 패키징할 때 기준 판을 `release.json`의 `base`에 남긴다. 커밋 패키징(기본)은 `package --base <판>`이 없으면 거부한다(`package_base_required`). 아래 두 가지는 옛 방식(`--from-tree`)에만 해당한다.
  - 환경 변수 `AGENTCON_RELEASE_BASE`
  - 복사한 릴리스 사본에 남아 있는 `release.json`의 이름(`cp -cR`로 활성 판을 복사했다면 지우지 말 것)
- `./agentcon deploy …`와 `worker-deploy …`는 기준 판이 지금 활성 판과 다르면 `release_base_mismatch`로 거부한다. 게이트 전에 한 번, 배포 잠금 안에서 한 번 더 본다.
  - 활성 판 위에 다시 패키징하는 것이 원칙이다. 일부러 덮어쓸 때만 `--force-base`를 붙인다(예: frontend 판으로 admin을 다시 만들 때).
- `base`가 없는 예전 릴리스와 되돌리기(`rollback`)는 검사하지 않는다.
- 시험: `tests/test_service_deploy_base.py`

## 오래된 릴리스 정리 (2026-11-04)
릴리스는 배포마다 `gateway-data/services/releases/`에 쌓이고 저절로 지워지지 않는다. 11-04에는 461개, `du` 기준 142GB였다. 그때 디스크 여유는 150GB였다.
- `.venv`는 APFS 복제라서 실제로 차지하는 공간은 `du` 수치보다 작다. 크게 차지하는 것은 그대로 복사되는 `new/`다(릴리스마다 약 146MB).

```bash
./agentcon prune-releases                    # 미리보기: 지울 개수와 남길 목록만 출력
./agentcon prune-releases --apply            # 실제 삭제
```

- 남기는 것
  - `state.json`에 이름이 있는 릴리스: 활성·대기 칸, `previous`, `pending`, jobs·execution의 현재·이전 릴리스
  - 실행 중인 프로세스의 경로에 들어 있는 릴리스(배포 전 점검 사본 포함)
  - 최근 10개(`--keep`)
  - 3일이 안 된 릴리스(`--min-age-days`). 다른 세션이 시험하거나 배포하려는 중일 수 있다.
  - 배포를 기다리는 릴리스(11-12 추가). 현황판 `## 배포 대기` 칸에 릴리스 이름이 낱말로 적혀 있거나, `gateway-data/services/pinned-releases.txt`에 한 줄에 하나씩 적힌 이름이다(`#` 뒤는 주석). 커밋 번호만 적으면 보호되지 않는다. 기다리는 릴리스는 이름을 꼭 적고, 배포가 끝나면 지운다.
    - 계기: 11-12 배포 뒤 자동 정리가 만든 지 6시간이 넘은 대기 릴리스(오전 묶음 r2, am08-jobs-r1)를 지웠다.
- 배포 잠금을 잡고 대상 목록을 정한 뒤 `.pruning-<이름>`으로 이름만 바꾼다. 실제 삭제는 잠금을 푼 뒤에 한다. 그래서 정리하는 동안에도 다른 세션은 패키지·배포를 할 수 있다.
  - 배포가 잠금을 잡고 있으면 `BlockingIOError`로 바로 멈추고 아무것도 지우지 않는다.
  - 중간에 끊긴 정리는 다음 `--apply` 때 `.pruning-*`를 마저 지운다.
- 11-04 실행 결과: 462개 중 383개 삭제, 79개 남음. 여유 공간 149.5GB → 191.7GB(약 42GB 늘어남). 서비스는 그대로 돌았고 공개 사이트는 200으로 응답했다.
- 배포 뒤 자동 정리(2026-11-04 사용자 결정)
  - `./agentcon deploy …`와 `./agentcon worker-deploy …`가 성공하면 바로 정리한다. 성공은 새 칸의 준비 확인과 시험 요청 5번 통과를 말한다(워커는 시작 확인). 남기는 것은 배포된 릴리스뿐이다.
    - `state.json`에 있는 것: 활성 칸, 되돌리기용 이전 칸, 워커의 현재·이전 릴리스
    - 실행 중인 프로세스가 쓰는 것
    - 6시간 안에 만들어졌지만 아직 배포되지 않은 것(`AFTER_DEPLOY_MIN_AGE_HOURS`). 다른 세션이 곧 배포할 수 있다.
  - 배포가 실패하면 아무것도 지우지 않는다. 정리에 문제가 생겨도 이미 성공한 배포는 실패로 바꾸지 않는다. 결과는 출력의 `pruned`에 나온다.
  - 지우지 않으려면 `--no-prune`을 붙인다.
  - 11-15(R60)부터 `./agentcon package`로 만든 릴리스는 `pinned-releases.txt`에 스스로 이름을 적어, 배포되거나 48시간(`PACKAGED_PIN_HOURS`)이 지날 때까지 지워지지 않는다. 48시간이 지나도 배포하지 않았으면 다시 패키지한다.

## 릴리스끼리 Python 환경 공유 (2026-11-10)
11-10 하루에 릴리스를 28개 만들면서, 릴리스마다 `.venv`를 복제했다. 그래서 macOS 실행 파일 검사(syspolicyd)가 새 사본마다 돌아 CPU를 84%까지 썼다(16GB 맥이 스왑 80%이던 때).
- `package`가 의존성이 같은 릴리스끼리 환경 하나를 함께 쓰게 한다.
  - 의존성 키 = 패키징하는 `.venv`의 `pyvenv.cfg`(인터프리터) + 설치된 배포판 목록(`site-packages/*.dist-info`) + 릴리스의 `requirements-runtime.lock` + `deploy/runtime-versions.json`
  - 키마다 `gateway-data/services/venvs/<키>`에 한 번만 복제한다(`.complete` 표시). 릴리스의 `.venv`는 그 폴더를 가리키는 심볼릭 링크다.
- 키 폴더는 만든 뒤 바꾸지 않는다. 의존성이 바뀌면 새 키, 새 폴더가 생긴다. 그래서 이전 버전과 되돌릴 버전은 자기 환경을 그대로 쓴다.
  - 공유 환경 안에서 `pip install`을 하지 않는다. 의존성을 바꾸려면 작업본 `.venv`를 바꾸고 다시 패키징한다.
- (옛 `--from-tree` 방식) 활성 릴리스를 `cp -cR`로 복사해 만드는 오버레이도 링크가 그대로 복사되므로 같은 환경을 쓴다. 지금은 오버레이로 릴리스를 만들지 않는다.
- 키를 읽지 못하면(배포판 목록이 없는 등) 예전처럼 `.venv`를 복제한다.
- 정리: 릴리스 정리(`prune-releases`, 배포 뒤 자동 정리)가 끝나면, 어떤 릴리스도 가리키지 않는 키 폴더를 함께 지운다. 결과는 `unused_environments`에 나온다.
- 시험: `tests/test_service_deploy_shared_env.py`. 실제 확인: `venv-share-frontend-20261110-r1`(게이트 passed), 성장 팀 `growth-md-frontend-20261110-r7`(같은 키, 패키지 목록이 운영 버전과 같음).

## 이전 칸 회수와 되돌리기 시간 (2026-11-10)
frontend·admin 배포는 이전 칸(직전 버전 프로세스)을 남겨 즉시 되돌릴 수 있게 한다. 이 칸이 약 1.5GB를 쓴다.
- 배포가 끝나고 30분(`RECLAIM_STANDBY_SECONDS`)이 지나면 이전 칸 프로세스를 멈춘다.
  - 배포가 `reclaim-standby --after 1800`을 분리된 프로세스로 한 번 띄운다. 로그는 `logs/services/reclaim-standby.log`다.
  - 수동 실행: `./agentcon reclaim-standby`(30분 지난 것만), `--min-age 0`은 바로 멈춘다.
  - `state.json`의 이전 칸·버전 기록은 그대로 둔다. 배포 중(phase가 stable·retained가 아님)이면 아무것도 하지 않는다.
  - `retained_at`이 없는 예전 배포의 이전 칸은 건드리지 않는다.
- **되돌리기 시간**: 30분 안에는 즉시(프록시 전환만)다. 30분이 지나면 `./agentcon rollback <역할>`이 이전 칸을 다시 띄우고 준비를 확인한 뒤 전환하므로 **수십 초가 걸린다**(frontend 시작·준비 약 20~40초).
- 시험: `tests/test_service_deploy_shared_env.py`(회수 시점, 상태 유지, 배포 중 건너뜀)

## restart는 코드를 바꾸지 않는다 (2026-11-10)
- 예전에는 `./agentcon restart`가 **작업본을 새 버전으로 패키징해 배포**했다. 다른 세션의 미커밋 변경도 함께 들어갔다. 11-10에는 의존성 검사에 막혀 다행히 배포되지 않았다.
- 지금은 각 역할(frontend·admin)의 **운영 중인 버전을 반대 칸에 그대로 다시 띄우고 전환**한다. 패키징하지 않는다.
  - 같은 버전을 다시 띄우는 것이라 기준 버전 검사는 건너뛴다(`force_base`).
  - 이전 칸은 30분 뒤 회수된다.
- 코드를 바꾸려면 restart가 아니라 운영 중인 버전의 커밋 위에 커밋을 얹어 패키징하고(`package <버전> --commit <커밋> --base <활성 릴리스>`), 게이트를 통과시킨 뒤 `deploy`한다.
- 시험: `tests/test_service_deploy_shared_env.py::test_restart_redeploys_the_active_release_and_never_packages_the_working_tree`

## 새 frontend 칸 미리 데우기 (2026-11-10)
- 배포 직후 첫 공개 탐색이 10.7초 걸렸다. 새 프로세스는 캐시가 비어 있고, 메모리 압박으로 검색엔진 메모리가 스왑에 나가 있었다.
- (11-11 대체됨: 지금은 아래 "배포 직후 첫 요청 데우기"의 `warm_web`, 최대 90초·처음 보는 질의) 이 때 `deploy frontend`는 준비 확인 뒤, 트래픽을 넘기기 전에 탐색 검색 4개(`WARM_QUERIES`, 최대 45초)를 새 칸에 보냈다. 실패하거나 느려도 배포는 계속하고, 시간은 출력의 `warmed`에 남는다.
- 11-10 실측(대기 칸): 196 / 113 / 3,283 / 277ms. 처음 보는 검색어는 데우지 않으면 3초를 넘긴다.

## 배포는 커밋 하나에서 (2026-11-10, 사용자 결정 "운영 = git")
11-10 점검 결과, 운영 네 역할의 파일 다수가 어떤 커밋과도 같지 않았다. 원인은 "운영 중인 버전 복사 → 작업본 파일 덮어쓰기" 방식이다. 덮어쓴 작업본 파일에 다른 세션의 미커밋 변경이 섞여 함께 나갔다(`reports/운영 = git 1단계 정리 2026-11-10.md`).
- `./agentcon package <버전> --commit <커밋> --base <활성 릴리스>`
  - `--base`는 필수다(없으면 `package_base_required`로 거부). `--commit` 기본값은 HEAD다. 그 커밋을 `git archive`로 풀어 버전을 만든다. 작업본의 미커밋·추적 안 된 파일은 들어가지 않는다.
  - `release.json`에 `commit`(전체 해시)을 남긴다.
  - `--from-tree`는 예전 방식이다(커밋 기록 없음). 쓰지 않는다.
- Python 환경: 커밋으로 만드는 버전은 운영 중인 frontend 버전의 검증된 환경을 공유한다.
  - 작업본 `.venv`에는 11-08부터 pytest·sqlite-vec 같은 시험 도구가 설치돼 있어, 런타임 의존성 검사(`runtime_dependency_profile_mismatch`)에 걸린다.
- `./agentcon status`의 `commits`에 역할별 커밋이 나온다. 네 역할이 같은 커밋이면 "운영 = 커밋 X"다.
- 고칠 것은 먼저 브랜치에 커밋하고, 그 커밋으로 버전을 만든다. 겹치기(오버레이)로 운영 버전에 파일을 덮어쓰지 않는다.
- 전체 순서: `./agentcon package <버전> --commit <커밋> --base <활성 릴리스>` → `.venv-tests/bin/python -m scripts.release_gate <버전>` → `./agentcon deploy frontend|admin <버전> --lock-owner <팀> [--no-prune]` 또는 `./agentcon worker-deploy jobs|execution <버전> --lock-owner <팀> [--no-prune]`
- 커밋 검사(11-16): `scripts/commit_check.py`가 `.githooks/pre-commit`·`pre-push`(`core.hooksPath=.githooks`)로 돈다. 11-16은 경고만, 2026-11-17부터 막는다. 한 번 통과시키려면 `COMMIT_CHECK_SKIP="<이유>"`(이유는 `logs/ops/commit-check.jsonl`). 팀 세션은 `git commit-tree`로 커밋하므로 그 커밋은 pre-push에서만 검사된다.
- 11-10 실측: HEAD 3f5e469d로 만든 frontend·jobs 시험 버전이 게이트를 통과했다(frontend 57, jobs 140 passed, 파일 1,064개).

## 배포 직후 첫 요청 데우기 (2026-11-11)
- 11-11: frontend 배포 직후 공개 주소의 첫 `/api/explore`가 14.4초 걸렸다(이어진 요청은 0.6~2.1초).
  - 원인: 새 칸을 데울 때 고정 질의 4개(`weather forecast` 등)를 썼다. 탐색 결과는 Redis로 칸끼리 공유되므로, 이 질의들은 이전 칸이 넣어 둔 캐시에서 바로 답이 나왔다(캐시 적중 0.04초, 처음 보는 질의 1.3초). 그래서 새 프로세스는 실제 검색 경로를 한 번도 타지 않은 채 트래픽을 받았다.
- 지금: `deploy`는 트래픽을 넘기기 전에 새 칸에서 다음을 한다(`warm_web`, 최대 90초).
  - 처음 보는 탐색 질의(동사×대상 무작위 조합)를 보내, 두 번 연속 2초 안에 들어올 때까지 반복한다.
  - 그다음 MCP `find_agents`를 한 번 부른다. 읽기 전용이고 대화 기록을 남기지 않는다.
- 데우기가 실패하거나 느려도 배포는 막지 않는다. 결과는 배포 출력의 `warm`에 남는다: `first_explore_ms`, `explore_goal_met`, `recommend_ms`, `recommend_goal_met`.
- 확인은 공개 주소에서 배포 직후 처음 보는 질의 3개로 한다(현황판에 기록).
- 근본 원인(11-11 로그): 새 frontend 칸은 시작하면 탐색 보고서 스냅샷(20,928건)을 만든다. 방문자에게 양보하려고 쉬면서 만들기 때문에 520~560초가 걸린다. 그런데 칸 전환은 시작 후 약 1분 만에 일어났다. 그 사이 첫 요청은 스냅샷 작업과 저장소 잠금을 다퉜다(11-01에도 같은 이유로 14초).
- 고친 것:
  - 아직 트래픽을 받지 않는 칸은 첫 스냅샷을 쉬지 않고 만든다(`report_snapshot.keep_fresh`).
  - 준비 확인(`/internal/service/ready`)에 `report_snapshot` 상태(building, ready, skipped, failed)를 넣었다.
  - `deploy`는 그 상태가 ready가 될 때까지 기다린다(`wait_snapshot`, 최대 600초, 넘어도 배포는 막지 않음). 그다음 데우고 전환한다. 결과는 배포 출력의 `report_snapshot: {state, seconds}`에 남는다.
  - 데우기 요청마다 Server-Timing을 `warmed[].server_timing`에 남긴다.
- 그래서 frontend 배포는 스냅샷을 만드는 몇 분만큼 길어진다. 속도 정책(첫 요청 2초)을 위한 대가다.

## 배포 잠금은 도구가 확인한다 (2026-11-11)
- 11-11에 다른 팀이 잠금을 쥐고 있는 동안 배포를 시작했다가 게이트에서 멈춘 일, 잠금이 풀리길 기다리거나 짐작한 일이 여러 번 있었다.
- 이제 `./agentcon deploy …`와 `./agentcon worker-deploy …`에는 `--lock-owner <팀>`이 반드시 있어야 한다.
  - 팀 이름: 운영·SRE, 검색과 RAG, 성장·유통, AI AD Coin, 오류 감시, 프론트앤드, PM
- 도구는 `logs/ops/status-board.md`의 `## 배포 잠금` 칸을 읽는다.
  - 다른 팀 줄(팀 이름으로 시작하지 않는 줄 포함)이 있으면 `deploy_lock_held_by_another_team`으로 거부하고 그 줄을 보여 준다.
  - 칸이 비었거나 `(비어 있음)`이면 `deploy_lock_not_taken`으로 거부한다. 먼저 `- <팀> <시각> <역할> <버전>` 한 줄을 적는다.
  - 자기 팀 줄만 있으면 그대로 진행한다(base 확인 → 게이트 → 배포).
- 현황판 파일이 없는 곳(시험, 다른 머신)에서는 검사하지 않는다.
- 끝나면 자기 줄을 지우고 `(비어 있음)`으로 되돌린다. 현황판은 바뀌면 10분 감시가 돌 때 `logs/ops/status-board-history/`에 사본을 남긴다(`ops_auto.py` `board_snapshot`).
- 오래된 잠금(11-11 PM 결정): 잠금 줄에는 `pid=<세션 PID>`(Claude 세션의 Bash에서는 `$PPID`)와 `MM-DD HH:MM` 시각을 적는다. 예: `- 운영·SRE 11-11 11:50 pid=45463 frontend warm-frontend-20261111-r1`
  - 다른 팀 줄의 PID가 없거나 60분이 지났으면 `deploy_lock_stale`로 알린다. `--take-stale-lock`을 붙이면 그 줄을 내 줄(`넘겨받음(오래된 잠금): <원래 줄> [pid_gone|older_than_60m]`)로 바꾸고, `logs/ops/deploy-lock-takeovers.md`에 기록한 뒤 진행한다.
  - 살아 있는 잠금은 넘겨받을 수 없다. 오늘(11-11)은 세션이 끝난 뒤 잠금이 4시간 반 남은 일이 있었다.

## 사용자 실행 스크립트를 넘기기 전 점검 (2026-11-14, PM)

같은 유형의 사고가 두 번 있었다.
- 11-13: Worker 배포 스크립트의 `"$PREV인지"`
- 11-14: 가용성 정정 스크립트의 `"$n건"`

macOS의 bash 3.2는 사용자 터미널의 UTF-8 로케일(ko_KR.UTF-8)에서 `$이름` 바로 뒤에 오는 비ASCII 글자를 변수 이름으로 읽는다. 한글뿐 아니라 `·` 같은 문자도 그렇다. 그래서 `set -u` 아래에서 unbound variable로 멈춘다. Claude 셸은 C 로케일이라 같은 스크립트가 통과한다. 그래서 세션 안의 dry-run만으로는 이 오류를 잡지 못한다.

사용자에게 넘기는 셸 스크립트(`deploy/ops/run-*.sh` 등)는 넘기기 전에 아래를 모두 한다.
1. 변수 뒤에 글자가 이어지면 항상 중괄호를 쓴다: `"${n}건"`, `"${PREV}인지"`.
2. `bash -n <스크립트>`로 문법을 확인한다.
3. 사용자 로케일로 dry-run을 실제로 한 번 돌린다(바꾸는 것 없는 모드): `LC_ALL=ko_KR.UTF-8 LANG=ko_KR.UTF-8 zsh -c 'bash <스크립트>'`
   - 쓰기 단계는 임시 클러스터나 사본에서 리허설한다.
4. `tests/test_shell_scripts_braced_vars.py`가 통과해야 커밋한다. 이 시험은 저장소의 모든 셸 스크립트에서 `$이름` 바로 뒤에 비ASCII 글자가 붙은 곳과 `bash -n` 실패를 찾는다.
5. 넘기는 메시지에 명령 한 줄과 함께 3번 dry-run의 출력 끝 몇 줄을 붙인다.

## 옛 방식 (보관) — 2026-09 무료 서버안, 지금은 쓰지 않음

> **폐기 후보 (2026-11-16 표시, 11-17 재확인)**: 이 절부터 끝까지는 소스와 맞지 않는 옛 기록이다. 따라 하지 않는다. 폐기·보관 이동은 PM이 11-17 topic 판정과 r11 뒤 결정한다.

### 무료 서버 + 무료 도메인에 게이트웨이 올리기

**권장 구성:** Oracle Cloud Always Free VM + DuckDNS 무료 도메인 + Caddy 자동 HTTPS. 비용은 0원입니다.
(2026-09 조사 기준: Render·Koyeb 무료 플랜은 유휴 시 잠들고 디스크가 없어 이 서비스에 맞지 않습니다. Fly.io·AWS·Hugging Face Docker는 더 이상 영구 무료가 아닙니다.)

가입은 본인 인증과 카드 확인이 필요해 직접 하셔야 합니다. 가입만 끝나면 나머지는 명령 한 줄입니다.

### 1. 수익 지갑 만들기 (본인 PC)
```bash
git clone -b claude/hopeful-darwin-i3qj6n https://github.com/prsky99/test.git && cd test
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-build.lock
.venv/bin/python -m pip install --no-cache-dir --require-hashes --no-build-isolation -r requirements-runtime.lock
.venv/bin/python -m pip uninstall --yes setuptools wheel packaging
.venv/bin/python -m agent_market.wallet create ~/gateway-wallet.json   # 출력되는 0x... 주소를 적어 두기
```
keystore 파일과 비밀번호는 따로 백업하세요. 서버에는 **주소만** 넣습니다.

### 2. 무료 서버 (Oracle Cloud Always Free)
1. https://signup.cloud.oracle.com 가입 (카드 확인 필요, 과금 없음. 선불·가상 카드는 거절됨)
2. Compute → Instances → Create: 이미지 **Ubuntu 24.04**, Shape **VM.Standard.E2.1.Micro** (Always Free), SSH 키 등록
3. 인스턴스의 서브넷 → Security List → Ingress Rule 추가: TCP **80**, **443** (소스 0.0.0.0/0)
4. 공인 IP 확인

> 주의: Oracle은 7일간 CPU·네트워크 사용률이 매우 낮은 무료 인스턴스를 회수할 수 있습니다. 계정을 Pay-As-You-Go로 전환하면(Always Free 자원은 계속 무료) 회수 대상에서 빠집니다. 예산 알림을 $1로 설정해 두세요.
> Oracle 가입이 안 되면 Google Cloud e2-micro(us-central1 등 미국 3개 리전)에서 같은 절차로 하면 됩니다.

### 3. 무료 도메인 (DuckDNS)
1. https://www.duckdns.org 에서 GitHub/Google로 로그인
2. 서브도메인 생성 (예: `myagentgw` → `myagentgw.duckdns.org`), 화면의 **token** 복사

### 4. 서버에 올리기
```bash
ssh ubuntu@<공인 IP>
git clone -b claude/hopeful-darwin-i3qj6n https://github.com/prsky99/test.git && cd test/deploy
cp gateway.env.example gateway.env && nano gateway.env   # DOMAIN, ADMIN_TOKEN, DUCKDNS_* 입력 (GATEWAY_WALLET은 유료 정책일 때만)
sudo bash setup.sh
```
끝나면 `https://<서브도메인>.duckdns.org/.well-known/agent.json` 이 열립니다. 첫 전체 수집은 몇 분 걸리고, 이후 연속 수집과 매시간 헬스체크가 자동으로 돕니다 (`COLLECTOR.md` 참고).

### 운영
```bash
cd ~/test/deploy
sudo docker compose logs -f gateway                      # 로그
curl -s localhost:8200/health                            # 상태
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8200/admin/report   # 수익·수락률·수수료 (서버 안에서만)
git pull && sudo docker compose up -d --build            # 업데이트
sudo docker compose cp gateway:/data/gateway.sqlite3 ./backup.sqlite3          # 백업
```
- 관리자 API(`/admin/*`)는 외부에서 막혀 있고 서버 안(localhost)에서만 됩니다.
- 기본은 **무료 정책**(`GATEWAY_FREE=1`)입니다. 모든 소개와 재소개가 무료이고 결제는 일어나지 않습니다.
- 나중에 유료로 바꾸려면 `GATEWAY_FREE=0`, `NETWORK=base`로 바꾸고 `docker compose up -d`.
- 에이전트들이 찾아오게 하려면 게이트웨이 주소를 알려야 합니다 (예: 자체 agent card를 x402/MCP/A2A 디렉터리에 등록).
