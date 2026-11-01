# 네이티브 독립 서비스 운영

이 문서는 `scripts/service_deploy.py cutover`를 검증 후 완료한 운영 상태에 적용한다. 현재 상태는 `./agentcon status`로 확인한다. `managed: false`이면 아직 기존 단일 프로세스다.

## 일상적인 변경 반영

```bash
./agentcon restart frontend
./agentcon restart admin
```

각 명령은 현재 작업 폴더를 새 배포본으로 보존하고 반대편 슬롯을 준비한다. 내부 준비 확인과 화면·정적 자산·인증 경계 점검을 통과해야 Caddy 연결이 바뀐다. 작업 폴더를 수정하는 것만으로 실행 중인 서비스가 변경되지 않는다.

```bash
./agentcon restart
```

인자 없는 restart는 프론트앤드와 어드민을 순서대로 교체한다. **수집·평가·헬스 및 실행 worker는 재시작하지 않는다.** 기존 슬롯은 진행 중 요청을 완료하고 즉시 복귀할 수 있도록 보존한다. 다음 배포에서 해당 슬롯을 재사용한다.

```bash
./agentcon rollback frontend
./agentcon rollback admin
./agentcon status
```

rollback은 해당 웹 서비스의 이전 슬롯으로 연결을 되돌린다. DB를 과거 백업으로 덮어쓰지 않는다. DB 스키마나 작업 계약이 이전 코드와 호환되지 않는 변경은 이 명령만으로 복구할 수 없으므로 배포 전에 호환성을 확보해야 한다.

## 작업 서비스 변경

먼저 배포본을 만들고 해당 역할만 교체한다. 아래 release 이름은 운영자가 선택하는 식별자다.

```bash
./agentcon package worker-update-001
./agentcon worker-deploy execution worker-update-001
./agentcon worker-deploy jobs worker-update-001
```

- `jobs`: 수집·헬스·capabilities·평가·임베딩·요약·유지 관리 작업 묶음.
- `execution`: 기존 영속 워크플로우와 워크스페이스의 typed/private 실행.

worker 교체는 해당 역할의 진행 중 작업을 마무리하고 소유권을 넘긴다. 웹 A/B 교체와 달리 worker 교체 자체에는 선점이 잠시 멈출 수 있다. 외부 실행 결과가 불확실하면 자동 재실행하지 않는다. 작업 계약을 바꾸면 신구 웹/worker 호환성을 함께 검증한다.

## 시작·정지와 OS 로그인

```bash
./agentcon start
./agentcon stop
```

`start`는 기록된 활성 배포본과 worker를 복구한다. `stop`은 프록시·웹·worker를 모두 정지하는 **전체 서비스 중단 명령**이다. 소스 반영에는 `stop`을 사용하지 않는다.

서비스는 사용자 `launchd` 영역에서 관리하며 활성 슬롯과 worker, 프록시의 LaunchAgent를 저장한다. 다음 사용자 로그인 시 다시 기동할 수 있다. 로그아웃·Mac 절전·전원·네트워크·PostgreSQL 장애까지 무중단인 구성은 아니다. 로그인 없이 부팅부터 운영해야 하는 서버는 별도 저권한 LaunchDaemon 또는 상시 서버로 이행한다.

## 주소와 경계

- 기존 공개 Tunnel origin은 로컬 `8400`으로 유지한다. 이 포트를 Caddy가 수신한다.
- 어드민의 기존 로컬 `8200`도 Caddy가 수신한다.
- 프론트앤드 슬롯: `8401 / 8402`, 어드민 슬롯: `8201 / 8202`.
- 모든 슬롯과 프록시는 `127.0.0.1`에만 바인딩한다.
- 공개 진입점은 `/admin`과 `/internal`을 차단한다. 어드민 진입점은 `/admin` 경로만 전달한다.
- 내부 준비 상태는 서명 키에서 파생한 비공개 probe 헤더가 있어야 읽을 수 있다. 토큰을 브라우저나 공유 로그에 넣지 않는다.

## 실패 시 대응

1. 후보 준비 실패: 기존 활성 서비스는 유지된다. 해당 역할의 로그를 확인하고 수정 후 새 release로 재시도한다.
2. 전환 명령 결과가 불명확하거나 프로세스가 중단됨: 두 슬롯을 임의로 종료하지 않는다.

```bash
./agentcon recover
./agentcon status
```

recover는 실제 Caddy 설정과 저장된 전환 기록을 대조한다. 상태가 모호하면 변경하지 않고 중단한다.

