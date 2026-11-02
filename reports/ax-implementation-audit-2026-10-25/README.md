# AX 개선 완료 주장 재검증

검토일: 2026-10-25 (Asia/Seoul)

## 결론

기능 구현과 운영 패키지 반영은 상당 부분 확인되지만, 첨부 문서의 ‘3개 권고안 해결 완료’ 판단에는 근거가 부족하다. 전역 차단 우회, 수동 차단 상태 불일치, 실패 이력 삭제, 정상 수요의 노이즈 오분류를 격리 테스트에서 재현했다. 회귀 테스트 통과만으로 이 문제들이 검증되지는 않는다.

이번 작업은 확인 요청에 따른 검토다. 제품 소스, 운영 DB, 서버 프로세스, Cloudflare 설정은 변경하지 않았다. 새로 만든 파일은 이 디렉터리의 검토 자료와 격리 재현 검사뿐이다.

## 확인된 구현

- `discovery_state.execution_state`의 capability evidence 조회는 레지스트리에 맞는 `SELECT *`를 사용한다.
- `currency`의 forex/fx/exchange rate, `resume`의 curriculum vitae 등 동의어가 반영됐다.
- 엄격한 A2A/MCP 탐색에 후보가 없을 때 `data.cross_protocol_hint`를 제공한다. 실제 REST 응답으로 확인했다.
- Agent 추천 성공 응답에 details/more/outcome/resume의 `continuation_plan`이 들어간다.
- weather 범위 필터, 실패 집계 및 동일 프로토콜·동일 이름 리소스 제외, Admin 제어 API/UI가 존재한다.
- 활성 Frontend·Admin 릴리스는 검토 시점 모두 `web-20261025-172043-97ce`였다. fast_chat, memory, PostgreSQL consumer, dashboard.py/html은 작업 소스와 동일했다. selection/discovery_state는 추가적인 최근 방어 코드 때문에 소스와 차이가 있었으나, 첨부의 동의어·weather 필터·SELECT * 수정은 활성 패키지에도 있었다. 파일 해시는 deployment-comparison.json 참조.

## 우선 해결 사항

### 1. 전역 차단 Agent가 다시 추천된다 — 높음

위치: `agent_market/concierge/fast_chat.py:103-110`, details 재검증의 `:242-246`.

전역 실패 리소스를 제외하고 탐색한 결과가 비면, 방문자 개인의 실패 목록만 적용해 재탐색한다. 전역 차단을 제거하는 폴백이다. 격리 카탈로그에 검증된 MCP weather Agent 하나와 서로 다른 방문자 실패 3건을 넣었을 때, 전역 차단 목록에는 포함되지만 새로운 방문자의 추천 결과로 그대로 반환됐다.

필요한 보완: 전역 차단은 후보가 없어도 유지하고, 다른 Provider·다른 프로토콜 안내 또는 명시적 no-match로 처리한다. details에서도 같은 제약을 유지해야 한다. 이 차단은 실행 전송의 Edge→Origin 폴백과 별개의 추천 신뢰성 정책이다.

### 2. 수동 차단 API의 응답과 실제 차단 상태가 다르다 — 높음

위치: `agent_market/gateway/dashboard.py:2391-2398`, PostgreSQL의 `agent_market/application_store_consumers.py:250-262`.

trip_circuit은 관리자 표시의 실패 3건을 넣고 항상 circuit_open=true로 응답한다. 실제 차단은 실패 >=3 및 실패 > 성공×2 조건이다. 과거 성공 10건이 있는 Agent에 수동 차단을 요청하면 API는 true를 응답하지만 실제 제외 집합에는 들어가지 않았다. 반복 클릭도 같은 관리자 행을 덮어쓰므로 확실한 강제 차단이 되지 않는다.

필요한 보완: 수동 override를 관측된 실행 결과와 분리하고, API/UI가 실제 유효 상태를 반환하도록 한다.

### 3. 차단 해제가 실제 방문자의 실패 이력을 삭제한다 — 높음

위치: `agent_market/gateway/dashboard.py:2399-2401`, `agent_market/application_store_consumers.py:263-265`.

reset_circuit은 해당 리소스의 success=0 행을 모두 DELETE한다. 격리 저장소의 일반 방문자 실패 행 1건이 해제 후 삭제됨을 확인했다. PostgreSQL에도 같은 의미의 DELETE가 있다. 과거 운영 데이터가 이미 삭제됐는지는 이번 검토에서 조사하지 않았다.

필요한 보완: 실제 실행·실패 증거는 보존하면서 수동 차단 상태를 해제한다. 회복 기준 시점이나 별도 상태 저장을 적용해 재개와 감사 이력을 함께 관리한다.

### 4. 정상 수요가 테스트 노이즈로 숨겨진다 — 중간

위치: `agent_market/gateway/dashboard.py:1818-1820`, `:1948-1957`, `:1967-1998`.

