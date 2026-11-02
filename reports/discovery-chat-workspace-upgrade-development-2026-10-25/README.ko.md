# 탐색·Chat·Workspace 품질 개선 — 첫 구현 결과

2026년 10월 25일. 앞서 작성한 개선 설계서 중, 다른 세션의 자율형 Agent v1.1 개발과 겹치지 않는 검색·목적 검증 내부를 구현했다. 전체 6~8주 설계의 완료나 운영 배포 완료를 뜻하는 자료로 사용하지 않고, 이번 구현 범위와 후속 범위를 구분한다.

## 이번에 바뀐 동작

### 제외 조건이 추천할 기능으로 섞이는 문제

공통 `QueryIntent`가 원문·긍정 검색문·제외 조건을 분리한다. `exclude`, `excluding`, `without`, `do not` 등과 제한된 한국어 제외 표현을 처리한다. 원문은 기존 입력·인증·Protocol Gate에 유지한다.

- `Python documentation; exclude news`에서 News가 추천 대상 검색어로 섞이지 않는다.
- `뉴스와 논문; GDP 제외`에서 GDP Node가 있는 Template은 추천에서 제외한다.
- `sports news; exclude financial news`처럼 같은 기능의 세부 주제를 제외했을 때 모든 News 기능을 차단하지 않는다.
- `not only`, `no more than` 같은 표현은 기능 제외로 오해해 지우지 않는다.
- 오디오 기능명으로 정규화할 때도 실제 Retrieval 입력에는 원문의 언어·형식·Timestamp·버전 조건을 보존한다.

이 해석은 로컬 규칙에 기반한다. 모든 언어·복합 부정·문맥을 이해하는 범용 자연어 모델이라고 표현하지 않는다.

### 검증된 정확한 이름 조회의 빠른 경로

PostgreSQL 검색에서 명시한 Agent 이름 또는 짧은 고유 이름이 정확하게 일치하고 **현재 Schema·Readiness·공개 Endpoint·입력 조건**을 통과하면 Query Embedding을 생략한다. 일반 의미 검색은 기존 Hybrid/RRF 경로를 유지한다.

정확한 이름의 Explore 조회에도 입력·실행 적합성 Gate를 적용한다. 검증되지 않은 이름이나 비공개 Endpoint는 빠른 경로의 조건을 통과하지 못한다. 후보 Cache로 검증 변경을 가리는 구현은 추가하지 않았다.

격리된 Native 경로 검사에서 검증된 이름 조회의 Embedding 호출이 0건임을 확인했다. 이 결과는 실제 PostgreSQL 성능 Benchmark나 운영 p95 측정과 구분한다.

### Workflow의 목적과 실제 연결 검사

기존 Schema·DAG Compiler·권한·후보 Fence를 유지하면서 다음을 보강했다.

- `FastAPI and PostgreSQL` 요청을 `FastAPI`만 남긴 검색문으로 축소하면 거부한다.
- 기존 버전 일치 검사를 유지한다. `APIs`와 `API` 같은 일반 용어의 복수형은 제품명 누락으로 오해하지 않는다.
- 독립적으로 나열한 Docker·Kubernetes·Terraform은 각각의 단계에서 자기 주제를 검증한다. 첫 단계에 세 주제를 모두 요구하는 과도한 검사는 적용하지 않는다.
- “첫 결과의 제목으로 다음 검색”을 요청하면 실제 `bindings.query`와 선행 Node의 `items[0].title`, 의존 순서가 있어야 한다. 단순히 두 단계에 같은 원문 Query를 넣어 성공으로 처리하지 않는다.
- 수정이 필요한 연결 문제는 `needs_details`와 고정된 안전한 설명으로 돌려준다. 검토안·Draft·Provider 실행은 생성하지 않는다.

AI 생성은 현재 승인된 News·Docs 계약 범위다. 요약·발송·집계 등 별도 계약이 필요한 기능을 검색으로 바꿔 지원한다고 표시하지 않는다. 자동으로 새 권한·Tool·네트워크 주소를 추가하지 않는다.

### 성능·품질 측정 도구

`retrieval_metrics.capture()`는 요청별 Lexical·Embedding·ANN·Projection·Exact 시간과 후보 수를 수집할 수 있다. 고정된 항목명과 숫자만 받으며 Query·Token·Identity·결과를 보관하지 않는다. ContextVar로 요청 사이의 값이 섞이지 않게 한다. 이번 범위에서 Admin Dashboard나 영속 관측 DB를 추가한 것은 아니다.

재실행할 수 있는 Offline 평가 CLI와 합성 사례 32개도 추가했다. 목적 보존·제외 조건·Template·생성 계획을 검사하고 입력/소스 Hash를 결과에 남긴다.

```sh
.venv/bin/python -m tools.evaluate_discovery_workflow \
  --cases reports/discovery-chat-workspace-upgrade-development-2026-10-25/offline-evaluation-cases.json \
  --output reports/discovery-chat-workspace-upgrade-development-2026-10-25/offline-evaluation-results.json
```

이 도구는 모델·네트워크·운영 DB를 사용하지 않는다. 계획한 전체 300개 과제, 운영 검색 정확도, 실제 Provider 업무 성공, 운영 SLO의 검증과 구분한다.

## 충돌 방지 방식

