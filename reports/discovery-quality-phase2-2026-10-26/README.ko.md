# 탐색·Chat·Workspace 품질 고도화 후속 개발

2026년 10월 26일. 자율형 Agent v1.1의 운영 반영이 끝난 소스를 기준으로 후속 개발·검증과 릴리스 패키지 준비를 완료했다. 이번 작업의 운영 서비스 전환은 아직 실행하지 않았다.

## 구현한 동작

- **Tool 단위 검색 Projection:** Agent 소개문과 Tool의 기능·입력 필드를 분리해 읽는다. 현재 Resource 내용의 Hash로 Cache를 구분한다. Schema나 Tool 설명이 바뀌면 이전 Projection을 재사용하지 않는다. Query·방문자·권한 판단·후보 목록은 Cache에 저장하지 않는다. Cache는 최대 128개와 2 MiB로 제한한다.
- **조건부 재정렬:** 상위 최대 40개 후보만, 30ms 작업 예산으로 구조적 적합도를 계산한다. 서로 다른 Tool의 단어를 모아 존재하지 않는 기능으로 점수화하지 않는다. 정확한 이름 조회는 기존 빠른 경로를 유지한다. Chat의 최근 성공 검증 우선순위와 Protocol 정책은 변경하지 않는다.
- **기본 순위 보존:** 재정렬은 기본적으로 Shadow 관측이다. 합성 평가에서 기존·새 순서 모두 통과했지만, 개선 효과를 확정할 실제 대규모 정답 데이터가 부족하므로 기본 순위를 일괄 교체하지 않았다. Cross-encoder 모델 다운로드·교체도 수행하지 않았다. 이는 검증 결과에 따른 적용 결정이다.
- **검색 일관성 보완:** 한국어 별칭이 격리 검증 경로의 Lexical 검색에도 전달되게 했다. Hybrid 후보에 현재 Tool·인증·기능 정보가 유지되도록 보완해, 범용 문서·뉴스 검색기가 정보 누락으로 탈락하는 문제를 수정했다. Equity·Equities·Stock 검색 표현도 연결했다.
- **PostgreSQL ANN 필터 보완:** 실제 pgvector 버전을 확인한 후 0.8 이상에서만 `strict_order` Iterative Scan을 사용한다. Scan 5,000개·Memory 배수 1의 상한을 두고 `SET LOCAL`로 해당 검색 트랜잭션에만 적용한다. 최신 원본·모델·발행 근거 검사는 그대로 유지한다.
- **Workflow 목적 자동 보정:** 승인된 공개 영어 목적이 명확한 경우, 모델 검색문에서 제품명이 빠지면 원래 목적에서 검색문을 한 번 재구성하고 전체 Compiler·목적·권한 검사를 다시 통과시킨다. 모델을 추가 호출하지 않는다. 임의 Graph·미등록 Agent·잘못된 Schema·미지원 목적·불확실한 실행은 이 보정으로 우회하지 않는다. 직접 호출하는 엄격한 Compiler 계약도 유지한다.
- **Admin 품질 화면:** 공개 서비스 메뉴에 **‘탐색·생성 품질’**을 추가했다. 탐색·Agent 추천·Workflow 생성의 요청 수, 오류·권한 거부·검색 0건·추가 정보 필요, 내부 처리시간 p50/p95, 정확한 이름 빠른 경로, Projection Cache, 재정렬 관측, 목적 보정 건수를 표시한다.
- **개인정보 없는 지표:** 원문·Prompt·Token·사용자 ID·입력 인자·결과·모델 이름을 저장하지 않는다. 기존 PostgreSQL `workspace_admin_state` Snapshot 저장소를 재사용해 서비스 간 집계를 전달한다. 신규 테이블은 없다. 저장은 최대 30초 간격의 Best-effort이며 관측 시각과 프로세스 세대를 표시한다. 처리시간은 최근 최대 2,048건 표본이고, 전체 네트워크 응답시간이나 24시간 SLA로 표시하지 않는다.

권한, Credit·구독 정책, 실행 승인, 결과 불명 상태의 중복 실행 방지는 기존 계약을 유지한다. Agent 출력도 계속 **Edge 우선, Edge 실패 시 Origin 복구**다.

## PostgreSQL 검증

운영 원본은 PostgreSQL 18이다. 후속 검증의 기본 실행 도구도 PostgreSQL로 설정했다. 운영 DB로 SQLite를 추가하거나 전환하는 변경은 없다.

최종 검증은 별도 Unix 소켓의 임시 PostgreSQL 18에 실제 **GIN·pgvector HNSW** 색인을 설치해 수행했다. 이 검증에는 SQLite 검색·저장 경로를 사용하지 않았다.

