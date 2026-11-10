# 작업 기록 (짧게 유지: 끝날 때마다 몇 줄 갱신)
- 11-04: 디스크 점검(여유 150GB, 릴리스 461개 142GB). `agentcon prune-releases` 추가, 383개 삭제, 여유 149.5→191.7GB. 배포·워커 배포 성공 뒤 자동 정리(배포된 것과 6시간 미만 미배포만 남김, `--no-prune`).

## 완료 (최근 것만)
- 추천 품질 결함(2026-11-10 저녁, 검색과 RAG, PM 실사용 점검): ① 게이트웨이 tools/list가 빈 MCP(활성 40,275 중 17,253: 조사 안 됨 14,208, 조사됐으나 안전·스키마 검사로 전부 걸러짐 3,045)를 추천 뒤로 보냄(concierge/gateway_exposure.py가 front.rec를 감쌈, 게이트웨이와 같은 tools_for+safe_registered_tool, 10분 캐시. selection.py·execution_policy.py는 탐색 문서 정책 해시라 손대지 않음). ② "PDF to text" 1~3순위는 모두 PDF 변환 도구였고 1순위 문제는 노출 0개. ③ chatLabel이 가격어를 낱말 단위로 지워 문장이 깨짐(활성 설명 9,903건) → 여러 문장이면 가격어 문장을 통째로 뺌(5,571건 해결, 한 문장 3,701·전부 가격어 631은 남음). ④ 첫 연결 7.3초는 한국→Cloudflare LAX 거점(우리 서버 안 거치는 /cdn-cgi/trace도 첫 바이트 중앙값 1.92초, cloudflare.com ICN은 0.02초), 게이트웨이 initialize는 로컬 0.03초.
- jobs 쿼리 후속(2026-11-10 16시, 검색과 RAG): 운영 PG는 조사 대상 조회를 gateway/store.py가 아니라 application_store_collector.py(등록 SQL을 거치지 않는 직접 SQL)로 실행한다. 1d6bac1c 배포 뒤에도 옛 조회문이 75초에 8회 계속 돌아 찾음. 같은 좁은 정렬을 이 구현에 적용(고른 id는 200개씩 IN으로 읽어 순서 유지). 벡터 정리 쉬기는 배포 뒤 90초 동안 정리 조회 0회로 작동 확인.
- jobs 5초 초과 쿼리 2건(2026-11-10 16시, 검색과 RAG, 운영·SRE가 넘김, e444d30c 뒤 근본 해결): ① A2A 조사 대상 조회는 넓은 행(106k×2.7KB)을 통째로 정렬해 디스크 약 180MB를 쓰고 결과는 2행 → 좁은 열(id, cap_checked_at, host)로 순위만 매기고 고른 행만 등록된 `SELECT * FROM resources WHERE id=?`로 읽음(운영 읽기 전용 601→310ms, 디스크 정렬 0). 새 SQL은 application_store_sql.json에 한 항목 추가(store.due_for_capability.narrow, 목록 재생성 없음). ② 벡터 정리 조회는 171,391회·평균 237ms·누적 약 40,600초(대부분 지울 것 없음) → 찾은 게 없으면 store별 300초 쉼. 시험 tests/test_jobs_query_load.py(실제 PG 포함), 관련 88 통과.
- 성장·유통 캐시 예외 효과 측정(11-10 13:5x, 재부팅 뒤 부하 5): 공개 경로 첫 방문 1.0~2.6초(변경 전 05시 부하 9에서 0.58~0.89초), 같은 연결 재요청 0.5~1.8초. HTML은 Cloudflare가 캐시하지 않고(DYNAMIC) If-None-Match 304도 HTML에는 전달되지 않음(JSON은 304). 효과는 5분 안 재방문 때 브라우저가 네트워크 없이 보여 주는 것에 한정. 첫 방문이 느려진 원인은 미확인(재부팅 직후 측정) → 다음 측정에서 Server-Timing으로 구간 분리 필요.
- 재개 뒤 작업(2026-11-10 12:2x~13:5x, 운영·SRE)
  - 재부팅 뒤 정상 확인: cloudflared·OpenSearch(green)·Ollama·맥미니 SMB. 12:56 재측정은 탐색 중앙값 1.3초, Chat 2.9초.
  - 03:30 전체 복원 연습, 11-11 07:30 과업 스냅샷 확인을 다시 예약했다.
  - 보안·감사 기록 기존 행 정리(사용자 승인)
    - 준비: 두 표 백업(gateway-data/backups/privacy-scrub-20261110), SQL·사용자 실행 스크립트(e4ddbdba), 사본 리허설 passed
    - 운영 실행은 자동 모드 권한 검사가 거부했다. 사용자 실행 대기다.
  - agentcon_config.py: admin만 예전 파일이라 config-admin-20261110-r1로 배포했다. 네 역할 모두 HEAD와 같다.
  - 90일 보존 정리는 등록 SQL 파일 충돌로 보류했다(지금 대상 0행).
  - AD Coin 데몬 설치는 그 팀의 배포 대기 등록을 기다린다.
  - 재부팅으로 scratchpad가 비워져 패키징·커밋 보조 스크립트를 다시 만들었다.
- 성장·유통 7차(2026-11-10 오전~13시)
  - 공개 성장 페이지 캐시 예외(PM 승인): 로그인 없는 GET이고 자격 증명이 없으면(분석 쿠키 제외) `public, max-age=300, stale-while-revalidate=600`, Vary: Accept, 약한 ETag(304). 나머지는 no-store. 서버 처리 3~30ms, 공개 경로 첫 방문 0.6초·재방문은 브라우저 캐시.
  - 주간 근거 보고서 /reports/weekly(첫 호 2026-W45, 실행 점검 876 = MCP 822·A2A 54, x402는 시험 호출 기준). jobs가 매주 월요일 발행(W46은 11-16).
  - 피드백 /api/feedback: 에이전트·답·시각만, 등록된 INSERT 재사용, 메모리 제한(시간당 20·에이전트당 하루 1·에이전트당 하루 300). 탐색 카드 버튼·에이전트 페이지 폼·과업 카드 링크, MCP report도 같은 제한(시간당 120). jobs가 매일 feedback-stats.json.
  - 개인정보 미수집(사용자 결정): 문의 양식 제거(410), 검토 요청은 메일, 이름·UA 미저장, 지문은 하루 단위 무작위 키 해시, 처리방침 33쪽 수정. 기존 행 정리 SQL·리허설 passed(문의 8·방문자 2,167·방문 1,543·컨텍스트 112) → 승인 대기(현황판). reports/개인정보 미수집 전환 2026-11-10.md
  - 배포: frontend growth-batch-frontend-r5(→ r8), jobs growth-batch-jobs-r1. 커밋 733bcead, 08226e3f, 856c42d1, 4206041b.
  - 실수 기록: "Cloudflare br 캐시가 옛 파일" 판단은 틀림. 이 맥 curl에 brotli가 없어 압축 바이트를 검색했던 것. 페이지는 pearl_view가 내용 해시로 자원 주소를 바꿔 이미 새 파일을 씀(내장 브라우저로 버튼 90개 확인). r8의 ?v= 추가는 불필요했지만 해는 없음. br 확인은 브라우저로 할 것.
- 탐색 3초 측정(2026-11-10 12:58, 검색과 RAG): 처음 보는 검색어 20개(필터·쪽 넘기기 섞음), 연결 재사용, 배포 1분 뒤, 부하 4.5~5.4. 서버 시간 = 전체 시간(Server-Timing explore). 중앙값 1.14초·p95 1.82초·최대 1.94초, 3초 초과 0. 가장 느린 것은 결과 0건 검색어(lithuanian invoice parser 1.94초, recipe scaling grams+필터 1.82초). 20개 중 9개가 0건(earthquake early warning feed·volcanic ash advisory 등): 속도 문제는 아니고 카탈로그 범위.
- 테스트넷 가격 표시(2026-11-10 13시, 검색과 RAG, PM 채택): Base Sepolia에서만 받는 x402 427개가 실제 가격처럼 보였다. 테스트넷 결제 조건은 가격으로 보지 않고(crawler.TEST_NETWORKS, 수집·견적 모두), 견적 유지 규칙은 등록 가격도 양수일 때만 적용 → 저장된 테스트넷 가격은 다음 수집 때 NULL(손 수정 없음). 상세 API에 price_note "testnet_only" 추가, 상세·칩에 "Testnet only". 탐색 결과는 문서에 네트워크가 없어 "Price on request". 시험 164 통과.
- 묶음 배포(2026-11-10 10:52~10:55, 운영·SRE, 현황판 잠금)
  - execution: rebuild-execution-20261110-r1. privacy-frontend-r1과 같은 내용이고, 기준 버전은 docs-execution-20261031-r2로 기록했다.
    - 10-31 이후의 수정(잠금 재시도, typed 엔진, 새 config)이 처음 들어갔다.
    - 게이트: 기본 목록에 execution 시험 3개를 더해 passed
  - jobs: erc-timeout-jobs-20261110-r1(backfill-quote-jobs-r3 위, 1b73a2e3)
  - frontend: privacy-frontend-20261110-r1(quote-keep-frontend-r1 위)
  - admin: privacy-admin-20261110-r1(ua-contact-admin-r2 위). frontend·admin 모두 bf365263(IP /24·/48, UA 계열화) 반영
  - 배포 뒤 확인
    - 공개 /·/llms.txt·탐색·카테고리 200(해외 경유 1.3~2.6초), admin 200
    - 네 역할 모두 새 오류 0(기존 rag index 제외), DB 연결 16
    - execution에 AD Coin 로그 0
    - 새 칸 데우기 첫 검색 1.7초
  - 남은 일: 90일 보존 삭제는 등록 SQL 파일 충돌로 보류, 기존 행 정리는 사용자 승인 대기, 03:30 전체 복원 연습 예약됨
- jobs 오류·가격 핑퐁·큐 대조(2026-11-10 07시, 검색과 RAG, 총괄 PM 과제)
  - `rag index loop error` 4,073건: ensure_jobs 백필 쿼리가 카탈로그 전체(289k)를 한 번에 훑어 6.8~11초 → jobs 5초 statement_timeout. 실패하면 BACKFILL_PAUSE를 정하기 전에 예외가 나가 10초마다 반복. 쉬는 시각을 먼저 정하고(실패해도 300초), 자원 번호 2만 개 구간씩 훑음(운영 읽기 전용 0.4~2.5초, 부하 15). 작업본의 출처 모름 미커밋 변경(database_error 삼킴)은 쓰지 않고 그대로 둠.
  - x402 가격 핑퐁: 등록 금액과 402 견적이 번갈아 저장돼 309개가 하루 1.48번 재색인(나머지 0.19번). 등록 항목(details)이 그대로면 양수 견적 가격·받는 주소 유지, 0·NULL이면 등록 가격(32172는 $0.06으로 돌아옴). 가격 집계는 COLLECTOR.md.
  - 탐색 문서 큐 대조: 5초마다 세대 309k행 전체 대조(평균 266ms, 147k회, 누적 39,252초, DB 시간 상위). 빈 대조 뒤 12회차(60초) 쉼, 들어온 게 있으면 계속.
  - 시험: test_embedding_churn 10, test_postgres_backfill_pause 4, test_explore_documents_postgres 새 1. 바뀐 부분 묶음 171 통과. 전체 pytest는 메모리 압박(스왑 83%)으로 88분 넘게 걸려 PM 지시로 중지.
  - 후속: 테스트넷(Base Sepolia) 전용 x402 427개가 실제 가격처럼 보임(PM 채택, 다음 과제). 탐색 3초 측정 스크립트 준비(scratchpad).
- restart·배포 직후 탐색 지연(2026-11-10 07시, 운영·SRE, PM 요청)
  - restart: 작업본(미커밋 포함)을 패키징하던 것을, 운영 중인 버전을 반대 칸에 다시 띄우도록 바꿨다(1d59f8f9, DEPLOY.md 경고 추가).
  - 배포 직후 탐색 10.7초와 OpenSearch 시간 초과(오늘 11회)
    - 원인: 메모리 압박이다. 남은 메모리 18MB, 스왑 85%이고, OpenSearch 상주 메모리가 74MB라 힙 대부분이 스왑에 나가 있다. 새 칸은 캐시도 비어 있다.
    - 수정: frontend 배포가 트래픽을 넘기기 전에 탐색 4개로 새 칸을 데운다(b15a549a). 대기 칸 실측은 196/113/3,283/277ms였다.
    - admin 이전 칸(writer-retry-admin-r1)은 승인된 30분 정책대로 멈췄다.
    - 현재 표본: 탐색 중앙값 1.7초, 최대 2.75초. Chat은 4.1~4.6초.
  - Antigravity 일반 종료(PM 사전 알림 뒤)는 자동 모드 권한 검사가 거부해 하지 않았다. 사용자 결정 사항이다.
  - 제안(승인 필요): OpenSearch 힙을 768m에서 512m로 줄이기(색인 160MB, 힙 사용 24%). OpenSearch 재시작이 필요하며, 그동안 탐색은 PG로 대체된다.
  - execution과 AD Coin v2: v2 라우터·풀은 create_front_app(frontend)에서만 켜진다. execution은 gateway 앱만 만들어 영향이 없다(배포 뒤 확인 예정).
- 운영 DB 구조 변경 절차·리허설 도구(2026-11-10 06:5x, 운영·SRE, 사용자 지시 "운영 DB 변경 절차 진행해줘")
  - 커밋 4c371fb5, 시험 3개
  - `scripts/db_change_rehearsal.py run`
    - 최신 일일 백업을 사설 PG에 복원한다. 스키마는 전부, 데이터는 큰 표 16개만 빼고(약 170MB) 넣고, 사본의 신원 게이트 스키마를 지운다.
    - 운영 중인 frontend·jobs 버전의 코드로 변경 전과 후에 앱 연결(불변 검사)·쓰기 트랜잭션·탐색을 검사한다. 운영 DB 표시가 들어간 명령은 거부한다.
    - `check`는 24시간 안에 지금 운영 중인 버전으로 통과한 같은 변경만 허용한다.
  - 실측: 표 주석은 passed(14.7초). 05:38과 같은 종류(public 표 + 트리거)는 application_refuses_changed_database(schema_invariants_mismatch, 11.3초)로 장애를 그대로 재현했다.
  - 문서: deploy/DATABASE_OPERATIONS.md "운영 DB 구조 변경" 절. CLAUDE.md 한 줄 초안은 PM에 보냈다.
  - 그 사이 처리: erc8004 resolve 시간 초과는 경고로 남기고 5분 대기(1b73a2e3), jobs 배포는 10시 묶음에 넣는다.
- 배포 도구: 환경 공유·이전 칸 회수(2026-11-10 06:2x, 운영·SRE, PM 승인)
  - 커밋 779e23c7, 시험 tests/test_service_deploy_shared_env.py 7개, 배포 도구 시험 43 passed
  - .venv 공유: `package`가 의존성 키(pyvenv.cfg + dist-info 목록 + runtime lock + runtime-versions)별로 services/venvs/<키>를 한 번만 만들고, 릴리스 .venv는 그 폴더에 링크한다.
    - 키 폴더는 바꾸지 않으므로 이전·되돌릴 버전이 안전하다. 쓰지 않는 키 폴더는 릴리스 정리 때 함께 지운다.
    - 확인: venv-share-frontend-20261110-r1 게이트 passed. 성장 팀 growth-md-frontend-20261110-r7이 작업본의 새 도구로 06:11에 먼저 패키징됐는데, 같은 키·같은 패키지로 import가 정상이었다.
  - 이전 칸 회수: frontend·admin 배포 30분 뒤 분리 프로세스가 `reclaim-standby`로 이전 칸을 멈춘다(state 기록은 유지).
    - 30분 뒤 되돌리기는 다시 띄우므로 수십 초가 걸린다(DEPLOY.md에 적음).
    - 11-10 이전 배포의 이전 칸(retained_at 없음)은 건드리지 않는다.
  - 사용자 보고 용어는 "판"이 아니라 "버전"으로 쓴다(사용자 지시, 기억 say-version-not-pan).
- 운영 맥 하드웨어 점검(2026-11-10 06시, 운영·SRE, 사용자 지시 "메모리와 디스크 등 하드웨어도 항상 체크")
  - 보고서: `reports/운영 맥 메모리·부하·디스크 2026-11-10.md`(1202b81d)
  - 측정: 부하 11~19, CPU idle 44%, RAM 16GB 중 압축 6.5GB·남음 0.2GB, 스왑 80%. 부하의 상당 부분이 스왑 대기다.
  - 원인
    - 메모리: PG shared_buffers 2GB, Antigravity IDE 3.5GB(사용자 앱), OpenSearch 1GB, 이전 frontend 대기 슬롯 1.5GB, Claude 세션들 1.7GB
    - CPU: syspolicyd 84%. 오늘 판 28개가 저마다 .venv를 복제해, 처음 실행 때마다 macOS가 검사한다.
  - 우리 시험은 측정 시점에 모두 nice(10·15)로 돌고 있었다.
  - 릴리스는 배포 때 자동 정리(배포된 판과 6시간 안에 만든 판만)되므로 추가 정리가 필요 없다. 백업은 7개 순환(24GB)이다.
  - 디스크: 홈 647GB 중 운영 데이터는 69GB다. 큰 것은 ~/Library 179GB, ~/.cache 108GB, ComfyUI 94GB, Downloads 50GB(정리는 사용자 결정). 경보 기준 제안은 여유 100GB 미만 주의, 50GB 미만 장애다.
  - 제안: 배포 묶기와 배포 전 pytest 확인, 판끼리 .venv 공유(배포 도구 변경), 이전 슬롯을 배포 30분 뒤 멈추기(PM 결정), IDE 닫기(사용자 결정). DB 메모리 설정은 재시작이 필요해 승인 대상이다.
- 성장·유통 6차(2026-11-10 07시, PM 후속)
  - Markdown 응답 첫 줄의 분류 글자("Connect" 등) 제거: 모든 Markdown 경로가 본문 H1부터 시작(10개 경로 확인).
  - Claude Code 플러그인 자체 사이트 공개(PM 승인): /claude-plugins/marketplace.json, /claude-plugins/agent-concierge-plugin-1.0.0.zip(archive 출처, sha256 8188f22b…, 매번 같은 바이트). 비밀값·내부 주소 없음 확인, README 설치 명령을 우리 주소로. archive 출처는 Claude Code v2.1.224 이상(이 맥 2.1.89라 실제 설치는 못 해 봄).
  - 새 과업 표본 10개(카드 46장) 모두 검사 날짜와 등급 또는 시험 호출 성공이 보임.
  - 디렉터리 확인에 A2A Registry(공개 API에 노출, conformance true)와 a2a.directory(/agents/agent-concierge) 추가. mcpservers.org·PulseMCP·mcp.so는 아직 없음.
  - 배포: frontend growth-md-frontend-20261110-r6(base writer-retry-frontend-20261110-r1), jobs growth-md-jobs-20261110-r5(base ua-contact-jobs-20261110-r1), 게이트 passed. r4는 쉬던 슬롯 준비 확인 503으로 배포 시작 전에 멈춤(변경 없음).
- 수집기 연락처 판 준비·execution 계획(2026-11-10 06시, 운영·SRE)
  - User-Agent 연락처: crawler.py의 `bot@a2a-discovery.org`(MX 없음)와 `github.com/a2a-discovery`를 `contact@agentconcierge.biz`, `https://agentconcierge.biz/`로 바꾼다. 제품 토큰은 A2A-Discovery-Crawler/1.0으로 유지한다. agentconcierge.biz에는 Cloudflare MX가 있다. contact@ 전달 규칙은 계정에서 확인해야 한다.
    - 사용자 승인(PM 경유) 뒤 06:00에 배포했다: jobs ua-contact-jobs-20261110-r1(base writer-retry-jobs-r1), admin ua-contact-admin-20261110-r2(base writer-retry-admin-r1). 게이트 둘 다 passed. admin r1은 patch .orig가 섞여 쓰지 않는다.
    - 커밋 8255d24b(HEAD 내용에 이 한 줄만 얹음, 시험 tests/test_crawler_contact.py). 다른 세션의 crawler.py 미커밋 변경(394행)은 그대로 두었다. 연락처는 crawler 한 곳뿐이었다(collector·health는 연락처 없음).
    - 배포 뒤 jobs·admin에 새 오류가 없다(06:00~, 기존 rag index 오류만).
  - execution 판 재구성 계획: `reports/execution 판 재구성 계획 2026-11-10.md`(1cd2df92)
    - 활성 frontend 판을 복사해 execution 판을 만들고, execution 시험을 게이트에 더해 조용한 시간에 배포하는 안이다.
    - 근거: execution 로그 "workflow round deferred: statement_failed"가 11-05 이후 373회이고, 10-31 이후 execution 관련 커밋 10개가 빠져 있다.
- 쓰기 잠금 재시도·게이트 역할별 시험(2026-11-10 05:4x, 운영·SRE, 총괄 PM 지시)
  - 오류 2건: 헬스체크 crash(05:24)와 엣지 output-observation 503(00:36)
    - 원인: 둘 다 DB 쓰기 advisory lock의 lock_timeout(1초) 초과다. DB 로그상 오늘 14회.
    - 수정: 본문 실행 전 잠금 시간 초과는 0.25초 쉬고 한 번 더 시도한다(tx·BEGIN IMMEDIATE). 세션 없는 rollback은 무시하고, 엣지 errors()가 503의 예외 종류를 로그에 남긴다.
    - 커밋 0eacf21e, 시험 6개(실제 PG 재시도 포함)
  - jobs 판의 application_store_postgres.py가 11-02 커밋(0769327e, WriterBusy 구분) 이전 사본이었다. jobs 판에 그 커밋도 함께 얹었다.
  - release_gate 수정(커밋 94284e4a)
    - 판 역할(release.json 'role' 또는 이름의 -jobs- 등)로 시험 목록을 고른다.
    - jobs는 수집·헬스·크롤러·평가 시험 5개를 돌리고, Chat 비교는 frontend만 한다.
    - test_release_gate의 가짜 Manager에 check_base가 빠져 있던 것도 고쳤다(1b67c238 이후 실패).
    - growth-md-jobs-r2가 passed였던 이유: 기본 목록으로는 지금도 실패하므로 시험을 직접 지정해 돌린 것으로 보인다. 새 jobs 목록으로는 141 passed.
  - 배포(모두 게이트 passed)
    - frontend writer-retry-frontend-20261110-r1(base growth-md-frontend-r3)
    - jobs writer-retry-jobs-20261110-r1(base growth-md-jobs-r2). 백분위 캐시(2df53d39)를 포함하므로 pct-cache-jobs-r1은 쓰지 않는다.
    - admin writer-retry-admin-20261110-r1(base ops-traffic-admin-r1, 고친 게이트 passed) 배포
    - execution(10-31 판)은 패치가 맞지 않아 제외했다.
  - 11-11 03시 과업 스냅샷: task-pages.json 수정이 11-10 05:37(성장 팀 --extend)이라 01:37에 20시간이 찬다. 03시 실행 대상이고, IndexNow 변경분 기준은 11-09 22:13 상태다. 07시 뒤에 다시 쓰면 그만큼 밀린다.
  - 넘긴 것: jobs `rag index loop error`(VectorError database_error, 누적 4,073건)는 application_store_vector.py라 검색과 RAG 팀으로 넘긴다.
- 성장·유통 5차(2026-11-10 06시, PM 결정 "품질 목표 100%")
  - 과업 페이지 품질 점검: 4차의 254쪽 중 설명에 문구가 지나가듯 나온 에이전트가 섞인 과업이 있었다(예: Google search에 광고 단가 API, latitude longitude에 병원 찾기). 일치 규칙을 "이름 또는 설명 앞 60자('Use when … needs' 머리말 제외)"로 좁히고, 맞은 에이전트 중 주 카테고리만 남김. 결과를 사람이 검토해 모호한 문구 20개 제거, 중복 개념 2개 제거, 검토를 통과한 30개 추가 → 201쪽. 운영 스냅샷 교체(254쪽 사본은 세션 스크래치). 빠진 53쪽은 404 noindex.
  - 공개 성장 페이지 속도: 서버 처리 3~30ms(슬롯 직접), 공개 경로 0.45~0.9초는 대부분 네트워크 왕복. 응답이 `Cache-Control: no-store`(front 미들웨어의 보안 정책)라 브라우저 재방문 캐시가 없음 → 공개 성장 페이지만 예외로 둘지 PM 판단 요청.
- DB 부하 줄이기: 평가 백분위 캐시(2026-11-10 05:3x, 운영·SRE)
  - 무엇이 무거웠나: pg_stat_statements(11-01 초기화 뒤)에서 누적 DB 시간 2위가 `score_percentile`의 COUNT 쿼리였다.
    - 73만 번, 평균 67ms, 4.9만 초로 전체의 9%다.
    - 한 번에 최대 0.5초가 걸렸고, 지금도 분당 46번 돈다.
  - 점수 값은 종류마다 300개 남짓뿐이라, (종류, 점수)별 결과를 10분 동안 기억하게 했다.
    - 새 파일 `collector/percentile_cache.py`. capabilities·a2a가 이것을 쓴다.
    - 등록 SQL은 바꾸지 않았다.
    - 커밋 2df53d39, 시험 4개.
  - 판 pct-cache-jobs-20261110-r1(base growth-md-jobs-20261110-r2)
    - 판 사본에서 관련 시험 125개가 통과했다.
    - release_gate는 기준 판도 똑같이 실패한다(jobs 판에 workspace_platform.typed_engine_for가 없어 tests/test_typed_engine_for.py 수집 오류). 규칙상 게이트 실패 배포라 PM 판단을 기다린다.
  - 기준선: 05:29 calls 730,683.
  - 그 밖의 DB 시간 상위는 embeddings 삽입·정리, explore_document_queue 삽입(각 8~9%)이다. 모두 검색과 RAG 영역이라 넘긴다.
