# r1 배포 후 운영 확인과 r2 보완

2026-10-25. 사용자가 실행한 배포 상태는 프론트엔드 `frontend-request-quality-20261025-r1`, jobs `jobs-request-quality-20261025-r1`로 확인됐다. 두 프로세스는 실행 중이며 서비스 상태는 stable이다. 공개 JS/CSS 해시는 활성 릴리스와 일치했다.

공개 서비스에서 AI 뉴스·스포츠·서울 날씨·문서 검색·불명확한 AI 요청·불가능한 요청 6종을 REST/A2A/MCP로 확인했다. 6종 모두 추천 ID가 일치했고, 후보가 있는 4종은 상세 조회도 일치했다. AI 뉴스의 첫 추천은 Technology News였다.

그러나 실제 운영 경로에서 다음 3가지 추가 문제가 확인돼 r1 전체 운영 검증을 완료 처리하지 않았다.

1. 공개 뉴스 실행이 503 `UNAVAILABLE`을 반환했다. 같은 요청은 원본 프록시에서 성공했다. 공개 Edge 경로가 자체 도구를 외부 MCP로 다시 조사하면서 `/api/owned-data-agents/...`에 403을 받았다. 같은 시각 보안 로그에는 Worker egress에 사용되는 Cloudflare 주소에 대한 scanner 자동 차단 이력이 있었다. 이미 로컬 실행 경로가 있는 자체 도구를 외부로 우회시키는 것이 문제였다. 인증·입력·Origin·속도 제한을 거친 뒤 자체 도구는 원래 공개 게이트웨이의 로컬 실행으로 보내도록 수정했다. IP 차단이나 보안 정책을 해제하지 않았다.
2. 실제 공개 도구 API는 `inputSchema` 외에 `params`/`required` 형식도 사용한다. 이 축약형에서 Chat 요청을 Test의 query로 복사하지 못했다. 실제 브라우저에서 재현했고 두 형식을 지원하도록 수정했다. 필수 입력 표시도 함께 수정했다. 기존 격리 테스트가 이 형식을 놓친 점을 보완해 두 형식 모두 브라우저 회귀에 포함했다.
3. jobs의 RAG backfill 조회에서 반복적인 DB 오류가 있었다. PostgreSQL 로그의 같은 시각·jobs backend PID에서 5초 statement timeout이 확인됐다. 동일 SQL은 단독 검사에서 정상으로 재현돼 SQL 등록 누락은 확인되지 않았다. 대량 카탈로그의 상관된 제외 조회를, 동일한 미완료 작업·게시 세대·head·모델 조건을 한 번 집계하는 native PostgreSQL 조회로 바꿨다. 운영 카탈로그 읽기 전용 비교 2회에서 후보는 같았고 약 1.56~1.68초에서 0.52초로 줄었다. 전체 파이프라인의 속도나 시간 초과 해소는 r2 적용 후 확인이 남아 있다.

## 검증

- r1의 실제 공개 3경로 검색 6종 및 후속 상세 조회는 일치했다.
- r2 프론트엔드 후보의 실제 명세 형식·브라우저·Edge 인증/라우팅·보안 회귀: 175개 통과, 레거시 화면용 6개 제외.
- Edge 라우팅 집중 회귀: 59개 통과. 자체 도구에 새 실행 grant를 만들지 않으며 서명 없는 요청 및 잘못된 Origin은 계속 거절한다.
- 새 backfill native SQL: 세션 전용 PostgreSQL 임시 테이블에서 1개 테스트 통과. pending/claimed/failed/current publication 제외와 stale generation/new/replaced head/다른 모델의 재처리 조건, 정렬·limit을 확인했다. 운영 public 테이블을 사용하지 않았다.
- jobs 관련 검사에서 73개는 통과했다. 별도의 전체 PostgreSQL Store 계약 1개와 기존 ANN 검사는 임시 서버 초기화가 호스트의 SysV 공유 메모리 ID 한도에 걸려 실행하지 못했다. 디스크 부족이나 코드 assertion 실패가 아니다. 신규 조회는 위의 실제 PostgreSQL 세션 전용 테스트와 운영 카탈로그 읽기 전용 실행으로 대체 검증했다. 기존 ANN 전체 회귀가 재실행됐다고 주장하지 않는다.
- 프론트엔드 콘텐츠 272개 파일 위반 0건, JS 문법 및 SQL 카탈로그 정합성 확인.

## 준비된 릴리스

- `frontend-request-quality-20261025-r2`: 실행 중인 frontend r1 기준. 자체 도구의 public prepare 라우팅과 compact 입력 명세·빌드 JS만 보완했다.
- `jobs-request-quality-20261025-r2`: 실행 중인 jobs r1 기준. native backfill 조회만 보완했다.

파일 해시는 `reviewed-releases-r2.json` 및 각 릴리스의 `release.json`에서 검증했다. 어드민·execution 워커·모델 서버·Cloudflare Worker를 교체할 필요는 없다. 현재 실행 중인 r1 파일이나 프로세스는 수정하지 않았다.

```sh
./agentcon deploy frontend frontend-request-quality-20261025-r2
./agentcon worker-deploy jobs jobs-request-quality-20261025-r2
```

AGENTS.md가 명시적 요청 없는 운영 프로세스 교체를 금지하므로 적용은 대기 중이다. 적용 후 공개 Edge를 통한 뉴스 실행과 실제 브라우저의 요청 전달, jobs의 다음 RAG 주기를 확인해야 최종 완료다. r1 점검에서 발생한 503과 브라우저 실패 증거는 `live-check.log`, `browser-check.log`에 보존했다.

2026-10-25 r2 적용 후 확인: 사용자가 두 서비스를 r2로 전환했다. 공개 6종 검색의 REST/A2A/MCP 결과 및 상세 조회 일치, 실제 뉴스 실행, 데스크톱/모바일 요청 전달과 실제 Run Test, r2 시작 이후 색인 완료 162건을 확인했다. 최신 결과는 [r2 운영 확인 보고서](../post-deploy-r2/REPORT.md)를 기준으로 한다. 위의 ‘적용 대기’는 r2 배포 전의 기록이다.
