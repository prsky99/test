# B2A 결함 수정 및 검증

## 현재 상태

사용자가 프론트엔드 수정 완료를 알려 최종 검증 대기를 해제했다. F01~F09·F11 수정과 공유 소스를 통합하고, **PostgreSQL 18.6의 전용 스키마에서 전체 애플리케이션 기능 95개·B2A 6개 계약을 통과했다.** `b2a-schema-20261025-r1` 패키지를 생성하고 무결성을 확인했다. 이후 사용자가 네 서비스를 같은 릴리스로 배포했고 운영 스모크 21개 조건이 통과했다. 에이전트가 서버를 재시작하거나 배포하지 않았다. 최종 통합 결과는 아래 최신 검증 항목과 JSON/XML 증거를 기준으로 한다.

제품 구현의 정리된 계약은 `docs/B2A_RETENTION.md`에 작성했다. 재방문·추천을 실제 실행 승인이나 자동 마케팅 권한으로 확장하지 않는다.

## 수정 내용

- **F01 배지**: 현재 불변 연결 버전의 최신 실행 자체가 최근 24시간 내 성공했는지 확인한다. 만료·실패·review·quarantine·지원 불가·실행 일시정지는 Verified를 내린다. 건강 체크와 사용자 성공 신고는 검증 증거가 아니다. 검증 시각·만료·범위를 SVG 속성으로 제공하고 캐시 TTL을 증거 만료 이하로 제한한다.
- **F02 후속 도구**: 최대 두 개의 힌트에도 프로토콜·현재 증거·안전 스키마·방문자 실패 제외를 적용한다. Auto/Any는 A2A→MCP이며 x402는 명시 선택만 허용한다. 주소는 게이트웨이로 투영한다. cold-start는 관련 도구만 제안하고 가짜 확률 0.45를 제거했다. 힌트를 호환성 보장이나 실행 권한으로 표시하지 않는다.
- **F03 재방문**: 카드의 계약·스키마·현재 증거 fingerprint와 의미 계약 승인/실행 가능 상태를 비교하고 갱신된 후보를 반환한다. 워크플로우도 표시된 후보 전체의 정의/가용성을 비교한다. 약한 ETag, 목록, `*` 비교를 지원하고, 인증을 먼저 확인한다. 변경 없는 304 본문은 비어 있다.
- **F04 장애 격리**: 잘못된 JSON/선택적 저장소 장애로 힌트가 실패하면 힌트만 비우고 정상 추천/실행 결과를 보존한다. 예외 메시지·제공자 본문 대신 오류 클래스만 내부에 기록한다. 도구 메타데이터를 생성 Python 코드에 직접 삽입하지 않고 안전한 문자열 리터럴로 넣는다.
- **F05~F08 실패 복구**: REST `/api/agent/v1/report`와 MCP report를 공통 서비스로 연결했다. 기존 `alternative`를 유지하면서 최대 세 개의 `alternatives`와 적격한 공개 워크플로우를 추가했다. 현재 성공 증거, 이전 프로토콜, 실패 목록, 같은 호스트/주소와 알려진 공유 의존성 제외를 적용한다. 다른 호스트라는 이유만으로 완전한 독립성을 보장하지 않는다. `error_type`을 검증하고 일반 단어 generate를 rate-limit으로 오인하지 않는다. 직접 MCP call의 확정 실패도 공통 선택기를 사용하며, 불확실한 실행은 계속 재시도 금지다.
- **F09 문구·성능**: ‘304=0토큰’, ‘0ms 프리페치’, 항상 대체 후보가 있다는 보장을 제거했다. 현재 증거는 요청마다 확인하며, 네트워크/LLM 프리페치나 새로운 LLM 호출을 추가하지 않았다. 안전한 전체 변경 무효화가 입증되지 않은 새 결과 캐시는 추가하지 않았다.
- **F11 수용 검사**: 감사 조건을 정규 테스트로 옮겼다. 정상 검증 배지/후속 도구/복구 테스트에는 실제 격리 Registry 증거를 넣고 거부 조건은 유지했다. ‘1개 추천’, ‘0ms’ 등 예전 문구 기대값과 x402 알림의 명시 선택 조건을 현재 정책에 맞췄다.

공통 파일의 다른 작업 변경분(추천 입력 조건, 중복 처리, 수집기 등)은 보존했다. 아래 과거 체크포인트와 최신 재검증 결과를 구분한다.

## 전용 스키마 방식으로 공유메모리 제약 해결

새 DB 서버 프로세스를 띄울 필요는 없다. 기존 로컬 PostgreSQL 18에 실행별 무작위 스키마를 만들고, 검증된 애플리케이션 스키마 232개 테이블을 가상 데이터로 초기화한다. 새 postmaster/initdb를 사용하지 않아 추가 System V 공유메모리 할당 실패를 우회한다. 이는 같은 서버에 새 데이터베이스를 생성하는 방식과도 다르다.

