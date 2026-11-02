# 공개 등록·문의 보안 개선 및 시험 데이터 정리

작성일: 2026-10-27. 범위: 공개 에이전트 등록/자동 조사, 문의, 개인정보 요청, 작업 알림과 사용자가 지정한 QA 데이터. 운영 데이터 삭제는 완료했다. 새 검증 정책은 사용자의 배포 실행 후 운영 반영까지 확인했다.

## 개선 내용

- 동의: 서버에서 `agreed: true`, 현재 약관·개인정보 버전 `2026.1`, 시간대가 포함된 ±10분 이내 시각과 boolean 개인정보 신호를 검사한다. 서버 수신 시각·동의 범위를 함께 비공개 감사 기록에 저장한다. 등록과 감사 저장을 한 트랜잭션으로 묶어 감사 저장 실패 시 등록도 취소한다. 클라이언트 주장 시각은 신원·소유권·법적 동의의 독립 증명으로 간주하지 않는다.
- 등록: 실제 MCP 초기화/탐색 응답, 이름·스킬·공개 연결 주소를 가진 A2A 카드, HTTP 402와 유효한 지원 네트워크/USDC 결제 조건을 확인해야 등록된다. 임의 HTTP 200·401·빈 402를 MCP/x402로 추정하지 않는다. 조사는 도구 실행이나 결제를 하지 않는다. 프로토콜 확인을 실행 품질 검증으로 표시하지 않는다.
- 입력: 카테고리, 가격의 정수·범위, 네트워크, 주소 형식, HTTP 메서드를 검사한다. Solana 주소의 대소문자를 보존한다. 사이트 자신·하위 게이트웨이·설정된 공개 도메인, URL 자격 증명, 내부 주소를 거절한다. DNS 실패/시간 초과/내부 목적지 오류를 구분하며 실제 전송에도 기존 제한·주소 고정 보호를 적용한다.
- 자동 조사 화면: 확인하지 못한 프로토콜을 성공으로 표시하지 않고 안내한다. 이전 이름·설명이 다음 조사에 남지 않게 한다. 동의 체크 값을 실제 전송하고 성공 화면의 허구 기본 도구 수 5개를 제거했다. 기존/새 화면 및 `extracted_html.txt`를 동기화했다.
- 문의: 이름·제목·메일의 CR/LF·제어 문자를 거절한다. 표준 이메일 주소 파서와 형식을 검사하고 HTML을 비활성화한 뒤 유효 길이를 다시 확인한다. 같은 출처·이메일·내용의 문의는 10분간 같은 접수번호를 반환한다. 이메일당 5건/시간, IP당 15건/10분을 DB에서 검사한다. PostgreSQL 트랜잭션과 잠금이 두 웹 슬롯의 경합을 막는다.
- 현재 문의 처리는 DB 접수이며 SMTP 발송 기능은 없다. 새 발송 기능을 임의 추가하지 않았다. 따라서 발송 헤더/Reply-To는 이번 검증 대상이 아니다. 기존 관리자 문의 표시의 출력 이스케이프 경계는 유지했다.
- 개인정보 요청: `request_type`을 필수로 하여 빈 요청을 CCPA 요청으로 자동 접수하지 않는다. 기존 확인·검토 완료 증거 요구는 유지한다.
- 제한: 등록 조사·등록·문의·개인정보 접수를 별도 한도로 관리한다. 429에 Retry-After와 실제 한도 정보를 제공한다. 이 경로의 정상적인 한도 초과 반복만으로 사이트 전체를 자동 차단하지 않는다. 악성 입력에 대한 기존 보안 차단은 유지한다.
- 알림: 인증되지 않은 외부 목적지는 생성 후 24시간 기준으로 연결 권한·이벤트·검증 기록과 함께 삭제한다. 기존 1시간 인증 코드 만료와 확인된 정상 구독의 보존은 유지한다. 작업 스케줄러의 유지보수 주기에 정리되므로 정확한 정각 삭제를 보장하는 것은 아니다.
- 구형 공개 등록 경로의 오류 문구를 영어로 정리했다. PostgreSQL 명시적 SQL 목록을 갱신했다. 신규 테이블이나 운영 스키마 전환은 필요하지 않다.