- 성장·유통 4차(2026-11-10 05시, 총괄 PM 과제 1~5)
  - 과업 페이지 99→254쪽(사이트맵 10,021). 검색으로 2개가 안 찬 과업은 근거 카탈로그에서 과업 문구가 그대로 나오는 에이전트로 보충하고, 근거 있는 에이전트 설명에서 자주 나오는 문구로 새 과업 약 140개를 만들었다(3개 이상일 때만). task_catalog.catalog_tasks, 운영 스냅샷은 `build_task_pages --extend`로 검색 없이 확장. IndexNow 변경분은 11-11 03시 jobs가 보낸다(새 쪽 포함).
  - 공개 페이지(/connect, /agents/*, /agent/*, /reports/*, /badges)가 `Accept: text/markdown`이면 같은 내용의 Markdown으로 답한다(page_markdown.py, 404는 X-Robots-Tag noindex). llms.txt에 한 줄 추가. 제목은 약어 유지(SEC EDGAR, IP, llms.txt).
  - /connect에 "After you connect"(예시 질문 3개, 재방문 안내) 절 추가. MCP initialize 안내문 끝과 A2A 새 대화 첫 응답 data(return_visit)에 whats_new·/api/task-updates 한 줄. 답변 본문은 그대로.
  - 검색 콘솔 확인 파일 자리: public-pages/site-verification/의 google*.html·naver*.html·BingSiteAuth.xml을 형식이 맞을 때만 루트에서 제공(배포 불필요). 사용자용 절차 deploy/distribution/SEARCH_CONSOLES.md.
  - PyPI·npm·Claude Code 플러그인: GitHub 없이 가능(PyPI·npm은 사용자 계정·토큰, 플러그인은 우리 사이트에 marketplace.json+zip을 archive 소스로). 빌드·검증만 함, 게시는 승인 대기. deploy/distribution/PACKAGES.md. 런칭 글 4번(GitHub README) 제외 표시.
  - 배포: frontend growth-md-frontend-20261110-r3(base category-bg-frontend-20261110-r1), jobs growth-md-jobs-20261110-r2(base price-unknown-jobs-20261110-r1), 게이트 모두 passed. 시험 tests/test_growth_markdown_and_tasks.py 10건.
  - jobs 첫 매일 갱신이 11-10에 돌지 않은 이유: 스냅샷이 11-09 21:51에 만들어져 20시간이 안 됨(정상). 첫 실행 11-11 03시.
- 응답 시간 추세·카테고리 페이지(2026-11-10 05시, 운영·SRE)
  - 측정(부하 11~19)
    - 탐색 중앙값 1.8~2.3초, Chat 2.8~4.5초
    - 과업·비교·best 페이지 10~20ms
    - 상세 API 25~75ms. 한 번 1.2초가 나왔는데, 부하 때 디스크에서 읽은 탓이다.
    - 카테고리 0.5~1.4초로, 가장 느렸다.
  - 원인: 10분 캐시가 만료된 뒤 첫 방문자가 페이지를 다시 만드는 동안 기다렸다.
  - 수정: 만료된 페이지도 바로 주고 뒤에서 다시 만든다. 기다리는 경우는 재시작 직후 각 카테고리의 첫 방문뿐이다.
    - 커밋 75788338
    - 판 category-bg-frontend-20261110-r1(base cookie-phone-frontend-20261110-r1, 게이트 passed)을 배포했다.
  - 추세 기록: `scripts.ops_daily_samples --record --trend`가 logs/ops/response-samples.jsonl에 하루 한 줄씩 쌓고, ISO 주별 중앙값을 보여 준다. 첫 기록은 11-10이다.
  - 일일 점검 지시문 반영은 사용자 승인 대기다.
- 운영 점검 묶음(2026-11-10 05시, 운영·SRE, 총괄 PM 요청)
  - Solana USDC 확인: 가격 없음 26→2, Solana가 더 싼데 Base 가격으로 저장 99→46. 줄어든 것은 헬스체크가 402 견적을 다시 받은 결과다.
    - 남은 46개 중 배포 뒤 점검된 23개는 실제 402가 두 네트워크 같은 값이다(예: stableupload 2 USDC, kino402 0.384). 오류가 아니라 등록부 accepts의 Solana 금액이 예전 값이다.
    - 남은 2개는 down 상태다.
  - x402 수집 주기: 정상이다. 마지막 전체 수집은 11-09 08시쯤이고(meta crawl_last_full), 증분 수집은 계속 돌고 있다. 다음 전체 수집은 11-10 08시쯤이다.
  - 새로 찾은 것: 등록부 가격과 저장(관측) 가격이 다른 x402 자원이 760개다. content_hash에 가격이 들어가므로, 등록부 수집 때마다 등록부 가격으로 덮이고 헬스체크가 관측가로 되돌리는 왕복이 생길 수 있다. 검색과 RAG의 "동적 가격 0" 규칙과 같은 판단(관측 vs 등록부 우선)이라 넘긴다.
  - jobs 야간 작업: 03~07시 jobs 로그에 경고·오류가 없다.
    - 과업 스냅샷은 11-09 21:51에 수동으로 만들어져 MIN_AGE 20시간 조건에 걸렸다. 그래서 오늘 새벽은 정상적으로 건너뛰었고, IndexNow 변경분 전송도 없었다. 첫 자동 실행은 11-11 03시다.
  - 09:05 일일 점검 보완
    - `scripts/ops_daily_samples.py`(+시험 2개): 날짜별 5xx 비율(전체·외부), 탐색 5건·Chat 3건 표본(처음 보는 질의, 연결 재사용, Server-Timing).
    - 실측: 탐색 중앙값 1.8초(3초 초과 0), Chat 2.9~4.5초(5초 초과 0, 추천 3), 11-09 5xx 0.18%(외부 0.27%).
    - 예약 작업 지시문 수정은 권한 검사에 막혔다. 보완안은 공유 노트 `운영SRE-일일점검-보완안-20261110.md`에 있다. 스크립트·시험은 미커밋이고 PM 확인 뒤 커밋한다.
  - 상태: 백업 04:30 ok, DB 연결 17, 디스크 7%. 부하 10은 다른 세션의 nice pytest와 fseventsd 때문이며 장애는 없다.
- 수집 낭비·가격 규칙 후속(2026-11-10 01시, 검색과 RAG): ① A2A 갱신 때 활동 수치(updated_at·호출 수)·카테고리만 바뀌면 cap_checked_at·eval_at 유지(c7f6990d, activity-refresh r1) → a2a-registry 활성 825개 중 미조사 33개로 고정(전에는 30분마다 613개). ② 402 결제 요구 금액 0 = 금액 모름: 저장 양수 가격 유지, 저장 0이면 NULL, 수집기도 0→NULL(8b98463c, 59208188). NULL x402는 탐색 카드·목록·상세(전에 "Free")·알림에 "Price on request". 32172는 다음 헬스체크(04:36) 뒤 NULL 확인 예정, 9573은 active=0이라 그대로. 배포: frontend price-unknown-frontend-20261110-r1, jobs price-unknown-jobs-20261110-r1(총괄 PM이 사용자 상시 승인으로 실행). 이전부터 실패하는 test_pearl_frontend::test_public_workspace_menu_opens_secure_customer_entry_on_desktop_and_mobile[390]의 원인: 390px에서 쿠키 동의 배너의 닫기 버튼이 "Open navigation" 메뉴 버튼 위를 덮어 클릭을 가로챔(시험이 배너를 닫지 않거나, 모바일에서 배너가 메뉴를 가림) → 운영·SRE와 정리 예정. embeddings 24시간 전후 기록은 11-11 00:40.
- embeddings 낭비 1·2번(2026-11-10 00시, 검색과 RAG, 총괄 PM 요청): 원인은 a2a-registry가 updated_at을 약 30분마다 바꿔 content_hash가 달라지고 upsert가 레지스트리 자체 카테고리로 덮어쓴 것(활성 825개 중 613개). crawler는 체계 밖 카테고리를 classify, _upsert는 이름·설명이 같으면 저장 카테고리 유지(등록문 재사용), postgres_ann은 같은 vector_hash면 갱신 안 함·대기 중 자원 행은 cleanup 제외·마지막 indexed 작업과 corpus·모델이 같으면 저장 벡터 재사용(Ollama 생략). 9fcdb1a5. frontend embed-churn-frontend-20261109-r1 배포(게이트 통과), jobs embed-churn-jobs-20261109-r1은 패키징·검증만(worker-deploy 권한 검사 거부, 사용자 실행 대기). 기준선(11-09 22:35): 색인 작업 24시간 175,148, embeddings 삽입 285만·삭제 258만·갱신 42만, autovacuum 8시간마다 1,052~1,951초 → jobs 배포 뒤 24시간 기준 재측정. 3번(트리거)은 측정 뒤 결정(앱이 시작 때 함수 본문을 대조하므로 코드·함수 동시 변경 필요). 남은 낭비: A2A 갱신마다 cap_checked_at·eval_at 초기화. 후보 40개+qwen3 재순위 실험: 1위 정답 +0.8~0.9%p, 임베딩 p50 +0.45초 → 보류.
- IndexNow 전송(2026-11-09 22:2x, 총괄 PM, 사용자 승인 "IndexNow 전송"): 사이트맵 URL 9,436개를 api.indexnow.org로 제출(Bing·Yandex·Naver 등 공유), 응답 200. 첫 일괄 요청은 키 확인 전이라 403 → 1개 URL로 키 확인(200) 뒤 재전송 성공. 키 파일 logs/service-frontend/public-pages/indexnow-key(git 제외). 같은 URL을 매일 다시 보내지 말고, 새로 생기거나 바뀐 페이지만 보낼 것.
- Chat 응답 시간(2026-11-09 밤, 총괄 PM 요청): 원인은 강한 임베딩 모델이 내려간 뒤 요청마다 1.5초 기다리다 재적재를 끊은 것과 predict_next 지연. 실패 시 60초 쉬고 뒤에서 재적재, predict_next 0.4초·10분 캐시, 결과 저장을 답 뒤로(VisitorBook.defer/settle), 대체 검색 8초 상한. latency-frontend-20261109-r2(ops-cache-r1 위) 배포. 새 질문 20개: 중앙값 7.29→2.71초, p95 11.81→4.51초, 5초 초과 19→1(부하 13.5→7.2). r1이 ops-cache를 약 4분 덮음 → r2로 복구. 시험용 Mock 엔진 판정 수정으로 test_fast_single_recommendation 9건·대명사·대안 시험 등 실패 해소(남은 2건은 다른 원인). → reports/Chat 응답 시간 측정 2026-11-09.md 5절
- 공식 MCP Registry 게시(2026-11-09 21:48, 총괄 PM, 사용자 승인 "게시 진행"): biz.agentconcierge/agent-concierge@1.0.0 active(remotes https://agentconcierge.biz/mcp). HTTP 도메인 확인(logs/service-frontend/public-pages/mcp-registry-auth, git 제외), 키 ~/.mcp-registry/key.pem, mcp-publisher 1.8.7. → deploy/mcp-registry/README.md 4절
- price_usdc 단위 조사(2026-11-10, 운영·SRE, 총괄 PM 요청): 설계는 USDC 원자 단위 정수라 BIGINT가 맞음, 소수로 0이 된 자원 0개(소수는 XRPL RLUSD뿐, USDC 아니라 제외). 대신 crawler USDC_ASSETS의 Solana USDC 주소 오타(g 하나 더)로 Solana 가격 미반영: 가격 없음 26·더 비싸게 99. 4dfaa386, 판 usdc-sol-jobs-20261110-r2(base activity-refresh-jobs-r1) 배포 요청. 스키마 변경 권하지 않음 → reports/price_usdc 단위 조사 2026-11-10.md. 기준 판 검사가 낡은 base(embed-churn-jobs)를 실제로 막음.
- 리포트 탐색 장애 해소(2026-11-10 00:44): snapshot-fix-frontend-20261110-r1(embed-churn-frontend-r1 위 + report_snapshot.py 62632799, 총괄 PM 배포)에서 스냅샷 20,589건 463.7초 생성, has_report 탐색 0.52~0.72초(부하 7.4).
- Chat 재측정(2026-11-09 23:14, 운영·SRE, autovacuum 끝난 뒤, growth-frontend-r5, 새 질문 20, 평균 부하 4.2): 중앙값 2.87초·p95 4.86초·최대 5.40초, 5초 초과 1/20 → 5초 목표 충족(21시 7.3초). 리포트 탐색 수정은 ops-snapshot-frontend-20261109-r5(base growth-frontend-r5, 게이트 통과)로 다시 만듦, 배포 대기(r4는 기준 낡음). has_report 탐색은 23:15 부하 4에서 1.7~2.9초(스냅샷 없음).
- 탐색 리포트 스냅샷 장애(2026-11-09 22시대, 운영·SRE): 21:40쯤 리포트 있는 자원이 a2a 10,023·mcp 10,001로 스냅샷 상한(front.MAX_REPORT_CANDIDATES 10,000)을 넘어, 그 뒤 시작한 모든 슬롯이 스냅샷 없이(로그도 없이) 돌았고 has_report 탐색 7.7초. report_snapshot에 전용 상한 50,000·초과 경고·첫 빌드 로그 버그 수정, 62632799. ops-snapshot-frontend-20261109-r4(base ops-snapshot-r3, 게이트 통과) 배포 요청 중(이 세션 배포 권한 없음). jobs ops-probe-r2는 배포 뒤 password 경고 0.
- 배포 도구 기준 판 검사(2026-11-09 밤, 운영·SRE, 총괄 PM 요청): package가 기준 판을 release.json base에 기록(--base, AGENTCON_RELEASE_BASE, 복사한 release.json), deploy·worker-deploy가 활성 판과 다르면 release_base_mismatch로 거부(게이트 전·잠금 안 두 번), --force-base로만 무시, base 없는 예전 판은 그대로. 1b67c238, deploy/DEPLOY.md, tests/test_service_deploy_base.py.
- 운영·SRE 22시대(2026-11-09): 배포 판을 새 활성 판 위에 다시 만듦 — ops-snapshot-frontend-20261109-r3(model-watch-frontend-r1 위, 게이트 통과), ops-probe-jobs-20261109-r2(growth-jobs-r1 위, 해당 시험 18개 통과). 이 세션 worker-deploy가 권한 검사에 막혀 배포 안 함 → 총괄 PM·사용자 실행 대기. test_concierge::test_whats_new_returns_current_choices는 시험이 낡음(Chat은 가격·결제자 수로 순위 안 매김, 동점 0.875) → 새 후보가 선택지에 있는지로 고침, 5c6d66c2.
- 운영·SRE 후속 3건(2026-11-09 밤, 총괄 PM 요청): (1) 정정: 대기 슬롯은 시작 때만 Report snapshot을 만듦(두 슬롯이 같은 concierge 로그에 써서 오해). 배포 직후 옛 활성 슬롯의 진행 중 스냅샷이 끝까지 돌던 것을 몇 초 안에 멈추게 함(_UntilStandby). (3) status.json 점검 실패 때 127.0.0.1:8400 직접 측정해 origin/path 문제를 jobs 로그에 남김(공개 행은 그대로). 862319ea. ops-snapshot-frontend-20261109-r2(growth-frontend-r3 위, 게이트 통과)·ops-probe-jobs-20261109-r1(collector-scavenger-jobs 위, 해당 시험 18개 통과) 패키징만, model-watch-frontend-r1·growth-jobs-r1 대기 때문에 배포 순서 총괄 PM 확인 중. (2) embeddings: 하루 재임베딩 17.5만 중 약 46%가 같은 글. 최대 원인은 629개 자원의 카테고리 줄다리기(crawler가 레지스트리 원본 카테고리로 덮어씀 ↔ a2a 조사가 재분류), 다음은 33개 필드 무효화 트리거. 수정안만 보냄(파일들 다른 세션 작업 중) → reports/embeddings 죽은 행 원인 2026-11-09.md (fed2a803).
- 카테고리 페이지 125초·status.json 시간 초과 조사(2026-11-09 밤, 운영·SRE, 총괄 PM 요청): 접근 로그가 없어 125초 요청 자체는 못 잡음. status.json "장애"는 가용성 점검기(이 맥→Cloudflare LAX→터널, 5초 제한)의 시간 초과 5번(20:44~20:56)이고 HTTP 오류 없음, 7일 실패율 2.1%. 같은 시각 OpenSearch·Edge 시간 초과, DB lock timeout, 두 슬롯의 Report snapshot(각 500초 안팎)이 겹침 → DB·IO 정체가 원인으로 추정. 막는 수: 카테고리 페이지 카테고리별 10분 캐시·한 번에 하나만 다시 만들기·다시 만드는 중이거나 실패하면 이전 페이지(최대 24시간), status.json 가용성 계산 30초 캐시. ops-cache-frontend-20261109-r1(growth-frontend-r2 위, passfile 수정 포함) 게이트 통과·배포(활성 a), 카테고리 2~4ms(첫 요청 0.4~0.6초)·status 2ms. 33e4c655. 기존 실패 2건(test_pronoun_retains..., test_alternatives_to_a_listed_agent...)은 원래 판에서도 실패.
- 운영·SRE 11-09 점검 후속(2026-11-09 밤, 운영·SRE 세션)
  - 로그 잡음: libpq 'password file "/dev/null" is not a plain file' 원인은 application_runtime._connect의 passfile=os.devnull과 runtime_snapshot(백업)의 PGPASSFILE=/dev/null. /dev/null/no-password-file(존재·생성 불가, libpq가 조용히 건너뜀)로 교체, psql 전후 확인. 07cc8dcc. frontend는 다음 frontend 릴리스에 실림.
  - admin 재빌드: ops-traffic-admin-20261109-r1(traffic-frontend-20261109-r2 위 + 내 파일 6개), release_gate passed, 배포(활성 a). '방문 에이전트' 탭에 '외부 유입 주간 지표'(외부 에이전트 세션·MCP 클라이언트·Google 외 AI 봇·사람 방문·internal 비율, gateway/traffic_report.py, /admin/api/traffic/weekly). 34e38951. 새 슬롯 첫 기동 WriterBusy 1회 후 자동 재시작 정상(기존 경합).
  - 시험용 PG 4개: driver_agent tests/conftest.py cluster() 픽스처의 고아(11-07). 사용자 승인·직접 실행으로 정리 완료(프로세스 0·폴더 0 확인). 이 세션 pg_ctl은 권한 검사에 막혀 실행 안 함.
  - Chat 응답 시간(서버 직접, 새 질문 20, 시작 부하 4.3): 중앙값 7.3초·p95 11.8초, 19/20이 5초 초과(11-05 1.7초). 로컬 LLM 생성 호출 0. 주 원인 추정은 agentcon_search.embeddings(2.3GB) autovacuum의 벡터 인덱스 정리(27분+, 디스크 115MB/s)와 임베딩 대기열(예산 소진 499 16건). 재측정·죽은 행 원인 조사는 SRE, 예산·후처리 지연은 검색과 RAG로 → reports/Chat 응답 시간 측정 2026-11-09.md
  - 한국 접속: 입구 LAX·터널 ICN, 요청마다 태평양 2왕복. 지출·설정 변경 없이 무료 개선 먼저 → reports/한국 접속 속도 의견서 2026-11-09.md
- AI AD Coin v6.2 로드맵 1순위(테스트넷 배포 및 PG 결제 연동) & 2순위(스테이징 활성화 및 백그라운드 워커 데몬화) 완료 (2026-11-09, 풀스택):
  1) 1순위: 테스트넷 배포 및 PG 결제 연동 (Testnet Deployment & Fiat/USDC PG Handlers):
     - Stripe 및 Circle 웹훅 서명 검증기 및 입금 처리기(fiat_providers.py: StripeWebhookVerifier, CircleWebhookVerifier, FiatWebhookHandler) 구현.
     - HTTP 라우터(real_value_http.py)에 /webhooks/stripe, /webhooks/circle 엔드포인트 연동.
     - Base Sepolia / Ethereum Sepolia 스마트 컨트랙트 배포기(scripts/deploy_token_testnet.py) 작성 및 시뮬레이션/Web3 연동 검증.
     - 신규 회귀 시험(tests/test_ad_coin_v2_fiat_providers.py) 통과.
  2) 2순위: 스테이징 활성화 및 백그라운드 워커 데몬화 (Staging Activation & Background Worker Daemon):
     - 멀티 워커 백그라운드 데몬(scripts/ad_coin_worker_daemon.py): Outbox 리스 처리, 만료 리스 회수(reclaim_stale_leases), 미결 영수증 서명 복구(reconcile_pending_receipts), 만료 어텐션 정산(reconcile_stale_attention), 우아한 종료(SIGINT, SIGTERM) 지원.
     - 워커 데몬 회귀 시험(tests/test_ad_coin_v2_daemon.py) 통과.
     - 스테이징 안전 라우터 마운트(front.py: AD_COIN_V2_ENABLED=1) 검증.
     - 전체 v2 회귀 시험 15개 파일 178/178 전수 통과 (100% Pass), dev 서버 무영향 확인.
  3) 법률 의견서 작성: 공정거래위원회(표시광고법·전자상거래법·추천독립성·다크패턴), 금융 규제(가상자산이용자보호법·전자금융거래법 선불업·자본시장법 증권성·유사수신·외국환거래법), 개인정보보호위원회(개인정보보호법·맞춤형 광고 가이드라인·블록체인 삭제권 분리·PII 제로 원장) 종합 법률 검토 완료.
- 외부 유입 0단계 계측(2026-11-09, 프론트앤드, 사용자 "0단계부터 시작"): concierge/traffic.py 익명 하루 집계(입구×클라이언트 종류, 상태, 봇 이름, MCP 클라이언트 이름, 하루 salt로 서로 다른 수; IP·UA·본문 저장 없음), front.py 미들웨어 끝에 연결. 우리 트래픽은 internal(127.0.0.1·internal-ips.txt·시험 UA). LOG_DIR 없으면 메모리만(r1 gate 시험 파일 오염 → r2 수정). traffic-frontend-20261109-r2 배포·운영 확인. 요약 `python -m agent_market.concierge.traffic logs/service-frontend/traffic 7`. 관리자 화면은 admin 재빌드 때. → reports/외부 유입 개선 계획 2026-11-09.md 6절
- AI AD Coin v6.2 로드맵 1단계(어드민 UI 통합), 2단계(스테이징 검수), 3단계/8번(실가치 발행 및 블록체인) 구현 완료 (2026-11-09, 풀스택):
  1) [1단계] 어드민 포털 통합 UI 개발 (Admin UI Integration):
     - 어드민 HTTP 엔드포인트(admin_http.py): 전체 복식부기 및 예산 대사(/api/ad-coin/v2/admin/reconcile), 플랫폼 통합 지표(/api/ad-coin/v2/admin/overview) 구현 및 live_service 라우터 마운트.
     - 어드민·워크스페이스 프론트엔드 연동(agent_market/ad_coin/v2/web/index.html, app.js): A/B 실험 및 퍼널·페이싱 분석(Growth & Analytics), 외부 에이전트 중계 및 결제 위임(Agent Relays), 플랫폼 무결성 및 복식부기 제로섬 감사(Platform Audit) 3개 신규 탭 및 대화형 제어 인터페이스 연동.
     - 신규 회귀 시험(tests/test_ad_coin_v2_admin_http.py) 통과.
  2) [2단계] 스테이징 롤아웃 및 최종 통합 검수 (Staging Rollout & End-to-End Verification):
     - 환경변수 AD_COIN_V2_ENABLED 기반 front.py 조건부 안전 마운트 유지(운영 및 개발 서버 100% 무영향 보장).
     - 전체 E2E 수명주기 시험(tests/test_ad_coin_v2_live_service_e2e.py) 및 Playwright 브라우저 9개 접근성/동작 시험 전수 통과.
     - 프론트엔드 정책 검사(scripts/check_front_content.py, 335개 파일 0건 위반), Ruff linter 0건, 한글 유출 0건 자동 검증 완료.
  3) [3단계] 8번 실가치 발행 및 블록체인 연동 (Real-Value Issuance & Blockchain / WP-06):
     - 스키마 버전 9 업그레이드(VERSION = 9): 법정화폐 입금 웹훅(adc2_fiat_deposits), 수탁 준비금 체크포인트(adc2_custody_reserves), 온체인 인출/상환(adc2_onchain_withdrawals).
     - 실가치 게이트웨이(real_value.py: RealValueGateway):
       * 입금 확인 웹훅 시 1:1 복식부기 원장 발행(model_seed 기반 청산-지갑 분개).
       * 100% 전액 준비금(Full-Reserve Backing) 및 Proof-of-Reserves 대사 검증(reconcile_proof_of_reserves).
       * 온체인 인출/상환(request_onchain_withdrawal): 지갑 잠금 에스크로 원자적 분개, 온체인 브로드캐스트 확인(confirm_onchain_withdrawal), 취소 환불(cancel_onchain_withdrawal).
     - 스마트 계약 아키텍처: AIADCoin.sol(ERC-20, Chainlink Proof-of-Reserves 오라클 피드 연동, 멀티시그 민팅/소각, 비상 일시정지) 및 aiac_token_spec.json 배포 규격 작성.
     - HTTP 라우터(real_value_http.py) 마운트 및 신규 회귀 시험(tests/test_ad_coin_v2_real_value.py) 통과.
  - v2 전체 14개 테스트 파일 175/175 전수 통과 (100% Pass), 폐쇄 SQL 카탈로그 536개 등록 동기화.
  9) 광고주 플랫폼 고도화 (Advertiser Platform Advancement):
     - 추가 보상 단계 (Multi-Stage Rewards, adc2_stage_claims): 클릭(click, 20), 피드백(feedback, 30), 시청 완료(watch_complete, 50), 전환(conversion, 200). PLAT-12/POL-11 준수(P1 기본 노출 보상 불변 보존, 중립적 피드백 보장 - 비판적 1점 평가도 동일 100% 약정 지급, 제안별 중복 보상 청구 차단).
     - 캠페인 A/B 실험 (Campaign Experiments, adc2_campaign_experiments): 변량 등록 및 가중치 합 100% 검증, 사용자/세션 기반 일관 해싱(consistent hashing) 결정론적 변량 배정, 상태 라이프사이클(draft, active, paused, completed).
     - 전환 측정 및 기인 분석 (Conversions, adc2_conversions): 오더/토큰 중복 방지, 30일 기본 기인 기간(attribution window) 검증.
     - 성과 분석 (Funnel Analytics): 노출→클릭→시청완료→피드백→전환 단계별 퍼널 집계, CTR, CVR, eCPM, eCPA, 평점 분포 및 감성 분석 통계 산출.
     - 예산 최적화 (Budget Pacing & Optimization): 실제 소진율 vs 경과일 기준 예상 소진율 비교, 페이싱 상태(on_track, overpacing, underpacing, exhausted), 번레이트 급증 및 저전환 이상 징후 알림, 일일 예산 조정 권고.
     - 시장 통계 (Market Benchmarks): 카테고리별(tech, finance, lifestyle, general) CTR, CVR, eCPM, eCPA 표준 벤치마크 제공.
     - REST API 엔드포인트 10종(/api/ad-coin/v2/advertiser/*) 및 live_service 라우터 마운트, 신규 회귀 시험(tests/test_ad_coin_v2_advertiser_platform.py) 및 v2 12개 전체 시험 172/172 통과.
- AI AD Coin v6.2 로드맵 7단계(외부 에이전트 광고 유통) 구현 완료 (2026-11-09, 백엔드):
  7) 외부 에이전트 광고 유통 (External Agent Ad Distribution):
     - 외부 중계 파트너(A2A·MCP) 등록 및 자격 검증 (adc2_relay_partners): 지원 프로토콜(a2a, mcp), 수수료율 상한(최대 30%), 활성 상태 및 운영자 정산 계좌(operator_payable) 검증.
     - 광고 제안 전달 및 프로토콜 규격 래핑 (adc2_relay_dispatches): 홉 카운트 3회 이하 제한(anti-infinite relay loop), 자기 중계(self-relay) 및 순환 배포 금지, 중복 활성 제안 빈도 제어(동일 소유자·캠페인 2건 초과 차단), A2A ad_proposal 메시지 및 MCP present_sponsored_offer 도구 호출 페이로드 포맷팅.
     - DEC-03 플랫폼 시청 연결: 외부 렌더러 자체 보고를 통한 부정 적립을 방지하고 플랫폼 표준 뷰어 웹 세션(platform_viewer_url, 1회용 단기 토큰)을 통해서만 노출 및 시청 시간(15~30초)·인터랙티브 증거 수집.
     - 보상 배분 및 복식부기 정산: 소유자 동의(consent), 플랫폼 시청(viewed), 완료 증거 검증 후 복식부기 모델 시드/정산(settle), 사용자 보상 전액 보존(감액 금지) 및 중계 파트너 운영자 수수료 원장 배분, ledger audit $0 보존 대사 완료.
     - REST API 엔드포인트 8종(/api/ad-coin/v2/relays/*) 및 실서비스 라우터 마운트, 신규 회귀 시험(tests/test_ad_coin_v2_ad_relay.py) 및 v2 11개 전체 시험 168/168 통과.
- AI AD Coin v6.2 로드맵 4단계(실서비스 연결/종합 검수), 6단계(유료 에이전트 결제), 5단계(운영 성능 검증) 구현 완료 (2026-11-09, 백엔드):
  4) 실제 서비스 연결과 종합 검수: Live Service 통합 팩토리(live_service.py: build_live_service, create_live_ad_coin_v2_router), conciege front 조건부 마운트(AD_COIN_V2_ENABLED 환경변수 기본 비활성화로 현재 개발 서버 무영향), E2E 전체 수명주기 통합 시험(test_ad_coin_v2_live_service_e2e.py: 정적 쉘·핑거프린트 자산, 사용자/광고주 온보딩, mTLS 심사, 챌린지 광고선호도 갱신, 복식부기 대사).
  6) 코인으로 유료 에이전트 사용: 에이전트 결제 위임 위임장(adc2_mandates), 작업 실행 및 에스크로 잠금·정산·환불(adc2_executions), 게이트웨이(agent_payments.py: AgentPaymentGateway), HTTP 라우터(agent_payment_http.py), 데드락 방지 계층적 잠금(Mandate → Account 정렬), 100% 잔액 보존.
  5) 운영 조건의 성능 검증: 격리 PostgreSQL 18 기반 부하 벤치마크(scripts/ad_coin_v2_operational_perf.py), 8개 동시 클라이언트 워커, 2,000건 사전 원장 이력, 5개 지역(KR, JP, US, GB, DE) 지연 시뮬레이션, 500건 전체 HTTP+인증+암호화+원장 트랜잭션 100% 성공(0 실패, 126.64 ops/sec, p50 24.58ms, p99 116.91ms), 복식부기 audit $0 대사 검증 완료.
  전체 v2 회귀 시험 157/157 전수 통과, Ruff 0건, 프론트엔드 정책 335개 파일 검사 0건, 한글 유출 0건.
- AI AD Coin v6.2 로드맵 1~3단계 구현 완료 (2026-11-09, 백엔드): 현재 운영 서비스 무영향 원칙 유지하며 권장 순서 1~3번 완료.
  1) 실제 로그인·권한 연결: 영속 DB 기반 자격증명 해석기(PersistentCredentialResolver), 사람 세션(adc2_human_sessions, __Host-ac_customer_session 쿠키 및 CSRF), 에이전트 토큰(adc2_agent_tokens), 심사자 mTLS(adc2_reviewer_credentials), 에포크 회전/세션 즉시 무효화.
  2) 운영 보안 기반: PostgreSQL 역할 분리 DDL 생성기(security_roles.py: ad_coin_app, ad_coin_migrator, ad_coin_readonly), Ed25519 서명 키 및 Fresh 챌린지 무중단 회전 키 볼트(key_vault.py), 토큰 버킷 속도 제한기(TokenBucketRateLimiter), 불변 감사 로그(AuditLogger, adc2_audit_log).
  3) 운영·장애 복구 기능: 고갈 리스 회수 및 지연 처리 복구 워커(workers.py: reclaim_stale_leases, reconcile_pending_receipts, reconcile_stale_attention), 복식부기 및 예산 보존 검증 대사기(reconcile.py: LedgerReconciler, scripts/ad_coin_reconcile.py), 심사 이의 제기 워커/워크플로(commercial.py: submit_review_appeal, decide_review_appeal, adc2_review_appeals).
  폐쇄 SQL 레지스트리 452개 동기화, v2 단위/통합 회귀 시험 154/154 전수 통과, Ruff 0건, 운영 및 개발 서버 무영향 격리 완료.
- AI AD Coin v6.2 WP-04 P1 전체 라이프사이클 및 29개 API 완성 (2026-11-08, 백엔드): PostgreSQL 전용 v2에 P1 13개 테이블 스키마(p1_schema.py), Ed25519 JWS 서명기(receipts.py), 4대 비동기 워커(workers.py: W01 증거/정산, W02 영수증 서명, W03 attention 만료/예산 반환, W04 일일 리포팅 계획/발행), 캠페인 리비전 수정(revise_campaign), 자격증명 어댑터(auth_adapter.py) 구현. OpenAPI v6.2의 29개 API 전 경로 및 폐쇄 SQL 397개 등록 완료. 격리 PostgreSQL 4개 회귀 시험 119/119 전체 통과(test_ad_coin_v2_contracts 31, test_ad_coin_v2_persistence 38, test_ad_coin_v2_commercial 42, test_ad_coin_v2_p1 8), Ruff 0건. 사용자 개발 서버 및 운영 DB 미수정.
- Chat 고르기 화면(2026-11-05, 프론트앤드, 사용자 "고르기 화면 만들기"): 검색과 RAG의 needs_choice(확신 낮음, 요청 약 10%) 응답에서 카드 3개를 모두 펼치고 위에 안내·Say more, 카드마다 Choose this option(44px). 고르면 그 카드만 남고 Change choice로 되돌림, 오른쪽 패널도 고른 카드로(chat-choice 이벤트), 서버 요청 없음. 보통 답변은 그대로(1장+접힌 대안). 운영 자산을 가로채 띄운 Playwright로 데스크톱 라이트·폰 다크 axe 위반 0·오류 0 확인. choice-ui-frontend-20261105-r1(choice-frontend-r1 위) 게이트 통과·배포(활성 b), 운영 실요청 'something for images'로 확인. 시험 tests/test_chat_needs_choice.py.
- 되묻기(단계 4, 2026-11-05 16시, 사용자 "되묻기"·"배포"): fast_chat이 1위 도구와 요청의 qwen3-embedding 유사도 0.70 미만이면 추천 3개를 유지한 채 needs_choice·confidence low로 되묻는다(부분 답·다시 거르기·다음 페이지 제외, 유사도 못 재면 평소대로). 평가 도구는 되묻기를 직접 답과 따로 센다(ASKED). 나란히(4샤드): 직접 답 정밀도 tuning 90.6→93.5%, holdout 86.9→93.0%, 정답 총수 유지. 첫 측정은 부하 15로 실패·흔들려 다시 잼. 배포 choice-frontend-20261105-r1(ad-coin-frontend-20261105-r6 위, 활성 a), 게이트 93→95/110, 운영 needs_choice 확인.
- 로그인 점검 정보 수준 1·2번 수정(2026-11-05, 프론트앤드, 사용자 "고쳐서 배포"·"관리자 배포"): dashboard agent.kind esc 11곳, provider-connections.js 문서 링크 https 검사. info-fix-frontend-20261105-r1(ad-coin-r3 위, 게이트 통과, 활성 b), info-fix-admin-20261105-r1(wf-admin-20261102-r1 위, 게이트는 원래 판과 같은 이유로 실패, 실패 목록 동일 확인 뒤 사용자 승인 배포, 활성 b). 관리자 서비스는 11-02 판 기반이라 다음 admin 배포는 최신 코드로. → reports/프런트엔드 보안 점검 검증·추가 점검 2026-11-05.md 8절
- 로그인 화면 보안 점검(2026-11-05, 프론트앤드, 사용자 "로그인 화면 점검"): 운영 릴리스 코드로 격리 앱 구성, 익명 847 경로(고객 401/303, admin 401·403), 고객 A·B 교차 74 경로·탈취 6종 모두 거부, CSRF·다른 Origin 403, 쿠키 __Host-·HttpOnly·Lax, 로그인 뒤 이동 허용 목록, 고객 화면 위험 출력 함수 0, admin CSP nonce+script-src-attr none. 정보 수준 3건(dashboard agent.kind esc, 문서 링크 https 검사, admin 껍데기 공개). → reports/프런트엔드 보안 점검 검증·추가 점검 2026-11-05.md 7절
- 의존성 취약점 점검(2026-11-05, 프론트앤드, 사용자 "pip-audit 진행"): 운영 6개 서비스 릴리스 .venv(60개, lock과 일치)·.venv-tests(70)·lock 5개 pip-audit(PyPI·OSV) 0건, edge-gateway npm audit 0건. .venv-security와 deploy/DEPENDENCY_MAINTENANCE.md 절차가 이미 있었음. → reports/프런트엔드 보안 점검 검증·추가 점검 2026-11-05.md 6절
- 보안 정리 2차(2026-11-05, 프론트앤드, 사용자 "이어서 진행"): testclient 분기 2곳 제거(conftest에서 시험 클라이언트 127.0.0.1), 검색어 든 탐색 캐시는 sessionStorage·옛 localStorage 항목 삭제. sec-cleanup-frontend-20261105-r1(ad-coin-r2 위) 배포(활성 b)·운영 확인. 전체 pytest 133 실패는 의미 순위 vectors Mock 원인(변경 전후 동일). 남음: pip-audit, 로그인 화면 점검. → reports/프런트엔드 보안 점검 검증·추가 점검 2026-11-05.md 5절
- 보안 점검 검증·추가 점검(2026-11-05, 프론트앤드, 사용자 "추가 점검·1번 수정"): 다른 세션 보고서(134aca61 사본) 검증, 운영 판과 차이 39개 파일 추가 점검(새 브라우저 코드 이스케이프·ReDoS·변조 본문·RUM·discover) 이상 없음. 고침: /api/agents 큰 ID 500→404(BIGINT 밖), /chat 본문 null이 "None" 검색되던 것→빈 요청. id-range-frontend-20261105-r1(neighbor-focus-r1 위) 게이트 통과·배포(활성 a)·운영 확인. testclient 분기 2곳·localStorage 키·pip-audit 남음. test_fast_single_recommendation 9건은 의미 순위 vectors 모의 문제(검색과 RAG). → reports/프런트엔드 보안 점검 검증·추가 점검 2026-11-05.md
- 최신 자료 조사·추가 실험(2026-11-05, 사용자 "최신 정보로 진행"·"내려받아 시험"·"문서 확장")
  - 논문·업계·SNS 조사: 2단 구조(임베딩 → 재순위 모델)가 표준, 점수 분포로 기권, 기준값은 별도 데이터로. 출처는 보고서 6.7절과 대화.
  - qwen3-embedding:0.6b를 로컬 Ollama에 내려받음(639MB). 재순위 효과 없음, 확신 AUROC 0.767→0.883, 기권 이득 작아 넣지 않음.
  - 문서 확장 시험(scratchpad dx/expand_lite.py, 맥미니 8병렬 0.93건/초): 낱말 검사 통과 변화 0, 의미 유사도 이득도 작음 → 전체 생성 보류. 병목은 요청 핵심어 낱말 검사. → 보고서 6.7절
  - 의미 기반 통과(qwen3 이웃 낱말 + 유사도 0.75): 오프라인 tuning 6/6·holdout 4/4였으나 1,089건 나란히 비교에서 효과 없음(667→666, 242→240) → 넣지 않고 작업본 되돌림. qwen3-embedding:0.6b는 로컬 Ollama에 남아 있음(쓰는 곳 없음).
  - 답 없는 요청 시간 예산(3.5초·5.0초): 둘 다 정확도 하락(tuning −12/−13)이라 배포 안 함, 커밋 되돌림. budget-frontend-20261105-r1은 패키징만 하고 폐기. 낮은 부하 기준선: tuning 665/800·정밀도 90.2%, holdout 241/289·87.0%·응답률 94.7%. 8샤드 측정은 부하를 8~15로 올림(시간 측정은 샤드 줄여서).
- 추천 정확도 단계 2 첫 단계(2026-11-04 밤~11-05 새벽, 사용자 "시작"·"배포", 병렬 측정 요청)
  - 병렬 평가: scripts/evaluate_chat_parallel.py(최대 8샤드, 샤드마다 DB 연결 1·모델 슬롯 1, DB 연결 40이면 정지). 1,089건 약 6.5분(전엔 1시간+).
  - 현재 운영 전체(재순위 전): tuning 623/800·정밀도 88.1%, holdout 219/289·84.6%(아침 553·83.3%, 196·84.8%). 응답률이 주로 오름.
  - 재순위 실험(운영 읽기 전용): 정답이 후보 10개 안 93%·1위 85%. 로컬 LLM 목록 고르기는 더 나쁨(+1/−38, 강제 선택 +6/−8). 임베딩 유사도(기준값은 tuning만으로 0.0 선택: +28/−5) → holdout +13/−3.
  - fast_chat.semantic_first: 첫 페이지 후보 10개 중 요청과 도구 설명이 가장 가까운 것을 1위로(0.8초 넘거나 실패 시 원래 순서). 나란히 1,089건: tuning 625→652·정밀도 87.6→91.8%, holdout 222→228·85.4→88.2%, 중앙값 +0.5초.
  - 배포 semantic-first-frontend-20261104-r1(lang-context-r1 위, 활성 a), 게이트 87→90/110. 운영 10건 중앙값 1.7초·최대 3.0초, rv1 flight status 1위 Flightstats로 해결.
  - 동의어 보완(사용자 "계속"·"배포"): fast_chat.neighbor_focus. 다른 검색이 모두 실패하면 의미가 가장 가까운 목록 30개 중 30% 이상이 공통으로 쓰는 낱말(요청에 없고 카탈로그 2% 이하) 최대 2개로 다시 검색, 고른 도구와 요청 유사도 0.73 이상일 때만 답함(tuning으로 결정: 새 답 39·95%). 확신 기준 없이 넣으면 정밀도 −2%p라 기준 추가. 나란히 1,089건: tuning 639→668(정밀도 91.1→90.1%, 응답률 84→89%), holdout 225→239 새 실패 0(정밀도 86.4→87.2%, 응답률 88→93%). 새로 답한 요청은 순차 p50 3.6초·최대 5.5초.
  - 배포 neighbor-focus-frontend-20261105-r1(semantic-first-r1 위, 활성 b), 게이트 89→95/110. 커밋 때 패치 한 덩어리가 HEAD에 안 붙어 빠진 채 커밋 → 보완 커밋으로 수정(릴리스는 작업본으로 만들어 영향 없음).
  - 운영: "compute text embeddings…" 새 경로로 답함, "emotion analysis…"는 기준 미만이라 답하지 않음, 날씨는 TidesAtlas get_weather(평가 환경은 Faceabot Weather).
- 추천 정확도 단계 1 질문 쪽(2026-11-04 밤, 사용자 "단계 1 시작"·"질문 쪽부터"·"배포")
  - 손실 분석: 참조 문구로는 찾는데 사용자 문구로 못 찾은 161건 중 후보 600개에 없음 100, 통과 검사 탈락 60, 미선택 1. 원인은 핵심어가 기능어가 아닌 것(오타 37, 장소·대상, 동의어, 긴 맥락 배경, 한국어 핵심어 빔 14).
  - 오타 교정: concierge/catalog_spelling.respell(어휘 22,354개 catalog_vocabulary.json, scripts/build_catalog_vocabulary.py). 한 글자 거리·첫 글자 제외·대문자 이름 제외·애매하면 그대로. Chat과 discover에 적용(정책 해시 아님).
  - 나란히 비교: 오타 사례 tuning 57→66/80, holdout 22→27/31. 다른 요청은 진짜 오타 3건만 바뀌고 통과. 커밋 앞 커밋.
  - 배포 typo-fix-frontend-20261104-r1(evidence-ui-r1 위, 활성 a), 게이트 83=83/110. 운영에서 교정 확인, 새 오류 0.
  - 남은 손실: 동의어·바꿔 말하기(의미 기반 통과 필요, 단계 2와 함께), 긴 맥락 배경 문장, 한국어 20건.
  - 한국어·긴 맥락(사용자 "한국어·긴 맥락"·"배포"): llm.rewrite_task가 다른 언어 요청만 바쁜 슬롯을 1초 기다리고 3초 허용(모델은 실패하던 한국어 10건을 약 1초에 정확히 번역). fast_chat.retrieval_text가 "Requirement:/Task:/automate one step:" 요구를 앞세움. 한국어·긴 맥락 283건 214→224(커버리지↑, 정밀도 유지). 배포 lang-context-frontend-20261104-r1(typo-fix-r1 위, 활성 b), 게이트 84→85/110. 운영: "웹페이지 내용 긁어오기"·"두 날짜 사이 일수 계산"이 되묻기 대신 추천, 새 오류 0.
- 5점 7단계 화면(2026-11-04 저녁, 프론트앤드): Chat 추천 카드마다 접힌 "Evidence: N of 3 recorded"(마지막 헬스체크·시험 호출 성공/실패·시각·보고서 번호·선택 도구 확인, evidence.unknown은 "Unknown — no record"), 이유 문장은 서버 reason.text 우선, 오른쪽 패널에 헬스체크·시험 호출 두 줄. evidence-ui-frontend-20261104-r1(reason-evidence-r1 위, 릴리스 사본 파일에 패치) 게이트 통과·배포(활성 b), 운영 화면 확인. summary 높이 43px(전역 24px !important 때문, AA 충족). 시험 tests/test_chat_recommendation_evidence.py. → reports/전문가 4인 재평가 2차 2026-11-04.md 6.4절
- 2차 재평가 4~7단계(2026-11-04 저녁, 사용자 "4~7단계 먼저"·"배포")
  - 4 평가 자동화: scripts/release_gate.py가 Chat 파일(정책 해시 7개+Chat 경로)이 바뀐 릴리스에서 고정 표본 110건(review 10+holdout 100)을 운영·새 릴리스로 평가, 새 실패는 양쪽에서 다시 재서 데이터 변화·흔들림을 빼고, 새 실패−새 통과 2 이상이면 배포 거부. 1회 약 6.5분.
  - 5 조건 충족 우선(fast_chat.condition_first). rv1용 단어 쌍 규칙은 holdout −3·+0이라 뺌(rv1은 단계 2 과제).
  - 6 추천 이유: "the listing covers" 대신 과업·도구·조건 문장, 응답 reason 객체.
  - 7 근거: Chat recommendations[].evidence, discover items[].evidence(health_checked_at, trial_call, selected_tool_check, unknown). 탐색 카드는 기존 last_check_at·trial_ok·connection_readiness.
  - 나란히 비교: holdout 214=214, review 9=9, 판정 변화 0. 커밋 47f88f70.
  - 배포 reason-evidence-frontend-20261104-r1(explore-prefilter-r2 위, 활성 a). 게이트: 85→84/110, 새 실패 stock_quote-ask는 운영 사본에서도 실패(데이터 변화) → 게이트가 양쪽 재측정하도록 고침.
  - 남음: rv1 flight status(FareEagle 1위), 이유 문장의 "forecast range, forecast window" 중복 표기.
- 탐색 사전 거르기(2026-11-04 17시, 프론트앤드 세션이 넘긴 탐색 서버 시간 단축, 사용자 "배포")
  - 원인: 결과 적은·0건 검색이 후보 600개 문서를 끝까지 읽음(큰 MCP 묶음 1.4초).
  - 고침: 한 묶음에서 통과 가능한 문서가 절반 미만이면 다음 묶음은 문서 텍스트만 먼저 읽고(explore_document_reader.texts), named_match·text_may_match를 통과할 수 없는 문서는 전체 읽기 생략(hybrid_explore._in_ranked_batches). jsonb 캐스트는 NUL 이스케이프 문서에서 실패해 Python 파싱으로.
  - 검증: 운영 읽기 전용, 같은 프로세스 끔·켬 교대 70건 결과 같음, 합계 39.4→33.4초, p95 1.40→1.11초. 커밋 20e002a7.
  - 배포 explore-prefilter-frontend-20261104-r2(home-auto-r1 위, 게이트 56 통과, 활성 b). 배포 뒤 처음 보는 40건(부하 6.8): 서버 p50 1.03·p95 1.63·최대 3.07초, 2.4초 초과 2건, 새 오류 0. 문서 재생성 17:30 완료 뒤 처음 보는 20건(부하 2.9): 중앙값 0.90초, 최대 1.40초, 3초 초과 0(일부 검색어는 앞선 측정에서 쓴 것).
  - Chat 빈 결과(PDF 요약, calendar alerts)는 검증된 작동 목록이 없는 것(참조 검색도 0건). rv1 flight status는 새 데이터(FareEagle get_airline_info 1위)로 실패, 순위 과제.
- 5점 8~11단계(2026-11-04 17:30, 프론트앤드): 0건·오류 다음 행동(recovery-a11y r1·r2), axe 36조합 위반 1→0(다크 Chat 버튼), 홈 프로토콜 기본값 A2A→Auto(home-auto-r1), 자체 과업 시험 3/5(실패 2건은 검증 목록 없음), D2 부분 적용은 이득 없음으로 미채택. 임시 인덱스 커밋 뒤 기본 인덱스에 18개 파일이 되돌림 상태로 남은 것 발견·정리. 7단계는 검색과 RAG 알림 대기.
- 탐색 서버 시간 원인 분석(2026-11-04 16:10, 프론트앤드): candidates 순차 읽기 7.5초·묶음 읽기 4.4초·과업 일치 검사 3.4초(검색 6건). 0건 검색어가 가장 느림(600 후보 전부 읽음). 구현은 사용자 지시로 검색과 RAG 세션에 넘김(2차 보고서 6.2절).
- 5점 1~3단계(2026-11-04 15:50, 프론트앤드): five-step-frontend-20261104-r2(lead-frontend-r1 위) 배포. 홈 숫자 data-primary, 배너 × "Essential only", RUM(/api/rum, rum.py, logs/service-frontend/rum, 식별자 없음·GPC/DNT 제외). r1이 lead-frontend를 몇 분 덮은 사고 → r2로 복구, 배포 직전 슬롯 재확인. 탐색 재측정은 부하 7~8에서 체감 p95 5.3초(서버 3.5초)로 미달, 부하<5 자동 재측정 대기, 타이머 밖 대기 1.6~4.1초 발견.
- Web Bot Auth jobs 켬·5점 개선 순서(2026-11-04 15:00, 프론트앤드, 사용자 승인): bot-auth-jobs-20261104-r1(gateway-scope-jobs-r1 + 서명 파일 4개, service_host는 3줄만) 배포(--no-prune). 검색과 RAG가 lead-jobs-r2를 이 위로 다시 패키징(배포 승인 대기). 2차 재평가 보고서 6절에 5점용 11단계(1~3·8~9 프론트앤드, 4~7 검색과 RAG, 10 실사용자 시험).
- 추천 정확도 단계 0(2026-11-04 오후, 사용자 "단계 0 시작"·"중단없이 진행")
  - 평가 세트·도구: 1,089건 세트(능력 묶음 130개, 묶음 단위 holdout, 생성기 scripts/build_chat_eval_set.py), 평가 도구에 REPEAT·RECALL·SUBSET.
  - 기준선(round10-r2): 정밀도 83.3/84.8%, 응답률 77%, 재현율@50 54%, 흔들림 7건.
  - 규모 25·50·100%: 정밀도 거의 그대로, 응답률만 오름. 막는 것은 요청 이해다.
  - 원인: 질문형 26%("there"가 핵심어), 흔들림은 LLM 다시 쓰기의 바쁨·2초 포기.
  - 고침: llm.py 성공 캐시, selection.NARRATIVE_LEAD 맨 앞·두 명사·첫 문장, 다른 언어 중심 번역 제외(rv3), discovery 문서 요약(rv2)·웹사이트 가동(rv10).
  - 1k 재평가: 맞음 553→612/800, 196→215/289. 정밀도 87.3/84.6%, 흔들림 2. review 7→10/10.
  - 릴리스 lead-frontend-20261104-r1(bot-auth-r2 위)·lead-jobs-20261104-r2(bot-auth-jobs-r1 위, 서명 파일 유지) 패키징·검증, 정책 해시 653423698c06. 사용자 "둘 다 배포": 15:3x jobs → frontend(게이트 56 통과, 활성 b). 운영 확인: 질문형 항공편·웹사이트 상태·영→한 번역이 맞는 1위, PDF 요약은 "없음", 5xx 0. 재생성 중 처음 보는 금융 검색어 1.1~3.2초(첫 1건 3.2초, bond yield curve 처음 연결 4.5초) → 재생성 끝난 뒤 다시 잴 것. 15:4x 프론트앤드가 five-step-frontend-20261104-r2(lead-frontend-r1 위 13개 파일)로 바꿈: 세 파일·정책 해시 653423698c06 유지 확인. 대기 슬롯 a(five-step-r1)에는 세 파일이 없으니 a로 되돌리지 말 것. 다음 frontend는 five-step-r2 기준.
  - 보고: reports/에이전트 증가 대비 추천 정확도 99% 개선 방안 2026-11-04.md 6절
- Web Bot Auth 켬(2026-11-04 12:50, 프론트앤드, 사용자 지시): 키 gateway-data/web-bot-auth/ed25519.pem, 경로는 gateway-data/web-bot-signer.env(agentcon.env에 넣으면 배포 도구·옛 릴리스가 멈춤 — 한 번 넣었다 즉시 되돌림). frontend bot-auth-frontend-20261104-r2(활성 a), 키 디렉터리 200·서명 검증됨. **jobs 다음 배포 때 web_bot_signer.py·broker/discovery.py·service_host.py·scripts/agentcon_config.py를 실어야 수집기도 서명함**(백엔드 세션 종료로 미전달). → reports/전문가 4인 재평가 2차 2026-11-04.md 4절
- 전문가 재평가 2차(2026-11-04 12시, 프론트앤드): UX 3.9·디자인 4.3·AI 3.4·웹개발 4.5. 폰 12px 미만 글자 8곳 수정(small-text-frontend-20261104-r1, 활성 b). 추천 항목(rv2·rv3·rv10, 평가 자동화, 조건 줄)은 검색과 RAG 99% 계획에 인계. D2 숨은 화면 보류(116개 ID 직접 참조, INP 64ms). Web Bot Auth 키 생성·agentcon.env 추가는 자동 승인에서 막혀 사용자 실행 대기(보고서 4절 명령). → reports/전문가 4인 재평가 2차 2026-11-04.md
- MCP 비동기 작업(2026-11-04 오후, 프론트앤드, 사용자 "설계대로 구현"): run_workflow 도구(공개 REST 실행과 같은 검사, definition_hash 필수, taskSupport optional)와 tasks/get·result·cancel(concierge/mcp_tasks.py, 작업 ID=실행 ID.실행 키). mcp_contract에 넣어 런타임·mcp.json·홈 JSON 14개 도구 일치. mcp-tasks-frontend-20261104-r2 배포(활성 a), 운영에서 워크플로 38번 작업 실행 completed 3/3 확인(첫 회는 제공자 일시 실패). → reports/전문가 4인 재평가 2026-11-04.md 6.6절
- 추천 정확도 99% 개선 방안 조사(2026-11-04): 활성 23.7만·하루 약 9천 증가·중복 이름 1.8만. 논문(RAG-MCP, Tool-DE, TOOLQP, RATED, 확신도 기반 응답)·SNS 정리, 단계 0~5 제안(측정 → 문서 확장·중복 묶기·증분 갱신 → 3단 검색·재순위 → 실행 결과 밴딧 → 확신도·되묻기). → reports/에이전트 증가 대비 추천 정확도 99% 개선 방안 2026-11-04.md
- 4분야 재평가·남은 작업 1~10(2026-11-04 10시, 프론트앤드): 재평가 UX 3.7·디자인 4.1·AI 3.2·웹개발 4.3. 소규모 개선 review-small-r1(07:23: 문서 edge s-maxage 600, 폰 배너 위로, 다크 주 버튼 흰 글자, 되묻기 선택지)·Cloudflare Browser TTL을 Respect Existing Headers로. 1~10: pytest.ini·흔들림 3건 커밋, Chat 평가 세트 review 10건, fast_chat merged_fit·subject_first(rv4 통과, 회귀 0), 데스크톱 배너 한 줄·홈 숫자 위계, WebMCP 도구 2개(panels-bootstrap.js), Web Bot Auth 서명(agent_market/web_bot_signer.py, public_client 훅, 키 없으면 꺼짐, 디렉터리 404). round10-frontend-20261104-r2(gateway-scope-frontend-r1 위) 배포(활성 b). 7번 숨은 화면·8번 MCP tasks는 설계만. 남음: 서명 키 생성·jobs 반영(백엔드, 사용자 승인), selection 수준 실패 rv2·rv3·rv10. → reports/전문가 4인 재평가 2026-11-04.md 6절
- 탐색 다어절 금융 검색어 지연(2026-11-04 09:18): 원인은 gateway.pipeworx.io 리스팅 1,917개가 게이트웨이 공용 도구 약 44개를 똑같이 실은 것(금융 검색어마다 후보 수백 개, 승인 검사 약 1.6초, 승인 1건). selection.task_scope_matches 앞에 싼 필요조건 `_coherence_possible`을 넣었다(판정 동일: 운영 45개 검색어·무작위 4,000건). jobs gateway-scope-jobs-20261104-r1(09:16)·frontend gateway-scope-frontend-20261104-r1(09:18) 배포, 게이트 56 통과, 정책 해시 8f329896 → 문서 재생성 11:15 완료. 재생성 중 처음 보는 40개 중간값 1.58초·최대 3.77초, 완료 뒤 새 30개 중간값 1.11초·최대 2.63초·3초 초과 0(bond yield curve 1.33초). 미커밋: selection.py, tests/test_selection_coherence_prefilter.py. → reports/탐색 다어절 금융 검색어 지연 2026-11-04.md
- 품질 정책 v1 운영 적용 완료(2026-11-04 08:39): r2가 id 50154에서 result_limit(500행 32MB 초과)로 멈춤 → 배치 절반 줄이기(760dcf82), jobs quality-policy-jobs-20261104-r3 07:08 배포(사용자 승인). 결과 A 비율 MCP 23.0%·A2A 1.6%·x402 46.8%, 평균 81.6·80.8·84.4. 정책 미적용 5건(10-16 manual blueprint 행, 조사 없이 94점·trial_ok=1)은 guard+record_evaluation으로 점수 없음 처리, trial_ok NULL(사용자 승인). 탐색 처음 보는 검색어 36개 중 3초 초과 1건('bond yield curve' 3.96초, 다시 보내도 2.19초, 따로 조사). → reports/에이전트 품질 평가 업그레이드 2026-11-03.md 5-1절
- 웹어워드 대비·agent-desktop·복원 연습(2026-11-02): 출품 확정이 아닌 품질 대비. 0~6단계와 13번, 버튼 대소문자까지 배포했다(award-buttons-frontend-20261102-r2; 내려받는 웹앱은 관리자 사본과 같아야 해서 "Run Workflow" 유지, 결과로 스크롤은 검색창에서 검색할 때만). 9개 화면 모두 12px 미만 글자 0, 이름 없는 조작 요소 0, 작은 누를 영역 0. 페이지 분리는 생략(한 페이지 앱). 'tide tables' 0건은 selection.capability_terms 원인만 기록(정책 해시 파일). 배포 전환 감시 2,376회 실패 0. 백업 복원 연습 11분·오류 0·리소스 237,585 일치(deploy/DEPLOY.md). agent-desktop(vercel-labs) 설치, 스킬 ~/.claude/skills/agent-desktop, 전역 ~/.claude/CLAUDE.md. 기록: reports/웹어워드 심사 예상 지적.md. 전체 시험(nice) 10,345 통과·4 실패 → 내 변경 원인 2건 고침, log_retention 1건은 기존 실패, pearl_task_ux는 실행 중 시험 파일 변경.
- 남은 작업(2026-11-02 오후): Chat 쓰기 묶기(VisitorBook.batch), 워크플로 오타 교정(p13, 73/73), 핵심어 3개(g3·h15, Chat 149→151/159), capability_text 새 정리 운영 확인(잠금 안 4.6ms), pg_prewarm은 안 함. 릴리스 chat-writes-frontend-20261102-r2·chat-terms-jobs-20261102-r1 패키징·검증, 12:53 jobs·12:55 frontend 배포(사용자 승인), 5xx 0, 재생성 중.
- admin 워크플로 생성 맞춤(2026-11-02 10:30): wf-admin-20261102-r1(idle-reaper-admin-r1 + 워크플로 4개 + workspace_access.py) 배포(활성 a). 사본 비교 새 실패 0, 43건 회복, 오류 0. 다음 admin은 이 릴리스 기준.
- 정책 파일 묶음(2026-11-02 09:00, 사용자 "묶어서 진행"): capability_text 정리를 읽기 스냅샷 검색 + id 재확인 삭제로(잠금 밖), selection.capability_terms에 text-to-speech·Wikipedia·similar 규칙 → Chat 147→150/159(94.3%, 실패 전환 0). bbdbf971(프론트앤드)·e6335cac(백엔드)도 함께. jobs policy-bundle-jobs-20261102-r1, frontend policy-bundle-frontend-20261102-r2(award-stage4 위) 배포, 게이트 56 통과, 5xx 0, 재생성 중 탐색 1.7~2.8초. 확인할 것: 재생성 끝난 뒤 탐색 속도, 다음 정리 때 잠금 보유.
- 워크플로 생성 p11(2026-11-02): 통번역 실패 시 "-고"·"그리고" 절마다 번역(workflow_model_proposer), 이어지는 "and also find related papers" 분리(workflow_goal_policy), 단계 주제 덮어쓰기를 apply_step_subjects로(후속 절은 모델 질의 유지). 평가 72/73(98.6%, holdout 30/30), 남은 실패 p13(오타 영어). 정책 해시 아님 → frontend만. workflow-split-frontend-20261102-r1(award-stage2-r1 위 4개 파일) 07:38 배포(활성 b), 새 실패 0, 5xx 0. admin은 11-01 개선도 없음(파일 70개 차이) → 따로.
- 스냅샷 이중 실행(2026-11-02 0시): 대기 슬롯은 시작 때 한 번만 만들고 활성 슬롯만 10분마다 갱신(report_snapshot.keep_fresh serving, service_host.serving_slot + AGENTCON_SERVICE_STATE_DIR). r5가 07:01 먼저 배포되어 그 위 standby-snapshot-frontend-20261102-r2를 07:03:47 배포(활성 a). r5의 customer_batch.py gzip 버그로 고객 워크스페이스 첫 화면 장애, 프론트 세션이 r6(이 위 + customer_batch.py) 준비.
- Chat 503 조사(2026-11-01 20시): 원인은 전역 쓰기 잠금(pg_advisory_xact_lock, lock_timeout 1s)과 Chat 쓰기 5개 이상. 표본 결과 jobs 벡터 대기열 정리 DELETE(LIMIT 500)가 잠금을 0.91초 보유. jobs vector-retention-r1(정리 검색을 읽기 스냅샷으로) 21:09 배포. 판정 경계 버그로 옛 in-lock 정리가 가끔 돎 → r2 패키징·승인 대기. frontend는 활성이 centre-progress-r3로 바뀌어 writer-retry-frontend-20261101-r3(그 위 2개 파일)로 다시 만듦. 넓은 비교(r1 기준 351개 파일)에서 새 실패 0(탐색 브라우저 시험 1건은 기준도 1/8 흔들림), r3 사본 핵심 158건 통과. jobs r2(22:58)·frontend r3(22:59) 배포. 배포 뒤 옛 in-lock 정리 0회, 0.5초 이상 보유 12→2, lock timeout 0, 5xx 0. 남은 최장 보유는 capability_text 정리 DELETE 0.81초. → docs/qa/chat-write-lock-503-2026-11-01.ko.md
- 워크플로 생성 품질(2026-11-01 밤): 읽기 전용 평가 `scripts/evaluate_workflow_goal_quality.py` + 사례 73건(`tests/data/workflow_goal_quality_cases.json`). 41.1% → 97.3%(holdout 30/30): 없는 기능 이름 붙이기·모호하면 되묻기·해로운 목표 거절·단계마다 자기 주제·번역 실패 시 영어 재작성 요청·한국어 연결어 (workspace_goal_coverage/workspace_app_factory/workflow_goal_policy, 정책 해시 아님). r1은 기준 read-only-r1의 버그(CustomerWorkspaceAccess._tx readonly TypeError, 프론트 세션 발견)로 폐기. r2·r3는 기준 변경으로 쓰지 않음. workflow-goals-frontend-20261101-r4(활성 read-only-r3 + 워크플로 3개 + fast_chat 엔진 활성 조건 수정)를 활성 사본과 비교(새 실패 0, 탐색 브라우저 시험 1건은 단독 0/8로 흔들림) 후 19:52 배포(활성 a). 19:49 첫 시도는 이전 슬롯이 스냅샷 중이라 timeout, 19:50 배포 뒤 내 확인 스크립트 파싱 오류로 잘못 롤백했다가 19:52 재배포. 배포 뒤 5xx 0. 다음: 소스 분석 snapshot-pause-r2를 r4 위로, /chat 쓰기 잠금 503 조사. → docs/qa/workflow-goal-quality-2026-11-01.ko.md
- Chat 답변 품질(2026-11-01 저녁): 읽기 전용 평가 `scripts/evaluate_chat_answer_quality.py` + 사례 159건(tuning 105·holdout 54, `tests/data/chat_answer_quality_cases.json`). 운영 88.1% → 92.5%(결과 0건일 때만 도는 후보 공유어 재검색·요약 기준 100자·오타 재작성·비밀번호 노출 감지, fast_chat/chat_guidance/chat_query_rewrite/chat_progress). 릴리스 chat-recovery-frontend-20261101-r1(support-lock-r1 기준, 정책 파일 없음 → jobs 불필요) 16:32 배포(활성 a, b=snapshot-progress-r2). 운영 확인: 원격 일자리·오타·식당·번역 추천, 비밀번호 노출 차단, 진행 스트림 정상, 응답 0.8~4.4초, 5xx 0건. 남음: selection.py 핵심어(정책 파일, jobs 동반), 검색 흔들림, 워크플로 생성. → docs/qa/chat-answer-quality-2026-11-01.ko.md
- 서버 맥 최적화·DB 매일 백업(2026-11-01): 사용자가 잠자기 방지(disablesleep 1, AC·배터리 sleep 0)·Power Nap 끔·멈춤 시 재시작·macOS 자동 설치 끔·방화벽 켬 적용. 그동안 DB 백업이 전혀 없었음 → `scripts/scheduled_backup.py`(runtime_snapshot 감싸기, 연결 19개 넘으면 대기, 7개 보관)와 launchd `biz.agentconcierge.backup`(매일 04:30) 등록. 운영 1회 343초, 덤프 2.7GB, 시험 5개 통과. Mac mini 공유(/Volumes/<공유>/agentconcierge-backups)에도 복사(launchd 환경 198초, sha256 일치), 시험 9개. 남음: 복원 연습, 재부팅 뒤 공유 자동 마운트, Ollama 로그인 항목, AirPlay 수신 끔. 미커밋 → deploy/DEPLOY.md
- 응답 시간 정책·보고서 스냅샷·Chat 진행 표시(2026-11-01 오후): 사용자 정책(탐색 모든 조작 3초·실시간 불필요, RAG 5초·99%, 복잡 10/15초)을 CLAUDE.md·메모리에 기록. 'Recorded reports' 체크를 10분마다 만드는 메모리 스냅샷(report_snapshot.py, PG 파서·ts_rank 재현, 운영 비교 결과 거의 동일, 0.1~7초→0.15~0.5초)으로 답함. /chat이 `Accept: text/event-stream`이면 단계 이벤트를 보내고 화면은 대화 영역에 단계·경과 시간 표시(chat_progress.py, operating.js/css). Chat 현재 2.1~5.2초, 정확도 99%는 미측정. r1을 14:30 배포했으나 패치 스크립트 index 오매칭으로 /chat JSON 처리가 빠져 500, 14:32 롤백(약 2분). 고친 snapshot-progress-frontend-20261101-r2(활성 screen-policy-r2 기준, 릴리스 사본 시험 새 실패 0건)를 14:56 배포(활성 b). 운영: Chat 200, 진행 스트림 정상, 스냅샷 8,207건 65.9초, has_report 첫 0.6~1.75초, 5xx 0건. 일반 첫 검색은 4.2~7.9초로 정책 초과 → 소스 분석 세션이 담당. 관련 시험 1,737 통과, 실패 6건 중 내 것 1건 수정, 나머지는 시험 중 다른 세션 파일 변경·workflow 시험(내 변경과 무관). → 설계 문서 8.36
- Edge 게이트웨이 모니터링 오류(2026-11-01): 어드민 Origin 중계 4.2만 건은 워커가 캐시 적중에도 Origin 표시를 붙인 오집계, Edge 준비 실패 4,862건은 관측 1회 실패 즉시 무효화+사유 뭉침, 공개 501은 의도된 x402 안내, 503은 Provider 실패. 워커·output_relay·output_monitor·monitor·edge-monitor.js 수정, 워커 88·Python 엣지 223 통과 → `reports/Edge 게이트웨이 모니터링 오류 분석 2026-11-01.md`. 배포: `edge-monitor-frontend-20261101-r1`(explore-speed-r1 기준, 활성 b)·`edge-monitor-admin-20261101-r1`(admin r7 기준, 활성 b), 워커 버전 2d9e2799(배포본 사본 `reports/edge-monitor-errors-2026-11-01/`). 4파일 오버레이(actor() 읽기 전용 변경 포함). **다음 frontend·admin은 이 릴리스 기준**(프론트앤드 세션 screen-policy-r2가 이미 이 기준). '소스 분석' 세션이 요청한 dashboard.py·application_store_postgres.py·security.py는 승인 범위 밖이라 넣지 않음
- 탐색 속도(2026-11-01 오전): 백필 r2(docs-jobs-r5 기준) 07:03 배포, 10분 98회·60초→2회·2초. 보고서 체크 첫 검색 9~12초 → count GIN 접두어·page 2,000행·Redis 공유로 5초(결과 동일). ranking_rows md5(65~294ms)를 generation 확인 기록으로 생략(확인 뒤 13~29ms). 시작 시 전체 확인 패스는 HNSW를 캐시에서 밀어내 ANN 40→420ms라 버림. 릴리스 explore-speed-frontend-20261101-r1(다른 세션 미배포 qa19-r10 기준, 관련 시험 1,528 통과) 13:27 배포(활성 a, b=r9). 배포 뒤 보고서 체크 첫 검색 0.8~2.4초, 다른 조건 0.3~1.3초, 5xx 0건. **다음 frontend는 explore-speed-r1 기준**(프론트엔드 세션 회신). 코드 미커밋. 남음: 가중 tsvector 저장(스키마), pg_prewarm(재시작). → 설계 문서 8.35
- 남은 작업(2026-10-31 밤): 백필 후보 쿼리(673ms, 6초마다, 결과 0건)를 빈 결과 뒤 300초 쉬게 함 → 릴리스 backfill-pause-jobs-20261031-r1(r4 기준) 배포 승인 대기. 다른 세션 요청으로 vector-queue-jobs r2 삭제(r4 기준 유지). 로그 보관 테스트 실패는 테스트 서버 uvicorn configure_logging 탓 → notification_test_inbox 수정. 세션 헤더 테스트는 다른 작업자가 고침. agent_infra→finance 29건은 규칙 변형 2개 모두 부작용·효과 부족으로 보류(낱말 사전 보강 필요). → 설계 문서 8.34
- 헬스 체크 주기·n8n 문구(2026-10-31 밤): '2시간' 문구는 운영·소스 어디에도 없어 engine.py의 'every hour'·'6-hour'를 'periodically/Periodic'으로, 워크플로 정의(operator_workflow_categories.py) 설명에서 n8n 제거(실행 단계 package n8n은 유지). `copy-frontend-20261031-r1`(qa19-r6 + 두 파일) 배포(활성 a, b는 r5 유지). **다음 frontend는 copy-r1 기준(qa19-r6 front.py 포함).** 운영 템플릿 57번 설명은 등록 SQL에 설명 UPDATE가 없어 psql로 한 행만 수정(이전 값 조건, 새 정의와 같은 문구라 fingerprint 일치), 운영 API 확인. 단계 이름 'n8n Release Metadata'·입력 package n8n은 유지
- 벡터 대기열 최적화(2026-10-31 밤): claim_batch 쿼리 4개가 30분에 약 16분. 부분 인덱스 `legacy_vector_jobs_open`과 `legacy_vector_heads_job`(운영 PG에 없었음), 삭제는 짧은 배치 뒤 60초 쉼. 운영 사본에서 50~66ms → 0.06~4ms. 22:35 인덱스 생성, 22:42 jobs `vector-queue-jobs-20261031-r1` 배포. 10분 측정에서 쿼리 평균 0.05~0.38ms, 대기열 합계 약 5분 25초→15초, 오류 0. 다른 작업자의 docs-jobs r2를 배포하면 이 변경이 빠지므로 대신 쓸 vector-queue-jobs r2를 만들어 둠. 다음 후보: exclusions CTE(615ms×98). 미커밋 → 설계 문서 8.33
- 분류 v10(2026-10-31 오후): v9 드라이런 2,110건 중 `→docs_knowledge`가 공통 도구 묶음(1만 4천 자) 탓에 대량 오분류(Twilio·PACER 등)여서 적용하지 않음. `classify_listing`: 도구 설명이 8,000자를 넘을 때만 설명 우선, osv 보안 권고 추가. 전체 변경 2,030건, 묶음 오분류 사라짐. 넓은 안(설명 우선·가중치·식별자 제외)은 20% 표본 변경이 3~6배여서 기각. 16:02 사용자 적용 1,966건(백업 category-refresh-20261031-160200.jsonl). jobs r9(r8+classify.py) 17:25 배포, 정상. 커밋 e0ba3464 → 원격 위에 다시 얹어 푸시 59a1a795(로컬 브랜치는 원격과 갈라짐). PG 재시작(20:20, 사용자): shared_buffers 2GB·pg_stat_statements, 30분 구간 적중률 99.1%, Explore 첫 검색 중앙값 1.8→1.36초. 다음 후보: legacy_vector_jobs 대기열 쿼리(30분에 약 11분). 미커밋 → 설계 문서 8.32
- 개선 확인 12차 대응(2026-10-30, Explore 항목 제외): 24px 타깃(헤더 Test 탭·숨긴 select), Chat PostgreSQL 0건·`sending` 보정(Chat 전용 `retrieval_text`), 주 OpenAPI에 v1 entry·badge·openapi. 시험 통과, frontend `qa12-frontend-20261030-r2` 배포(r9 위 오버레이, Explore 세션은 r2 기준으로 다음 릴리스를 만들어야 함). CORS는 설계상 제한이라 사용자 결정 대기 → `reports/improvement-check-12-2026-10-30/README.md`
- CORS 절충안(2026-10-30, 사용자 결정): `/chat`·`/mcp` 읽기 전용 도구를 모든 사이트에 `*`로 개방(쿠키·Authorization 제거, Origin별 분당 60회), 실행·연락처·피드백·`/a2a`는 허용 목록만. frontend `qa12-cors-frontend-20261030-r2` 배포(r11 위). Explore 세션은 이 릴리스 기준으로 다음 릴리스를 만들어야 함
- 12차 남은 항목(2026-10-30 오후): 크롤러 본문은 이미 해결, 카테고리 페이지 본문 보강, Chat 사이트 감시+텔레그램(채널 표현·부분 채우기), 감사 스크립트 CORS 기준 갱신. 시험 통과, rest r1~r3 배포 후 Explore r15(내 변경 포함)가 활성. 재측정: 24px 0·axe 0·포커스 0, 시나리오 PASS 69/WARN 7. 엣지 워커가 다른 출처 `call`을 원 서버 검사 없이 처리 → worker.mjs 수정·시험 통과, 엣지 `05579c7d…` 배포·운영 확인(다른 출처 call 403)
- 12차 후속(2026-10-30): `hello` 설명 "Start here" 제거, `/` HTML·JSON에 `Vary: Accept`, 카탈로그 수 WARN은 판정 오류라 스크립트 수정, 메일 1위는 데이터(mifactory 검증 오르내림)라 코드 수정 없음. 릴리스 `qa12-frontend-20261030-vary-r1`(r16 + front.py·mcp_contract.py) 배포(슬롯 a, r16 보존)·운영 확인, 시나리오 mcp 17/17·llm_fetcher 6/6 PASS. 다음 frontend 릴리스는 vary-r1 기준
- 개선 확인 19차(2026-10-31): qa18-r2 배포 뒤 새 워크플로 저장 전부 409(활성 수 COUNT 쿼리가 운영 등록 SQL에 없음) → 등록된 목록 쿼리로 세게 고쳐 `qa18-frontend-20261031-r3` 긴급 배포·저장 확인, 등록 검사 시험 추가. **다음 frontend는 qa18-r3 기준.** Explore(OpenSearch·Redis 뒤) 76개: 중앙값 1.87→1.50초, p90 3.53→2.32초, 3초 초과 12→1건, 결과 동일. 반복 질의 0.66초(서버 0.02초). 에이전트 B 8/9 충족(도구 설명 5.77/6, 오류 복구 7/8, MCP 중앙값 1.42초), 시나리오 74/1/0. 새 문제: AI 제안 평생 100건 한도(QA 워크스페이스 생성 409), 워크플로 목록 50개 제한 — 새 SQL 등록 필요, 방식 결정 대기 → `reports/개선 확인 19차.md`. 후속: AI 제안 한도를 감사 기록 기준 최근 30일만 세게 수정(등록 SQL 1건 덧붙임) → `qa19-frontend-20261031-r1` 배포(활성 b), QA 워크스페이스 AI 생성 200 확인. 목록 50개 제한 → 500개(등록 SQL 2건, 운영본 workspace_typed_flows.py에는 SQL만 패치) `qa19-frontend-20261031-r2` 배포(활성 a), 51개 표시 확인. **다음 frontend는 qa19-r2 기준.** 세션 활동 연장(유휴 1시간·최대 12시간) `qa19-frontend-20261031-r3` 배포. 문서 검색 에이전트 Technical Documentation(MDN+Context7, 별도 모듈·별도 해시, 기존 해시 fa0c5038 불변) → `docs-execution-20261031-r1`, `docs-jobs-20261031-r1`, `qa19-frontend-20261031-r4`(활성 a) 배포, approve_model_contracts 운영 실행 4개 모두 성공, 운영 MCP 확인. **다음 frontend는 qa19-r4, execution은 docs-execution-r1, jobs는 docs-jobs-r1 기준.** 재로그인 뒤 세션 연장 운영 확인. 문서 과제 AI 제안은 문서 에이전트로 가지만 단계 분리 때 "Kubernetes"가 빠져 엉뚱한 문서 → topics()가 앞 대상 이름 유지하도록 수정 → `qa19-frontend-20261031-r5`(r4 + workspace_goal_coverage.py) 배포(활성 b), 운영 제안에 Kubernetes 유지 확인. **다음 frontend는 qa19-r7, jobs는 docs-jobs-r4 기준.** (r5 뒤 다른 세션 copy-frontend-r1·vector-queue-jobs-r1 위에 다시 패키징.) 문서 에이전트가 후보에서 빠짐 → 재검증기 `_recover_docs`(명시적 실패 시 실제 조회로 헬스 복구)·frontend 시작 헬스체크 추가, 승인 재실행 뒤 Kubernetes 문서 워크플로 저장·실행 2/2 성공. vector-queue-jobs-r2(내 수정 전 재검증기 포함)는 배포 금지. 남은 작업 2~4: 결과 단계 "Documentation search" 표시, docs.py 공식 문서 고정표(Django 등 12개)·Context7 제목에 라이브러리 이름·사용량 로그 → frontend r8, execution docs-execution-r2, jobs docs-jobs-r5 패키징(관련 1,167 통과), 배포 승인 대기. 배포 뒤 approve_model_contracts 재실행·QA Kubernetes 문서 워크플로 재저장 필요. backfill-pause-jobs-r1은 docs-jobs-r5 위에 재패키징 필요. 슬롯 정리는 설계상 보존이라 안 함. 전체 시험: 나머지 9,501 통과, 일시 실패 2(단독 통과). 낡은 CORS 브라우저 시험을 10-30 공개 /mcp 정책에 맞게 수정(익명 연결 허용·call 403·/a2a 차단). 남음: 문서 워크플로 저장·실행(QA 워크스페이스 활성 50개 한도, 방식 결정 필요), Django 등 공식 문서 고정표, 2단계 제목 연결 검색, Context7 사용량 관찰. QA 워크스페이스 활성 50개 한도라 저장·실행 미확인.
- 개선 확인 18차(2026-10-31): 기준 `docs/qa/usability-criteria-18.md`. qa17-r4 배포. 에이전트 B 9개 중 6개 충족(도구 설명 3.6/6·오류 복구 5/8·Chat 3.3초 미달), 사용자 A는 성공·적합·일관 충족. 새 문제: 워크플로 50개 한도 무안내(409), 불확실 상태로 생성 잠김(새로고침만 해제), 로그인 1시간 고정 만료 → `reports/개선 확인 18차.md`. 다음 frontend는 qa17-r4 기준. 18차 개선 1~6 → `qa18-frontend-20261031-r1` 패키징·검증, 배포 승인 대기. 주의: 작업 트리 workspace_typed_flows.py에는 운영(typed-dispatch)의 EXECUTOR 코드가 없음, front.py에는 Explore 미배포 Redis 캐시 코드가 있음 → 이 두 파일은 운영 사본에 패치로만 얹을 것.
- 개선 확인 17차(2026-10-31): 워크스페이스 집중. qa16-r2 배포로 AI 제안 2단계 주제 유지·이름·저장 문구 확인. 뉴스 과제 전부 거부 원인 = Technology News·Research Papers 현재 연결 버전에 capability_approvals 없음(운영 데이터, 승인 필요). 거부 이유 표시·실행 완료 문구·개요/지원 병렬 호출 → `qa17-frontend-20261031-r1`(Explore r21 기준) 배포·확인(개요 2.58→2.09초, 지원 2.47→1.89초). 다음 frontend는 qa17-r1 기준. 기능 승인 복구: `scripts.approve_model_contracts`(Research Papers 추가) 운영 실행 → Technology News·Research Papers·Paper Finder 승인·계약 시험 성공, 뉴스 과제 생성·저장·실행 확인. 자체 에이전트 스키마를 바꾸면 이 스크립트를 다시 돌려야 함. 다른 종류 연결 단계는 원래 주제로 검색(`topic_followups`) → `qa17-frontend-20261031-r2`(typed-dispatch-frontend-r1 기준) 배포·확인(2단계가 주제 검색). 다음 frontend는 qa17-r2 기준. 추가: separately 주제 분리·세션 확인 재시도(503)·지원 화면 401만 로그인 안내·저장 잔액 중복 조회 제거 → `qa17-frontend-20261031-r3` 배포·확인(Docker/Kubernetes 단계 분리, 저장 API 6회). 다음 frontend는 qa17-r3 기준. 남음: docs.search.v1에 실제 문서 검색 에이전트 없음(논문 색인만, 13절 후보 조사·사용자 결정 필요). 예시 버튼 비활성·조회 2초·이름 부사·Chat 후속 조건 → `qa17-frontend-20261031-r4` 패키징·검증, 배포 승인 대기(권한 검사 차단). 18차 기준 `docs/qa/usability-criteria-18.md`. 로딩·세션 개선 방안 → `reports/개선 확인 17차.md`.
- 개선 확인 16차(2026-10-31): 시나리오 74/1/0, UI 지표 0, Explore 중앙값 1.85초(3초 초과 12건). 15차 수정 3건 운영 확인(실행 성공, 이름 단어 단위, 잔액 쉼표). 새 문제: 실행 확인 필터 둘러보기 1위가 성인 서비스(정책 결정 필요), AI 제안 2단계가 주제를 잃음, 이름이 연결어로 끝남 → `reports/개선 확인 16차.md`. 다음 frontend는 `qa15-frontend-20261031-r1`, execution은 `qa15-execution-20261031-r1` 기준. 성인 서비스 공개 목록 제외(사용자 결정, 워크스페이스는 제외 안 함) → `qa16-frontend-20261031-r1` 배포·확인. AI 제안 2단계 주제 유지·이름 연결어·완료 문구 → `qa16-frontend-20261031-r2` 배포(다음 frontend 기준). 주의: Explore 세션의 `explore-os-frontend-20261031-r20`은 qa16-r1 기준이라 배포 전에 qa16-r2 위에 다시 얹어야 함(workspace_goal_coverage.py·workspace-studio.js·customer_typed_authoring_view.py). 17차는 워크스페이스 자연어 생성·실행·수정 집중, 크레딧 제한 없음.
- 개선 확인 15차(2026-10-31): 시나리오 74/1/0, UI 지표 0, Explore 중앙값 1.63초. 14차 수정 7건 운영 확인. 새 문제: 워크스페이스 실행이 실행 서비스에서 `WorkspaceDenied`(_actor 형식 검사)로 실패, Test Country Profile 실패, AI 생성 이름 단어 중간 잘림, 바닥글 © 2025 → `reports/개선 확인 15차.md`. 크레딧 1 사용(사용자 허락). 대응: 워크스페이스 실행 실패 원인 = 실행 서비스가 고객 실행을 직원용 실행기로 처리 → `service_host.execute_typed`로 고객 실행기 분기. `qa15-execution-20261031-r1`(r4 기준)·`qa15-frontend-20261031-r1`(qa14-r2 기준, 이름 단어 자르기·잔액 쉼표 포함) 배포(07:05, execution `worker-deploy`·frontend) 후 워크스페이스 실행 성공 확인.
- 개선 확인 14차(2026-10-31): 운영 점검(시나리오 72/1/2, UI 지표 0, Explore 중앙값 1.89초로 느려짐) → `reports/개선 확인 14차.md`. 보고서 필터 500·실행 확인 필터 누락·오타 제목·카드 중복·워크스페이스 숫자/비활성 이유/목록 링크 수정 → `qa14-frontend-20261031-r1`(qa13-r2 기준, 8파일) 패키징·검증 → Explore r19가 먼저 배포돼 r19 위에 다시 얹은 `qa14-frontend-20261031-r2`로 배포(다음 frontend는 이것 기준). 남음: x402 검색 0건·속도·분류(Explore 세션), Chat 순위(selection.py, jobs 동반), x402 503 후보.
- 13차 대응(2026-10-30): 재측정 시나리오 74/1(남은 WARN x402 정책), UI/UX 타깃·axe·포커스 0, INP 최대 64ms. Chat 번역 언어 조건 수정(`translate`에서도 검사, 인도어 전용 범위, 한국어 언어명 별칭) → 릴리스 `qa13-frontend-20261030-r1`(vary-r1 기준) 패키징·검증, 2026-10-31 배포·운영 확인(번역 4문항 1위 Faceabot, 힌디어는 Bhasini). 다음 frontend는 qa13-r1 기준(Explore r17은 vary-r1 기준이라 selection.py·chat_task_spec.py를 다시 얹어야 함). [10-31] Explore 오타(translte·gihtub)를 교정어로 검색(front.py, `corrected_query`·`search_notice`) → `qa13-frontend-20261031-r2`(r18 기준, front.py만) 배포·운영 확인(translte·gihtub·wether 결과 나옴). 다음 frontend는 qa13-frontend-20261031-r2 기준. Origin·INP는 변경 없음. 기록 `reports/improvement-check-13-2026-10-30/`
- 남은 작업 진행(2026-10-28 저녁): Chat AI 고지·피드백·중지, Test 지연·캐시 표시, /status.json, Explore 커서, 전문 검색 SQL 3~4배(흔한 단어), 워크스페이스 이름·중복 안내·공급자 연결 바로 이동. ux6 배포·확인 → `reports/improvements-2026-10-28/README.md`
- 4차·UI/UX·워크스페이스 평가 반영(2026-10-28): 정적 파일 읽기 한도 제외(정상 사용자 15분 차단 해결), 내용 해시 캐시, 대비 0(라이트·다크), 포커스·24px, RFC 9457 인자 오류, 한도 헤더, 오타 제안, Chat 대안 요청, 워크스페이스 문구·이름, 기능 텍스트 v2(탐색 -23%) → `reports/improvements-2026-10-28/README.md`
- 기능 텍스트 사전 저장(2026-10-28): `agentcon_search.capability_text` 설치, jobs가 183k건 채움, Explore 콜드 약 9% 개선(결과 동일, 위반 0/199k). 홈 일일 스냅샷을 서버 원본에서 기본 접힘으로 변경 → `reports/capability-text-design-2026-10-28/README.md`
- QA 3차 후속(2026-10-28): MCP·A2A 규격 경계, 공개 조회 GET CORS, llms.txt 일일 스냅샷 숫자, 사설 주소·유료 call 문구, 결제 이유 코드(원 서버 501+reason, 엣지 워커가 결제 헤더를 원 서버로 전달), Chat 오타 교정 표시. `qa4-*` 4역할과 엣지 워커 배포·확인. 승인된 문의 1건 삭제. Explore 콜드 속도는 도구 계약 요약을 DB에 저장하는 설계 필요
- 개선 확인 3차 대응(2026-10-28): 체크박스 요청 1건, x402 카드 이름 보존, 429 대기 시간, 순번 후속 질문, 8004 안내, 다단어 오타 제안. 기능 색인 사전 계산은 측정 결과 효과 2%·메모리 0.5GB라 미적용. 전체 트리로 `qa3-*-20261028-r1` 4역할 배포 → `reports/qa-round3-2026-10-28/README.md`
- MCP·x402·A2A 수집·헬스체크·인증·사용 안내·평가, 14개 카테고리(agent_infra 포함, 분류 v5, 정밀도 84.9%)
- 맥 이전: 소스는 브랜치, 수집 DB는 `exports/` 스냅샷으로 전달 완료
- 사용자 맥 커밋: 관리 대시보드, 에이전트 전용 프론트(:8400, 로컬 LLM), SNS 피드
- 토큰 절약 조사 보고서(`reports/클로드코드 토큰 절약 방법.md`), CLAUDE.md·전역 규칙 적용

- Explore 검색 브라우저 테스트(2026-10-26): 개선 17건 → `reports/Explore 검색 브라우저 테스트.md`

- Chat 자연어 요청 브라우저 테스트(2026-10-26): 개선 14건 → `reports/Chat 자연어 요청 브라우저 테스트.md`
- 사이트 전반 브라우저 테스트(2026-10-26): 개선 14건, 핵심은 `#` 주소 변경 시 화면 미전환 → `reports/사이트 전반 브라우저 테스트.md`
- 자율형 에이전트 접속 테스트(2026-10-26): 종류 조사 12종 → `reports/자율형 에이전트 종류 조사.md`, 시나리오 76개 `scripts/agent_scenarios.py`(안내 `docs/qa/autonomous-agent-scenarios.md`), 결과 PASS 42·WARN 30·FAIL 4, 개선 20건 → `reports/자율형 에이전트 접속 테스트.md`
- 등록된 테스트 결과 보고서 품질 분석(2026-10-26): 2,855건(전체 3,998 중), 개선 13건 → `reports/테스트 결과 보고서 품질 분석.md`. 주의: 목록 API를 limit=300으로 90회 연속 호출한 직후 사이트가 502(재시작 필요)였음 — 대량 조회는 1건씩 0.5초 간격으로
- 보고서 개선 방안(2026-10-26): 판정 3단계·스키마·종류별 규칙·검수 R1~R8·적용 순서 → `docs/qa/test-report-improvement-plan.md`
- 등록 기능 테스트(2026-10-26): 개선 13건 → `reports/등록 기능 테스트.md`. 시험 데이터 남음(등록 206598·206599·206602~206604, 문의 7, 개인정보 3, 알림 tw_6a58) — 사용자 정리 필요. inspect는 분당 13회쯤 429, 5회 위반이면 사이트 전체 Auto-jail
- 등록 기능 개선 방안(2026-10-26): 서버 동의 검사·프로토콜 확인 등록·자기 도메인 거절·문의 CRLF/중복/한도·차단 범위·적용 5단계 → `docs/qa/registration-improvement-plan.md`
- 결제 기능 테스트(2026-10-27): 돈 안 씀(잔액 0 일회용 키), 개선 8건 → `reports/결제 기능 테스트.md`. 실제 결제 성공 흐름은 사용자 승인·지갑 필요. 게이트웨이 x402 경로는 20초 10회쯤 429
- 결제 기능 개선 방안(2026-10-27): 실패 이유 코드 10단계·실제 결제 확인 작업·상태 일치·v2 통일·한도·문구·OpenAPI → `docs/qa/payment-improvement-plan.md`
- 워크스페이스 기능 테스트(2026-10-27, 로그인 전 범위): API 138개·화면 6개, 개인 데이터 노출 0, 개선 8건 → `reports/워크스페이스 기능 테스트.md`. 로그인 뒤 기능은 맥 로컬 세션 필요
- Explore 검색 재시험(2026-10-27): 17건 중 개선 9·일부 5·그대로 3, Weather 칩 미동작, 속도 개선 없음(p50 1.8s, max 11.5s, 캐시 없음) → `reports/Explore 검색 재시험.md`
- Chat 재시험(2026-10-27): 14건 중 개선 6·일부 4·그대로 4, 속도 7.3s→4.9s(화면), 도구 매칭 도입·집합형 서비스 쏠림·서울 날씨 오답 → `reports/Chat 재시험.md`
- 개선 확인 종합(2026-10-27): 107건 중 개선 43·일부 18·남음 28·미확인 18 → `reports/개선 확인 종합.md`. 재확인 중 생긴 데이터: 문의 inq_aavyTwAl3VU17-qgKkXlZU8m 1건
- 개선 확인 2차(2026-10-27): 남은 22건 중 개선 1·일부 5·그대로 16, 회귀 4(Chat 다국어·속도, Explore 체크박스, 새 라벨) → `reports/개선 확인 2차.md`. 생긴 데이터: 문의 inq_LPrDvXkFp4nTjCVT_T2A7jtc
- 개선 확인 3차(2026-10-27): /api/agents/{id} 전부 500(Test 실행·Explore 상세 막힘), Chat 다국어·속도 복구, Explore 속도 개선(API p50 0.95s) → `reports/개선 확인 3차.md`. 생긴 데이터: 문의 inq_ObOcUR50djvGsukLwApp8UJi
- 개선 확인 4차(2026-10-28): 상세 API·Test 예제 복구, A2A·MCP 규격 일부 개선, 정적 파일 no-store로 첫 화면 느림 → `reports/개선 확인 4차.md`
- UI/UX 평가(2026-10-28): 기준 `docs/qa/uiux-evaluation-criteria.md`, 측정 `scripts/uiux_audit.js`(axe·Web Vitals·키보드), 종합 64(C) 사람 62·에이전트 62·접근성 69, 개선 20건 → `reports/UI UX 평가.md`
- 개선 확인 5차(2026-10-28): UI/UX 68(C, 접근성 74 B), 정적 캐시·대비 0·커서·server.json 개선, 새 문제 CLS 전 화면 0.15~0.64·x402 게이트웨이 결제 501 → `reports/개선 확인 5차.md`
- 개선 확인 6차(2026-10-28): UI/UX 70(B 경계, 접근성 78), axe 0·포커스 링 4곳·INP 112ms, CLS 원인=첫 방문 2.3~2.9s 뒤 본문 밀림(쿠키 배너 추정) → `reports/개선 확인 6차.md`
- 개선 확인 7차(2026-10-29): UI/UX 71(B), CLS 0.104·검색 최대 1.49s·날씨 분류·오타 개선, 새 문제 모바일 가로 넘침(select#chatProtocol 533px)·Test 예제 전부 502/비활성·Chat 추천 흔들림 → `reports/개선 확인 7차.md`
- 개선 확인 8차(2026-10-29): UI/UX 73(B), 가로 넘침·Test 예제·Chat GitHub/번역 해결, 회귀 MCP readOnlyHint 4개 false. uiux_audit.js가 로그인 버튼을 눌러 Google 페이지를 재던 문제 수정 → `reports/개선 확인 8차.md`
- 개선 확인 9차(2026-10-29): UI/UX 74(B), 속도 개선(Chat 1.9s, Explore 0.71s), 나머지 남은 작업 그대로(readOnlyHint, x402 402 표시, Chat 날씨·지시어) → `reports/개선 확인 9차.md`
- 개선 확인 10차(2026-10-29): UI/UX 75(B), Chat 영어 날씨·계약서 번역, Explore translate 개선. 나머지 그대로 → `reports/개선 확인 10차.md`
- 개선 확인 11차(2026-10-29): UI/UX 75(B) 유지, readOnlyHint·x402 402/403·포커스 링 해결, 회귀: 흔한 단어(data/api/agent/mcp)·의미 없는 검색어 0건, Test CLS 0.16, Explore 다시 느림 → `reports/개선 확인 11차.md`
- 개선 확인 12차(2026-10-30): 새 환경에서 시험 도구 재작성(스크래치 qa/), UI/UX 75(B), 11차 회귀 해결·Chat 지시어·RFC 9457 해결, 남은: Explore 지연 꼬리·오타 일부 회귀·타깃 76·CORS → `reports/개선 확인 12차.md`
- 개선 확인 13차(2026-10-30): UI/UX 75(B), 시나리오 69 PASS, CORS·카테고리 본문·Explore 꼬리·Chat 메일/PDF/PostgreSQL 개선, 회귀 Chat 번역→Bhasini(인도 언어), Origin 검사 → `reports/개선 확인 13차.md`
- 2차 개선 확인 보고서 회귀 해결 및 배포(2026-10-28): Chat 다국어(일/스/한) 의도 매칭 우회 차단 해제, Explore 체크박스 즉시 재조회(force=true), 카테고리 'Data-Analytics' 라벨 정규화(DB 49건 마이그레이션 + 프론트 별칭 매핑), Test 화면 Country Profile 기본 매개변수 매핑(133020 -> country_code: US, 627ms 완료), 결제 10단계 실패 코드 검증, 릴리스 `qa-remediation-frontend-20261028-r1` 배포(슬롯 b 전환, PID 41438), 테스트 문의(inq_LPrDvXkFp4nTjCVT_T2A7jtc) 정리 완료

## 진행 중
- Explore A1(PostgreSQL 검색 문서) 운영 적용(2026-10-30 10:18~10:23): jobs/frontend/admin `explore-a1-*-20261030-r2`. 검색 문서 초기 적재 진행 중(10:25 기준 2,117건, 대기 219,183건). 적재 정체 위험이 있어 `status`로 확인 필요 → `docs/qa/explore-opensearch-design-2026-10-30.ko.md` 8절, `reports/explore-postgres-a1-2026-10-30/REPORT.ko.md` 6절. OpenSearch(B)는 A1 운영 재측정 후 결정
- Explore A1 r5(12:10 기준): jobs/frontend/admin r5·admin r6, 정책 `008d6c3a…`. 일괄 기록으로 약 2,350건/분, 노출 대상 대기 139.7천 건 감소 중(약 13:15 완료 예상) → 완료 후 8.3 조건 재측정. 독립 정답 집합 초안 201개 `docs/qa/explore-eval-tasks-2026-10-30.json`(사람 검토 필요). [15:40] 전체 테스트 624개 완료(실패 1개는 부하 18에서의 화면 대기 시간 초과, 재실행 통과). Chat 지연 분해·회로 차단 같은 이름 조회 색인화(115ms→1ms, 결과 동일) → frontend `explore-a1-frontend-20261030-r15` 배포(15:44, 활성 qa12-rest-frontend-20261030-r3 기준, 반복 Chat 서버 1.7~1.8초). r14는 SQL 목록 재생성 때문에 시작 실패(front.py 보고서 쿼리 누락) → 다른 세션 릴리스 위에 얹을 때 SQL 목록은 재생성하지 말고 내 파일 해시만 바꿀 것. 참고: qa12-rest-r1/r2의 SQL 목록(application_store_sql.json) 파일 해시가 갱신되지 않은 상태였음(r13에서 재생성). [16:10] 검증기 캐시 4096·거부 기억 배포: jobs r6·frontend r16·admin r7, 정책 `57e5ebe0…`, 문서 동등 3,000/3,000, 반복 Chat 서버 1.13~1.47초. 문서 재생성 분당 약 2,300건(17:50 전후 완료 예상) → [22:31] 재생성 완료(225,371건, 대기 0) 후 재측정: 반복 Chat 서버 0.98~1.58초(r16 직후와 같은 수준), Explore API 반복 0.70~0.98초, 오류는 무관한 x402 501 2건뿐. [10-31 01:00] Explore 캐시 미스 개선: 더 보기 재계산 제거(complete 결과 재사용)·중복 제외를 작업어 검사 앞으로·작업 사실 키 단일 계산. 결과 동일 188/188, 1쪽 -15%(p90 3.68→2.71s). frontend r17 패키징(vary-r1 기준) 완료, 배포는 분류기 차단으로 승인 대기 → 설계 문서 8.22. [05:37] 다른 세션이 qa13-frontend-r1을 frontend에만 배포해 정책 불일치(189af1c9 vs 문서 57e5ebe0) → r17 대신 frontend r18(qa13+네 파일)·jobs r7(r6+qa13 selection.py) 배포(jobs는 `./agentcon worker-deploy jobs`). 문서 재생성 분당 약 2,400건, 07:12경 완료 예상 → 첫 검색 재측정 필요. 더 보기는 이미 0.02~0.04초. [06:10] 다음 쪽 미리 계산 → frontend r19(qa13-r2 기반) 패키징, 06:2x 배포(더 보기 대부분 0.15~0.75초, qa14 미배포본에는 없음 주의). 정답 집합 201개 검토(승인 140·수정 61). 워크스페이스 워크플로 시험(내장 브라우저, 운영): 생성 30건 중 성공 6, **고객 워크플로 실행이 작업자에서 관리자용 typed_flows로 처리돼 항상 denied(10-21 이후 성공 0)** → `reports/Workspace 워크플로우 생성 테스트.md`. Explore has_report 필터 500(connection_agents INSERT 실패, qa13-r2). [07:42] OpenSearch 3.9.0 로컬 PoC(127.0.0.1:9200, 힙 1GB, 227,941건 색인 19초). 정답 집합 200개 A1 vs B(어휘만 BM25로 교체): p50 1.89→1.38초, p95 4.41→2.70초(-39%), 품질 동일(통과 124/124, P@10 0.540/0.545). PostgreSQL 관련도 순(A2)은 어휘 단계 7~18초로 불가 → 8.24. 07:25 비교 스크립트가 런타임 풀로 DB 연결 고갈(측정 요청 3건 500) → 연결 1개·자동 중단 장치로 재실행. [07:55] OpenSearch 연결: 어댑터 opensearch_lexical.py(off/shadow/on, 실패 시 PG·30초 차단, 설정 gateway-data/explore-opensearch.json), 동기화 scripts/explore_opensearch_sync.py(별칭 교체, 14초, 10분 주기 실행 중), 시험 21건+관련 482건 통과. frontend r20(qa16-r1 기반) 배포는 분류기 차단으로 승인 대기, shadow 설정 파일 준비 → 8.25. [08:02] 다른 세션 qa16-r2 배포 완료를 기다린 뒤 r21(qa16-r2 기반) 배포, shadow 시작: 150건 실패 0, OS 35ms/PG 38ms, Jaccard 0.53, shadow 부담 측정 안 됨. [08:12] OpenSearch·동기화 launchd 등록(biz.agentconcierge.opensearch, -sync). kill -9 후 10초 재기동·27초 green, 엔진 다운 중 탐색 200. 동시16+동기화 병행 p95 ≤104ms(부하 평균 12.4로 처리량은 PoC보다 낮음), forcemerge는 효과 없어 되돌림 → 8.26. [08:33] **OpenSearch on 전환**(설정 파일만, 재배포 없음). 활성 typed-dispatch-frontend-r1(r21 기반)에 어댑터 포함 확인. 운영 API 번갈아 측정 p50 2.01→1.47초, p95 4.03→2.81초(-30%), 120건 200, 되돌림 0 → 8.27. 되돌리기는 mode off. [12:20] PG 재시작 없는 조정(jit off, random_page_cost 1.1, io 200, cache 6GB, work_mem 48MB → 임시 파일 2분 35→0), OpenSearch 힙 768MB·_source 끔·preload·웜업(인덱스 -18%, 속도 동일), Redis 공유 탐색 캐시·AI 안내 문구 → frontend r22(qa17-r4 기반) 배포 승인 대기. 승인 대기: Redis maxmemory, PG shared_buffers 2GB(재시작), 분류 v9d 적용 → 8.29. [12:30] r22 배포(AI 문구 확인, 첫 쪽 0.8~1.1초). Redis 키가 프로세스별 시험 접두어여서 공유 안 됨 → r23(a2a:shared: 접두어) 배포 승인 대기 → 8.30. [12:55] 전체 승인 처리: r23 배포(Redis 공유 확인), Redis 256MB·volatile-lru, 분류 v9 트리·시험·jobs r8 배포. 분류 일괄 갱신과 PG 재시작(shared_buffers 2GB·pg_stat_statements, 설정은 재시작 대기)은 분류기 차단 → 사용자 직접 실행 필요(gateway-data/maintenance/pg-restart-shared-buffers-20261031.sh) → 8.31. 다른 세션 qa13-frontend-r1은 selection.py(정책 파일) 변경 → frontend만 배포 시 문서 불일치 주의. 전체 시험 627파일: 실패 2(관리 화면 대기 시간 초과는 단독 재실행 통과, CORS 시험은 다른 작업자의 의도된 공개 /mcp 변경을 못 따라감). 분류 VERSION 9 재분석: 저장 대비 2,103건 변경(배포된 단독 forecast가 예측시장 323건을 날씨로 오분류, VERSION 9는 이를 되돌리지만 NHC·SPC 같은 실제 날씨를 messaging으로 옮기는 역회귀 포함) → 일괄 적용 보류, 8.23. resource_at은 이미 일괄 처리라 변경 없음 → 설계 문서 8.21. 분류 VERSION 9는 dry-run이 65건이 아닌 1,759건(저장 분류 누적 차이)이라 보류. 미커밋 변경 다수(테스트 수정·scripts/agent_discovery_audit.py·operating.js·protocols.py·front.py 등). frontend r10(14:45, qa12-frontend-20261030-r2 기준)·r11(14:51) 배포: 예시 거짓 가용성·워크플로 사용 불가 안내·Chat 키보드 접근·병합 순서, 보고서 필터 묶음 50건(200건은 문장 제한 5초 초과로 500). 다음 frontend는 최신 활성 릴리스 기준. frontend r7(13:06) Recorded reports 필터 시간 초과 수정(일괄 읽기, 31초→4초)·운영 확인. frontend r6(12:46) 정확한 이름이 작은 limit에서 빠지던 문제 수정·운영 확인. 분류 규칙(ping/날씨어) 수정(dry-run 65건 변경), VERSION 9 일괄 갱신은 dry-run 후 승인 대기. 트리 `classify.py`의 다른 작업자 단독 "forecast"는 미배포, 오분류 유발 → 확인 필요
- 워크스페이스 워크플로우 자연어 생성 테스트: 계획 `docs/qa/workflow-test-plan.md` 작성. 로그인된 맥 Chrome이 필요해 맥 로컬 세션에서 실행 대기

## 다음
- 11-01 14:30 오류 분석(10-31~11-01) → `reports/오류 분석 2026-10-31~11-01.md`: 관리 test-reports 500(세션 확인이 쓰기 잠금), 벡터 통계 상시 실패(해시 26초), Worker 공용 IP 자동 차단으로 홈 403, x402 빈 쪽 재시도 수정·테스트 통과. 14:37 jobs `errfix-jobs-20261101-r1`·14:38 admin `errfix-admin-20261101-r1`(edge-monitor-admin-r1 기준) 배포, frontend `screen-policy-frontend-20261101-r2`(프론트 세션, security.py 포함). 배포 뒤 공용 IP 차단·홈 403 0건. 다른 세션 snapshot-progress-frontend-r1(14:30~35)에 /chat NameError 500 3건 → 프론트 세션에 전달
- 11-01: 문서 에이전트 후속(14절) 배포 완료 — execution docs-execution-20261031-r2, frontend qa19-frontend-20261101-r9(편집 화면 라벨 보완), jobs는 다른 세션의 backfill-pause-jobs-20261031-r2에 포함. 승인 4개 ok, Django 공식 문서 실측 확인(보고서 19차 15절)
- QA: Perovskite 워크플로 보관(활성 49/50), Kubernetes 문서 워크플로 재저장·실행 2/2(kubernetes.io)
- 남음: 내일 Context7 사용량 로그 확인(logs/services/*.log에서 "Context7 calls today"·"allowance used up")
- 다음 jobs 릴리스는 backfill-pause-jobs-20261031-r2 위에
- 11-01: 워크플로 50개 한도 제거·목록 분할 조회·(workspace_id,id) 인덱스 → qa19-frontend-20261101-r10 패키징 → 다른 세션 explore-speed-frontend-20261101-r1(r10 포함)로 13:27 배포됨, 화면 확인은 로그인 만료로 미실시(보고서 19차 16절). 다음 frontend 기준은 explore-speed-r1. 작업본 workspace_typed_flows.py에 운영의 EXECUTOR 변경이 빠져 있음

## 보류 (아이디어만 기록, 요청 전에는 착수하지 않음)
- Explore 검색 개선 17건 수정(보고서 우선순위 순)
- Chat 개선 14건 수정(의미 기반 매칭·대화 맥락·되묻기 우선)
- 사이트 개선 14건 수정(화면 전환·링크·이미지 우선)
- 에이전트 접속 개선 20건 수정(문장형 추천·sitemap 404·HEAD·MCP 주석·CORS 우선)
- 등록 기능 개선 13건 수정(서버 법적 동의 검사·문의 CRLF·프로토콜 확인 후 등록 우선)
- agent_infra 오분류 61개 추가 정리, 바로잡은 항목의 분야 키워드 보강
- ERC-8004 수집 완료 후 A2A 통계 갱신
- 클라우드 컨테이너의 수집기 종료(맥에서 이어 수집 중)
- 11-01 오후: 사용자 화면 정책 docs/FRONTEND_SCREEN_POLICY.md를 새로 만들었다(고정 내용 즉시 표시, 전체 화면 로딩 금지, 영역별 로딩, 병렬 요청). 메모리 저장, 다른 세션 공유 완료.
  - Test·Workflows 화면은 페이지에 넣은 데이터로 열린다(API 0회, scripts.build_public_page_snapshots).
  - 워크스페이스 전체 화면 게이트를 없앴다.
  - Chat 결과의 안쪽 스크롤 상자를 없앴다.
  - Provider 메뉴의 모달을 본문 표시로 바꿨다.
  - 20차 숨은 내용 감사: tests/test_screen_hidden_content_browser.py, 보고서 "개선 확인 20차".
  - 릴리스 screen-policy-frontend-20261101-r2(edge-monitor-frontend-r1 + 화면 12개 파일 + 소스 분석 세션 security.py)를 14:35에 배포했다(활성 a, b=edge-monitor-r1). 운영 확인 완료(보고서 20차 §8).
  - 검색과 RAG 세션의 snapshot-progress-frontend-20261101-r1은 r2를 포함한다. 다음 frontend 기준은 그것 또는 최신 활성.
- 11-01 15:00 Support 화면이 안 나온 원인: 고객 세션 확인 identity.actor()와 Support 읽기가 쓰기 트랜잭션을 연다. 운영 PG에서는 전역 쓰기 잠금이라 14:50:09에 lock timeout으로 500이 났고, 화면은 하나만 실패해도 전체를 숨겼다.
  - 수정: read_tx(readonly), 만료 연장 때만 쓰기, 503 재시도 응답, 화면 병렬 요청·즉시 표시.
  - support-lock-frontend-20261101-r1의 4개 파일이 다른 세션의 chat-recovery-frontend-20261101-r1에 포함돼 16:34에 배포됐다.
  - 운영 확인: Support 요청 3개 병렬(각 0.61초), 세션 API 중앙값 0.45초(대부분 네트워크 왕복), 배포 뒤 lock timeout 0건. 보고서 20차 8-1절.

- 11-01 미추적 코드 1,269개 커밋(216a2489~6a90e8ad, 6개, 미푸시). 제외: 개인 경로 스크립트 25개·브라우저 테스트 3개, Cloudflare 계정 ID가 든 scripts/verify_edge_provider_campaign.py, insert_batch*.py 206개(일회성 데이터 삽입). 깨끗한 클론: pyflakes undefined name 0, 표본 67파일 280 통과·15 실패·83 수집 오류(수정된 추적 파일 categories.py/classify.py·chain.py가 미커밋, .venv-tests에 anthropic 없음).
- 11-01 저녁: 워크스페이스 읽기 경로 11곳을 읽기 전용 트랜잭션으로 바꿨다(크레딧, 조직, 워크플로, Provider, 관리자 세션).
  - r1은 CustomerWorkspaceAccess._tx에 readonly가 없어 TypeError가 날 상태였다. 릴리스 사본 시험에서 발견해 배포하지 않았다.
  - read-only-frontend-20261101-r2: 활성 대비 새 실패 0.
  - 18:50 배포: snapshot-lock-r1 위에 같은 8개 파일을 얹은 read-only-frontend-20261101-r3(활성 b). 워크스페이스 API 9개 200(0.36~0.6초).
  - 배포 직후 Chat 503 1건은 Chat 경로의 쓰기 잠금 대기로, 검색과 RAG 세션에 전달했다. 보고서 20차 8-2절.
- 11-01 18:45 탐색 속도: 문서 재생성이 18:23에 끝났고, 처음 보는 검색어 50여 건이 0.9~2.4초였다. 3초를 넘은 것은 리포트 스냅샷이 만들어지는 동안의 요청뿐이었다(최대 14초).
  - 원인: 스냅샷이 front.store 잠금을 200행 묶음마다 오래 잡았다.
  - 25행 묶음과 20ms 양보로 바꿔 잠금 대기 상위 10%를 3.07초에서 0.17초로 줄였다.
  - workflow-goals-frontend-r3(검색과 RAG 세션)에 포함된다. 보고서 `reports/오류 분석 2026-10-31~11-01.md`.
- 11-01 19:15 r3 뒤 측정: 스냅샷 중 3.2~4.2초가 남았다(GIL 경합). PAUSE_RATIO 2.0으로 느려짐 상위 10%를 1.47배에서 1.22배로 줄였다. snapshot-pause-frontend-20261101-r1은 배포 승인 대기다.
- 11-01 20:06 운영 DB 연결 상한을 24에서 48로 올렸다(사용자 승인, 백업 `postgresql.conf.bak-20261101`).
  - 원인: 앱이 21개 중 17~20개를 썼고, 그중 7개는 롤백용 대기 슬롯(frontend a, admin a)이 잡고 있던 유휴 연결이었다.
  - 서비스는 20:03:57~20:06:26에 멈췄다. 재시작 뒤에는 활성 슬롯만 떠 있고 앱 연결은 11개다. 홈과 탐색은 200을 돌려준다.
  - 남은 일: 대기 슬롯이 유휴 연결을 반납하도록 고치는 것(선택).
- 11-01 20:35 snapshot-pause-r2 배포(19:56) 뒤 스냅샷 중 지연은 거의 사라졌다(1.1~2.8초).
  - 20:10~20:23 서버 시간은 3초를 넘지 않았다(중앙값 0.96초).
  - 20:23 뒤 서버 2~6초는 다른 세션의 pytest·playwright가 CPU 300%를 쓴 탓이다(부하 11.5). 코드 회귀가 아니다.
- 11-01 밤: 남은 작업 1~9를 처리했다(보고서 20차 8-3절).
  - 운영 배포: executor-fix-frontend-20261101-r2(20:23)
    - 내 r3에서 빠졌던 EXECUTOR(18:50~20:23 누락, zsh 단어 분리 사고)를 복구했다.
    - 워크스페이스 요청 병렬화, 초대 목록 읽기 전용을 넣었다.
  - 21:13 배포 frontend edit-revision-frontend-20261101-r1(워크플로 수정 저장 → 같은 워크플로 다음 리비전, 화면 스냅샷 캐시 자동 갱신). 활성 대비 새 실패 0.
  - 21:09 배포 admin admin-tabs-admin-20261101-r1(관리자 상단 탭 줄바꿈).
  - 커밋: 96b5f773(이 세션 78개 파일). new/는 미추적이라 넣지 않았고, 푸시하지 않았다.
  - 진행 표시 위치는 사용자 정정으로 "가운데 작은 표시"가 맞다. 다른 세션이 작업본과 정책 문서를 고쳤고 배포도 그 세션 몫이다.

- 11-01 23:50 미커밋 정리와 연결 반납
  - 10월부터 커밋되지 않았던 추적 파일 71개(운영 릴리스와 같은 버전)와 미추적 문서·스크립트·테스트 177개를 커밋했다(deddd599, 3caeb6ec).
    - `.gitignore`에 `.DS_Store`, `outputs/`, `output/`, `new/qa/`, 미리보기 이미지, `.wrangler/`, `insert_batch*.py`를 추가했다.
    - 사본 시험: 실패 545건 중 31건이 남았고, 모두 git에 넣지 않는 로컬 증거 파일(`gateway-data`, `reports/*/screenshots`)에 기대는 시험이다. 실제 작업 트리에서는 원래 있던 실패 2건만 남는다.
  - `AdminReaderPool`에 `idle_seconds`를 추가했다(운영값 300초). 쉬는 세션을 백그라운드 스레드가 닫아, 롤백용 대기 슬롯이 연결을 반납한다.
    - admin 릴리스 `idle-reaper-admin-20261101-r1`은 패키징·검증까지 했고, 배포는 승인 대기다. frontend는 프론트앤드 세션의 다음 릴리스에 들어간다.
  - 공개 저장소의 개인 경로·맥 이름을 일반화했다. 스크립트는 `Path(__file__)`, launchd plist는 `__REPO__`·`__BACKUP_COPY_TO__` 템플릿으로 바꿨고, 이전 커밋 이력에는 남는다.
  - 23:35~23:47 탐색 측정(로컬 :8400, 연결 재사용, 처음 보는 검색어 178개): 중간값 1.57초, 상위 10% 3.24초, 최대 6.9초, 3초 초과 21개(12%), 오류 0.
    - 이때 다른 세션의 pytest 10개가 돌아 load average가 9 안팎이었다.
    - 3초 초과 요청은 12분 내내 고르게 흩어졌고 스냅샷 시간대에 몰리지 않았다. 앱 시간(`Server-Timing`)도 같은 값이라, 원인은 머신 부하로 본다.
    - 운영 맥에서 큰 시험을 돌리면 탐색 3초 정책이 깨진다. 부하가 낮을 때 다시 재야 한다.

- 11-02 07:01~07:10 묶음 읽기 장애와 복구
  - r5 배포 직후 하위 응답이 gzip으로 돌아와 고객 첫 화면이 모두 실패했다. 하위 요청에서 `accept-encoding`을 빼서 고쳤다(5c233610).
  - 07:06:33에 r6을 배포했다(frontend active b). Workflows·Overview·Plan·Support 확인, 로그 오류 0.
  - 다음 frontend 릴리스는 r6을 바탕으로 만든다. 테스트는 `.venv-tests/bin/python`으로 돌린다(`.venv`에는 pytest가 없다).
  - 11-02 07:10~07:15 대기 슬롯 확인(standby-snapshot-frontend-r2, 07:06:33부터 대기): DB 연결 3개가 남았다(예전 대기 슬롯은 4개).
    - 시작할 때 연 두 연결(81405·81406)은 풀 밖의 기본 연결이라 정리 대상이 아니다.
    - 풀 세션 1개(81515)는 대기 중에도 몇 초마다 쓰여, 300초 동안 쉬는 일이 없다.
    - 더 줄이려면 대기 슬롯에 들어오는 주기 요청을 찾아 없애거나, 기본 연결을 닫는 설계가 필요하다(보류).
- 11-02 07:40 평소 부하 측정(연결 재사용) 158건: 중앙값 1.12초, 상위 10% 1.94초, 3초 초과 6건(3.8%, 대부분 weather alerts).
  - 날씨 판정 비용은 selection.py에 있다(정책 해시 파일).
  - CLAUDE.md에 nice -n 10 규칙을 넣었다(4f641ae3).
- 11-02 11:17~11:26 대기 슬롯 탐색 미리 데우기 중지 확인(e6335cac, award-stage6-frontend-r1이 11:17부터 대기)
  - 대기 전환 직후 약 4분은 탐색 일괄 읽기가 이어졌다(90초에 39번). 운영 중에 시작한 미리 데우기 회차(칩 검색어 24개 × 8초 간격)를 끝까지 돌았기 때문이다.
  - 11:21부터 탐색 쿼리 0, DB 연결은 4개에서 2개로 줄었다. 쉬는 풀 세션은 300초 뒤 닫혔고, 남은 2개는 풀 밖의 기본 연결이다.
  - 회차 중간에도 운영 슬롯인지 확인하면 전환 직후 4분도 없앨 수 있다(선택).
  - 11:30 회차 중간 확인을 넣어(7c647748) round-stop-frontend-20261102-r1로 배포했다(release_gate 56건 통과). 이 릴리스가 다음 배포로 대기 슬롯이 되면 전환 즉시 탐색 미리 데우기가 멈춘다.
- 11-02 12:30 남은 작업 정리
  - `reports/` 아래 미추적 보고서 md 394개를 커밋했다(41abdc43, 014fef90). 개인 경로·사용자 이름은 `<저장소>`·`<user>`로 바꿨고, 개인 이메일이 든 1개는 뺐다. 증거 파일(json·png·xml 등 약 7,600개)은 그대로 미추적이다.
  - 11-01 사본에서 실패하던 `test_application_store_postgres` 계약 시험과 연구 제어 시험은 지금 둘 다 통과한다(38건). 앞의 것은 부하가 높을 때만 실패한 것으로 보여 코드는 바꾸지 않았다.
  - 배포 순간 끊김: 프록시 로그에는 오류가 없고 접속 기록은 꺼져 있다. 다음 frontend 배포 때 공개 홈 2초 간격 요청과 대기 슬롯 탐색 쿼리를 관측 중이다(scratchpad `deploy_watch.py`, 12:31부터 90분).
- 11-03 품질 정책 v1(증거 기반 등급, 43da2264). 보고서 `reports/에이전트 품질 평가 업그레이드 2026-11-03.md`.
  - 기존 등급은 A가 MCP 63%, A2A 97.5%, x402 88.6%였고, 실제 호출을 한 번도 안 한 대상도 A였다.
  - 바꾼 것: 7일 헬스체크 Wilson 하한, 시험 판정 4분류(판정 불가는 실패 아님), 보안 통제 수단 15%, 가중치 조정, 증거 수준별 등급 상한(A는 시험 통과와 안정적인 7일이 필요, 미시험·점검 부족은 최고 B, 서버 장애는 최고 C, 순서를 지켜 눌러 담음).
  - 운영 모의 적용: A 비율이 MCP 23%, A2A 1.7%, x402 34%로 바뀐다.
  - 13:37 jobs `quality-policy-jobs-20261103-r1`을 배포했다(사용자 승인, ux-100-jobs-r1 + 6개 파일, store.py는 패치).
    - 일괄 작업이 500개 id를 한 쿼리에 넘겨 PG 값 256개 제한(`invalid_parameters`)에 걸렸다.
    - `health_counts`를 200개씩 나누도록 고쳐 13:49에 r2를 배포했다. 시험도 추가했다.
  - 13:52부터 일괄 재평가가 1분에 약 500건씩 진행된다. 22만 건이라 7~8시간 걸린다.
    - 진행 중 탐색은 중간값 1.18초, 최대 3.55초였다(15건, 부하 5~7). DB 연결은 15개다.
- 11-04 20:35 AI AD Coin 기획안 v3 작성(`reports/AI-AD-Coin-business-plan-v3-2026-11-04.md`, 같은 이름 .docx). 첨부 v2 분석 + 뉴스·논문·SNS 조사.
  - 핵심: 선택–재원 분리 1원칙, 작업 후원 거래소(후원 실행권 우선), 서명 스폰서 오퍼 피드, 이중 신원, 영수증.
  - v2 정정: SRA-RiskGate 수치(0%가 아니라 0.47%, 사후 규칙), 모델 가격을 Claude 5.5 계열로 재계산.
  - 코드·정책 파일·운영은 바꾸지 않았다. 문서만 커밋했다. 다른 세션의 미커밋 변경은 건드리지 않았다.
- 11-04 21:45 AI AD Coin 시험 모드 개발(기획 v3, 사용자 결정: 전체 한 번에·자체 시험 캠페인·플래그 숨김·50/10/15/25).
  - `agent_market/ad_coin/` 신설: 복식부기 원장·재원 불변식·회로 차단, 작업 후원 2위 가격 입찰·실행권, P2 코인 보상, 지갑 이전·회수, 의도 위임장, Ed25519 영수증, 서명 오퍼 피드, 숨김 화면 `/ad-coin`.
  - front.py에 라우터 2줄. `AD_COIN_ENABLED` 기본 꺼짐이라 운영 동작은 그대로다. 배포는 하지 않았다.
  - 시험 23건 + 관련 456건 통과, 로컬 데모 화면 확인. 남은 일은 `docs/AD_COIN.md` 끝.
- 11-04 22:10 AI AD Coin 이어서: 업그레이드 확인(`ad_coin/upgrade.py`, 답변 뒤 별도 요청), 한국어 운영 화면 `/ad-coin/admin`, 방문자 화면에서 답변 ID → 견적 연결.
  - 실측: 코인 수납 가능한 유료 x402 27,152개, 호출당 중간값 13.8원, 후원 가능(500원~5만 원)은 634개(2.3%). 후원은 작업 묶음 단위여야 한다.
  - 시험 28건(+관련 90건) 통과. Chat 화면 자동 호출은 다른 세션 파일이라 남김.
- 11-04 22:40 AI AD Coin 작업 묶음 견적: 단계×호출 수 묶음을 한 번 올림으로 계산하고 줄별로 지급·환불(부분 실패는 코인은 지갑, 후원은 에스크로로). 위임장은 묶음 안의 모든 유료 제공자를 덮어야 함.
  - 실측: 50코인에 닿는 호출 수 중간값 37회(20회면 30.2%, 50회면 62.8%). 시험 31건 통과, 화면 확인.
- 11-04 23:05 AI AD Coin 공개 워크플로 → 묶음 견적(실행 횟수 1~100, 라우터는 상한, 꺼진 노드 제외, 가격 없는 단계 표시). front.py는 `published_detail` 연결 3줄.
  - 실측: 운영 공개 워크플로 25개 모두 무료 MCP 단계(48개)라 후원 대상 0. 유료 단계가 있는 워크플로 상품이 먼저 필요. 시험 33건 통과.
- 11-04 23:35 AI AD Coin 숨김 시험 상품(`ad_coin/test_products.py`): 실제 카탈로그 에이전트로 관리자가 만들고 공개 목록에는 나가지 않음. 송금·쓰기로 보이는 에이전트, 코인 불가 유료 에이전트 거부.
  - 화면 확인: send-token(134) 거부, "Market brief"(74·484·414 + 무료 32926) 5회 = 345코인, 후원 카드 표시. 시험 35건 통과.
- 11-04 23:55 AI AD Coin 고객 비공개 워크플로 견적(`ad_coin/private_workflows.py`): 고객 세션·구성원·typed flow 상세 읽기 경계를 재사용하고 카탈로그 ID와 개수만 꺼냄. 조건부 단계는 상한.
  - 통합 시험(실제 고객 코어) 401/200/403/교차 출처 확인. 오류 코드가 400으로 바뀌던 버그 수정. 관련 시험 136건 통과. 브라우저 확인은 로컬 고객 세션이 없어 못 함.
- 11-05 00:10 AI AD Coin 초대·로그인 연결(`ad_coin/people.py`): 관리자가 고객 계정 ID로 초대, 고객 세션(+CSRF)으로 이용, 고객이 만든 에이전트 키(해시 저장·1회 표시·에이전트 이름 고정·철회)로 에이전트가 같은 사람 몫으로 동작. 초대를 거두면 키도 정지.
  - 실제 고객 코어 통합 시험 통과, 관련 147건 통과. 로그인 흐름 화면은 로컬에 고객 세션이 없어 운영 시험 계정으로 확인 필요.
- 11-05 00:40 AI AD Coin 실행 결과 연결(`ad_coin/run_results.py`): 공개 워크플로(등록된 SQL)·고객 비공개 흐름(`core.typed.get`)의 실제 실행 기록으로 줄별 성공 호출 수만큼 지급·나머지 환불. 기록은 그 워크플로·결제 뒤·1회만. 시험 상품은 제외.
  - 실행 완료에 성공 호출 수 비례 지급 추가. 시험 5건 + 비공개 통합 1건, 관련 153건 통과. 운영 화면 버튼은 브라우저 미확인.
- 11-05 01:00 AI AD Coin 월간 후원 감사(`ad_coin/audit.py`, `scripts/ad_coin_sponsorship_audit.py`): 질문마다 후원 끔→켬(실제 후원 예약)→끔으로 상위 3개 비교, 바뀜이면 회로 `audit_mismatch` 열기, 통과면 회로 복원·예약 해제. 운영 화면에 감사 기록.
  - 실측(운영 Explore 읽기 20×3): 흔들림 0. 같은 측정 Explore 왕복 중간값 1.46초, 상위 10% 3.55초, 최대 10.1초(부하 5~6). 시험 3건, 관련 89건 통과.
- 11-05 01:40 AI AD Coin 운영 PG 이전 준비: `AD_COIN_STORE=application`이면 애플리케이션 PG 저장소의 같은 연결·트랜잭션에서 `ad_coin_*` 표 사용(등록 SQL 목록·스키마 프로필 무변경, 연결 증가 없음). 표·인덱스 `ad_coin_` 접두사, 트랜잭션 안 예외 잡기 제거, 이전 전이면 AD Coin만 503.
  - 운영자 CLI `scripts.ad_coin_migrate_postgres status|migrate|copy`. 격리 PG18 시험 4건(재접속 스키마 검증 포함), 관련 161건 통과. 운영 DB `migrate`는 아직 실행 안 함(승인 필요).

## 2026-11-05 AI AD Coin 운영 리허설(완료)
- 결과: `reports/AI-AD-Coin-운영-리허설-2026-11-05.md`.
  - 연기·소량·중량·대용량 단계에서 보안·품질·속도 모두 통과했다(대용량 200/s, 견적 p99 24ms).
  - 극한 단계는 367/s에서 정합성을 지켰다(교착 17건은 재시도로 해결).
- 구조:
  - 전용 PG 세션 풀(기본 6)
  - 행 단위 동시성: 사람 잠금, 캠페인 행 잠금, 원자적 잔액, 합계 16줄 분할, savepoint, 교착 재시도
  - 견적 2단계, 등급별 후보 조회, 일별 집계 사전 필터, 백그라운드 만료 정리와 전체 재계산, Server-Timing(adc-*)
- 운영 DB: 11-05 09:22 승인 후 `migrate` 실행. ad_coin 표 33개, 스키마 3. 기능은 아직 꺼져 있다.
- 배포: `ad-coin-frontend-20261105-r1`(12:20). 기준 `id-range-frontend-20261105-r1` 위에 AD Coin 패키지와 front.py 연결부만 얹음. gate 56개 통과. 기능은 꺼짐(404).
  - `AD_COIN_STORE` 기본값을 `auto`로 바꿈(PG면 application). agentcon 설정 허용 목록에 AD_COIN_* 키가 없어서다. 플래그를 켜려면 허용 목록 변경이 먼저다.
- 광고주 콘솔을 Pearl Connection 디자인으로 다시 만듦(사용자 결정: 사이트 디자인·UI/UX 유지).
  - 공용 assets와 워크스페이스 틀을 쓰고, 페이지 전용 스타일은 없앰. 내장 브라우저로 데스크톱·어두운 테마·375px 확인.
  - 배포: `ad-coin-frontend-20261105-r2`(12:33, gate 통과).
- 12:35 이후 Explore 첫 검색이 서버 1.7~6초로 느렸다. 두 슬롯(r1·r2)이 같았고, 원인은 다른 세션의 전체 pytest와 Chat 평가가 만든 부하 16~20이다.
- 사람용 `/ad-coin`과 관리자 `/ad-coin/admin`도 Pearl 디자인으로 바꿈. 첫 쓰기 전 CSRF 자동 확보, 관리자 캠페인은 상세 카드 방식.
  - 배포: `ad-coin-frontend-20261105-r3`(13:29). 기준은 활성 `sec-cleanup-frontend-20261105-r1`이고 AD Coin 파일 3개만 얹음. gate 통과.
  - 대기 중이던 `budget-frontend-20261105-r1`은 검색과 RAG 세션이 폐기한다고 확인해 줌.
- 영어 전용·내부 정보 금지 적용(f9bc4131): `/ad-coin/admin` 영어화, 화면 스크립트 주석 제거, 감사 실행 명령 문구 제거, Server-Timing 기본 끔, 공개 /status O(1).
  - r4 패키징·gate 통과. 그러나 13:56·14:05 배포는 새 슬롯이 `WriterBusy`(앱 저장소 쓰기 잠금, 부하 19)로 준비 시간 초과 → 자동 취소, r3 유지.
  - 다른 세션의 `info-fix-frontend-20261105-r1`이 대기 중이다. 그 배포가 끝나면 그 위에 r4를 다시 만들어 배포한다.
- 규칙 적용 완료(331e7f84, 1b618fbd):
  - 등록 SQL(174개, 모든 어댑터에서 거부), 보안 이벤트 로그(ad_coin 소스, 비밀 없음), 견적 30일 점진 삭제
  - 탐지 패턴 이스케이프, 읽기는 세션 확인 없이, 공식 Lucide, 유휴 세션 정리
  - `/ad-coin/admin`은 한국어로 되돌림(사용자 정정: 백엔드·어드민은 한국어, 광고주 콘솔은 영어)
  - 판매 정책 문서 `docs/AD_COIN_SALES_POLICY.md`
  - 배포: `ad-coin-frontend-20261105-r5`(14:33). 기준은 info-fix-frontend-20261105-r1이고 AD Coin 파일만 얹음. gate 통과, 홈·Explore 정상.
- 결정 대기: 15초 카운트다운 예외(화면 정책 7), Chat에 AD Coin 가격 표시(Chat 규칙과 충돌), 거래 기록 보존 기간.
- 결정 반영(권장안): 15초 카운트다운은 화면 정책 7번 예외, Chat 답변에는 가격 없음(업그레이드 확인 뒤 별도 영역), 거래 기록 5년 보존.
- LCP는 로컬 헤드리스 기준 데스크톱 40~76ms, 모바일 가정 약 0.5초. `/admin/ui` 링크는 기능을 켤 때 함께 한다(지금은 404, 관리자 서비스 배포 필요).
- 보안 점검: bandit 높음 0건, 결함 4건 수정, 동적 219/219. 보고서 `reports/AI-AD-Coin-보안점검-2026-11-05.md`.
  - 배포: `ad-coin-frontend-20261105-r6`(14:48, r5 위에 AD Coin 파일만). gate 통과, 홈·Explore 정상, AD Coin은 꺼짐.

## 2026-11-06 AI AD Coin 소스 기반 문서 최신화
- 목표 우선순위: 완벽 보안 → 품질 100% → 글로벌 최고 처리 속도. 목표와 달성 증거를 구분하고 보안 미완 항목을 출시 차단으로 기록.
- 최신 현황 v4(Markdown·Word), AD_COIN·TARGETS·SALES_POLICY 갱신. v1·v3 기획에는 역사본과 최신 문서 안내. 고객 로그인 초대·키, 실행 기록 정산 등 오래된 미구현 표시와 저장소 기본값·SQL 수를 정정.
- 검증: 관련 시험 최신 고유 89건 통과(초기 80 통과·PG 9 건너뜀, 격리 PG 파일 10건 재실행으로 해소·중복 1건), 기존 HTTP 동적 보안 219/219. 원자료·소스 SHA-256은 reports/ad-coin-doc-refresh-2026-11-06/.
- 보안 차단 항목: 사람 승인과 에이전트 키 권한, /spends 행위자·위임 결속, 클라이언트 노출 값 신뢰, 고액 이전 재인증, 운영 경계·복구·실재원 증거. 소스 수정은 이번 범위 아님.
- 성능 근거 정정: 이전 원장 약 195건/초는 사전 seed 분개 포함 최종 행 수의 비율이라 측정 구간 처리량으로 승인 불가. 이전 p99 표본 3건도 부족. 부하·LCP·정적 분석은 재실행하지 않음.
- 운영 서버·DB·플래그·릴리스 변경 없음. 격리 임시 PostgreSQL과 localhost 시험 서버만 사용.

## 2026-11-06 AI AD Coin v5 정책 수립과 기술 설계
- 정책 POL-01~24, 기술 설계 INV-01~06, 구현 순서와 제품 검수 43개, docs/ad_coin_v5_spec.json 작성. 현재 구현·판매 정책·목표 문서에서 v5로 연결.
- 사용자 요구 반영: 초기 공급 0, 광고주 실제 입금 기반 발행, 승인 노출만의 P1 보상, 추가 성과 보상, 사용자 귀속 에이전트 임시 지갑, 내부·외부 이전, 유료 AI·가맹점 사용, 준비금·상환·상장 준비.
- 설계 기본안(확정 발행 승인 아님): 단일 EVM/ERC-20·공식 USDC 담보·1:1 USDC 상환·6자리 정수, 예치/발행·소각/지급 원자성, 임의 민터 없음. 달러는 실제 USDC 전환 뒤 토큰화.
- R>=S와 C>=B를 동일 확정 블록에서 대사. 사용자 승인·에이전트 위임 분리, 출고 결과 불명·재전송·복구·미집행 환불·실행 결속·준비금과 수익 분리를 명세. 기존 시험 잔액 자동 승계 금지.
- 검증: 문서·정책 추적 125개 검사, 후원 가격 정수 경계 24개, 임의 회계 시퀀스 12,000회(5,117 적용·6,883 거부 후 보존). 실제 v5 제품 검수 통과는 0으로 표기. 기존 v4 제품 소스 해시 유지.
- 설명용 Canvas v5의 문법·3개 탭 대체 실행·총량 모형 확인. 원자료는 reports/ad-coin-design-v5-2026-11-06/.
- 메인넷·공식 주소·법적 주체·관할·한도·서명자·수수료·상환·가맹점 계약은 실제 가치 활성화 전에 확정. 이번에는 제품 코드·배포·운영 DB·플래그·자금·키·체인 거래·상장 신청을 변경하지 않음.

## 2026-11-07 AI AD Coin 광고주 플랫폼 정책 v6
- 목표를 모든 AI 에이전트에 열린 광고주 중심 플랫폼으로 확장. 전략→매체 제안·거래→소재·집행→사용자 승인·보상→AI 작업→성과·시장 분석→광고주 재집행의 순환을 정책 PLAT-01~30으로 수립.
- v5 발행·준비금·사용자 권리 기반 유지. 선택 서비스·대행사·분석 수익, 투명한 과금·배분, 중복 매출 방지, 광고주 재집행·실제 AI 작업 효용·매체 수익·공헌이익 지표와 GROW-01~18 개발 검수 추가.
- 기존 개발·판매·목표·자산 정책·기술 설계·구현 순서 문서에 v6 연결. 미래 정책이 기존 시험 기능에 제한되지 않도록 개정 범위와 단계별 관문을 명시.
- 공식 AAMP·AdCP, 논문·공개 SNS 확인. 실험 표준·SNS 의견·논문 효과를 실제 제품 성과로 표현하지 않음. 문서 검증은 reports/ad-coin-platform-v6-2026-11-07/에 기록하며 과거 증거는 보존.
- 이번 범위는 정책·기획 문서. 제품 코드·공개 화면·배포·운영 서버·DB·플래그·실제 자금·체인 거래 변경 없음. v5·v6의 신규 제품 검수 통과 증거는 이번 작업에서 0건.

## 2026-11-07 AI AD Coin 최신 조사 기반 정책 재검토 v6.1
- 뉴스·당사자 발표, 최신 논문 초록·버전 이력, 공개 LinkedIn·X 검색을 검토. AdSteer 11월 3일 제출, 역할에 따른 후원 편향 논문 10월 28일 수정본, 브랜드 대화·측정 연동·에이전트 시장 정보 발표를 반영.
- PLAT-01~30 보존·보완 및 PLAT-31~38 추가: 구조화 광고 정보, 중계 광고 표시·조건 보존, 브랜드 상담, CRM·주문 대사, 최소 맥락·민감 정보 보호, 외부 통계 질의, 자율 수준·사용자 역할 검수, 지역별 발행 적합성.
- GROW-19~28 추가 및 기존 문서 연결 갱신. 기본 노출 보상·초기 공급 0·실입금 기반 발행·준비금·사용자 지갑 권리 유지. 사업 가설·문서 정합성·미구현 제품 검수를 구분.
- X 두 게시물 직접 접근 실패는 당사자 글·기사 통한 간접 확인으로 기록. 기업·논문 성과를 플랫폼 수익 예측으로 사용하지 않음. 근거·변경 이유·검증은 reports/ad-coin-policy-review-v6.1-2026-11-07/에 보관하며 이전 v6 증거는 보존.
- 정책·기획 문서 범위이며 제품·운영 서버·배포·DB·플래그·실자금·체인 거래 변경 없음. 신규 제품 검수 실행 0건, 실제 사업 효과·법적 적합성·보안·성능 검증은 구현 후 수행.

## 2026-11-07 AI AD Coin v6.1 개발 설계
- 최종 정책 기반 플랫폼 아키텍처·데이터/API·개발 작업/인수 기준 작성. 설계 결정 7개·모듈 9개·작업 WP-01~12, 38개 정책과 GROW 28개 검수 연결. v5 자산·담보·상환 불변식과 43개 검수 유지.
- 기존 FastAPI/PG 기반 모듈 구조, v2/adc2 격리, 사람·에이전트·광고주·검토자 권한, revision·최대 보상 예약·일 예산·단회 분개·outbox/inbox·unknown 지급·중계·브랜드 대화·CRM·통계 경계 설계.
- 첫 개발은 격리 모형 P1: 플랫폼 텍스트 렌더러, 승인 전 소재 차단, 독립 노출 보상, 거절·중지·만료·검증 중 hold 보존. OpenAPI와 기계 설계 명세·생성/검증 도구 추가. 실가치 발행·출고·상환은 별도 활성화 관문.
- 문서·계약 구조/스키마/참조/추적/상태/정수 예시 검증과 원자료는 reports/ad-coin-development-design-v6.1-2026-11-07/. 설치 FastAPI의 mutualTLS enum 미지원은 부분 구조 검사와 별도 형식 검증으로 명시하고 실제 계약의 mTLS 요구는 유지.
- 제품 코드·공개 화면·운영 서버·배포·DB·플래그·실자금·키·체인 거래 변경 없음. 실제 제품 인수 기준 통과 0건이며 운영 보안·PG 동시성·브라우저·스마트 계약·성능은 후속 구현 검증 대상.

## 2026-11-07 AI AD Coin 최신 조사 기반 설계 v6.2
- 최종 정책 v6.1·v5 자산 기반은 유지하고 플랫폼 아키텍처/데이터/API/개발 작업을 v6.2로 보강. DEC-08~13, 미실행 제품 검수 DES-01~10 추가.
- 뉴스·공식 프로토콜 문서·논문·공개 SNS 12개 근거 확인. on-policy 광고 유도, stable/beta·인증 전환, 측정 관계·보고 누락/정정, 실행 통제를 구분. 정확한 게시일·직접 접근·실험 재현의 한계를 기록.
- 프로토콜/schema/auth profile 고정, 광고 주장의 독립 근거, 사용자 전체 횟수·시간 quota, 운영 비용 예약, 불변 보고 revision·소비 상태, dispatch epoch·lease generation·unknown 복구, 용도가 고정된 JWS 영수증 설계.
- v6.2 P1 OpenAPI·기계 명세를 새 파일로 생성하며 v6.1 계약/증거 보존. 검증·조사 기록은 reports/ad-coin-design-upgrade-v6.2-2026-11-07/.
- 제품·공개 UI·운영 서버·DB·플래그·키·실재원·체인 거래 변경 없음. 검증은 문서/계약 범위이며 실제 인수·암호 서명·PG 경쟁·브라우저·성능·시장 효과 시험 통과를 주장하지 않음.

## 2026-11-08 AI AD Coin v6.2 상세 설계와 개발 착수
- 상세 설계 목차/부록 5개/API 29개/저장 객체 35개/DTL 20개/카탈로그 작성. 문서 검사 155개 통과이며 실제 제품 검증과 구분.
- 사용자가 상세 설계 완료 후 개발 진행 승인. R0를 WP-01부터 구현하며 운영 배포·실재원·메인넷은 열지 않음. 권한 API 및 회귀 시험 수정 중.
- 진행·완료·남은 작업과 검증은 reports/ad-coin-v6.2-development-2026-11-08/PROGRESS.md에 기록.
- 첫 개발 검증 완료: 관련 고유 시험 134개(전체 131개 실행 후 영향 시험 45개 중복 제거), 격리 PG 파일 10개, 실제 localhost HTTP 보안 219/219. 변경 제품 Ruff S 0건, 공개 content 331개 파일 위반 0건.
- v2 계약 parser·uint256 배분·immutable Principal/만료/epoch/객체 scope 기반 추가. v2 router·DB 원장/예약·P1 handler/UI는 아직 미구현으로 명시. 코드만 수정했으며 사용자의 실행 서버 적용에는 재시작/리로드가 필요하지만 직접 수행하지 않음.

## 2026-11-08 AI AD Coin v6.2 WP-02 PostgreSQL 기반
- 사용자 지시에 따라 신규 v2는 PostgreSQL 전용. 과도기 SQLite 구현·시험·허용 SQL 제거; 기존 v1 역사 코드/자료와 다른 세션 변경 보존.
- 16개 model 기반 표·명시적 migration·uint256 원장·예산 예약/단계 소비/최초 창 반환·멱등 명령/현재 권한 재확인·inbox/outbox lease·일회성 승인·UTC attention 예약 구현. 실제 자금·API 발행·chain·운영 migration·배포 없음.
- 단일 회귀 78/78(새 PG 38+계약 31+기존 PG 9), skip 0; SQLite 이전 시험 1개 수집 제외. 임시 PG+localhost 기존 API 동적 보안 219/219, Ruff S 0 및 일반 규칙 통과.
- SQL 기존 174개 전부 보존+v2 87개=261개. 설계/개발 계획에 PostgreSQL 전용·소수 반올림 거부·구현 범위/남은 도메인과 role/복구 검수 반영. 증거: reports/ad-coin-v6.2-development-2026-11-08/wp02/.
- 다음: WP-03 광고주·조직·캠페인/심사/승인 handler, WP-04 P1·receipt/report·전용 UI 연결. v2 router·인증 adapter·전체 R0는 아직 미완료. 사용자 서버 재시작/운영 변경 없음.

## 2026-11-08 AI AD Coin v6.2 WP-03 모델 광고주 API
- PostgreSQL 전용 schema 2(25개 표): 저장 principal/membership, 불변 campaign revision·등록된 review evidence·fresh 예산 승인, 단회 funding·pause/resume·dispatch epoch/control 구현. 기존 model schema 1 upgrade/unknown version fail-closed; v1 표·실자금 변경 없음.
- v2/http.py의 9개 부분 API factory 및 필수 AuthContext resolver 추가. 전체 29개 계약은 보존하며 미완성 endpoint를 자동 OpenAPI에 광고하지 않음. proof는 idempotency snapshot에 저장하지 않고 별도 key/domain HMAC에서 session/TTL 확인 후 복구.
- 단일 회귀 120/120(새 commercial 42+기존 v2 38+계약 31+기존 PG 9), skip 0. 최종 HTTP 영향 3/3은 같은 testcase 중복. 실제 임시 localhost에서 심사→승인→활성화→중지→재개 및 9개 경계 확인. 기존 v1 HTTP 보안 219/219, Ruff S 0. SQLite 이전 1개 제외.
- 기존 SQL 174개 전부 보존+v2 138개=312개. 증거/해시/제한: reports/ad-coin-v6.2-development-2026-11-08/wp03/.
- 사용자 서버/운영 DB/실자금/체인/배포 건드리지 않음. 실제 IdP/인증서·조직 온보딩/agent binding·광고주 UI·P1 나머지 API·서명/보고/worker·role/복구/부하 인수 미완료.

## 2026-11-08 AI AD Coin 개선 적용 재검수 및 결함 수정
- 추가된 WP-04의 완료 주장을 소스/계약/실패 재현과 대조. 유효 재현 8개 실패를 보존하고 시간 조작·background 경계·정지 누락·nonce 재시도·mTLS truthy·반복 보고·worker cache 신뢰를 수정. 원본 prefix 독립 verifier, owner/authority 잠금, quota 축소, qualified cancel/expiry 권리 보호 추가.
- schema 3에서 구 principal 제약/manifest 열을 명시적으로 이전. 실제 journal과 qualification 기간에 따른 report source manifest·pending 상태·공개 DTO digest·늦은 지급 정정, lease 기한 효과 rollback·미지원 event 거부, Ed25519 목적/정형 검증, 승인/배정 후 revision 수정 차단과 HTTP 202 보강.
- PostgreSQL 전용 단일 회귀151/151, skip0(기존 SQLite 이전1개 제외). 실제 localhost 시간조작 무보상 확인; 기존 v1 동적 HTTP219/219, Ruff S0 및 일반규칙 통과. 증거: reports/ad-coin-v6.2-development-2026-11-08/wp04-review/.
- 잘못된 WP-04 전체 완료·운영 인증 완성 표현과 없는 HTTP operation명을 정정. 현재 모델 schema3·38개 표·계약29개 operation·SQL403(기존174보존). 실제 IdP/TLS·UI/브라우저·role/복구/부하·외부 실가치 gate는 미완료로 기록. 운영 서버/DB/배포/실자금/체인 변경 없음.


## 2026-11-09 AI AD Coin 화면·성능 개선
- 별도 opt-in /ad-coin/v2 영어 화면에 사용자 선택/조건 검토/승인/시청/보상과 역할별 광고주 작성·심사 요청·예산 승인·활성화·중지/재개·보고 조회를 구현. 정적 shell은 초기 API/DB 접근 없이 표시하며 개인 데이터는 사용자가 열 때만 읽는다. 공개 Chat과 실제 앱 mount는 변경하지 않았다.
- cookie/CSRF·CSP·textContent·BigInt·최신 권한 guard·최소 BFF projection·keyset 10개를 적용. 권한 철회/지연 응답 방어와 승인 네 단계의 메뉴 이동 경합·높이0 visibility를 수정. 중지는 즉시 DOM을 숨기고 서버 취소를 수행한다.
- PostgreSQL 전용 schema4·38표·여섯 인덱스. 최종 회귀169/169, skip0(기존 SQLite 이전1개 선택 제외), Ruff 일반/S 위반0, 공개 콘텐츠335파일 위반0, 계약29개 동일·SQL412/기존174보존·소스 해시 검증.
- 시험 종료 후 단독 PG 측정: 이력6000·warm8연결·200건/s×5초, 전후각1000성공/오류0, 도착지연 포함p95 5.336→5.142ms, DBcalls21유지·원장보존·임시DB제거. 로컬 DB command 수치이며 운영/글로벌 최대 성능이 아님.
- 증거/화면/실패 기록/한계: reports/ad-coin-v6.2-ui-performance-2026-11-09/. 실제 IdP/mTLS·운영 role/복구/다지역 부하 인수는 남음. 실행 중 사용자 서버·운영 DB·배포·실자금·체인 변경 없음.

## 2026-11-09 AI AD Coin: 소스 분석, v1 동결, v2 현황 보고
- 소스 분석과 개선사항 17개: reports/AI-AD-Coin-소스분석-2026-11-09.md (계약 준비금 fail-open·단일 소유자, v2 미커밋, v2 화면 디자인 체계 위반, MD5 1건).
- 사용자 결정: v1은 시험 전용 동결. Settings·AdCoinService·Signer가 test_mode=False를 거부(config.require_test_mode, tests/test_ad_coin_v1_frozen.py). 규칙: docs/AD_COIN_V1_FREEZE.md. AD Coin 시험 275개 통과. 전체 시험은 무관한 collector 시험 1개(다른 세션 미커밋 변경)에서 멈춤.
- 총괄 PM 요청으로 v2 현황·남은 과제·법률 검토 자료 목록: reports/AI-AD-Coin-v2-현황과-법률검토자료-2026-11-09.md. 배포·운영 DB 변경 없음.

## 2026-11-09 AI AD Coin 팀: v2 커밋·계약·실가치 잠금·디자인 체계 (총괄 PM 지시)
- v2 커밋(아직 배포 안 함): e346295d(v1 신원 확인 보안), c83c5eda(v2 코드·시험, AD_COIN_V2_ENABLED 기본 꺼짐 시험), 501c399a(설계 문서·검증 기록). 비밀·개인정보 검사 통과. 시험 기록의 호스트 이름과 로컬 경로는 지움. 커밋할 트리를 따로 풀어 AD Coin 시험 293개 통과.
- a60dac6c 토큰 계약 초안: 준비금 fail-closed(피드 없음·0 이하·자릿수·1일 초과·미래 시각 거부), 다중서명 계약 소유자, 2단계 이전, 발행자·피드 변경 2일 지연(7일 만료), 발행은 브리지 발행자만. 배포 도구는 시뮬레이션 계획만 출력하고 --execute는 거부. 가짜 배포 기록 삭제. 결함 목록: docs/AD_COIN_TOKEN_CONTRACT.md. 실험 배정 MD5를 sha256으로 교체(배정은 저장되지 않아 이전 작업 불필요). solc가 없어 컴파일 시험은 못 함(설치는 승인 필요).
- 353c9a0f 실가치 이중 잠금: AD_COIN_REAL_VALUE_ENABLED(기본 꺼짐) 없이는 라우터를 붙이지 않고, 요청이 와도 404, 게이트웨이와 웹훅 처리기는 403. front.py는 v2 마운트만 HEAD 사본에 붙였고, v2는 켤 때만 import한다(os 미import로 서버가 죽을 뻔한 것을 막음). 법률 문서는 "법률검토-쟁점초안"으로 낮춤(단정 삭제, 근거 없는 수치는 확인 필요로 표시, 일정은 검토 후보로).
- 694bd955 v2 화면을 공용 디자인 체계로: 공용 styles/necklace/pearl-live/app.js, 워크스페이스 틀 적용. 자체 app.css·테마 코드·주석 제거. 디자인 유지 시험 추가. 브라우저 시험 21개 통과.
- 남은 일: 4개 법률 자료 초안(약관, 개인정보 흐름도, 화면 문구 묶음, 법령 원문 근거) + 로펌 후보 비교표, 5~7번(커버리지 95%, Redis 속도 제한·jobs 이동, 문서 색인). 화면의 "Platform Audit"·"Agent Relays" 보기는 공개 화면에 내부 용어가 많아 정리가 필요함.

## 2026-11-09 AI AD Coin 팀: 계약 동작 시험, v2 운영자 권한 결함 수정, 법률 작업 보관
- 6f544931 Foundry 1.9.0·solc 0.8.24(사용자 승인, PM 전달)로 AIADCoin 동작 시험 19개(퍼징 2개) 통과. 외부 라이브러리 없이 로컬 EVM만 사용. out/cache는 .gitignore. 결과는 docs/AD_COIN_TOKEN_CONTRACT.md 1.1절.
- 보안 결함(v2, 운영 미연결): 로그인한 아무 사람이나 할 수 있던 것을 운영자 권한(platform.operate, 기본 부여 없음)이 있어야 하도록 바꿈. 대상은 전체 대사·통계, 중계 파트너 등록·목록·해지, 중계 정산. 정산은 클라이언트가 보낸 "증거 확인됨" 값을 믿지 않고 플랫폼이 기록한 노출(viewed) 뒤에만 함. 파트너 주소는 공개 https만 허용. AD Coin 시험 332개 통과.
- 문서: 개인정보 처리 흐름도(v2 감사 로그에 IP·브라우저 정보가 원문으로 저장되고, v2에 보존 기간·삭제 작업이 없음), 화면 문구 묶음, 시험 이용 조건 초안. 법률 원문 확인 결과는 쟁점 초안 7절에, 로펌 후보 비교는 보관(11-09 방향 변경으로 법률 작업 중단).
- 남은 문제: 중계 수수료가 광고주 예산이 아니라 그 자리에서 만든 정산 계정에서 나감(시험 코인이라 실해는 없음). 포인트 모드 설계 때 함께 고침.

## 2026-11-09 성장·유통: 연결 안내·과업 페이지·Registry 준비
- 배포: `growth-frontend-20261109-r1`(21:08, 바탕 traffic-r2) → `r2`(21:36, 공개 페이지 CSP 수정). 게이트 둘 다 passed(113 통과·1 건너뜀). Chat·탐색 로직과 정책 해시 파일은 바꾸지 않음.
- 새 공개 페이지(영어, Pearl 공용 assets): `/connect`(Claude Code·Desktop·Cursor 딥링크·VS Code·OpenAI Agents SDK), `/agents/tasks`, `/agents/task/{slug}`. llms.txt·About·사이트맵에서 연결. 모듈 `concierge/growth_pages.py`, 시험 `tests/test_growth_pages.py` 13건.
- 과업 페이지는 스냅샷 파일 `logs/service-frontend/public-pages/task-pages.json`만 읽음(요청 경로에 DB 없음, 운영 응답 0.9~1.2초). 생성 `scripts/build_task_pages.py`: 공개 Explore API 순차 호출 약 25분, 230개 과업 중 근거 있는 에이전트 2개 이상인 99쪽·424건. 사이트맵 29→130. 근거 기준: 30일 내 실행 점검 성공, 또는 14일 내 정상 헬스체크+시험 호출 성공+품질 A/B. 이름·설명에 과업 핵심어가 없으면 제외.
- 실패에서 배운 것: 첫 배포는 front 기본 CSP(script-src 'none')가 공용 CSS·JS를 막아 무스타일로 보였음(미리보기 서버엔 미들웨어가 없어 못 잡음). 페이지가 자체 CSP를 보내게 고치고 실제 앱 통합 시험에 헤더 검사를 넣음.
- 승인 대기: MCP Registry 게시(`deploy/mcp-registry/`, HTTP 확인 파일 방식 권장, DNS 변경 불필요), 디렉터리 4곳(`reports/MCP·A2A 디렉터리 선별 2026-11-09.md`), 런칭 글(`reports/런칭 글 초안 2026-11-09.md`), 스냅샷 매일 갱신 예약.
- 남은 것: 스냅샷 주기 실행 없음(21일 뒤 사이트맵 제외·noindex). 일부 과업은 관련성이 느슨함(예: search-reddit). `/agents/category/web_search` 125초 응답 발견, SRE에 전달.

## 2026-11-09 AI AD Coin 팀: v2 감사 로그 개인정보 최소화·보존 기간 (PM 1순위 지시)
- 감사 로그는 저장하기 전에 IP를 IPv4 /24, IPv6 /48로 자르고, 브라우저 정보는 browser·mobile_browser·automated·other 분류로 바꿔 저장한다. 지금까지 IP·UA를 넘기는 코드는 없었지만 함수가 원문을 받을 수 있었다.
- 보존: 감사 로그 90일, 끝난 세션·에이전트 토큰·심사자 자격 30일. 작업자 데몬이 1시간마다 500건씩 삭제. 삭제 SQL 4개를 등록 목록에 추가(scripts.ad_coin_sql_registry --add-v2, 540개).
- 시험 15개 추가, AD Coin 시험 347개 통과. 남은 것: 노출 증거·동의·전환의 보존 기간.

## 2026-11-09 성장·유통 2차: 공격적 성장 지시 반영
- 배포: frontend `growth-frontend-20261109-r3`(22:0x, 바탕 latency-frontend-r2, 게이트 118 통과), jobs `growth-jobs-20261109-r1`(바탕 collector-scavenger-jobs-r1, 해당 시험 4통과·1건너뜀, `worker-deploy`). Chat·탐색 로직·정책 해시 파일 변경 없음.
- 새 공개 페이지(`concierge/growth_catalog.py`): 에이전트 페이지 `/agent/{id}` 8,931쪽, 카테고리·프로토콜 순위 `/agents/best/...` 80쪽(순위 기준을 페이지에 공개, 돈으로 순위를 살 수 없음 명시), 비교 `/agents/compare/a-vs-b` 293쪽(공개 순위의 이웃끼리만, "어느 쪽이 낫다"고 말하지 않음), 월간 보고서 `/reports/state-of-ai-agents`(서버 SVG 차트, 수치는 하한), 배지 안내 `/badges`, 증거 카드 `/agent/{id}/card.svg`. 사이트맵 130→9,436. 운영 응답 0.9~2.4초(한국 왕복 포함).
- 스냅샷: 공개 API로 카탈로그 수집(카테고리 20×프로토콜 3×실행 점검 여부, 각 300개 창) → 근거 있는 에이전트 8,931개. 매일 갱신은 jobs 유지보수 칸에서 KST 03~07시, 20초 조각으로 내부 저장소를 직접 검색(`task_pages_job.py`, PM 결정). 운영 PG 경로는 첫 실행(11-10 03시) 로그 "Task page snapshot"으로 확인 필요.
- IndexNow: 키 파일·`/<key>.txt` 제공·`scripts/indexnow_submit.py`(기본 미리보기, 9,436 URL, key_served true). 전송은 승인 대기.
- 등록 제출물 `deploy/distribution/SUBMISSIONS.md`(공식 Registry·mcpservers.org·awesome-remote-mcp-servers PR·mcp.so·MCP Market·Glama·A2A 2곳, 아이콘), 통합 초안 `integrations/`(Claude Code 플러그인 validate 통과, PyPI·npm 패키지 시험 통과), 런칭 글 5~14번 추가. 모두 게시 승인 대기.
- 발견: 실제 플러그인 검증기는 marketplace 최상위 description을 거부(metadata.description 사용). jobs 로그의 VectorError database_error는 이전 판에도 151건 있던 기존 문제. release_gate를 jobs 릴리스에 돌리면 활성 frontend와 비교해 Chat 평가 100건을 돌리므로 `--skip-chat`이 필요.

## 2026-11-09 성장·유통 3차: Registry 반영·IndexNow 차이분
- 공식 MCP Registry 게시(PM, 12:48 UTC) 확인: `biz.agentconcierge/agent-concierge@1.0.0` active. Glama가 Registry를 자동으로 가져가 `/mcp/connectors/biz.agentconcierge/agent-concierge`에 올림(상태 "아직 시험 안 됨"). PulseMCP·mcpservers.org·mcp.so는 아직 없음. `scripts/directory_presence.py`로 하루 1회 확인·기록(`logs/growth/directory-presence.jsonl`).
- /connect·llms.txt에 "Listed on the official MCP Registry" 문구와 링크(커밋 e60f3518). frontend r4로 배포 예정: SRE ops-snapshot 배포 뒤 그 활성판 위에(PM 순서).
- IndexNow: PM이 9,436 URL 전송(첫 일괄 403 → 1개로 키 확인 뒤 성공). 그 뒤 jobs 갱신기가 매일 바뀐 페이지만 보내게 함(`concierge/indexnow.py`, 커밋 8026891d). 지문은 페이지가 보여 주는 사실(점검 종류·등급·목록 구성과 순서)로 만들고 시각·지연은 뺌. 1개 URL로 키 확인 → 403이면 15분 뒤 재시도(최대 8회). 오늘 전송분을 기준선 9,407쪽으로 기록(`public-pages/indexnow-state.json`). jobs r2로 배포 예정: SRE ops-probe-jobs-r2 뒤.
- 1~2주 뒤 확인(11-16·11-23): Bing Webmaster·Naver 색인 수(사용자 계정 필요), traffic 요약의 AI 봇(Google 제외) 요청, MCP clientInfo 이름 수, directory_presence 기록. 기준선은 11-16 traffic 요약.

## 2026-11-10 폰 쿠키 배너가 메뉴 버튼을 덮던 문제 (성장·유통, PM 지시)
- 재현(운영, 390×812, 동의 기록 없음): 11-04 변경으로 폰 배너가 화면 맨 위(top 12px, z-index 99999)에 고정돼 로고와 "Open navigation" 버튼을 덮음. 닫기 버튼도 24px로 44px 기준 미달(전역 24px !important 하한이 32px 규칙을 누름). `test_pearl_frontend` 메뉴 390 시험 실패와 같은 원인.
- 수정(`pearl-live.css` 끝 블록만 추가): 폰에서 배너를 헤더 바로 아래(top 84px)에 두고, 메뉴가 열리면 헤더를 배너 위(z-index 100000)로 올림. 닫기 버튼 44px, "How we use cookies" 줄은 버튼과 겹치지 않게 여백. 홈 입력창(710px)은 여전히 가리지 않음.
- 시험: 새 `tests/test_cookie_banner_phone.py` 9건(390·375·320 × 홈·탐색·Chat), `test_pearl_frontend.py` 41건 통과. 게이트 106건 통과.
- 배포: `cookie-phone-frontend-20261110-r1`(--base price-unknown-frontend-20261110-r1). 운영 390×812에서 메뉴 클릭·닫기 44px·헤더 아래 배치 확인.

## 2026-11-10 AI AD Coin 팀: v2 무상 활동 포인트 모드, 공개 화면 용어 정리
- 실가치 스위치가 꺼져 있으면 v2는 활동 포인트 모드로만 동작한다(docs/AD_COIN_POINTS_MODE.md).
  - 원장 자체가 서로 다른 두 사람의 개인 계정 사이 이동을 거부한다(points_not_transferable).
  - 포인트는 플랫폼 혜택 목록에만 쓸 수 있다.
  - 365일 동안 활동이 없으면 플랫폼 만료 계정으로 옮긴다(작업자가 1시간마다 실행).
  - 구매와 현금화는 기존 실가치 잠금으로 막혀 있다.
- 공개 v2 화면: 사람에게는 points, 광고주 예산은 test credits로 표시한다. 잔액 카드와 바닥글에 포인트 규칙을 보인다. 운영자 보기(Platform Audit, Agent Relays, 위임 결제)와 내부 용어는 공개 화면에서 뺐다.
- 시험: AD Coin 381개 통과, 공개 파일 341개 검사 위반 0건. 원장 기계 시험 3개와 외부 제공자 결제 시험은 실가치 모드로 돌린다.

## 2026-11-10 디렉터리 무료 등록 (총괄 PM, agent-desktop으로 Chrome 조작)
- 사용자 결정: 연락 메일은 contact@agentconcierge.biz, 지출 0, 품질 목표 100%, 속도는 계속 개선, 멈추지 않고 진행(CLAUDE.md·헌장 67365780).
- A2A Registry 제출(Conformant, 검토 대기), a2a.directory 즉시 게시, mcpservers.org 무료 제출(2주 심사).
- MCP Market($69)·mcp.so($39)는 원격 서버의 무료 경로가 없어 건너뜀. 진행표는 deploy/distribution/SUBMISSIONS.md.
- 효과 비교: 11-16 traffic 기준선에서 a2a·mcp 입구 외부 요청과 MCP clientInfo 이름 수를 본다.

## 2026-11-10 AI AD Coin 팀: 공개 Sponsored 영역, 제안 후보 20개 제한 결함 수정
- `GET /api/ad-coin/v2/sponsored` 추가(docs/AD_COIN_SPONSORED_SLOT.md).
  - "Sponsored" 표시를 단 카드를 최대 2개 보인다.
  - 추천과 연결되지 않고, 개인정보와 보상이 없다.
  - 심사를 통과하고 예산이 있는 활성 캠페인만 보이며, 1분마다 돌아가며 보인다.
  - 60초 메모리 스냅샷과 (분류, 지역) 색인을 쓴다. 캠페인 5,000개에서 스냅샷 9.2ms, 조회 1.2µs(최적화 전 85.7µs).
- 결함 수정: 제안 요청이 활성 캠페인을 처음 20개만 읽은 뒤 걸러서, 조건이 맞는 캠페인이 빠질 수 있었다. 분류·지역 조건을 SQL로 옮겼다(jsonb_exists, 등록 SQL 543개).
- AD Coin 시험 387개 통과. 남은 일: Chat·Explore 화면에 붙이는 것(공용 파일이라 PM과 조율).

## 2026-11-10 AI AD Coin 팀: v2 운영 연결 결함 수정과 승인 요청 목록
- 결함 1: v2를 켜면 front.py가 저장소 없이 v2를 만들어 서버가 시작하지 못했다. front.py가 front.store를 넘기고, v2는 같은 DB에 전용 풀(기본 4, 처음 권장 2)을 만든다.
- 결함 2: 키 환경 변수가 없으면 프로세스마다 서명·확인 키가 달라, 슬롯 사이 확인 실패와 재시작 뒤 영수증 검증 불가가 생겼다. 운영 경로는 gateway-data/ad_coin_v2_keys(0600, git 제외)의 파일 키를 쓴다.
- scripts/ad_coin_v2_migrate.py 추가: plan(연결 없음), status, migrate(--i-have-approval 필수, 멱등). 표 53, 색인 31, 함수 5, 삭제 문장 없음.
- 승인 요청 목록: docs/AD_COIN_V2_PROD_CONNECT.md(A1 표 생성, A2 켜기, A3 설정 허용 목록). 시험 435개 통과. 운영 DB·배포 변경 없음.

## 2026-11-10 AI AD Coin 팀: 코인 수익·지출 설계안
- docs/AD_COIN_COIN_ECONOMY.md(설계안, 구현 전).
  - 코인은 플랫폼↔사용자 사이에서만 돈다.
  - 사람↔사람, 사람→광고주 이동은 금지한다(바깥 현금 시장 차단).
  - 광고주는 환영 지급, 제공자 보상, 활동 적립으로만 코인을 얻고, Sponsored 하루 노출을 코인으로 예약한다.
  - 플랫폼 수익은 기여 보상, 신규 등록 보상, 노출 지원으로 쓰고 원장에 남긴다.
  - 발행은 월 상한을 둔다. 혜택은 바깥 비용이 0인 것만 둔다.
  - 새 표는 adc2_sponsored_bookings 1개(A1 승인안에 추가).

## 2026-11-10 AI AD Coin 팀: 코인 경제 1단계(원장 규칙) 구현
- PM이 설계안을 승인했다.
- 원장이 사람→광고주, 광고주→사람 이동을 거부한다. 사람↔사람은 이미 막혀 있었다.
- 새 종류 4개: issuance, grant, sponsored_purchase, growth_reward.
- 발행은 발행 계정→성장 예산만 허용하고 월 상한 100,000코인을 둔다. 제공자 보상 상한은 월 1,000코인이다. 둘 다 코드 상수다.
- 스키마 10: adc2_sponsored_bookings 추가. A1 승인안은 표 54, 색인 32로 바뀌었다.
- 시험 7개 추가, AD Coin 시험 375개 통과. 남은 단계: 성장 예산·지급, Sponsored 예약·결제, 운영 화면 대사, 혜택 연결.

## 2026-11-10 AI AD Coin 팀: 포인트 혜택 후보와 비용 0 근거
- docs/AD_COIN_BENEFITS.md
  - 채택: 포인트 → 워크스페이스 크레딧(customer_credits, 1크레딧=워크플로 저장 1개). 바깥 비용 0(우리 DB만 씀).
  - 보류: 자체 에이전트 추가 실행. 키 없는 공개 API·LLM 없음이라 돈은 0이지만, 사람별 한도가 없어 혜택이 되지 않고 외부 출처 속도 제한만 압박한다.
  - 기각: 기록 보존 연장(개인정보 최소화와 충돌).
- 교환 초안 10:1, 한 번 10, 한 달 50. 크레딧 약관 문구 추가는 사용자 승인 필요.

## 2026-11-10 AI AD Coin 팀: v2 마이그레이션 장애(05:38~05:40) 재발 방지
- 원인: 첫 migrate가 v2 트리거 12개를 애플리케이션의 public 스키마에 만들었고, 앱이 연결 때마다 하는 트리거 검사(_validate_native_invariants)가 실패했다.
- 대응(권장안 a): v2는 자기 스키마 ad_coin_v2에만 표·함수·트리거를 만들고, 모든 연결이 search_path를 고정한다. 앱 검사는 바꾸지 않았다. 트리거를 없애는 안(c)은 원장 불변성을 잃고, 앱 검사를 넓히는 안(b)은 보안 검사를 약하게 해서 쓰지 않았다.
- migrate 도구에 사전·사후 앱 검사를 넣었다.
- public-status와 drop-public 추가: 운영 public에 남은 빈 표 54, 함수 5, 기본 행 3을 정리한다. 기본 행 말고 데이터가 있으면 거부한다.
- 시험으로 장애를 재현(schema_invariants_mismatch)하고, 고친 뒤 앱이 열리는 것을 확인했다. AD Coin 시험 405개 통과. 역할 DDL 기본 스키마도 public에서 ad_coin_v2로 바꿨다.

## 2026-11-10 AI AD Coin 팀: 공개 약관·정책 페이지에 AD Coin 운영 방식 반영(사용자 지시)
- new/en 정책 문구가 들어 있는 33개 페이지에 같은 내용을 넣었다.
  - Terms: Points, Sponsored content and advertisers, Fair use
  - Privacy: Sponsored 영역은 로그인·쿠키·개인정보 미사용, 광고 선택·동의·노출 기록, 보안 기록 90일, 포인트·코인 기록 5년
  - Cookies: Sponsored 영역 쿠키 없음
  - AI 공시: Sponsored는 추천과 분리, Chat 답변에 광고·가격 없음
- 갱신일을 Updated November 10, 2026으로 바꾸고, "Design layout preview" 개발 문구를 시행일로 바꿨다.
- 교환 상수(10 points=1 크레딧, 1회 10, 월 50)를 코드에 두고 약관 문구와 시험으로 묶었다. 공개 문구 검사 342개 위반 0, new/en 관련 시험 367개 통과.

## 2026-11-10 AI AD Coin 팀: 포인트→워크스페이스 크레딧 지급 진입점과 크레딧 약관
- customer_credits.exchange_points(customer, credits, exchange_id) 추가.
  - 가입하고 활성인 계정만 받을 수 있다. exchange_id로 멱등이다.
  - 1회 10, 월 50 상한은 AD Coin 상수를 그대로 쓴다.
- 크레딧 약관(TERMS)에 교환 문구를 추가하고 버전을 workspace-free-2026-11-10-v3로 올렸다. 기존 v2 동의는 LEGACY_ACCEPTANCES에 넣어 유효하게 유지했다.
- 시험 4개 추가, 크레딧 관련 시험 32개 통과. 남은 일: AD Coin 쪽 교환 흐름(포인트 이동 → outbox → 이 진입점 → 실패 시 환불)과 화면.

## 2026-11-10 AI AD Coin 팀: 포인트→크레딧 교환 흐름, 분리 규칙 위반 수정
- 교환 흐름(points_exchange.py)
  - v2 거래 하나에서 포인트 차감과 outbox 일 기록을 함께 한다.
  - 작업자가 customer_credits.exchange_points를 부른다. 교환 id로 멱등이다.
  - 크레딧 쪽이 거절하면(미가입·월 상한 등) 포인트를 환불하고, 일시 실패면 다시 시도한다.
  - 시험 6개(실제 크레딧 진입점 통합 포함).
- 결함 수정: 604f6bc9의 customer_credits.exchange_points가 함수 안에서 AD Coin 상수를 import해, "AD Coin 밖 코드는 AD Coin을 import하지 않는다" 분리 시험(test_ad_coin.py)을 깼다.
  - 운영 버전에 들어갔지만 부르는 곳이 없어 실제 영향은 없었다. 릴리스 게이트 시험 목록에 이 시험이 없어 걸러지지 않았다.
  - 상수를 customer_credits에 두고, 양쪽 값이 같은지 시험으로 묶었다.
- 시험 421개 통과.

## 2026-11-10 AI AD Coin 팀: 코인 경제 2단계(성장 예산과 지급)
- economy.py
  - 월 발행: 달 1회, 원장의 월 상한 검사
  - 환영 지급: 100코인, 1회, 활성 광고주만
  - 제공자 보상: 달 1회, 1,000코인 상한
  - 운영자 수동 지급: platform.operate, 1회 최대 1,000코인, 대상은 사람·광고주 잔액만, 사유는 감사 로그
  - 모두 멱등 원장 기록이다.
- 운영자 API(/api/ad-coin/v2/admin/coins/*, welcome-grant, provider-reward)는 운영자 권한과 CSRF가 필요하다.
- 함께 고침: 중계 파트너 등록·해지·정산 같은 운영자 쓰기 API에 CSRF 검사가 없었다. 이제 막는다.
- 시험 5개 추가(+중계 CSRF 1), AD Coin 시험 398개 통과.
