# 개선 설계 2.1 — 현행화·개발·검증

2026-10-26 KST · source delta와 격리 검증 완료 · 운영 전환 미실행

## 결과

[기존 설계서](../../docs/AGENT_CONCIERGE_BUSINESS_PRODUCT_IMPROVEMENT_2026-10-25.md)를 **2.1**로 현행화했다. compact MCP·고객 승인 grant·feed/watch·얇은 client, Tool projection·Shadow 재정렬·local query repair·품질 관측을 이미 구현된 자산으로 정리했다. 기존 IMP-01~08을 유지했고 같은 저장소·실행기·서명기를 다시 만들지 않았다.

이번 코드 변경:

1. 자동/Any·strict 추천에서 category/auth preference/hint/exclude를 보존한다. 잘못된 옵션은 후보 조회 전에 거부한다. 카테고리와 인증 선호를 실제 resource admission에 적용한다. 힌트로 원래 업무나 실행 권한을 바꾸지 않는다.
2. 일반 hybrid의 native ANN에 protocol/category/검증·resource 상태 필터를 조회 단계부터 적용한다. 기존 version-gated iterative scan과 current proof 검사는 유지한다.
3. 정확한 이름은 최신 lexical 300개 절단 전에 조회한다. GIN membership·정확 이름·현재 상태·protocol/category·현재 schema/readiness를 검사하며, 정상적인 이름 조회에 모델 호출을 추가하지 않는다.
4. 상태/요청 ID/고정 완료 문구뿐인 객체를 업무 결과로 받아들이지 않게 했다. 합법적인 빈 검색 결과와 상태 조회는 유지한다. file URI나 schema 통과를 사실성·업무 성공으로 승격하지 않는다.
5. 첫 단계뿐 아니라 모든 literal workflow query의 named subject를 검사한다. 후속 단계가 다른 제품으로 바뀌면 review 전에 거부한다. 미래 title binding의 의미를 일반 분석/요약 완수로 확대하지 않는다.
6. 연결 수명·만료 임박·재연결·인증 검사 여부·별도 실행 승인을 구조화했다. API 키와 OAuth의 만료 안내를 구분하고 만료/변경/사용 불가 연결의 불필요한 확인 버튼을 막았다. 자동 refresh나 범용 인증 provider 실행은 활성화하지 않았다.

## 검증

- 기능/API/보안 영향 회귀 **고유 392개 통과**. 기본 통합 391개, 그 안의 최종 source 영향 82개 교체 확인, 이후 추가한 명시 이름 경계 1개를 포함한다. 부분 실행 수를 단순 합산하지 않았다.
- 실제 Chromium + 가로챈 격리 HTTP에서 **6개 통과**. desktop/mobile, 만료 연결의 재연결과 disabled 확인 버튼, 만료 임박 안내, 기존 키 저장·교체·연결 해제·OAuth 안내·입력 보존을 확인했다.
- 공개 콘텐츠 **290개 파일, 위반 0**. embedded HTML mirror 정합성 포함. 공개 Chat의 금지 정보·기존 protocol/후보 호환성 회귀를 유지했다.
- 변경 runtime Python의 Ruff `F/E9/S` 통과. 정적 SQL prefix/고정 predicate/최대 100개의 placeholder 조립에 대한 S608 네 지점은 값 바인딩을 검토하고 해당 식에만 이유를 기록했다. 검증 도구의 합성 random과 assert는 각각 암호·운영 권한 판단 용도가 아니다. JS 문법 통과.
- SQL catalog **3,801 statements / 232 required tables** 정합성 통과. 새 운영 테이블·schema migration 없음.

### Native pgvector 비교

[합성 native 결과](filtered-ann.json): 4,096개 벡터, 768 차원 중 16개 비영(非零) 차원의 고정 seed 데이터, 4개 필터 구간 × 8개 query = **32회 비교**. exact eligible top-k와 비교한 최소 Recall@k **1.0**, 부적격 최근접 제외, HNSW 계획, transaction-local 설정 복원을 확인했다. k는 적격 후보가 10개 미만이면 실제 적격 개수다.

