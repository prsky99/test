# 무료 서버 + 무료 도메인에 게이트웨이 올리기

**권장 구성:** Oracle Cloud Always Free VM + DuckDNS 무료 도메인 + Caddy 자동 HTTPS. 비용은 0원입니다.
(2026-09 조사 기준: Render·Koyeb 무료 플랜은 유휴 시 잠들고 디스크가 없어 이 서비스에 맞지 않습니다. Fly.io·AWS·Hugging Face Docker는 더 이상 영구 무료가 아닙니다.)

가입은 본인 인증과 카드 확인이 필요해 직접 하셔야 합니다. 가입만 끝나면 나머지는 명령 한 줄입니다.

## 1. 수익 지갑 만들기 (본인 PC)
```bash
git clone -b claude/hopeful-darwin-i3qj6n https://github.com/prsky99/test.git && cd test
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-build.lock
.venv/bin/python -m pip install --no-cache-dir --require-hashes --no-build-isolation -r requirements-runtime.lock
.venv/bin/python -m pip uninstall --yes setuptools wheel packaging
.venv/bin/python -m agent_market.wallet create ~/gateway-wallet.json   # 출력되는 0x... 주소를 적어 두기
```
keystore 파일과 비밀번호는 따로 백업하세요. 서버에는 **주소만** 넣습니다.

## 2. 무료 서버 (Oracle Cloud Always Free)
1. https://signup.cloud.oracle.com 가입 (카드 확인 필요, 과금 없음. 선불·가상 카드는 거절됨)
2. Compute → Instances → Create: 이미지 **Ubuntu 24.04**, Shape **VM.Standard.E2.1.Micro** (Always Free), SSH 키 등록
3. 인스턴스의 서브넷 → Security List → Ingress Rule 추가: TCP **80**, **443** (소스 0.0.0.0/0)
4. 공인 IP 확인

> 주의: Oracle은 7일간 CPU·네트워크 사용률이 매우 낮은 무료 인스턴스를 회수할 수 있습니다. 계정을 Pay-As-You-Go로 전환하면(Always Free 자원은 계속 무료) 회수 대상에서 빠집니다. 예산 알림을 $1로 설정해 두세요.
> Oracle 가입이 안 되면 Google Cloud e2-micro(us-central1 등 미국 3개 리전)에서 같은 절차로 하면 됩니다.

## 3. 무료 도메인 (DuckDNS)
1. https://www.duckdns.org 에서 GitHub/Google로 로그인
2. 서브도메인 생성 (예: `myagentgw` → `myagentgw.duckdns.org`), 화면의 **token** 복사

## 4. 서버에 올리기
```bash
ssh ubuntu@<공인 IP>
git clone -b claude/hopeful-darwin-i3qj6n https://github.com/prsky99/test.git && cd test/deploy
cp gateway.env.example gateway.env && nano gateway.env   # DOMAIN, ADMIN_TOKEN, DUCKDNS_* 입력 (GATEWAY_WALLET은 유료 정책일 때만)
sudo bash setup.sh
```
끝나면 `https://<서브도메인>.duckdns.org/.well-known/agent.json` 이 열립니다. 첫 전체 수집은 몇 분 걸리고, 이후 연속 수집과 매시간 헬스체크가 자동으로 돕니다 (`COLLECTOR.md` 참고).

## 운영
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

의존성 프로필과 선택형 Claude SDK/레거시 SQLite 벡터 설치는 [의존성 관리 안내](DEPENDENCY_MAINTENANCE.md)를 참고하세요.

## frontend 릴리스 배포 전 점검 (2026-11-02)
릴리스는 활성 릴리스에 파일을 얹어 만들기 때문에, 작업본에서 시험이 통과해도 릴리스가 맞다는 보장은 없다. 배포 전에 릴리스 사본에서 첫 화면 경로 시험을 돌린다(약 40초, `nice -n 10`).

```bash
.venv-tests/bin/python -m scripts.release_gate <release>
```

- 마지막 줄이 `passed`일 때만 배포한다.
- 시험 목록은 `scripts/release_gate.py`의 `TESTS`에 있다.
  - 묶음 읽기, 실행 엔진 선택, 읽기 전용 경로, 공개·워크스페이스 첫 화면 브라우저 시험이 들어 있다.
- 11-02 07:01 장애 버전 `batch-reads-frontend-20261101-r5`는 이 점검에서 실패로 걸린다(gzip 시험).
- 배포 뒤 점검(`verify_web`)은 로그인하지 않으므로 고객 화면의 데이터 읽기를 확인하지 못한다. 그래서 배포 전 점검이 필요하다.
