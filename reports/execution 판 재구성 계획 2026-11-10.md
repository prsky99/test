# execution 판 재구성 계획 (2026-11-10, 운영·SRE)

결론: execution은 10-31 판(`docs-execution-20261031-r2`)에 머물러 있어 이후 수정이 들어가지 못한다. **지금 활성 frontend 판을 통째로 복사해 execution 판을 만들고**, execution 전용 시험을 게이트에 넣은 뒤 조용한 시간에 배포하는 것을 권한다. DB 변경은 없다.

## 1. 지금 상태
- execution 판과 최신 frontend 판(`writer-retry-frontend-20261110-r1`) 차이
  - agent_market에서 87개 파일이 다르다.
  - frontend에만 있는 파일이 25개다.
  - 같은 코드베이스이고, 역할은 `service_host --role execution`으로만 갈린다.
- 그래서 생기는 문제
  - 11-10 쓰기 잠금 재시도(0eacf21e)의 패치가 맞지 않는다. 11-02 WriterBusy 구분(0769327e)도 없다.
  - execution 로그 "Due workflow round deferred after a storage error: statement_failed"가 같은 잠금 시간 초과다.
    - 11-05 228회, 11-06 39회, 11-07 26회, 11-08 2회, 11-09 60회, 11-10 18회
    - 예약 워크플로가 그 회차를 건너뛴다.
  - 10-31 이후 execution 관련 커밋 10개가 빠져 있다.
    - typed 엔진 선택 복원(db8ac7d8)
    - 작업공간 쓰기 잠금 단축(96b5f773)
    - Web Bot Auth 서명(d06755b7)
    - 잠금 재시도(0eacf21e) 등

## 2. 방법 비교
| 방법 | 장점 | 단점 | 판단 |
|---|---|---|---|
| A. 활성 frontend 판을 복사해 execution 판으로 | 운영에서 이미 도는 코드와 같다. 이후 패치가 frontend와 똑같이 맞는다 | 87개 파일이 한 번에 바뀐다. execution 경로 시험이 필요하다 | **권장** |
| B. 10-31 판에 필요한 패치만 골라 얹기 | 바뀌는 양이 적다 | 의존 커밋을 계속 추적해야 하고, 다음 패치도 또 안 맞는다 | 비권장 |
| C. 저장소 HEAD로 새로 패키징 | 최신이다 | 다른 세션의 미배포·미커밋 변경이 섞인다(오버레이 규칙 위반) | 금지 |

## 3. 순서 (A)
1. 게이트 보강: `scripts/release_gate.ROLE_TESTS['execution']`에 기본 목록과 execution 시험을 넣는다.
   - 기본 목록(typed_engine_for 포함)
   - `tests/test_execution_authority.py`, `tests/test_service_split.py`, `tests/test_workflow_product_cli.py`
   - 오늘 최신 판에서 앞의 두 개가 통과했다.
2. 판 만들기
   - `cp -cR` 활성 frontend 판 → `latest-execution-YYYYMMDD-r1`
   - `package(name, base='docs-execution-20261031-r2')`: 기준 판 검사는 활성 execution을 기준으로 한다.
   - release.json에 "내용 출처 = frontend 판 이름"을 함께 남긴다.
3. `release_gate`(role execution)가 passed인지 확인한다.
4. 배포 직전 확인
   - 활성 execution이 base 그대로인지 본다.
   - 실행 중인 작업이 없는지 본다: `edge_gateway_runs`의 미완료 수, 워크플로 due.
   - 조용한 시간(트래픽이 적은 새벽)에 `./agentcon worker-deploy execution <판>`
5. 배포 뒤 30분 관찰
   - execution 로그의 ERROR·Traceback
   - 'statement_failed' 회차 연기 수
   - 'Admitted execution ended without a confirmed result'
   - 엣지 실행 성공률(edge_gateway_runs state)
6. 되돌리기: `./agentcon worker-deploy execution docs-execution-20261031-r2`
   - 이전 판은 prune 보호 대상(previous)이다.
   - execution은 DB 스키마를 바꾸지 않으므로 되돌려도 데이터 문제가 없다.
7. 이후에는 frontend 판을 만들 때 execution 판도 같은 내용으로 함께 만든다. 절차(DEPLOY.md)에 한 줄 추가한다.

## 4. 승인
- 배포는 상시 승인 범위다(게이트 passed, 기준 판 기록).
- DB 변경, 데이터 삭제, 외부 게시는 없다.
- 다만 87개 파일이 바뀌는 큰 교체라, 배포 시각은 총괄 PM과 맞춘다.