다른 활성 세션의 현재 작업 기록과 변경 경로를 읽어 범위를 분리했다. 다른 세션에 메시지를 보내거나 작업을 중단하지 않았다.

- 이 작업: `concierge/query_intent.py`, `retrieval_metrics.py`, `discovery.py`, `selection.py`, `hybrid_explore.py`, `workflow_discovery.py`, `workflow_goal_evaluation.py`, `workflow_goal_policy.py`, `workspace_app_factory.py`의 목적 검증 연결, 전용 평가 도구·테스트·보고서.
- 다른 세션의 소유 영역 보존: `agent_access/*`, `capability_registry.py`, `concierge/front.py`, `security.py`, `task_updates.py`, `gateway/store.py`, 공통 SQL Catalog·마이그레이션·공개 Metadata·서버 연결 파일.
- 다른 세션의 변경을 Reset·Checkout·Stash·Commit하거나 전체 파일로 덮어쓰지 않았다. 현재 작업 폴더의 필요한 함수에만 작은 Patch를 적용했다.
- 현재 디스크의 AGENTS.md는 이미 최대 3개 추천·A2A 우선/MCP 보충·x402 명시 선택 정책과 정합하다. 이 작업에서 Protocol 정책·추천 수를 변경하지 않았다.
- 마지막 통합 회귀에는 다른 세션의 자율형 Agent 수용 테스트도 포함했다. 당시 수집된 35개가 통과했다. 다른 세션이 이후 추가하는 코드와 실제 운영 반영은 해당 세션의 최종 통합 검증 범위다.

## 검증 결과

- 최종 통합 기능·API·보안: **392개 통과, 실패 0개**. 신규 품질 검사 36개, 당시 자율형 Agent 테스트 35개를 포함한 중복 없는 단일 실행 결과다. 원본은 `final-regressions.xml`, `final-regressions.log`에 있다.
- 격리 브라우저: **6개 통과**. 공개 Template 페이지 두 진입점과 모바일/데스크톱 Workspace를 검사했다. 마지막 Factory 보완 후 신규 브라우저 4개를 다시 확인한 결과는 별도 `final-browser.*`에 기록한다.
- Offline 의미·계획 평가: **32개 통과**. 모델·Provider 호출 0건이다.
- 공개 콘텐츠 검사: **275개 파일, 위반 0개**. 다른 세션도 공개 파일을 추가하므로 이 수량은 검사 당시 값이다.
- 신규 실행 모듈 4개에 Ruff `F,E9,S` 검사: **보안·정적 지적 0건**. 변경 모듈 Python 문법 검사도 통과했다. Bandit은 설치돼 있지 않아 Ruff의 보안 규칙과 실제 API·브라우저 보안 회귀를 사용했다.
- 모바일 화면을 캡처해 검토했다. 합성 계정·모의 모델·격리 Catalog만 사용했다. 운영 Provider 호출, 운영 DB 변경, 운영 서버 재시작, 배포는 0건이다.

초기 검사에서 독립 주제 목록에 대한 과도한 검사와 `APIs` 일반 복수형의 오판을 발견해 수정했다. 잘못된 Fixture와 평가 정답도 실제 계약에 맞게 보완했다. 초기 로그는 삭제하지 않았으며 최종 결과와 구분한다.

Chromium 최초 실행은 macOS Sandbox의 MachPort 초기화 제한으로 중단됐다. 격리 브라우저에 필요한 권한으로 재실행해 해결했다. 운영 브라우저나 사용자의 실행 서버를 대체하지 않았다.

## 설계 중 다음 단계로 남은 범위

다음은 구현 완료나 달성 성능으로 표시하지 않는다.

1. 현재 Catalog에 정답 라벨을 붙인 300개 평가 과제, 실제 장비·동시성별 p50/p95와 전체 Workflow 결과 검증.
2. Tool 단위 검색 Projection 확장, 작은 Cross-encoder의 조건부 Reranking 비교, 다국어 모델 선택, ANN의 Iterative Scan 보정. 검증 전 기본 검색 알고리즘과 DB 설정을 일괄 교체하지 않았다.
3. 후보 Cache의 완전한 변경 무효화와 Shadow·점진 적용. 기존 모델별 Embedding Cache·Singleflight는 재사용한다. 자율형 Agent v1.1의 변경 Feed 소유 영역과 중복 구현을 피했다.
4. Node 단위 자동 수정과 상태 재개, 확장된 Capability 계약, 별도 품질 Admin 화면. 이번 구현은 의미 이탈을 차단하고 정확한 수정 요청을 제공하는 단계다.
5. 유료 AI/Fallback Entitlement. 현재 소스의 Credit 약관은 무료 가입과 향후 유료 기능을 구분하고 있으며 구독 원장·새 고지 계약은 이번 검색 품질 범위와 구분한다. 가입 Credit을 유료 권한으로 간주하는 우회 처리는 추가하지 않았다.

기존 **모든 결과 Edge 우선·Edge 실패 후 Origin 복구** 경로와 중복 실행 방지, Credit 차감·저장 권한은 그대로 사용한다. 이 작업의 운영 활성화는 다른 세션의 통합 릴리스와 함께 검토·반영할 수 있도록 변경 목록과 Hash를 `validation-summary.json`에 남겼다.