처음에는 별도 PostgreSQL initdb가 호스트의 공유 메모리 ID 한도로 실패했다. 서버·IPC·인증 설정을 바꾸지 않고, 명시 opt-in으로 로컬 PostgreSQL 18의 **postgres 관리 DB 안에 무작위 rollback-only 테스트 namespace**를 사용했다. 고정된 검증 SQL의 namespace만 매핑했고 애플리케이션 DB는 열지 않았다. 모든 테스트 schema/extension/데이터는 트랜잭션 rollback으로 제거하고 제거 여부를 확인했다. 운영 애플리케이션 데이터 쓰기는 0건이다.

이 native 결과는 합성 저차원 분포에서의 SQL/ANN·필터 검증이다. 운영 embedding 분포·full-catalog recall·provider 업무 성공률·p95 SLA·전역 동시성 수용이 아니다. 초기 실패 로그도 보존했다.

재현 도구는 [evaluate_design21_filtered_ann.py](../../scripts/evaluate_design21_filtered_ann.py)다. 기본값은 별도 Unix-only PG18 fixture이며, 이 호스트처럼 initdb 자원이 부족할 때만 `--shared-local-test-schema`로 위의 롤백 격리를 명시한다. 운영 DSN/대상 DB 인자는 받지 않는다.

## 배포 준비

불변 릴리스 **`strategy-design21-20261026-r1`**, **1,268개 파일**을 생성했다. 전체 manifest와 이번 영향 source 10개의 현재 파일 일치를 확인했고, 패키지 자체 Python으로 변경 모듈 import를 확인했다. 생성·검증만 수행했으며 운영 서비스를 중지·재시작·교체하지 않았다.

프로젝트 루트에서 같은 릴리스를 각 역할에 반영한다.

```sh
agentcon deploy frontend strategy-design21-20261026-r1
agentcon deploy admin strategy-design21-20261026-r1
agentcon worker-deploy jobs strategy-design21-20261026-r1
agentcon worker-deploy execution strategy-design21-20261026-r1
```

이 명령은 준비된 동일 source/SQL catalog를 반영한다. 일반 `restart`의 웹 전용 교체와 구분한다. 기존 배포/worker 보호 절차를 유지하며 추가 migration·secret·모델 변경은 필요하지 않다. 운영 반영 후에는 기존 검색·추가 조회·Chat·워크플로우·연결 페이지와 jobs/execution 상태를 현재 release 기준으로 확인한다.

## 잔여와 완료 범위

이번 source delta·격리 검증 완료가 전체 IMP-01~08의 사업/운영 수용 완료를 뜻하지 않는다. 실제 full-catalog held-out 품질·출처 진실성, provider별 인증 dispatch/refresh, 전역 admission·장기 부하, 상용 host·Registry, 실제 고객 성과/독립 평가, 결제·정산은 기존 profile·사업·승인 조건을 유지한다.

이 개발은 기존 후보/protocol 정책·권한·unknown 실행 방지·비공개 정보 보호를 유지한다. [구현 상태](implementation.json), [source snapshot](source-snapshot.json), [전체 산출물 검증](verification.json), [package 검증](package-verification.json)이 최신 증거다. `design-2.0.snapshot.md`는 byte hash 보존용 원문이며 상대 링크는 원래 docs 위치 기준이다.

화면 증거: [만료 연결 desktop](connections-expired-desktop.png), [만료 임박 mobile](connections-expiring-mobile.png). 테스트 계정·제공자는 합성 데이터다.

## 사용자 적용 후 운영 확인 — 2026-10-26

네 서비스 모두 `strategy-design21-20261026-r1` 실행을 확인했다. 서비스 점검 40개와 공개 데스크톱·모바일 흐름 2개가 통과했다. 검색 기대 조건 8개 중 7개를 충족했으며, 문서 검색 compact 후보의 최근 실행 검증 미충족은 별도 기록했다. [운영 점검 보고서 및 화면 증적](post-deploy/REPORT.ko.md)을 참조한다. 위 배포 준비·격리 검증 기록과 JSON은 적용 전 시점의 증거로 보존한다.