Worker 배포 중 `worker_draining` 또는 `worker_recovery_required`에 남으면 `agentcon recover`가 저장된 Worker 교체 기록을 확인한다. 기록을 지원하기 전 배포에서 중단됐다면 대상 역할과 준비된 release를 명시한다.

```bash
agentcon recover --worker jobs --release discovery-quality-20261026-r1
agentcon status
```

복구는 이전 PID의 종료와 역할 소유권 잠금 해제를 확인한 후 해당 Worker만 시작한다. 이미 목표 release가 실행 중이면 준비 상태를 확인하고 기록을 맞춘다. 잠금이 유지되거나 실행 release를 확인할 수 없으면 중단한다. `stable`로 복구된 뒤 다음 Worker를 순서대로 배포한다. 상태 JSON을 수동으로 `stable`로 바꾸거나 DB를 초기화하지 않는다.

3. 새 화면/기능에서 문제 발견: 호환성을 확인한 뒤 해당 서비스만 rollback한다.
4. worker가 비정상 종료됨: launchd 재기동과 heartbeat를 확인한다. 실행 소유권과 외부 부작용의 중복 여부를 먼저 확인하며 실행 레코드를 삭제해 재시도하지 않는다.
5. 초기 전환 실패: 준비된 새 프로세스를 정리하고 기존 legacy 모드 복구를 시도한다. `--legacy`는 이 복구용이며 정상 운영에서 새 worker와 함께 실행하면 안 된다.

## 파일과 검증 기록

- 배포 상태·프록시·서비스 명세: `gateway-data/services/`.
- 고정 배포본과 복사된 가상환경: `gateway-data/services/releases/`.
- 서비스 시작/종료 출력: `logs/services/`.
- 역할별 구조화 로그: `logs/service-frontend`, `logs/service-admin`, `logs/service-jobs`, `logs/service-execution`.
- 설계·시험 기록: `reports/zero-downtime-service-design-2026-10-22/`.
- 최초 전환 전 비공개 백업: `gateway-data/runtime-backups/pre-split-20261022-verified/`.

DB 백업에는 원래 DB 식별자에 연결된 쓰기 승인 기록도 포함된다. 다른 DB에 복원하면 자동으로 운영 쓰기 권한을 얻지 않는다. 복구 시험은 데이터 복원과 이 격리 상태의 보존을 확인하며, 다른 DB의 실제 운영 활성화는 별도의 복구 승인 절차를 거친다. 평상시 앱 rollback은 원래 DB를 계속 사용하므로 이 재활성화가 필요하지 않다.

웹 변경 후에는 관련 테스트와 콘텐츠/보안 검사를 실행한다. 정적 자산 URL과 공개 API, DB 스키마, 작업 payload는 최소 신구 두 배포본이 함께 동작하도록 유지한다. 파괴적인 스키마 변경과 이전 자산 삭제를 웹 교체와 동시에 수행하지 않는다.

## 로컬 생성 모델 설정

2026-10-23부터 새 서비스 배포본은 소유자 전용 `gateway-data/local-model.env`를 `agentcon.env` 다음에 읽는다. 예시는 `deploy/local-model.env.example`이다. 생성 모델과 Ollama 사용 여부만 설정할 수 있고 DB·로그인·관리자 설정은 덮어쓸 수 없다. 이전 배포본의 시작을 손상시키지 않도록 기존 `agentcon.env`와 분리했다.

현재 지정 모델은 OpenAI 호환 `http://192.168.0.25:8000/v1`, `gemma4-e4b-mlx`다. 요청마다 `chat_template_kwargs.enable_thinking=false`를 보낸다. 서버 측 단일 인스턴스와 16개 병렬 슬롯 구성은 변경하지 않는다.

`LOCAL_OLLAMA_ENABLED=0`은 로컬 Ollama 임베딩 호출과 벡터 적재를 중지한다. 기존 벡터는 보존하고 키워드 검색을 계속 사용한다. 현재 Gemma 생성 모델은 기존 임베딩 모델의 대체가 아니다. 벡터 검색을 다시 활성화하려면 호환 임베딩 제공자를 별도로 구성해야 한다.

처음 이 설정을 적용할 때는 frontend/admin과 자동 임베딩을 소유한 jobs 역할을 모두 새 배포본으로 교체해야 한다. 사용자 실행 worker는 생성 모델을 호출하지 않는다. `restart`만 실행하면 jobs는 교체되지 않는다. 프로필을 이해하지 못하는 이전 배포본으로 rollback하면 옛 Ollama 설정으로 돌아갈 수 있으므로 복귀 시 모델 연결 정책도 확인한다. 이 설정은 Ollama OS 프로세스를 중지하는 명령이 아니다.
