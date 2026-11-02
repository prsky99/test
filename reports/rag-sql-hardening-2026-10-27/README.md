# RAG 검색 유지 · SQL 조합 8건 개선 · 시작 전 임베딩 예열

**운영 반영 확인 완료: `rag-sql-hardening-20261027-r3` 활성, 시작 임베딩 예열 성공. 최종 운영 점검은 문서 마지막 절 참조.**

**최종 통합 배포 대상: `rag-sql-hardening-20261027-r3`. 최신 Chat 릴리스를 보존한 통합본이며, 이전 r2 대신 이 패키지를 사용한다.**

2026-10-27. 사용자의 최종 지시는 RAG/자연어 검색 유지, 초기 모델 로딩 보완, 앞선 SQL 조합 경고 8건 수정이다. 일반 SQL 검색 전환은 취소됐으며 적용하지 않았다. 서버 수명주기는 사용자 터미널에서 관리한다. 운영 서버·워커·DB 설정은 변경하지 않는다.

## 조사와 적용 기준

- [Halfond·Orso·Manolios, FSE 2006: Using Positive Tainting and Syntax-Aware Evaluation](https://www.khoury.northeastern.edu/home/pete/research/positive-tainting.html): 개발자가 정의한 구조만 신뢰하고 비신뢰 데이터를 SQL 문법으로 취급하지 않는 원리를 적용했다. 논문의 자바 도구를 이식했다는 뜻은 아니다.
- [Psycopg 매개변수](https://www.psycopg.org/psycopg3/docs/basic/params.html), [SQL 조합 공식 문서](https://www.psycopg.org/psycopg3/docs/api/sql.html), [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html): 값은 바인딩하고, 가변 식별자는 Identifier로 인용하며, 구조는 코드 소유 선택지만 허용한다.
- [Bandit B608](https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html): 문자열 조합 자체를 발견하는 낮은 신뢰도의 경고와 실제 사용자 입력의 SQL 편입을 구분했다. 검사 제외/noqa/nosec 추가로 해결하지 않았다.
- [Reddit의 Psycopg 조건 조합 논의](https://www.reddit.com/r/PostgreSQL/comments/za8w79/), [안전한 바인딩 논의](https://www.reddit.com/r/learnpython/comments/1bm0aa0/): 동적 WHERE에도 값 바인딩과 전용 조합 API가 필요하다는 실무 논의를 조사했다. 검색 결과는 확인했으나 게시물 본문 열기는 실패했으므로 이를 독립 검증/벤치마크 근거로 사용하지 않는다. 구현 판단은 위 원 논문·공식 문서로 검증했다.
- [Ollama 공식 API 소스](https://github.com/ollama/ollama/blob/main/docs/api.md?plain=1), [API 명세](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml), [모델 재로딩에 대한 Reddit 논의](https://www.reddit.com/r/ollama/comments/1k16pd2): 임베딩 요청의 keep_alive와 모델 로드 시간을 구분했다. 무한 상주나 모델 강제 언로드를 선택하지 않았다.

## 구현 범위와 완료 기준

1. 대상 8개 B608 경고를 코드의 안전한 SQL 조합으로 제거한다. RAG/ANN/자연어 해석·프로토콜·관련성·권한 경계를 유지한다.
2. 잘못된 WHERE/주석/연산자/파라미터 수는 DB 실행 전에 거절한다. 정상 필터·대용량 명세·캐시 검증·행/바이트 제한은 보존한다.
3. 프론트엔드 서비스 시작 시 수신 준비 완료 전에 공개 고정 문구로 임베딩을 예열한다. 예열 실패를 성공으로 표시하지 않고, 기존 임베딩 실패 시 제한된 검색 경로는 유지한다.
4. 실제 PostgreSQL 및 격리 브라우저/API 검사, 코드 스캔, 같은 데이터에서 RAG 결과 동등성 검증 후 불변 배포 패키지를 만든다.

## 수정 내용

- `application_sql.py`: 코드 소유 필터 원자만 다시 선택해 WHERE를 구성한다. 내부 호출자도 임의 SQL/주석/리터럴/새 연산자를 끼워 넣을 수 없다. 기존 프로토콜·등급·지역·가격·네트워크·활성·보안·인증 필터의 정확한 형태와 값 자리 수를 허용한다. 최대 길이/조건 수/placeholder 수를 제한한다.
- `application_store_resource_batches.py`: 표준 SQL 템플릿, `sql.Placeholder`, `sql.Identifier`로 본문 크기 조회·일반 행/좁은 행·캐시 미적중 원문 조회를 구성한다. 실제 데이터는 계속 별도 바인딩한다. 현재 read-only snapshot/원문 hash/원문 바이트 예산/명세 비절단 규칙을 유지한다.
- `application_store_vector.py`: 실제 벡터 hash와 출처를 대조하는 조회의 IN placeholder 조합을 표준 조합기로 바꿨다. 세대·모델·작업 상태·현재 출처 검증은 그대로다.
- `discovery.py`, `hybrid_explore.py`: 고정 CTE/고정 탐색 조건을 문자열 덧셈 대신 명시적인 SQL 구조로 결합한다. 사용자 질의·프로토콜·카테고리는 계속 값으로 바인딩한다. RAG 분기·임베딩·ANN·재정렬·관련성 게이트는 제거하지 않았다.
- `gateway/rag.py`: 임베딩 요청에 유한한 30분 keep_alive를 전달한다. 시작 전 예열은 요청 예산 8초와 기존 응답 크기/벡터 검증을 사용한다. 짧은 중복 예열만 합치며 모델/endpoint가 바뀌면 다시 예열한다. 공개 테스트 문구 외 고객 질의는 예열에 쓰지 않고 고객 검색 캐시와 분리한다.
- `service_host.py`: frontend 서비스의 기존 시작 준비 절차에서 임베딩이 켜져 있을 때만 예열한다. admin/비활성 임베딩/검증용 warm=False는 호출하지 않는다. 서명된 비공개 readiness에 예열 성공/실패/비적용 상태를 제공하고 공개 API에는 노출하지 않는다. 예열 실패 시 기존 서비스의 제한된 검색 동작을 유지하며 무기한 시작 대기나 자동 모델 다운로드·언로드는 하지 않는다.

## 현재 확인된 모델 상태와 한계

설정된 임베딩 서버에 공개 고정 문구로 2번 요청했다. keep_alive가 포함된 요청 모두 HTTP 200/유효한 768차원 응답이었다. **28.9ms / 13.0ms**, 서버 보고 load_duration은 **3.882ms / 1.657ms**였다. `embedding-probe.json`.

이미 올라와 있는 모델을 측정한 것이며 모델을 내리거나 재시작하지 않았다. 따라서 앞선 7.4초 첫 번역 검색의 원인이 모델 로딩이었다고 단정할 수 없다. 이번 예열은 서비스 재시작 후 로딩 비용이 첫 고객 요청으로 넘어오는 위험을 줄이는 조치다. 서버 재시작·메모리 압력·다른 모델의 메모리 사용으로 인한 강제 퇴거까지 방지하는 보장은 아니다.

## 진행 상태

소스 수정·동일 snapshot RAG 결과 비교·전용 스키마·최종 고정본 회귀를 완료했다. 최종 결과는 아래에 기록했다.

## 범위 고정과 중간 검증 결과

다른 작업의 공개 화면 변경이 현재 작업 디렉터리에 함께 들어왔다. 이를 포함해 만든 중간 r1에서 중앙 로딩 관련 브라우저 9건이 실패했다(`unscoped-release-integration-final.log`, 855 passed/9 failed). 이번 요청의 SQL 수정으로 해결할 화면 설계 변경으로 취급하지 않고, 사용자 작업 디렉터리는 보존했다.

최종 **`rag-sql-hardening-20261027-r2`**는 실제 운영 중인 `explore-search-speed-20261026-r4`의 별도 복사본에 이번 수정만 합쳐 만들었다. 변경은 새 SQL 구성 모듈 1개와 기존 SQL/예열 관련 코드 6개 및 SQL 원본 해시 카탈로그 1개뿐이다. 공개 HTML·원본 HTML 두 파일·발행 자산과 나머지 운영 코드가 그대로임을 전체 manifest로 확인했다. `scoped-package.json`. 이 최종본으로 영향 회귀를 다시 고정했다. 중간 r1은 배포 대상이 아니다.

SQL 카탈로그는 등록 SQL **3,801문/232테이블**, unique SQL 추가·삭제 **0**, 스키마·런타임 정의 변경 **0**이다. 달라진 것은 코드의 source_manifest뿐이며 DB 마이그레이션이 아니다.

같은 PostgreSQL exported snapshot에서 이전 r4와 비교한 내부 6개/API 8개, 총 **14개 조건의 결과 ID·순서·개수가 동일**했다. SQL 호출 수도 모두 동일했다. 임베딩과 ANN이 실제 켜져 있었고 첫 조건에서 dense 후보 100개가 조회됐다. 별도 고정 문구 예열은 약 **22.7ms**에 성공했다. `rag-equivalence-summary.json`, `native-comparison.json`.

이번 소표본에서는 날씨/탐색 일부가 빨라지고 뉴스 반복 요청 등 일부는 느리게 측정됐다. 새 SQL 구성의 주목적은 안전한 구조를 보장하는 것이며, 모든 질의 속도 개선이나 p95를 입증한 시험이 아니다. 이미 실행 중인 모델을 강제로 내리지 않았으므로 실제 cold load를 재현했다고 주장하지 않는다. 모델 예열·유지시간은 최초 요청에 로드가 겹치는 위험을 줄이지만 명세 파싱·DB·네트워크 등 나머지 지연을 없애지는 않는다.

정적 분석을 새로 만진 RAG 파일까지 확장하자 **기존 레거시 RAG 경고 4건**(SQL 문자열 조합 3, 예외 처리 1)도 잡혔다. 이전 불변 운영 릴리스의 같은 파일을 동일 도구로 검사해 네 건의 코드·종류·심각도·신뢰도가 모두 동일하고 **신규 경고 0**임을 대조했다. 앞서 요청한 네이티브 검색 SQL 경고 8건은 모두 제거됐으며, 기존 레거시 경고를 이번에 새로 생긴 것 또는 해결한 것으로 계산하지 않는다. `bandit-baseline-comparison.json`, `bandit-rag-baseline.json`.


## 최종 결과

- 최종 고정본 통합 회귀 **864 passed / 실패 0 / skip 0**. 허용된 SQL 필터 전체 원자/복합 조건/바인딩 개수, SQL 주입 문자열·주석·추가 연산자 차단, 가장 많은 필터를 사용하는 실제 PG 조회, 대용량 명세·바이트 경계, 벡터·원문 변조, 현재 상태 철회, 브라우저 XSS/CSP·중앙 로딩·페이지 이동, 시작 예열 성공·실패·비활성·동시 호출·짧은 상태 만료를 포함한다. `release-integration-final.xml`, `test-inventory.json`.
- PostgreSQL 전용 스키마 **18개 계약 통과** 및 스키마 삭제 확인. 운영 테이블 쓰기와 외부 에이전트 실행은 0. `release-native-freshness.json`.
- 대상 8개 SQL 경고는 최종 패키지의 동일 코드 검사에서 **8 → 0**, 파싱 오류 0, 스캔 종료 코드 0. `target-bandit-final.json`.
- RAG 파일까지 확장한 스캔은 앞서 대조한 **기존 Medium 3/Low 1**로 종료 코드 1이다. 대상 8건과 분리해서 기록하며 High/신규 경고는 0이다. 기존 경고를 숨기기 위한 검사 예외는 추가하지 않았다. `release-bandit.json`, `bandit-baseline-comparison.json`.
- 공개 콘텐츠 **300개 파일/위반 0**, 발행 JavaScript 구문 통과. 공개 페이지·원본·발행 자산은 운영 r4와 바이트 단위로 같다. SQL 카탈로그 재생성 검사 변경 없음. `release-content-final.log`, `release-javascript-final.log`, `release-sql-catalog-final.log`.
- 불변 릴리스 manifest 확인, 검증 복사본의 코드·자산 **1,279개 파일**이 manifest와 일치. 고객 정보·토큰·시스템 설정을 공개 화면에 추가하지 않았다. `release-source-freeze.json`, `scoped-package.json`, `validation-summary.json`.
- 중간 111건·모델 11건·전용 필터 검사와 최종 864건은 중복 합산하지 않는다. 최종 고유 pytest 수는 864다.

## 사용자 터미널에서 운영 반영

개발 범위는 완료했다. 이 패키지는 현재 운영 공개 화면을 보존하고 SQL 안전성 및 시작 예열만 적용한다. 프론트엔드만 다음 명령으로 교체한다. 관리자·워커·DB 마이그레이션은 필요하지 않다.

```bash
./agentcon deploy frontend rag-sql-hardening-20261027-r2
```

제가 배포·서버 교체·DB 또는 모델 서버 재시작을 실행하지 않았다. 실제 운영 새 프로세스의 시작 예열 상태와 첫 검색 시간은 사용자 배포 후 별도로 확인해야 한다. 모델 예열 성공과 개별 에이전트의 실행/품질 검증은 별개다.

## 사용자 실행 통보 후 배포 불일치와 통합본 준비

사용자의 실행 완료 통보 후 활성 릴리스를 실제 조회했으나 `chat-remediation-20261027-r4`였다. 이 릴리스는 준비 상태는 정상이었지만 이번 SQL 구성 모듈과 예열 수정이 포함되어 있지 않았다. 사용자 명령이 실행되지 않았는지, 이후 다른 배포가 있었는지는 단정하지 않는다. 현재 활성 상태만 기록한다. `deployment-discrepancy.json`.

최신 채팅을 보존하기 위해 **`rag-sql-hardening-20261027-r3`**를 `chat-remediation-20261027-r4`의 복사본에서 준비했다. SQL·벡터·RAG·service_host 6개 모듈이 기존 기준 r4와 정확히 같음을 먼저 확인한 뒤, 검증된 r2의 이번 변경 7개 파일을 이식했다. SQL 카탈로그는 source_manifest만 갱신했다. 운영 서버는 교체하지 않았다.

최신 채팅 화면에서는 앞서 복구한 Explore 중앙 로딩 토큰이 다시 빠져 있어, 입력과 실제 검색의 진행 토큰 두 곳을 복구했다. 현재 페이지 구성·문구·최신 채팅 코드는 보존했다. 원본 HTML 두 파일을 동기화하고 재발행했으며 전체 manifest 대조에서 나머지 공개 HTML/CSS/자산은 그대로이고 `operating.js`와 원본 해시 manifest만 달라졌음을 확인했다. `combined-package.json`, `prepare_combined_release.py`.

첫 통합 검사에서는 다른 작업에서 추가된 아직 배포하지 않은 무한 keep-alive/생성 모델 heartbeat/추가 readiness 필드를 요구하는 테스트가 섞여 있는 것을 발견했다. 현재 검증 대상의 유한 30분 임베딩 예열과 별개이므로, 기존 864건을 통과한 테스트 버전을 고정하고 최신 채팅 검사 2개 파일을 더해 다시 실행했다. 검사 자체를 건너뛰지 않았다. 기존 혼합 버전 실행의 실패는 `combined-validation/mixed-test-version-release-integration-final.xml`에 보존한다.

또한 새 채팅 릴리스의 엄격한 CSP 아래에서 Playwright의 문자열 조건 평가가 unsafe-eval에 막혔다. 해당 대기를 같은 조건을 반환하는 함수 형태로 수정했다. **CSP·브라우저 보안 설정을 완화하지 않았다.** 테스트 복사본에만 반영했고 다른 작업의 테스트 파일은 변경하지 않았다.


## 최신 Chat 통합본 최종 검증

`rag-sql-hardening-20261027-r3`의 고정 복사본에서 **944 passed / 실패 0 / skip 0**. 이전 864개 사례와 최신 채팅 회귀 80개 사례를 함께 검사했다. 중간 실행과 합산하지 않는다. `combined-validation/release-integration-final.xml`, `combined-validation/test-source-hashes.json`.

- PostgreSQL 전용 스키마 **18개 계약 통과**, 검증 스키마 삭제 확인.
- SQL 경고 대상 **8 → 0**, 대상 스캔 종료 코드 0. 확장 범위의 기존 레거시 경고 4건은 이전 기록과 동일하다.
- 공개 콘텐츠 **300개/위반 0**, SQL 카탈로그 일치, JavaScript 구문 검사 통과.
- 릴리스 manifest와 검증 복사본 코드·자산 **1,282개 파일 일치**, 원본 HTML 동기화.
- 최신 채팅 기능/배치/문구는 보존했다. 공개 화면 변경은 검색 중앙 로딩 복구 두 곳뿐이다.

위 통합본 준비 당시 활성 상태는 `chat-remediation-20261027-r4`였으므로 당시에는 운영 반영을 확인했다고 판단하지 않았다. 이후 사용자 재배포 결과는 아래에 추가했다. 다음 명령을 사용자 터미널에서 실행하면 SQL·예열 수정과 최신 채팅 변경을 함께 반영할 수 있다. 서버·DB·모델 서버를 제가 교체하거나 재시작하지 않았다.

```bash
./agentcon deploy frontend rag-sql-hardening-20261027-r3
```

이전 r2를 배포하면 최신 채팅 변경을 되돌릴 수 있으므로 위 r3만 사용한다. 다른 서비스나 DB 마이그레이션은 필요하지 않다. `combined-package.json`, `combined-validation/validation-summary.json`.


## 사용자 재배포 후 실제 운영 확인 — 2026-10-27

사용자의 두 번째 실행 통보 후 **frontend 활성 B 슬롯 `rag-sql-hardening-20261027-r3`**, 준비 상태 정상, 시작 임베딩 예열 **성공(true)**을 비공개 서명 probe로 확인했다. SQL/벡터/RAG/서비스 모듈과 화면 스크립트가 최종본과 일치하고 manifest도 유효했다. 로컬과 공개 도메인의 operating.js도 릴리스와 같았고 공개 자산은 Cloudflare BYPASS였다. 운영 서버 수명주기 명령은 실행하지 않았다.

실제 GET 검색 **10회 모두 HTTP 200**:

- 공개 날씨: **5.216초 / 1.458초**, 29개 결과.
- 공개 번역: **6.747초 / 1.703초**, 45개 결과.
- 로컬 날씨: rollout-api.json에 기록. 로컬 번역: **3.328초 / 0.955초**.
- 공개 자연어 `Find an agent for weather forecasts`: **6.196초**, A2A 결과 3개.
- 공개 자연어 `Translate English text into Spanish`: **5.746초**, MCP 결과 3개.

기본 A2A 우선/MCP 보완, x402 자동 제외, 중복 ID 없음도 확인했다. 이번에는 공개 요청을 로컬 요청보다 먼저 측정했다. 위 첫 표본은 이번 점검의 첫 요청이며 운영 프로세스에 그 이전 요청이 없었다거나 모델을 강제 unload한 cold-start 실험이라는 뜻은 아니다. 모델 예열 성공 이후에도 **첫 질의 5~7초 지연은 남아 있다**. 예열만으로 전체 검색 지연이 해결됐다고 판단하지 않는다. 소표본이므로 p95/SLA 또는 모든 질의의 속도를 보장하지 않는다. `rollout-r3/rollout-api.json`, `rollout-r3/natural-search.json`.

배포된 실제 UI를 별도 Chromium 프로필에서 확인해 **5개 검사 통과**, JavaScript pageerror **0건**이었다. 입력 즉시 화면 중앙 로딩, 완료 후 진행 해제, 검색 주소·프로토콜 복원, 캐시 재검증, 모바일 버튼 표시·가로 넘침을 확인했다. GET/HEAD 외 요청은 차단했으며 고객 변경 요청과 에이전트 실행은 0이다. MCP 전용 브라우저 결과 16개와 기본 A2A+MCP 결과 29개는 범위가 다르다. `rollout-r3/rollout-browser.json`, `rollout-r3/screenshots/`.

**이번 통합본의 운영 반영·예열·확인한 검색/로딩 기능은 정상이다. 초기 검색 지연은 성능 한계로 유지한다.** `rollout-r3/summary.json`.