## 운영 데이터 삭제 결과

삭제 전 ID와 이름/URL/계정을 대조하고, 연관 데이터와 함께 소유자 전용 권한(0600) 백업을 남겼다. 백업은 공개 서비스·Git 대상에서 제외했다. 외래키를 포함한 동일 삭제 코드의 격리 PostgreSQL 검증 후 트랜잭션으로 정리했다.

- 에이전트: 206598, 206599, 206602, 206603, 206604 — 5건 삭제.
- 문의: 지정한 `inq_...` 7건 삭제.
- 개인정보 요청: 지정한 `prv_...` 3건 삭제.
- 알림: 지정한 pending/failed 및 revoked 구독 2건과 연결된 확인 기록·권한 삭제.
- 평가: QA 방문자 `av_fea05423e252`의 성공/실패 결과 2건 삭제. 실패 시각과 일치하는 `feedback` 1건도 삭제. 실제 AgentBIT(34471), 리소스 1번은 유지.
- 해당 가짜 에이전트에 생성된 결과 보고서 1건, 보고서 예약, 연결 버전·검증 근거·헬스 이력·검색 색인 및 pgvector 임베딩 5건과 벡터 작업/출처도 함께 삭제.
- 전체 재조회에서 지정 대상과 연결 데이터가 0건이다. 공개 `/api/agents/{id}`는 삭제한 5개 모두 404, 실제 1번·34471번은 200이다.
- QA 문의 출처의 차단 규칙은 0건이었다. 해제할 차단이 없다.

선택 항목인 일반 방문자/대화/트래픽 통계는 삭제하지 않았다. 실제 크롤러나 브라우저 방문과 섞이는 GPTBot·HeadlessChrome 등을 일괄 삭제하지 않았다. 공개 API 확인 자체는 `RegistrationCleanupVerification/1.0`이라는 별도 점검 방문 기록을 남길 수 있다. 비공개 복구 백업은 의도적으로 남아 있다.

삭제 수치와 공개 확인: [cleanup-result.json](cleanup-result.json), [cleanup-postcheck.json](cleanup-postcheck.json), [public-cleanup-verification.json](public-cleanup-verification.json), [qa-ip-rule-check.json](qa-ip-rule-check.json).

## 검증

- 등록·문의·프라이버시·알림·기존 보안/법적 UI 회귀: 115개 통과.
- 구형 브로커/인증 조사 회귀: 33개 통과. 공통 프록시 회귀: 4개 통과.
- 실제 Chromium의 기존/새 공개 등록 화면: 2개 통과. 동의 요청 전송, 미확인 프로토콜 안내, 실패 시 미등록, 스크립트 오류 여부 확인. 증적: `registration-legacy.png`, `registration-published.png`.
- 격리 PostgreSQL 18 회귀: 1개 통과. 동의 원자성, 중복 등록 거절, 지속형 문의 중복/한도, 생성 후 24시간 삭제, 실제 외래키를 가진 QA 정리 및 재실행 안전성, TCP 차단 확인.
- 고정 배포 후보 자체에서도 임시 PostgreSQL 계약 검증을 별도로 통과했다. [packaged-native-postgres.json](packaged-native-postgres.json).
- 새 정책 모듈의 Ruff 검사 통과. 공개 콘텐츠 검사 위반 0건, embedded HTML/추출 파일 일치. 자동 보안 스캐너 Bandit은 이 테스트 환경에 설치되지 않아 실행하지 않았으며 전체 서비스 무취약성 인증을 의미하지 않는다.
- 실제 이메일 발송·제공자 도구 실행·유료 결제·OAuth 소유권 증명은 실행하지 않았다. 등록 프로토콜 검증과 입력 경계를 중심으로 점검했다.

