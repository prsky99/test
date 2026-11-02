# Autonomous Agent Adoption v1.1 — development and acceptance

기준: [수정 설계서](../../docs/AUTONOMOUS_AGENT_ADOPTION_DESIGN.md)의 AE-01~AE-08. 소스 구현과 격리 검증을 완료했다. 이후 사용자가 migration과 4개 서비스 배포를 실행했고, 운영 읽기 점검 **37건 / 실패 0건**으로 반영을 확인했다. 개발 검증에는 실제 계정·수신처·제공자 대신 합성 데이터를 사용했고, 운영 점검에서는 고객 세션 생성·제공자 실행·발송을 하지 않았다.

## 구현 결과

1. **AE-01 계약**: `/mcp/compact`의 `discover`, `describe`, `execute`, `resume`, `report` 다섯 도구를 고정했다. 기존 `/mcp`를 유지한다. `/api/agent/v1/openapi.json`은 앱의 공개 5개 route와 같은 discovery/report DTO에서 생성하며 관리자·고객 관리 경로를 포함하지 않는다. overview GET/HEAD operation ID 중복을 제거했다.
2. **AE-02 효율·제한**: 실제 limiter 판단의 snapshot을 헤더에 반영한다. 공유 계층의 가짜 잔여량을 만들지 않는다. 후보 cache는 비활성화하고 불변 schema만 최대 128개·300초로 cache한다. single-flight는 대기자·시간을 제한한다. 현재 증거는 batch 조회하며, 3개 자원 projection 검사에서 DB query 3회를 확인했다. 전체 검색의 query 수가 3회라는 뜻은 아니다.
3. **AE-03 준비·승인·실행**: `discover(prepare=true)`는 호출 없이 입력을 검증·암호화하고 최대 5분의 준비 결과를 만든다. 실제 고객 세션·동일 출처·CSRF와 별도의 정확한 입력 공유 승인이 있어야 grant를 발급한다. 대상·버전·도구·계약·입력·grant·kill switch를 전송 직전에 다시 확인한다. 초기 실행은 승인된 stateless MCP docs/news 계약에 한정한다. 같은 작업은 한 번만 dispatch하며 불확실한 결과는 `unknown`으로 남긴다. 실행 결과 조회도 현재 고객 세션/철회를 확인한다.
4. **AE-04 변경 ledger·피드**: 원본 변경 transaction의 intent를 기존 worker가 게시한다. publisher transaction의 확정 순번을 cursor로 사용한다. 최신 상태를 별도로 재검증해 과거 사건이 현재 권한을 되살리지 못한다. 빠른 실행 실패→성공 및 건강 실패→복구를 보존하고, 건강·schema·실행 검증·품질·철회를 구분한다. feed는 최대 30일, 서명 cursor는 다음 UTC 정시까지 최대 1시간이다. 동일 시간 구간의 같은 페이지는 안정적이며 현재 증거가 바뀌면 ETag가 달라진다. 시간 경계의 cursor 만료는 정상적인 응답 변경이다.
5. **AE-05 의존성 감시**: 기존에 인증·목적별 동의를 완료한 Task Updates watch에 추가 동의를 받아 자원·선택 버전·선택 계약·event 종류를 바인딩한다. event/watch/수신처 revision을 HMAC으로 묶고 발송 직전 재검증한다. webhook/A2A의 수신 불확실성은 자동 재발송하지 않는다. 브라우저·수신처 인증과 독립 철회, 광고 발송 disabled 경계를 유지한다. 자동 대체 실행이나 자동 workflow 편집 권한을 만들지 않는다.
6. **AE-06 연결·배포 준비**: 얇은 Python client, remote MCP 설정 예시, 공식 Registry 스키마를 통과한 metadata 초안을 제공한다. Python HTTPX와 Node Fetch 두 실제 HTTP 클라이언트가 임시 서버에서 연결·검색·상세·resume를 통과했다. 별도 stdio bridge나 두 번째 SDK는 추가하지 않았다. Claude Desktop/Cursor/ChatGPT 등 상용 host의 설치·심사 통과를 의미하지 않는다. namespace 검증·업로드·등록은 수행하지 않았다.
7. **AE-07 공개 색인**: 현재 증거를 사용하는 영어 category SSR, canonical/description/OG/JSON-LD, gateway 링크와 현재 publication 기반 sitemap 연결을 추가했다. 빈 category는 404다. `llms.txt`와 공개 metadata에 compact/feed 진입점을 반영했다. 임의 upstream·개인정보·원시 입력은 공개하지 않는다. 기존 관측 저널에 최소한의 discovery trace를 기록한다. 실제 유입/검색순위/7일 재방문 효과는 아직 측정하지 않았다.
8. **AE-08 수용**: 신규 동적 API·실제 브라우저·클라이언트·보안·PostgreSQL 전용 schema 검사를 완료했다. 검증된 release를 준비했다. 이후 사용자 배포와 운영 읽기 확인 결과는 아래에 기록했다.