단순 `SET search_path`만으로는 부족했다. Store의 public 고정 경로, 트리거 함수의 public 테이블 참조, 공용 advisory lock, 운영 검색 인덱스 연결을 확인했다. 운영 Store의 기본 동작은 유지하면서 **명시적 리허설 전용 클래스**에 스키마·소유권·ACL·DB OID 확인, 트랜잭션별 search_path, 전용 잠금과 범위 밖 스키마 참조 차단을 적용했다. 임의 DSN/스키마명을 인수로 받지 않고 기존 비공개 로컬 Unix 소켓 설정만 사용한다. 활성 event trigger가 있으면 DDL 실행을 거부한다.

생성·권한 철회는 한 트랜잭션으로 처리하고, 종료 시 생성 당시 스키마의 OID·소유자·권한이 그대로인지 확인한다. 외부 의존성이 있으면 삭제를 거부하며, 정상 종료 때 자신의 스키마만 제거한다. 리허설 후 독립 READ ONLY 조회에서도 잔여 스키마 **0개**를 확인했다. 원래 세션 search_path도 유지됐다. 운영 애플리케이션 행 읽기/복제/수정은 없지만 시스템 카탈로그 DDL·테스트 행 쓰기는 실제 발생한다.

전체 리허설에서 발견한 보완 사항도 반영했다. 검색 목표를 ‘Review’로 적고 다른 검색어를 반환하던 오래된 가상 모델 입력을 현재 목표 일치 검사에 맞췄다. 임시 클러스터 경로만 허용하던 두 검사에는 정확한 리허설 클래스와 현재 소유권을 재검증하는 경로를 추가했다. 현재 DB의 연결 슬롯 한도에 걸려 불필요한 연결을 먼저 닫고, 공유 DB의 동시 쓰기는 **2개 워커**로 제한했다. 운영 프로세스나 DB 설정은 변경하지 않았다. A2A 추천 양성 테스트에도 실제 격리 실행을 통한 현재 버전의 성공 증거를 준비했다.

재실행:

```bash
.venv/bin/python -m scripts.rehearse_b2a_retention_postgres --run --schema --full
```

필요 권한은 연결 대상 DB의 CREATE와 새 스키마 객체 소유권이다. 추가 역할 발급·서버/OS 설정 변경·운영 재시작은 필요 없다. 명령의 `--schema`를 빼면 기존 별도 임시 클러스터 방식이 유지된다. 스키마 생성 권한만으로 공유 서버의 장애·자원 격리가 생기지는 않는다.

범위는 실제 PostgreSQL 저장소의 고객 인증·조직·초대·권한 철회, 워크플로우·SDK·다운로드·명시 동의, 계약·실행 증거·알림 수신·재전송 거부, 벡터 바이트/출처·트랜잭션·동시 ID 정합성 및 B2A 상태 수명주기다. 외부 모델·실제 고객·결제·광고 발송은 사용하지 않았다. **운영 pgvector HNSW/네이티브 lexical 인덱스, crash/DR/HA·부하·전체 인스턴스 복구 합격을 의미하지 않는다.** 운영 인덱스는 연결하지 않고 기존 bounded FTS·exact vector 경로를 검사한다. 결과의 `full_application_ready=false`도 실제 운영 수용을 대체하지 않는다는 기존 계약을 유지한 것이다.

조사 근거:

