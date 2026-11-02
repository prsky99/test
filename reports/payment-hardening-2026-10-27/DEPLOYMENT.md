# 결제 개선 전용 배포

대상: `payment-hardening-20261027-r2`.

**상태: 사용자 실행 후 운영 반영 확인 완료. frontend/admin/execution이 대상 릴리스이며 점검 36건 통과. 아래 명령은 적용·복귀 기록으로 보관한다. 추가 재배포는 필요 없다.**

`package-validation.json`의 `ready_to_deploy: true`를 확인한 뒤 아래 명령을 사용자 터미널에서 순서대로 실행한다. r1은 중간 검사에서 Redis 경로의 헤더 누락을 발견한 버전이므로 사용하지 않는다.

## 패키지 범위

- 현재 frontend/admin 운영 기준 `registration-hardening-20261027-r1` 위에 결제 관련 변경만 적용했다.
- 운영 화면, embedded HTML, 발행 자산을 바이트 단위로 보존했다. 별도 작업의 미배포 워크스페이스·로그인 변경은 포함하지 않는다.
- SQL·스키마 변경은 없다. SQL 카탈로그의 소스 증빙만 갱신했다. DB 마이그레이션·DB 재시작·jobs 재배포는 필요하지 않다.
- 공개 x402는 요구사항 조회 전용이며 실제 결제·일일 자동 결제·토큰 환불을 활성화하지 않는다.
- 이미 만들어 검증한 패키지이므로 `package`나 일반 `restart` 명령으로 다시 만들지 않는다.

## 적용 명령

```bash
./agentcon deploy frontend payment-hardening-20261027-r2
./agentcon deploy admin payment-hardening-20261027-r2
./agentcon worker-deploy execution payment-hardening-20261027-r2
./agentcon status
```

각 명령이 성공한 뒤 다음 명령을 실행한다. 상태 출력에서 frontend/admin의 active 슬롯과 execution이 모두 `payment-hardening-20261027-r2`인지 확인하고 관리자 탭을 새로고침한다. 이전 슬롯 종료·신규 준비 상태·요청 배출은 기존 배포 도구가 관리한다. 실패한 명령을 무시하거나 프로세스를 임의 강제 종료하지 않는다.

이후 읽기 전용으로 준비 상태·공개 OpenAPI·429 헤더를 확인하고, 실제 서명·정산 없이 테스트/워크플로우의 기존 실행 경계와 관리자 오프라인 오류를 확인한다. 본 작업은 패키지 준비만 수행했으며 위 배포 명령은 실행하지 않았다.

## 복귀 기준

준비 상태 실패, 화면/자산 오류, 인증 회귀, 예기치 않은 결제 실행, 정상 요청 실패 증가가 있으면 해당 서비스 반영을 중단한다. 이번 준비 당시 기준은 다음과 같다. 아래 값은 실제 배포 직전 상태가 같을 때만 적용한다.

```bash
./agentcon deploy frontend registration-hardening-20261027-r1
./agentcon deploy admin registration-hardening-20261027-r1
./agentcon worker-deploy execution db-reconnect-execution-20261027-r1
./agentcon status
```

기존 기준 패키지는 보존했다. 이전 릴리스에는 이번 결제 보완이 없으므로 복귀 후 관련 입력은 별도 점검해야 한다.

## 검사 중 발견·보완

처음 패키지 의존성 검사에 테스트용 PYTHONPATH가 전달되어 sqlite-vec가 운영 의존성으로 잘못 집계됐다. 패키지 생성 과정에서만 테스트 경로를 제거했고, 정확한 lock/OpenSSL/libpq 검사를 유지해 통과했다. 운영 가상환경이나 lock을 수정하지 않았다.

첫 전체 검사에서 Redis의 Boolean 허용 결과에는 정확한 잔여량이 없다는 점을 확인했다. 허용 시 숫자를 지어내지 않고 정책 헤더만 제공하며, 차단이 확정된 경우에는 실제 판단에 근거한 `r=0`과 보수적인 재시도 시간을 제공하도록 보완했다. 별도 카운터 조회나 추가 차감은 없다. 로컬·Redis 허용/차단을 각각 검사한다. 일회용 테스트 네임스페이스를 사용했으며 후속 전체 검증은 Redis 연결도 운영 경로와 분리했다.

세부 증빙: `deployment-package.json`, `package-validation.json`, `package-integration.xml`, `package-security-comparison.json`, `operating-preflight.json`. 초기 실패 증빙은 `r1-*` 및 `package-audit-first-attempt.json`에 보존했다.