## 검증 증거

- 기존 기능 통합: **593 passed, 1 deselected** — [integration-frozen.log](integration-frozen.log). 별도 임시 cluster를 기동하는 PG 검사는 제외했고 아래 기존 PG18 전용 schema 검사로 검증했다.
- 최종 신규 계약·공격 입력·고객 세션/CSRF·수신처·클라이언트·브라우저: **43 passed** — [adoption-final-acceptance.log](adoption-final-acceptance.log). 위 통합과 39건이 겹치므로 단순 합산하지 않는다. 나머지는 이후 보강한 작은 OpenAPI·client backoff/cancellation과 두 transport/browser 검사다.
- 기존 공개 브라우저: **27 passed** — [browser-final.log](browser-final.log). 신규 browser 1건과 합쳐 브라우저 28건이며 위 수치와 일부 중복된다.
- PostgreSQL **18.6**: 신규+B2A **12개 계약**, 전체 애플리케이션 **95개 계약** 통과 — [postgres-final-acceptance.log](postgres-final-acceptance.log), [postgres-full-retry.log](postgres-full-retry.log). 전용 schema 제거·search_path 보존·운영 데이터 write 0·소스 고정을 확인했다. 두 리허설을 겹쳐 실행했을 때 연결 슬롯 부족이 있었으며 단독 실행으로 해결했다. DB 설정이나 운영 프로세스를 변경하지 않았다.
- 공개 콘텐츠 **288개 / 위반 0** — [content-final.log](content-final.log). embedded HTML과 `extracted_html.txt` 동기화도 검사했다.
- SQL catalog **3,802 statements / 기존 필수 232 tables / 변경 없음** — [catalog-final-check.log](catalog-final-check.log). 추가 6개 테이블은 명시적 migration 대상이며 native startup DDL에 넣지 않았다.
- Bandit **1.8.6**, 신규 production Python **974 LOC**, 발견·파싱 오류 **0** — [bandit.json](bandit.json). 도구는 임시 폴더에만 설치했다. 프로젝트 runtime dependency는 추가하지 않았다.
- Registry 초안: [registry-validation.json](registry-validation.json), [공식 스키마 보관본](registry-server.schema.json). [공식 원본](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json)으로 형식만 검증했다.

### 측정 범위

[최종 클라이언트 로그](adoption-final-acceptance.log)의 동일 합성 fixture에서 기존 tools/list **9,687 bytes**, compact tools/list 본문 **2,428 bytes**를 확인했다. 같은 compact discovery는 최초 **1,715 bytes**, 알려진 schema digest 재사용 시 **710 bytes**였다. warm HTTP 5회는 약 **6.6~6.8ms**였고 추가 provider 호출은 0이었다. 결과 크기는 JSON 직렬화 기준이며 tokenizer를 임의 환산하지 않았다. 작은 로컬 fixture 결과이므로 운영 p95·SLA·토큰 비용·검색 품질 개선율로 일반화하지 않는다.

검색 payload 내부는 7,800 bytes로 제한하여 JSON-RPC envelope까지 8KiB에 여유를 둔다. 큰 schema는 deferred하며 별도 상세 조회는 32KiB 안으로 제한한다. 원시 실행 산출물 보관은 64KiB로 제한한다. schema 비교만으로 전체 처리 비용이 20% 감소했다고 주장하지 않는다.

## 보안 확인과 실제 한계

방문 세션과 고객 실행 권한을 분리했다. token은 헤더·POST body로만 전달하고 grant 원문은 DB에 저장하지 않는다. 암호문과 grant의 고정 필드를 변조하거나, 다른 owner·로그아웃/철회·만료·schema 변경·정책 중지를 적용하면 provider 전송을 차단한다. 같은 키의 동시 요청과 응답 유실 뒤 반복 요청도 추가 호출하지 않았다. 출력 escaping, CSP, gateway projection, 광고 동의 분리, 검증된 수신처·HMAC·수신 불확실성 장벽을 검사했다.

