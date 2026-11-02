# initdb 없이 PostgreSQL 검증 완료

2026-10-25 · Agent Concierge 추천 차단·해제 후속 검증

## 결론

임시 PostgreSQL 서버 초기화는 필수가 아니다. 남아 있던 목표는 새 서버 설치가 아니라 실제 PostgreSQL에서 추천 차단 상태, 실행 이력 보존, 트랜잭션과 동시 변경을 확인하는 일이었다. 기존에 설정된 PostgreSQL 18 서버에서 전용 Schema를 만들고 고정된 검증 SQL만 실행한 뒤 제거하는 방식으로 이를 완료했다.

기존 서버 버전은 180006이다. DB 생성 권한은 없지만 Schema 생성 권한은 있었다. 새 서버 시작·initdb·운영 설정 변경 없이 검증용 테이블 3개(resources, agent_outcomes, meta)를 사용했다. 운영 테이블에는 쓰지 않았다. 최종 카탈로그 조회에서 `ax_circuit_check_` 검증 Schema의 잔여 개수는 **0개**였다.

## 검증 방식과 범위

- 매 실행마다 임의의 전용 Schema 이름과 소유 확인용 태그를 생성한다.
- 테스트 트랜잭션의 search_path는 pg_catalog, 전용 Schema, pg_temp로 고정하며 public은 제외한다. 실제 meta가 전용 Schema로 해석되는지도 확인한다.
- 실제 `PostgresConsumerMixin`의 두 메서드와 `PostgresApplicationStore._native`, `_execute`를 그대로 사용한다. SQL 결과나 연결을 모의 처리하지 않는다.
- 트랜잭션 드라이버는 이 테스트의 전용 Schema를 선택한다. 제품 Store의 public Schema 고정·프로필 검증·복원 보호 장치는 수정하지 않았다.
- 서버 연결은 동시에 최대 2개를 사용한다. 두 DB 트랜잭션이 열린 뒤 barrier를 통과시켜 실제 실행 구간이 겹치는지 확인한다.
- 마지막에 생성자·소유 태그를 확인하고 자신이 만든 Schema만 제거한다.
- 추가로 실제 애플리케이션 Store를 초기화 없이 연결해, DB 세션 자체를 읽기 전용으로 설정한 상태에서 수정된 차단 조회를 확인했다. 현재 애플리케이션 프로필 검증이 통과했고 차단 대상 3개 조회도 성공했다.

이것은 기능·SQL·트랜잭션 검증이다. 새로운 전체 DB 프로필을 설치하는 시험은 별도 범위다. 같은 DB 역할의 권한이 남아 있으므로 Schema를 별도 서버와 같은 보안 경계로 표현하지 않는다. 여기서는 고정된 테스트 SQL과 제한된 검색 경로로 운영 테이블을 피했다.

## 실제로 발견하고 수정한 PostgreSQL 오류

첫 실제 실행에서 `ApplicationStoreError: invalid_parameters`가 재현됐다.

원인: `global_failing_resources`의 중복 리소스 조회가 `ANY(%s)`에 Python list를 전달했다. 공통 실행기의 `_values`는 scalar 파라미터만 허용하므로, 차단 대상이 생기는 순간 DB 조회 전에 실패했다.

수정: ID 목록을 JSON 문자열 파라미터로 전달하고, PostgreSQL의 `jsonb_array_elements_text(%s::jsonb)` 결과를 bigint로 변환해 조회한다. 공통 실행기의 파라미터 허용 범위는 넓히지 않았다. 이 오류를 막는 단위 회귀 검사도 추가했다.

변경 파일:

- `agent_market/application_store_consumers.py`: scalar JSON 파라미터로 중복 대상 조회.
- `scripts/rehearse_recommendation_circuit_existing_postgres.py`: 전용 Schema 검증 도구.
- `tests/test_application_store_consumers.py`: 실제 파라미터 계약을 사용하는 오류 회귀 검사.
- `tests/test_recommendation_circuit_rehearsal_scope.py`: 운영 Schema 이름·SQL 주입형 이름을 연결 전에 거부하는 검사.
- `tests/test_recommendation_circuit_postgres.py`: 명시적으로 선택할 수 있는 existing-schema 모드.

최초 실패 자료는 reproduced-invalid-parameters.json과 first-native-run.log다. 수정 후 첫 연결 확장 시도에는 OperationalError가 발생했다. 이후 최대 연결 수를 2개로 제한한 구성으로 실제 검사와 pytest가 통과했다. 해당 OperationalError의 세부 원인은 확인되지 않았으므로 별도의 원인 해결 성과로 집계하지 않는다.

## PostgreSQL 실제 검사 8항목 — 전체 통과