- 합성 평가 과제 **300개**: 탐색 120개, Chat 80개, Workflow 계획 100개.
- 재정렬 Off/On 비교 **600건 모두 통과**. 이 중 400건은 실제 Frontend API 검색·추천이고, 200건은 목적·계약 기반 계획 Compiler 평가다.
- 별도 Native 색인 검사: 실제 GIN/HNSW 실행 계획, 필터가 있는 Iterative Scan, 트랜잭션 종료 후 설정 복원, 원본 변경 후 오래된 Dense 후보 제외를 확인했다.
- 테스트 인스턴스와 데이터 디렉터리 정리를 확인했다. 운영 데이터 변경은 0건이다.

참고로 앞선 PG18 소유 Schema 검증도 600건 통과했지만, 그 검증은 운영 색인을 건드리지 않기 위한 기존 격리 검색 대체 경로를 포함했다. 최종 Native 결과는 별도 `native-index-acceptance.json`에 보관했다. 초기 SQLite 실행 자료는 과거 구현과 비교한 Reference 기록으로만 유지한다.

재실행 도구의 기본 경로:

```sh
.venv/bin/python -m scripts.evaluate_search_workflow_quality \
  --output /private/tmp/discovery-quality-postgresql.json
```

이 명령은 운영 접속 정보 대신 테스트 소유 PostgreSQL 인스턴스를 만들고 정리한다. 과거 SQLite 비교는 `--reference-sqlite`를 명시해야만 실행된다.

## 검증 수치와 해석

- 최종 기능·API·보안·v1.1 호환 회귀: **473개 통과**, 실패 0개.
- 모바일·데스크톱 Admin 및 Workspace 브라우저: **6개 통과**, 실패 0개. HTTP는 격리 TestClient·모의 모델로 처리했다.
- 실제 PostgreSQL GIN/HNSW 평가: **600/600 통과**, 위 Native 검사도 모두 통과.
- 기존 사설 Primary/Fallback 모델 설정으로 공개 합성 목적 **4개를 순차 실행해 4개 통과**. 해당 소표본의 p50/p95는 각각 **0.5초/0.5초**였다. 별도 모델 설치·설정 변경·실제 Provider 업무 호출은 없다. Cold/Warm 상태를 통제하지 않은 작은 표본이므로 운영 SLO·보장 속도로 사용하지 않는다.
- 신규 Production Python 4개 모듈 Ruff `F,E9,S`: 지적 0개. Admin JavaScript 문법 검사 통과.
- 공개 콘텐츠 **290개 파일, 위반 0개**. SQL Catalog **3,802개 Statement·232개 필수 테이블** 정합성 통과.

합성 Catalog는 9개 기능별 Fixture다. 실서비스 전체 Provider의 정확도나 운영 대형 Catalog·동시 부하 성능을 대체하지 않는다. 계획 유효성, 실제 Provider 업무 완료, 네트워크까지 포함한 응답시간은 계속 구분한다. 평가 조건을 숨겨 정확도 100.0%나 전 서비스 성공으로 확대하지 않는다.

원본 증거:

- `final-regressions.xml`, `final-regressions.log`
- `browser-final.xml`, `browser-final.log`, Admin·Workspace 캡처
- `native-index-acceptance.json`, `postgres-acceptance.json`
- `private-model-calibration.json`
- `secure-coding-final.log`, `content-check-final.log`, `sql-catalog-check-final.log`
- `validation-summary.json`

초기 평가에서 검색 표현·후보 정보 누락·Fixture 정합성·Admin 데이터 Envelope 연결 문제를 발견해 보완했다. 실패 로그도 그대로 보관했으며 최종 결과와 구분한다.

## 운영 반영 준비

불변 릴리스 **`discovery-quality-20261026-r1`**, 파일 **1,267개**를 준비했다. 전체 패키지 Hash와 이번 변경 20개 파일의 원본 일치를 확인했고, 패키지 자체 Python에서 신규 모듈 Import·합성 Context 구성을 검사했다.

이전 자율형 Agent v1.1 소스·승인·Feed·SDK를 포함한 현재 통합 소스를 유지했다. 신규 Schema 마이그레이션이나 Secret은 필요하지 않다. 이번 작업에서 운영 서버를 중단·재시작·전환하지 않았다.

검증한 릴리스를 반영하는 명령은 `ROLLOUT.ko.md`에 있다. 프로젝트 AGENTS.md의 서버 운영 규칙에 따라 사용자가 서버 전환을 실행하거나 명시적으로 요청하는 단계다.

유료 상품·구독 원장·요금 확정, 추가 Capability의 실행 권한, 실행 불명 상태의 자동 재시도, 외부 Registry 게시는 이번 검색 품질 변경에서 새로 활성화하지 않는다. 실제 운영 트래픽의 라벨링과 장기 성능 평가는 배포 후 관측으로 이어갈 범위다.
