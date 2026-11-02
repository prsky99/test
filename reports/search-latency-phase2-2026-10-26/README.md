# Explore 검색 지연 2차 개선

2026-10-26. 요청 범위는 논문·SNS 조사에 근거한 추가 검색 최적화와 기능·보안 검증이다. 1차 릴리스 `explore-search-speed-20261026-r1`을 기준으로 비교한다. 운영 서비스 배포·재시작·DB 설정 변경은 하지 않았다.

## 조사와 실측

- [Materialization Strategies in a Column-Oriented DBMS, ICDE 2007](https://www.cs.umd.edu/~abadi/papers/abadiicde2007.pdf): 넓은 본문을 필요한 시점에 읽는 원리를 참고했다. PostgreSQL을 컬럼 저장소로 바꾸거나 index-only scan을 구현했다는 뜻은 아니다.
- [Scaling Memcache at Facebook, NSDI 2013](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf), [저자의 설명](https://engineering.fb.com/2013/04/15/core-infra/scaling-memcache-at-facebook/): DB의 현재 사실과 캐시의 재사용 범위를 분리했다. 검색 결과나 실행 권한을 그대로 캐시하는 방식은 채택하지 않았다.
- [pgvector 공식 문서](https://github.com/pgvector/pgvector): 필터와 ANN 검색 경계를 검토했다. 이번에는 후보 창·HNSW 검색 정확도·인덱스·스캔 한도를 낮추지 않았다.
- [Reddit의 임베딩 지연 논의](https://www.reddit.com/r/Rag/comments/1t3f72i/embedding_latency_killing_my_rag_speed_any_fixes/), [하이브리드 검색 구현 논의](https://www.reddit.com/r/Rag/comments/1wvmja5/i_built_a_document_rag_chatbot_with_hybrid_search/): 최초/반복 요청, 원문과 보정 질의, 데이터 변경 시 캐시 무효화를 조사 방향으로 참고했다. 게시자의 수치나 주장을 이 서비스의 성능 근거로 사용하지 않았다.

현재 세대 관측 9건에서 전체 p50 3,387ms/p95 6,235ms였다. 단계별 p95는 임베딩 25ms, ANN 1,065.5ms, 전체 명세 투영 815.6ms였다. 단계별 p95를 합산한 값은 전체 p95가 아니다. 실제 병목이 아닌 임베딩을 추측으로 비동기화하거나 실패 시 검색을 생략하지 않았다. `operating-diagnosis.json`.

날씨 MCP 후보 300건은 compact/full/hash 원문 합계 약 29.35MB, full 원문만 약 17.26MB였다. 이전 512KiB 파싱 캐시의 개별 한도를 넘는 명세도 있었다. ANN의 출처 검증에는 11개 필드만 필요하지만 전체 행을 가져오던 비용도 확인했다.

## 구현

1. `application_store_vector.py`: ANN 출처 검증에 필요한 정확한 11개 원본 필드만 읽는다. 모델·세대·상태·벡터 원문 해시·출처 검증은 유지한다. 전체 행 기준 바이트 예산과 후보 순서도 유지한다.
2. `application_store_resource_batches.py`: 읽기 전용 repeatable-read 트랜잭션에서 DB가 계산한 현재 compact/full 원문 SHA-256으로 캐시를 확인한다. 적중한 본문은 재전송하지 않고 현재 메타데이터와 결합한다. 제공자가 주장한 hash만으로 재사용하지 않는다. 캐시가 비었거나 적중률이 낮은 배치는 전체 행을 한 번에 읽어 최초 요청의 중복 전송을 피한다. 원문을 자르거나 바이트 한도를 늘리지 않는다.
3. `discovery_contracts.py`: 동일한 명세의 파싱 결과를 프로세스 안에서 재사용한다. 원문과 파싱 결과의 공유 캐시는 1,536개/직렬화·UTF-8 본문 합계 64MiB로 제한하고, 요청 내 캐시는 768개/32MiB다. 파싱 항목당 2MiB, 원문 항목당 4MiB를 넘으면 기존 경로를 쓴다. 이 한도는 Python 객체·키·참조 오버헤드를 포함한 RSS 상한이 아니다. 반환 객체는 다시 복원하여 호출자 변경으로 공유 캐시가 오염되지 않는다.
4. 순수한 작업 적합성 판정은 정확히 같은 질의·terms/core·모든 현재 자원 필드에 대해서만 최대 30초 재사용한다. 키는 프로세스별 임의 HMAC, 값은 boolean이며 입력 원문·고객 식별자·응답을 저장하지 않는다. 유효기간이 지난 사실은 사용하지 않으며 키는 조회/교체 시 정리된다. 최대 4,096개로 제한한다. 30초에 모든 메모리가 자동 물리 삭제된다는 뜻은 아니다. 현재 활성·권한·실행 증거는 별도로 계속 확인한다.
5. `hybrid_explore.py`: 검색어 없는 탐색에서 기존 다양성·중복 처리 후 필요한 카드만 읽는다. 검증 필터는 뒤쪽 후보를 잃지 않도록 기존 전체 후보를 확인한다. A2A로 채운 수만큼 MCP의 불필요한 카드 투영을 줄이되 두 범위의 합계는 계속 계산한다. 기본 x402 제외를 유지한다.
6. `selection.py`: 동일 도구 설명 중복 횟수를 이중 순회 대신 Counter로 계산한다. 판정 기준은 동일하다.

7. 최종 브라우저 검사에서 현재 화면 원본의 검색 중앙 로딩이 빠져 있음을 발견했다. 버튼·필터·입력 debounce·취소·동시 상세 조회 각각의 진행 토큰을 복구하고, HTML 원본 두 파일과 발행 자산을 다시 동기화했다. 다른 화면 변경은 보존했다. 이 수정 전 9건의 로딩 회귀 실패는 `pre-loader-repair-release-integration-final.log`에 남겼으며 최종 통과로 계산하지 않는다.

## 실제 전체 검색 경로 비교

`compare_native.py`는 같은 PostgreSQL exported read-only snapshot을 이전 불변 릴리스와 개선 코드에 제공한다. **실제 설정된 로컬 임베딩과 ANN을 포함**하며 운영 애플리케이션 쓰기와 외부 에이전트 실행은 0이다. 보안/세션 scaffold는 별도 메모리 DB이고 HTTP는 in-process이므로 Cloudflare/인터넷 시간은 포함하지 않는다.

`native-comparison.json`에서 내부 6개 + API 8개 조건의 결과 ID·순서·개수는 모두 일치했다.

- 날씨 최초 API 표본: **3.111 → 1.313초**, 반복 **2.806 → 1.364초**.
- 번역 최초 API 표본: **5.826 → 5.156초**, 반복 **2.345 → 0.944초**.
- 검색어 없는 탐색 최초 표본: **0.902 → 0.396초**, 반복 **0.621 → 0.411초**.
- 뉴스 최초 API 표본: **4.086 → 3.317초**, 반복 **2.040 → 1.049초**.

이 표본에서 반복 API는 약 34~60% 단축됐다. 일부 내부 A2A 경로는 3~12% 느리게 측정됐다. 최초 번역은 여전히 약 5초다. 전체 DB/OS/모델 캐시를 비우거나 무부하를 보장한 시험이 아니며, 순차 실행·소표본·호스트 부하 영향을 받는다. 운영 SLA/p95나 모든 질의의 개선을 보장하지 않는다. 이전 실험은 별도 JSON으로 보존하고 최종 수치와 혼합하지 않았다.

## 검증 진행 기록

- 전용 PostgreSQL 18 스키마 **18개 계약 통과**: 프로토콜·관련성·페이지·중복 외에 캐시 적중 후 kill switch·실패 증거·비활성화·위조 full hash·원문 변경·현재 메타데이터 갱신·전체 행 바이트 제한을 확인했다. 스키마는 삭제했다. `native-freshness.json`.
- SQLite 벡터 출처 회귀에서 테스트 의존성 누락이 발견되어 운영 환경 대신 `/private/tmp`의 격리 테스트 경로에 sqlite-vec를 설치했다. 해당 오류를 제품 통과로 처리하지 않았다.
- 별도 PostgreSQL 클러스터 초기화가 이 환경에서 실패하여 대용량 명세 테스트에 명시적인 owned-schema 실행 옵션을 추가했다. 같은 바이트·행·인자 검사를 수행하고 원래 private-cluster 경로도 보존한다. owned-schema에서는 운영 GIN/HNSW를 설치하지 않고 실제 PG 행 + 격리 FTS 경로를 검사한다. 운영 인덱스 경로는 위 읽기 전용 실측에 포함된다. `large-contract-final.log`.
- 전체 통합 검증은 불변 릴리스 `explore-search-speed-20261026-r3`의 별도 복사본에서 수행했다. 최종 r4는 이 코드·화면을 그대로 보존하고 SQL 원본 해시 메타데이터만 동기화했다. 다른 세션의 계속되는 작업 디렉터리 변경 때문에 검사를 반복하지 않도록 코드·화면·테스트를 고정한다. 최종 결과는 아래와 같다.

## 운영 반영

최종 검증을 완료했다. frontend만 교체하면 된다. 관리자·워커·DB 마이그레이션은 필요하지 않다.

```bash
./agentcon deploy frontend explore-search-speed-20261026-r4
```

패키지 준비 시점에는 배포하지 않았다. 이후 사용자 배포 확인 결과는 아래에 기록했다.


## 최종 검증 및 패키지 확정

- 전체 영향 회귀 **748 passed / 실패 0 / skip 0**. 검색 중앙 로딩·중복 진행·취소·캐시 재검증·필터·페이지 이동·공개 CSP/XSS·실행 권한·벡터 출처 검사를 포함한다. `release-integration-final.log`, `release-integration-final.xml`, `test-inventory.json`.
- 최종 패키지의 PostgreSQL 전용 스키마 계약 **18개 통과**, 스키마 삭제 확인. `final-native-freshness.json`.
- 공개 콘텐츠 **300개 파일/위반 0**, 발행 JavaScript 구문 검사 통과. HTML 원본 동기화와 발행 manifest의 source hash도 확인했다. `final-content.log`, `release-javascript-final.log`.
- Bandit **High 0 / Medium 8 / Low 0**, 구문 분석 오류 0. 8개는 모두 낮은 신뢰도 B608이며 기존 검색 SQL과 이번 좁은 읽기의 고정 SQL 조합이다. 식별자·WHERE는 저장소 소유 상수/검토된 메타데이터에서만 오고, 질의·카테고리·ID 등 값은 바인딩한다. 관련 인자 주입 회귀도 통과했다. 이 경고를 숨기거나 저장소 전체 취약점 0으로 해석하지 않는다. 정적 스캔 종료 코드 1과 원본 경고는 `release-bandit.json`에 보존했다.
- 마지막 로딩 UI 수정 후 SQL 카탈로그의 `source_manifest`만 달라졌다. **SQL 3,801문/232테이블, unique SQL 추가·삭제 0, 스키마와 런타임 필드 동일**임을 확인하고 원본 해시 메타데이터를 동기화했다. 운영 DB 마이그레이션이 아니다. `catalog-equivalence.json`, `final-sql-catalog.log`.
- r3의 이미 통과한 코드·화면을 바꾸지 않고 위 메타데이터만 동기화한 최종 **`explore-search-speed-20261026-r4`**를 만들었다. r3/r4의 전체 manifest 비교에서 차이는 `agent_market/application_store_sql.json` 한 파일뿐이고, 그 JSON에서도 차이는 `source_manifest`뿐이다. 그 후 카탈로그 소비 경로 **39건**과 위 PostgreSQL 18개 계약을 재확인했다. 39건은 748건의 부분집합으로 중복 합산하지 않는다. `final-catalog-consumers.log`, `final-package.json`.
- 최종 릴리스 manifest **1,293개 파일 검증**, 검증 복사본의 코드·화면 **1,278개가 manifest 해시와 일치**. 실제 측정한 검색 핵심 파일과 최종 릴리스의 코드도 동일하다. 운영 서버·관리자·워커는 교체하지 않았다.

현재 개발 범위의 수정과 검증은 완료했다. 최초 번역 지연, 인터넷/Edge 추가 시간, 부하에 따른 변동은 남은 성능 한계이며 장애나 통과하지 않은 검사로 숨기지 않는다. 최종 배포 대상은 r4 하나이며 r2/r3는 중간 검증 자료다.


## 사용자 배포 후 실제 운영 확인 — 2026-10-27

사용자의 실행 완료 통보 후 frontend 활성 A 슬롯이 `explore-search-speed-20261026-r4`인 것을 확인했다. 비공개 준비 상태 조회 성공, 불변 릴리스 manifest 유효, 로컬/공개 도메인의 `operating.js`가 릴리스와 일치했다. 공개 자산 Cloudflare 상태는 BYPASS였다. 서버 수명주기 명령은 실행하지 않았다.

`limit=45`, 기본 A2A+MCP로 날씨·번역을 로컬/공개 각 2회 조회한 **8회 모두 HTTP 200**이었다. 기본 x402 제외, A2A 우선, 중복 ID 없음도 확인했다. `rollout-api.json`.

- 실제 공개 날씨: **3.721초 / 2.255초**.
- 실제 공개 번역: **2.318초 / 2.181초**.
- 로컬 날씨: **2.964초 / 2.026초**.
- 로컬 번역: **7.408초 / 1.129초**. 첫 번역 표본의 지연은 여전히 크며 해결됐다고 판단하지 않는다.

공개 요청은 로컬 요청 뒤에 실행했으므로 이미 데워진 서버 캐시의 이점을 포함한다. 이 수치로 신규 프로세스의 첫 요청, 모든 질의, p95 또는 SLA를 보장하지 않는다. 수집·호스트 부하도 통제하지 않았다. 앞선 동일 스냅샷 in-process 비교와 이번 인터넷 요청을 같은 조건으로 혼합하지 않는다.

실제 배포 UI를 별도 Chromium 프로필로 열고 GET/HEAD만 허용하여 **5개 확인 통과**: 오타 제안/선택한 프로토콜 복원, 입력 즉시 중앙 로딩, 완료 시 진행 토큰 해제/주소 유지, 새로고침/캐시 재검증, 모바일 프로토콜 글자·가로 넘침. JavaScript pageerror **0건**, 고객 변경 요청 **0건**, TLS 검증 비활성화 없음. 브라우저의 MCP 전용 날씨 19개와 API 기본 A2A+MCP 날씨 33개는 범위가 다르다. `rollout-browser.json`, `screenshots/deployed-progress.png`, `screenshots/deployed-mobile.png`.

배포와 확인한 검색·로딩 기능에서 새 오류는 발견하지 않았다. 초기 번역 지연은 성능 한계로 유지한다. `rollout-summary.json`.
