# Explore A1 운영 적용 절차 — 실행 전 승인 필요

이 문서는 적용 이력이 아니라 준비한 실행 절차다. 사용자 승인 전 운영 스키마·서비스를 바꾸지 않았다.

> 적용 기록: 2026-10-30 10:17~10:23 KST에 이 절차로 적용을 마쳤다. 결과와 남은 확인은 [REPORT.ko.md 6절](./REPORT.ko.md)에 있다. 아래 명령을 다시 실행하지 않는다. 특히 `install`은 한 번만 실행한다.

정확한 후보:

- frontend: `explore-a1-frontend-20261030-r2` — 현재 활성 QA11 frontend r1 기반.
- admin: `explore-a1-admin-20261030-r2` — 현재 활성 QA11 admin r1 기반.
- jobs: `explore-a1-jobs-20261030-r2` — 현재 활성 experience jobs r4 기반.

같은 작업에서 먼저 만든 `explore-a1-각역할-20261030-r1`은 미배포 초안이다. 최종 바이트 예산을 포함한 r2를 사용하며 r1을 대신 적용하지 않는다. `candidates.json`과 `frozen-verification.json`의 역할·기반·파일 hash·공통 정책 hash를 먼저 확인한다. 활성 릴리스가 달라졌으면 다른 작업을 덮어쓰지 않고 재검토한다.

## 적용 범위

PostgreSQL 보조 테이블 두 개와 대기열 인덱스 한 개 추가, frontend/admin/jobs 교체다. 리소스 무결성 트리거를 추가·변경하지 않는다. PostgreSQL 재시작·execution 교체·Cloudflare Worker 변경·모델 서버 변경·OpenSearch 설치는 필요 없다.

## 1. 상태와 스키마 준비

프로젝트에서 `./agentcon status`를 확인한다. 다음 명령은 공유 작업 트리가 아닌 정확한 jobs 후보의 소스로 실행한다. 경로를 바꿔도 `--root`는 서비스 프로젝트를 가리켜야 한다.

```sh
cd <저장소>/gateway-data/services/releases/explore-a1-jobs-20261030-r2
./.venv/bin/python -B -m scripts.explore_search_documents status --root <저장소>
```

`installed=false`를 확인한 뒤 승인된 경우에만 한 번 실행한다.

```sh
./.venv/bin/python -B -m scripts.explore_search_documents install --root <저장소>
```

이때 기존 ID가 대기열에 등록되며 전체 계약을 한 번에 읽지 않는다. 이미 설치되어 있으면 install을 반복하지 않는다. 스키마 준비만으로 기존 서비스가 새 검색 경로로 바뀌지는 않는다.

## 2. 초기 적재와 jobs 적용

작은 배치로 시작해 시간·메모리·웹 응답을 확인한다.

```sh
./.venv/bin/python -B -m scripts.explore_search_documents refresh --batch 25 --rounds 20 --root <저장소>
./.venv/bin/python -B -m scripts.explore_search_documents status --root <저장소>
```

초기 명령은 최대 500건이다. 전체 적재 완료를 의미하지 않는다. 무제한 병렬 적재나 대형 단일 트랜잭션으로 바꾸지 않는다. jobs 교체 후 나머지는 제한된 maintenance 작업이 계속 처리한다. 적재 중인 항목은 기존 전체 계약 검색으로 정확성을 유지한다.

```sh
cd <저장소>
./agentcon worker-deploy jobs explore-a1-jobs-20261030-r2
```

jobs 교체 동안 신규 자동 작업 처리가 잠시 대기할 수 있다. 기존 frontend/admin은 이 단계에서 계속 운영한다.

## 3. 두 웹 전환

```sh
./agentcon deploy frontend explore-a1-frontend-20261030-r2
./agentcon deploy admin explore-a1-admin-20261030-r2
./agentcon status
```

## 4. 적용 후 실제 확인

- 활성 후보·준비 상태·기존 execution/프록시 유지 확인.
- 문서 수·현재 정책 문서 수·대기열 변화와 메모리/DB 대기 확인. 적재 도중 모든 검색에 같은 개선 폭을 약속하지 않는다.
- 일반 용어, 날씨·번역·GitHub, 엄격 프로토콜·인증·보고서 필터와 추가 조회 확인.
- 읽기 전용 실제 검색의 결과·지연을 이전 자료와 비교하고, 문서 적재 범위와 결과/임베딩 캐시 조건을 함께 기록.
- 원본 변경 뒤 현재 문서 사용 또는 전체 계약 폴백이 유지되는지 확인. 새 실행 보고서나 권한을 만들어 검증을 대신하지 않는다.

문제가 있으면 웹은 배포 전 상태에 기록한 직전 QA11 릴리스로 복구한다. 새 보조 테이블을 급하게 삭제하지 않는다. 이전 jobs r4는 새 보조 테이블을 사용하지 않으므로 스키마가 남아 있어도 기존 작업을 유지한다. 정확한 현재 상태를 확인하고 승인된 관리 명령으로 복구한다.