- [PostgreSQL 18 Schemas](https://www.postgresql.org/docs/18/ddl-schemas.html): 스키마는 이름 충돌을 줄이지만 강한 보안 격리가 아니며, search_path에 쓰기 가능한 스키마를 넣으면 객체 이름을 신뢰하게 된다. 그래서 단순 경로 변경 대신 위 경계 검사를 적용했다.
- [Scaling Automated Database System Testing, SQLancer++](https://arxiv.org/abs/2503.21424): DBMS 방언 차이를 고려한 실제 DB 검증과 test oracle을 다루는 연구다. 이 프로젝트의 적용 판단은 SQLite/PG 결과 비교·버전 변경·증거 철회·롤백 등의 불변 조건을 실제 PG에서 검사하는 것이다. 논문이 전용 스키마의 장애 격리를 보장한다는 뜻은 아니다.
- [Reddit: Database testing practices](https://www.reddit.com/r/golang/comments/1r0qkvi/how_do_you_test_your_database_in_production/): 실제 DB 통합 검사와 테스트마다 새 스키마를 사용하는 의견을 참고했다. SNS 의견은 보안 보증으로 취급하지 않고 공식 문서·프로젝트 실행 결과로 판단했다.

## 검증 증거

**최신 최종 검증**:

- API·추천·게이트웨이·알림·보안·Store 경계 **459 passed, 1 deselected**. `current-integration-tests.log`, `current-integration-results.xml`. 제외한 1건은 별도 initdb를 요구하는 기존 전체 애플리케이션 검사다. 원래 OS 공유메모리 제약은 남아 있으며 같은 기능 계약을 위 전용 스키마 모드로 실행해 대체했다. 개별 postmaster 생성 가능성까지 통과했다고 주장하지 않는다.
- Chromium 보안·콘텐츠 **27 passed**. `current-browser-tests.log`, `current-browser-results.xml`.
- 전용 스키마 기능 계약 **95+6 전부 true**, PostgreSQL **18.6**, 애플리케이션 **232개 테이블**, 동시 워커 **2개**. `schema-full-results.json`, `schema-full-rehearsal.log`.
- 독립 read-only 정리 확인 **잔여 스키마 0개**. `schema-cleanup-check.json`.
- 공개 콘텐츠 **273개 파일, 위반 0**, HTML 동기화 확인. SQL 카탈로그 **3,743문장·232테이블**, `--check` 변경 없음. 다른 작업의 최신 SQL 소스와 카탈로그 provenance를 반영한 수치다.
- 배포 패키지 `b2a-schema-20261025-r1`, **1,238파일**의 해시 무결성과 현재 소스 일치 확인. `package-result.json`, `final-source-hashes.json`. 배포·재시작 없음.
- 기존 FastAPI OpenAPI operation ID 중복 경고 1건이 있다. 실패는 아니며 본 수정에서 중복 경로를 추가하지 않았다. 별도 운영 API 정리 항목으로 남긴다.

아래는 이 최종 실행 이전의 이력이다:

- 원래 감사의 **23개 조건 전부 통과**. 정규 B2A 검사에 포함되므로 중복 집계하지 않는다.
- 최신 B2A 전용 정규 검사 **54개 조건 통과**. 감사 호환 진입점 23개를 함께 실행한 로그는 77 passed지만 독립 조건 수는 54개다. `scoped-tests.log`, `scoped-results.xml`.
- 공통 파일의 후속 변경 **이전** 통합 체크포인트에서 API·추천·게이트웨이·알림·보안 **411건 통과**. `final-api-tests.log`, `final-api-results.xml`. 이 결과를 최종 현재 소스 통합 합격이라고 표현하지 않는다.
- 실제 Chromium CSP/XSS/개인정보·상업 문구·메뉴 회귀 **27건 통과**. `browser-tests.log`, `browser-results.xml`. 후속 렌더링 변경이 있다면 최종 소스에서 다시 확인해야 한다.
- 콘텐츠 검사 체크포인트 **272파일, 위반 0건**, embedded HTML과 `extracted_html.txt` 동기화 확인. `content-policy.log`.
- Python 관련 소스 10개 구문 컴파일 및 수동 보안 리뷰. Ruff/pyflakes/Bandit은 설치돼 있지 않아 실행 완료로 주장하지 않는다. 새 런타임 SQL은 파라미터 바인딩을 사용하고, 새 추천/재방문/복구 모듈에는 외부 제공자 실행이 없다.
- SQL 카탈로그 체크포인트 **3,745문장·232테이블**. 스키마 이전은 없다. 다른 작업이 완료되면 전체 source manifest를 한 번 갱신·재검사해야 한다.
- 기존 OpenAPI operation ID 중복 경고 1건을 관측했다. 테스트 실패는 아니며 이번 B2A 수정 때문에 중복 경로를 추가한 것은 아니다.

### PostgreSQL 검증의 실제 범위

설치된 PostgreSQL 18로 별도의 Unix 소켓 임시 클러스터를 생성하려 했으나 OS의 System V 공유메모리 식별자/자원 한도로 initdb가 중단됐다. 로그의 ‘No space left on device’는 이 경우 디스크 부족을 뜻하지 않는다. 운영 DB·서버·커널 설정이나 다른 프로세스를 변경하지 않았다. 참고: https://www.postgresql.org/docs/18/kernel-resources.html

대신 설정된 로컬 **PostgreSQL 18.6**에서 **READ ONLY 트랜잭션 + EXPLAIN(ANALYZE 없음)**으로 변경 경로의 SELECT/INSERT 두 문장을 확인했다. 둘 다 계획이 유효했고 애플리케이션 데이터 쓰기·스키마 변경은 0이다. `postgres-readonly-plans.json`.

이 read-only 체크포인트 자체는 쓰기·수명주기 합격이 아니었다. 후속 전용 스키마 전체 리허설로 기능 검증을 완료했으며, 별도 postmaster 생성 실패의 원래 로그는 `postgres-init-diagnostic.log`에 보존한다.

## 논문·SNS 조사와 적용 판단

자료에서 곧바로 성능 향상률이나 특정 토큰 절약을 보장한다고 추론하지 않았다. 아래 자료를 설계 근거로 참고하고 실제 수용은 프로젝트 회귀로 검증했다.

1. [AgentDojo, NeurIPS 2024](https://arxiv.org/abs/2406.13352): 외부 도구 반환을 신뢰 경계 밖의 데이터로 다루는 평가 환경이다. 이 프로젝트에서는 제안/메타데이터와 실행 권한을 분리하고 유효한 주 작업이 선택적 힌트 때문에 실패하지 않도록 적용했다.
2. [ToolLLM, 2023](https://arxiv.org/abs/2307.16789): 관련 API 검색과 도구 활용을 구분하는 연구를 참고해, 전체 도구를 주입하지 않고 선택한 계약만 제한적으로 제공한다. ‘3개’라는 수는 논문의 최적치가 아니라 제품 요구다.
3. [OWASP MCP Security](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html): 전체 도구 정의의 무결성 고정, 검토 없는 변경과 호출 권한의 분리, 최소 권한을 참고했다. 스키마 fingerprint·읽기 도구 검사·실행 승인 비상속으로 구체화했다.
4. [RFC 9110 If-None-Match](https://www.rfc-editor.org/rfc/rfc9110.html#name-if-none-match): GET의 약한 비교 의미에 따라 공개 프록시의 `W/` ETag와 목록을 처리했다. 인증을 대체하지 않는다.
5. [Reddit MCP 아키텍처 논의](https://www.reddit.com/r/mcp/comments/1waf9kv/where_mcp_lives_in_your_architecture_matters_more/): 계약 소유권과 프롬프트 밖의 인가 경계를 검토하는 실무 의견으로 참고했다. 기술적 보장은 논문·규격·자체 검사로 판단했다.
6. [Reddit outputSchema·컨텍스트 논의](https://www.reddit.com/r/mcp/comments/1tauwhg/outputschema_in_mcp_useful_feature_or_token_tax/): 클라이언트에 따라 스키마의 모델 노출/비용 해석이 다르고 댓글에도 이견이 있다. 그 수치를 제품의 ‘0토큰’ 주장으로 채택하지 않았다.

## 다음 진행 범위

최신 패키지의 사용자 배포 이후 공개 경로·재방문 조건부 응답의 운영 확인이 남는다. 소스 검증과 운영 반영을 혼동하지 않는다. 서버 직접 실행 지침에 따라 이번 작업은 패키지 생성까지만 수행했다. 동일 패키지로 반영할 명령은 아래와 같다.

```bash
./agentcon deploy frontend b2a-schema-20261025-r1
./agentcon deploy admin b2a-schema-20261025-r1
./agentcon worker-deploy jobs b2a-schema-20261025-r1
./agentcon worker-deploy execution b2a-schema-20261025-r1
```

이 명령들은 실행하지 않았다. 프록시·DB 서버의 재시작이나 운영 스키마 마이그레이션 명령은 포함하지 않는다.

외부 스킬 채택·홍보 성과, 실고객 과금, 실제 제공자 호출, 자동 마케팅 발송, 운영 SLA는 이번 합격 범위에 포함하지 않았다.


## 사용자 배포 후 확인 완료

사용자 재시작·배포 완료 통보 후 활성 frontend/admin과 jobs/execution이 모두 `b2a-schema-20261025-r1`인지 확인했다. 준비 상태·워커 프로세스·릴리스 해시 및 HTTP 스모크 **21개 조건 전부 통과**. 실제 공개 도메인과 로컬에서 skill/llms/agent-card/test presets GET 200, skill 약한 ETag 목록 304, 세션 없는 resume의 wildcard 요청 401을 확인했다. 로컬 합성 방문 세션 1개로 추천 **3개**, **2,199ms**, context_ready 및 인증된 resume의 weak/list/wildcard 304·빈 본문·비공유 캐시를 확인했다. 실제 제공자 실행·고객 계정 변경·결제·설정 변경은 하지 않았다. 합성 방문자의 토큰·응답 본문·개인정보는 파일에 저장하지 않았다.

증거: `post-deploy-smoke.py`, `post-deploy-smoke.json`, `post-deploy-smoke.log`. 유효 세션의 조건부 resume 검사는 로컬 경로에서, 공개 프록시 조건부 검사는 skill 경로에서 수행했다. 공개 도메인의 인증된 세션 재사용까지 별도 검증한 것으로 확대하지 않는다.

위 ‘다음 진행 범위’의 배포 명령은 사용자 실행이 완료된 이력이며 다시 실행할 필요가 없다. 이번 B2A 수정·전용 스키마 기능 검증·운영 반영 확인 범위의 필수 잔여 작업은 없다. 기존에 명시한 native ANN/DR/HA/부하 검증과 OpenAPI 경고 정리는 별도 범위다.