준비 입력과 성공/실패/취소 산출물 본문은 worker의 증분 정리로 24시간 이후 제거한다. idempotency·미확정/unknown 메타데이터는 일반 GC로 지우지 않는다. schema cache가 현재 증거/권한을 대신하지 않는다. 사용자별 PostgreSQL listener, 새로운 영속 SQLite DB, 신규 생성 모델, speculative provider 호출을 추가하지 않았다.

실제 Edge/Origin 코드는 기존 machine gateway와 로컬 owned dispatch를 재사용한다. 기존 Edge machine/direct-result 회귀도 통합에 포함했다. 신규 compact MCP의 운영망 전체 구간별 전송량이나 Origin 경유 0을 입증한 검사는 아니며 `delivery_backend`만으로 그런 주장을 하지 않는다. 상용 MCP host, 외부 Registry 게시, 운영 부하·HA·DR, 실제 고객 알림은 별도 검증/운영 절차다. 동기 Python client 취소는 요청 사이에서 확인하며 이미 진행 중인 HTTP 요청은 최대 timeout까지 기다릴 수 있다.

## 운영 반영

검증 package: **`agent-adoption-20261025-r1`**. [release.json](release.json), [소스 SHA-256](source-sha256.json), [직접 사용 component 목록](component-inventory.json)을 보존한다. component 목록은 전체 SBOM이나 dependency 취약점 진단을 대신하지 않는다. 재게시하지 않았고 장기 서비스·브라우저·로그인을 자동 설치하지 않는다.

사용자 터미널에서 프로젝트 루트 기준으로 실행한다. 명시 migration은 먼저 적용하고 4개 서비스를 같은 package로 배포한다. 이미 package를 생성했으므로 다시 package 명령을 실행할 필요가 없다.

```bash
.venv/bin/python -m scripts.migrate_agent_adoption --run
./agentcon deploy frontend agent-adoption-20261025-r1
./agentcon deploy admin agent-adoption-20261025-r1
./agentcon worker-deploy jobs agent-adoption-20261025-r1
./agentcon worker-deploy execution agent-adoption-20261025-r1
```

마이그레이션은 설정된 PostgreSQL backend에 6개 테이블/인덱스/버전 marker를 더하며 기존 운영 row를 수정하지 않는다. 이전 프로세스는 migration marker를 cache할 수 있으므로 migration 이후 새 프로세스로 반영한다. 운영 권한이 승인한 고객 세션 없이 실행 grant를 만들어 넣지 않는다. 공개 Workspace 링크와 광고 발송 상태도 바꾸지 않는다.

반영 후 `/api/agent/v1/openapi.json`, `/mcp/compact` initialize/tools/list/discover, `/api/feed/verified.json`의 상태·ETag를 읽기 전용으로 확인한다. 새 피드는 feature 활성 이후 증거 변경부터 채워지므로 첫 응답이 비어 있을 수 있다. 서버 ready와 provider 성공은 서로 다른 검사다. 아래 기록은 사용자 migration/배포 이후의 운영 읽기 스모크 결과다.

## 운영 반영 확인 — 사용자 실행 이후

사용자가 안내 명령을 실행한 뒤 읽기 전용으로 확인했다. [live-smoke.json](live-smoke.json), [live-smoke.log](live-smoke.log), [검증 스크립트](verify_live_readonly.py)에 증거를 보존했다. **37 pass / 0 fail**이다.

- frontend/admin/jobs/execution 모두 `agent-adoption-20261025-r1`; 두 웹 서비스 ready와 불변 package hash 정상.
- PostgreSQL read-only 연결에서 migration marker와 추가 6개 테이블을 확인했다. jobs/execution heartbeat도 현재 상태다.
- 로컬 proxy와 공개 HTTPS 양쪽에서 작은 OpenAPI 200·조건부 304, 검증 피드 200·조건부 304, 고정 MCP 도구 5개를 확인했다. 피드는 당시 각각 1개 사건을 반환했다.
- 고객/방문 세션 없이 실행 상태를 요청하면 401이며, 공개 proxy의 내부 probe는 404다. frontend와 admin 진입 화면은 200, frontend CSP와 전체 OpenAPI operation ID 유일성도 확인했다.
- 점검 중 서버·DB 설정 변경, 고객 세션 생성, 제공자 실행, 알림 발송을 하지 않았다. 소스/격리 인수와 운영 배포 확인을 완료한 상태다. 실제 고객 실행·외부 host 인증·Registry 게시·부하/HA/DR를 추가 완료했다고 주장하지 않는다.