1. 성공 10건이 있어도 수동 차단이 적용되며 가짜 실패를 생성하지 않는다.
2. 차단 해제 후 실행 결과 13개 행이 보존된다.
3. 새 관찰 구간의 실패 누적으로 다시 차단된다.
4. SQLite와 PostgreSQL의 제외 결과가 일치한다.
5. 동시 관리자 변경에서 서로 다른 리소스의 상태가 유실되지 않는다.
6. 두 실제 PostgreSQL 트랜잭션의 실행 구간이 겹친다.
7. 커밋된 상태를 새 연결에서 읽을 수 있다.
8. 실제 PostgreSQL 롤백 후 이전 상태가 유지된다.

최종 결과: existing-schema-result.json, native-pytest-final.log.

## 회귀·안전성 확인

- 영향 범위 회귀 검사: **70 passed** (affected-regression.log).
- API 보안·Schema 범위 거부 검사: **32 passed** (security-regression.log). 이 중 범위 검사 10개는 위 그룹과 중복된다.
- PostgreSQL 정식 pytest: **1 passed**, 내부 실제 검사 8항목 (native-pytest-final.log).
- 위 세 그룹의 고유 pytest 항목은 93개다(collection.log).
- 실제 애플리케이션 Store 읽기 전용 연결·조회: 성공(real-store-read-only.json).
- 검증용 Schema 잔여 개수: **0개**(cleanup-confirmation.json).
- Provider 호출, 운영 테이블 쓰기, 서비스 재시작: **0회**. 검증 Schema 생성·쓰기·제거에 따른 시스템 카탈로그 변경은 있었다.

브라우저 검사도 **1 passed**(browser-regression.log)로, 전체 고유 pytest 검사는 **94개 통과**다. 전체 서비스 성능·장기 부하나 모든 PostgreSQL 기능에 대한 포괄적 인증으로 확대 해석하지 않는다.

## 연구·공식 문서·SNS 근거

- [Mini-Transactions 연구, 2025](https://arxiv.org/abs/2504.02344): 작은 read-modify-write 트랜잭션으로 동시성·격리 문제를 확인하는 접근을 참고했다. 이번에는 전체 논문 도구를 도입하는 대신, 두 연결의 상태 변경을 재현 가능한 순서로 검사했다.
- [PostgreSQL 18 Schema 공식 문서](https://www.postgresql.org/docs/18/ddl-schemas.html): 같은 이름의 테이블을 서로 다른 Schema에 두고 검색 경로를 선택하는 방식과 신뢰 경계를 확인했다.
- [PostgreSQL JSON 함수 공식 문서](https://www.postgresql.org/docs/18/functions-json.html): JSON 배열을 text 행으로 전개하는 지원 함수에 맞춰 scalar 파라미터 오류를 수정했다.
- [PostgreSQL 14 커널 자원 공식 문서](https://www.postgresql.org/docs/14/kernel-resources.html): 새 서버의 공유 메모리 자원 문제와 기능 검증 목적을 분리했다. 시스템 설정을 바꾸거나 공유 메모리를 삭제하지 않았다.
- [Hacker News: PostgreSQL 통합 테스트 환경 논의](https://news.ycombinator.com/item?id=40082409): 서버 재기동 대신 기존 인스턴스·분리된 Schema를 활용하는 개발자 경험을 참고했다.
- [Reddit: PostgreSQL 통합 테스트 논의](https://www.reddit.com/r/golang/comments/125p66i): 테스트별 Schema 및 search_path 방식의 사례를 확인했다.

SNS 사례는 선택지 탐색용이다. 완료 판정은 실제 PostgreSQL 실행 결과와 재현 검사에 근거한다.

## 다시 실행하는 명령

운영 설정 파일에 지정된 서버를 사용하는 가역적인 검증용 DDL이므로 명시적으로 선택해서 실행한다. 기본 private-cluster 모드를 자동으로 운영 서버에 전환하지 않는다.

```
AGENTCON_CIRCUIT_PG_TEST_MODE=existing-schema .venv/bin/python -m pytest -q tests/test_recommendation_circuit_postgres.py
```

직접 실행:

```
.venv/bin/python -m scripts.rehearse_recommendation_circuit_existing_postgres --existing-runtime
```

## 운영 반영 확인 완료

새로 발견된 scalar 파라미터 오류 수정은 소스에 반영했다. 확인 시 활성 Frontend·Admin 릴리스 `web-20261025-194831-2de0`에는 이 후속 수정이 아직 없었다(deployment-comparison.json).

프로젝트의 서버 운용 규칙에 따라 이 작업에서 서버를 재시작하지 않았다. 반영 대상은 Frontend·Admin이다.

```
./agentcon restart frontend
./agentcon restart admin
```

DB 초기화·마이그레이션·Worker 재배포는 필요하지 않다.

후속 재시작 확인: Frontend·Admin이 `web-20261025-202033-b4d1`로 전환됐고 수정 파일 일치·readiness·실제 Store 읽기 전용 조회를 확인했다. 추가 재시작은 필요하지 않다. 확인 기록은 reports/local-postgres-memory-review-2026-10-25에 있다.
