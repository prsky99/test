# Worker 배포 중단 복구

## 확인된 상태

`agentcon status`에서 Frontend와 Admin 활성 release는 `discovery-quality-20261026-r1`이다. Jobs는 이전 release로 기록돼 있지만 PID가 없고, Execution은 이전 release에서 실행 중이다. 전역 phase가 `worker_draining`이므로 후속 배포는 `stable_managed_state_required`로 거부된다.

중단된 이전 Worker 배포에는 `pending_worker` 기록이 없다. 기존 도구는 Worker 정지 전에 phase만 저장하고, 정지 실패나 명령 중단 후 복구할 대상 기록을 남기지 않았다. 기존 `recover`는 웹 전환 복구만 지원했다. 최초 중단의 직접 계기는 현재 상태 기록만으로 확정하지 않는다.

## 수정

- Worker 정지 전에 역할, 목표 release, 이전 release, 이전 PID를 기록한다.
- 정지 확인 뒤 이전 PID 기록을 해제하고, 소유권 잠금 해제를 확인한 후 후보를 시작한다.
- 후보와 rollback이 모두 실패하면 복구 기록을 유지한다.
- `agentcon recover`가 Worker 교체 기록을 복구한다. 이전 형식에는 `--worker`와 `--release`를 명시한다.
- 이전 PID 생존, 잠금 점유, release 불일치, 웹 전환 진행 중에는 복구를 거부한다.
- 목표 release가 이미 실행 중이면 재시작 없이 준비 상태를 확인하고 기록을 확정한다.
- 강제 종료, 실행 작업 재등록, DB 초기화, 운영 상태 JSON 수동 변경은 수행하지 않는다.

수정 파일: `scripts/service_deploy.py`, `agentcon`, `deploy/NATIVE_SERVICES.ko.md`. 신규 회귀 검사: `tests/test_worker_deploy_recovery.py`.

## 검증

```bash
.venv/bin/python -m pytest -q tests/test_worker_deploy_recovery.py tests/test_service_deploy.py tests/test_agentcon_config.py tests/test_agentcon_runtime_profile.py -k 'not real_launchd and not real_caddy'
bash -n agentcon
agentcon recover --help
```

82개 통과, 운영 서비스와 별개인 기존 launchd/Caddy 통합 검사 2개는 이번 실행에서 제외했다. 새 Worker 회귀 검사는 임시 상태 파일, 모의 프로세스, 실제 임시 파일 잠금을 사용한다. 운영 Worker 시작·정지와 DB 변경은 수행하지 않았다.

Ruff 보안 규칙을 현재 배포 도구와 고정 release의 동일 파일에 비교했다. 기존 경고 15개, 현재 경고 15개, 새 경고 0개다. 기존 subprocess와 URL 검사 경고의 전체 해소를 의미하는 결과는 아니다. 신규 테스트의 assert 경고는 테스트 단언문으로 분리했다.

## 운영자 실행 순서

현재 Frontend·Admin은 이미 목표 release여서 재배포할 필요가 없다. 아래 명령을 하나씩 실행하고 오류가 나면 다음 명령을 진행하지 않는다.

```bash
agentcon recover --worker jobs --release discovery-quality-20261026-r1
agentcon status
```

`phase: stable` 및 Jobs의 목표 release/PID를 확인한 후:

```bash
agentcon worker-deploy execution discovery-quality-20261026-r1
agentcon status
```

최종 조건은 `phase: stable`, 네 역할의 목표 release 활성화, 각 활성 프로세스 PID 확인이다. 실제 Worker 기동 및 PostgreSQL heartbeat 성공 여부는 위 운영 명령 실행 후 확정된다. 고정 release의 내용은 변경하지 않았으며, `agentcon`이 호출하는 작업 폴더의 배포 도구 수정은 즉시 적용된다.