## 운영 반영

배포 후보: `registration-hardening-20261027-r1`. 1,311개 파일 해시와 후보 자체의 SQL 목록을 검증했다. 작업 중 다른 변경이 있는 공용 작업 폴더와 분리해 고정 후보를 검증했다. 서비스 교체는 사용자가 실행했고, 이후 실제 프로세스와 공개 API에서 반영을 확인했다.

```sh
./agentcon deploy frontend registration-hardening-20261027-r1
./agentcon deploy admin registration-hardening-20261027-r1
./agentcon worker-deploy jobs registration-hardening-20261027-r1
```

프론트엔드는 공개 입력 검증/화면, 어드민은 알림 관리 경로, jobs는 주기적인 미인증 알림 정리에 해당한다. execution·PostgreSQL·모델 서버 교체는 이번 범위에서 필요하지 않다. jobs 교체 시 신규 자동 작업 처리가 잠시 멈출 수 있다. 위 명령은 사용자가 실행했다. 프론트엔드·어드민의 실제 준비 상태와 jobs 실행/생존 신호에서 동일 릴리스가 운영 중임을 확인했다. 정리 데이터와 신규 검증 정책이 모두 운영에 반영되었다.

## 적용 근거

- [OWASP 입력 검증](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html): 서버의 허용 값·형식·길이 검증.
- [OWASP SSRF 방어](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html): 공용 주소 확인, 주소 재검증, 리디렉션 제한.
- [Python 표준 이메일 주소 처리](https://docs.python.org/3/library/email.headerregistry.html): 주소 파싱과 헤더 입력 경계.
- [Circle 공식 USDC 계약 주소](https://developers.circle.com/stablecoins/usdc-contract-addresses): 지원 네트워크의 실제 USDC 식별.
- [A2A 규격](https://a2a-protocol.org/v1.0.0/specification/), [MCP 버전별 공식 SDK 문서](https://ts.sdk.modelcontextprotocol.io/v2/protocol-versions): 프로토콜 응답과 실행 확인의 구분.


## 배포 후 실제 운영 확인 — 2026-10-27 09:42 KST

- 프론트엔드·어드민·jobs 모두 `registration-hardening-20261027-r1`. 두 웹 서비스 준비 상태 정상, jobs 생존 신호 약 1초 이내. 파일 1,311개 무결성 확인.
- 공개 API/페이지 점검 24건 통과: 동의 누락·거부·만료·버전 불일치, 허용 값, 음수 금액, 자기 사이트·내부 주소·URL 자격 증명, 문의 헤더 제어 문자·잘못된 메일·분류·스크립트 본문, 개인정보 요청 종류 누락을 실제 서비스에서 거절했다. 기능별 한도 정책 헤더도 확인했다.
- 실제 공개 사이트의 Chromium 등록 화면에서 체크된 동의 값 전송, 자기 사이트 등록의 거절 및 사용자 오류 안내를 확인했다. 스크립트 오류 0건. 증적: `registration-live-deployed.png`.
- 삭제한 5개 에이전트 404, 실제 에이전트 1번/34471번 200 유지. 원래 삭제 대상·연결 데이터 재조회 0건. 이번 거절 점검으로 만들어진 에이전트/문의도 0건.
- 24시간 초과 미인증 외부 알림 목적지 0건. jobs 현재 시작 시각은 09:39:31 KST이며 최근 50KB 로그 중 그 이후 ERROR 기록 0건. 확인된 이전 수집/벡터 오류는 이 시작 시각 전의 이력이다.
- 운영에서는 성공하는 새 등록·문의·개인정보 요청·알림을 만들지 않았다. 정상 저장·중복 방지·정리의 양성 검증은 앞서 격리 PostgreSQL에서 수행한 범위다.

증적: [deployment-verification.json](deployment-verification.json), [live-browser-verification.json](live-browser-verification.json), [jobs-deployment-log-check.json](jobs-deployment-log-check.json).