image generation workflow 또는 book a hotel workflow 문구만 포함해도 합성 테스트로 분류한다. 실제 고객을 나타내는 방문자 정보와 ‘Create an image generation workflow for product photos’ no-match 기록을 격리 DB에 넣자 synthetic_probe_count=1이 되고 unmet 목록에서는 사라졌다. 테스트 출처 증거를 확인한 결과가 아니다.

또한 unmet 집계는 후보 20개만 재평가하고 최대 15개만 노출하며, 현재 추천 후보나 Workflow 템플릿이 존재하면 해결된 이력으로 분류한다. 따라서 ‘14→0’은 대시보드 분류 결과일 수 있으며, 14개 업무의 실제 실행 성공을 입증하지 않는다. 이번 검토에서는 운영 DB의 당시 숫자나 실제 Provider 실행을 재검증하지 않았다.

필요한 보완: 격리 테스트 식별자·환경·명시적 출처로 테스트를 분리하고, 미해결 전체 수와 샘플 노출 수를 구분한다. 후보 발견, 계약 적합성, 실제 업무 성공도 별도 지표로 관리해야 한다.

### 5. 설명과 구현 사이에 작은 누락이 있다

- `_term_in('resume', 'cv')`는 false다. 첨부에서 추가했다고 한 cv 동의어는 해당 매핑에 없다. currency의 forex/fx/exchange rate와 resume의 curriculum vitae는 true다.
- 교차 프로토콜 힌트는 data에는 있지만 자연어 reply는 ‘No currently active, relevant agent found.’로 끝난다. 재질의 안내가 자연어에도 표시된다는 설명은 현재 응답과 다르다.
- continuation_plan은 Agent 추천 성공 경로에서 확인됐다. 이 필드 제공을 재방문 개선 성과로 판단할 수는 없다. ‘단발 방문 88.4%’의 개선 여부는 변경 전후 동일 기준의 방문 집단과 실행·재방문 데이터로 추가 측정해야 한다.

## 검증 결과 및 재현

첨부에 명시된 7개 테스트 파일을 다시 실행했다.

```
.venv/bin/python -m pytest -q tests/test_dashboard.py tests/test_storage_inventory.py tests/test_application_store_coverage.py tests/test_fast_single_recommendation.py tests/test_selection_capability_rules.py tests/test_workflow_discovery.py tests/test_front_hybrid_discovery.py
```

결과: **171 passed**, 종료 코드 0. 원본 출력은 regression.log.

추가 격리 재현:

```
.venv/bin/python -m pytest -q -s reports/ax-implementation-audit-2026-10-25/test_reproductions.py
```

결과: **5 passed**, 종료 코드 0. 이 중 4개는 결함이 실제로 재현되는지를 확인하는 검사이고, 1개는 힌트·행동 계획의 존재 및 자연어 안내 누락을 확인한다. 따라서 이 ‘통과’는 제품에 결함이 없다는 의미가 아니다. 원본 출력은 reproductions.log.

공개 콘텐츠 검사: **272 files / 0 violations**, 종료 코드 0. 원본 출력은 frontend-content.log.

동의어 단위 탐침: synonym-probe.json. 운영 패키지 비교: deployment-comparison.json.

검사는 로컬 격리 TestClient 및 메모리 저장소를 사용했다. 실제 Provider 요청, 운영 업무 실행, 운영 데이터 변경, 프로세스 재시작은 수행하지 않았다. PostgreSQL 경로는 구현의 SQL 의미를 대조했으며 운영 PostgreSQL에서 제어 API를 실행하지 않았다. 공개 콘텐츠 검사는 문구 정책 검사로, 전체 브라우저·보안 감사의 대체 자료가 아니다.

## 연구 근거에 대한 구분

MCP-Zero(arXiv:2506.01056)와 ToolRet(arXiv:2503.01763)는 도구 탐색·검색 품질을 논의하는 실제 연구다. 해당 연구 자체가 이 서비스의 미해결 0건, 임계값 3건, 이탈률 개선을 검증해 주지는 않는다. 첨부의 COBRA/Cobalt ‘Contextual Bandit Router & Circuit Breaker for Multi-Agent Systems’ 및 ‘Tool Inertia in LLM Agents’ 표기는 정확한 논문 식별자와 원문 링크의 보완이 필요하다. SNS 근거도 구체적인 원문 링크가 있어야 재현 가능한 근거로 평가할 수 있다.

## 권장 처리 순서

1. 차단 우회 제거와 수동 override 상태 분리.
2. 실패 이력을 보존하는 reset 동작으로 수정.
3. 정상 질의의 노이즈 오분류 제거 및 unmet 집계 의미 수정.
4. cv 동의어·자연어 recovery 안내 보완.
5. 위 재현 사례를 정상 동작을 요구하는 회귀 검사로 전환한 뒤 운영 반영 및 실제 개선 지표 측정.
