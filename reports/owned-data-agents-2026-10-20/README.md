# 자체 데이터 에이전트 6개 개발·검증 — 운영 미적용

2026-10-20 KST. 사용자 마지막 지시에 따라 개발만 완료했다. 운영
프론트엔드·메타태그·기존 예제·템플릿·운영 DB·서버·Cloudflare 설정은
변경하지 않았다. 적용은 사용자의 별도 요청 후 진행한다.

## 개발 결과

- 테스트 예제 준비4개: Technology News, Research Papers,
  Country Profile, Package Metadata.
- 추가 에이전트2개: Economic Indicators, Package Security Advisories.
- 워크플로우3개: 뉴스→논문, 국가→인구 지표, 패키지→보안 권고.
  각각2개 에이전트와 수동 트리거로 구성해 총6개를 모두 사용한다.
- `agent_market/owned_data_agents/`: 소스 조회 엔진, 개별 도구 스키마,
  기본 비활성 MCP 라우터, 적용 없는 staging 명세 및 격리 검증 도구.
- `scripts/verify_owned_data_agents.py`: `--live`와 새 결과 디렉터리만
  받으며, 운영 DB 인자·적용 명령·서버 실행 옵션이 없다.

모든 데이터는 실제 Hacker News/Algolia, Crossref, World Bank, npm,
OSV의 공개 API에서 조회한다. 모델·구독 로그인·외부 에이전트·지갑을
사용하지 않는다. 원천 API까지 항상 성공한다고 보장할 수는 없다.
이전 검증 데이터를 재사용할 때는 원래 조회 시각과 stale 표시를 유지하며,
유효한 이전 결과가 없거나 너무 오래됐으면 오류를 반환한다. 샘플용 고정
기록·가짜 성공 결과를 반환하지 않는다.

## 최종 검증

`final-regressions.xml`: **75개 전부 통과**, 실패·오류·skip0.
이전 부분 검사38/66개와 브라우저1개를 이 수에 더하지 않는다.

검증 내용:

- 도구6개의 게이트웨이 지원 스키마·읽기 전용 판별, 원천별 정규화.
- 입력에 따라 결과가 달라지는 처리와 단계 간 입력·출력 전달.
- 캐시 원래 시각/유효 기간, stale 한도, 동시 중복 조회 합치기,
  원천 실패 시 가짜 성공 방지와 실패 쿨다운.
- 잘못된 국가/패키지/버전, URL·자격증명·개인 이메일·사설 경로 입력,
  HTTP/다른 포트/허용되지 않은 메서드, 리다이렉트, JSON 중복 필드·
  비정상 수치·과대 응답, HTTP 쿼터와 내부 오류 노출 차단.
- 격리 프론트엔드에서 테스트4개 실행, 템플릿3개 실행,
  ZIP3개 다운로드와 다운로드한 웹앱3개 실행.
- 기존 자체 문서 검색·Testbench 초기화·템플릿 동작·DNS 재바인딩·
  과대 원격 응답 차단 회귀.

`live-acceptance/verification.json`: 실제 원천 HTTPS로 에이전트6개와
워크플로우3개 모두 성공. 추가로6개 모두 입력을 바꾸어 실제 소스 결과가
달라지는 것을 확인했다. 예: US→GB, express→lodash, AI→quantum computing,
이전 express 버전→현재 npm이 반환한 정확한 버전의 OSV 권고.

실측 개별 호출은 이번 환경에서 약0.05~1.12초였다. 서비스 SLA가 아니다.
워크플로우는 같은 검증 프로세스의 실제 조회 캐시도 정상 사용한다.
원천 HTTP는 실제 TLS/공개 IP로 조회했으며, MCP 서비스 연결은 격리 ASGI다.
외부에 배포된 MCP 엔드포인트의 운영 수용 검증을 완료했다는 의미는 아니다.

`ruff.json` 및 `bandit.json`: 이번 신규 패키지/CLI의 발견 사항0.
기존 공개 콘텐츠 검사217개 파일 위반0, 신규 패키지의 공개 문구/주석
영어 검사 통과. 검증 대상 소스 지문은 검사 중 바뀌지 않았다.

## 적용 상태와 인계

`staged-bundle.json`: 미래 실제 origin의6개 에이전트 스키마,
테스트4개·템플릿3개. **applied:false**, 자동 등록/승인/기동 없음.
격리 proof DB와 내부검증용 `.example` 리소스 ID는 운영으로 가져오지 않는다.
새 경로는 현재 운영 앱에서 import/mount되지 않고 기본 비활성이다.

[개발 명세와 추후 적용 절차](../../docs/OWNED_DATA_AGENTS.md)를 사용한다.
사용자가 요청하기 전에는 운영 Testbench/템플릿을 바꾸지 않는다.
이번 개발을 확인하기 위한 운영 서버 재시작도 필요 없다.

주요 근거: `verification.json`, `final-regressions.xml`,
`live-acceptance/verification.json`, `staged-bundle.json`,
`source-before-final.json`, `source-final.json`, `ruff.json`, `bandit.json`,
`content.txt`.
