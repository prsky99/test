# compact 검색 복구와 로그인·외부 실행 최종 점검

최종 확인: 2026-10-26. **미충족 검색 복구와 실제 로그인 세션의 워크플로우 저장·실행·다운로드 앱 실행을 확인했다.**

## 운영에 적용한 수정

프론트엔드를 `compact-discovery-proof-20261026-r2`로 전환했다. 활성 슬롯 준비 상태 `ready=true`이며, 이전 릴리스는 롤백용으로 보존 중이다(`retained`). 어드민·jobs·execution 프로세스와 Cloudflare 설정은 변경하지 않았다.

- compact 검색은 기본 후보 1개를 확인하고 끝내던 구조였다. 프로토콜별 최대 32개를 먼저 검증하고 최대 3개를 반환하도록 수정했다. 자동/Any의 A2A 우선·MCP 보충과 명시적 x402 조건은 유지한다.
- 공개 `/api/test/execute`와 일부 MCP 실행은 Cloudflare Worker가 직접 처리한다. 이 경로는 Origin MCP 프록시와 ManagedGateway를 거치지 않아 실행 성공이 검색용 검증 이력에 반영되지 않았다.
- 최종 수정은 서명된 Worker 완료 통보를 받는 공통 `Service.finish`에서 현재 연결 버전의 MCP 결과를 기존 Registry에 반영한다. 실패·불확실 결과를 성공으로 인정하지 않는다. 변경된 연결 버전도 임의 승격하지 않는다.
- 동일 완료 통보는 중복 기록하지 않고 원래 완료 시각과 만료 시각을 유지한다. 이력 기록만 일시 실패했을 때 완료 통보를 재처리해도 제공자를 다시 호출하지 않는다. 8개 완료 통보를 4개 스레드로 처리하는 격리 회귀도 통과했다.
- 최종 영향 소스는 `agent_market/agent_access/catalog.py`, `agent_market/edge_gateway/service.py`, SQL 등록 생성기·카탈로그다. SQL 3,802개·기존 테이블 232개이며 새 테이블·마이그레이션은 없다.

최초 r1의 ManagedGateway 보완만으로는 공개 Worker 경로를 해결하지 못했다. 배포 후 실패를 확인해 위 r2로 바로잡았으며, r1의 실패 증거와 [반영 전 보고서](REPORT.pre-rollout.ko.md)를 보존한다. 최종 판정은 r2 운영 결과를 기준으로 한다.

[패키지·소스 일치](r2-package-verification.json), [배포](r2-deploy.log), [활성 준비 상태](final-readiness.json), [PostgreSQL 읽기 전용 쿼리 계획](r2-native-sql.json).

## 이전 미충족 검색: 복구 확인

[이전과 동일한 검색 조건 8개](search-results.json)가 **8개 모두 통과**했다.

- 실제 ByJG Open Source Docs의 `search_docs`에 공개 질의 `micro-orm`을 전달해 약 2.67초에 성공했다. 시뮬레이션이 아니다.
- 동일 현재 버전의 `edge-worker-execution-v1` 성공 증거가 새로 저장됨을 읽기 전용 DB로 대조했다.
- 이전에 `no_match`였던 공식 소프트웨어 문서 검색이 MCP·자동 모드 모두 `matched`로 ByJG 결과와 현재 검증된 계약을 반환했다. 실제 실행 권한은 계속 별도이며 `execution_authorized=false`를 유지했다.
- 뉴스 탐색·채팅·compact, 문서 탐색·채팅, 정확 이름 검색, 공개 템플릿 25개 조회도 정상이다. 이번 소수 표본 응답은 약 1.2~1.8초였으며 부하/SLO 보증은 아니다.

[외부 문서 실행](r2-operating-docs-execution.json), [MCP·자동 복구 응답](r2-operating-recovered-discovery.json), [현재 증거 대조](r2-operating-evidence.json).

## 로그인된 Chrome에서 실제 확인

사용자가 지정한 기존 로컬 Chrome을 `@oai/sky` 컴퓨터 유즈로 조작했다. 기존 브라우저 프로필·쿠키를 추출하거나 세션을 복사·위조하지 않았다. 새 Google/GitHub OAuth 인증이나 로그아웃을 수행한 결과로 보고하지 않는다.

- 기존 세션에서 owner 접근 확인. 로그인 주소 재진입 시 세션 확인 후 `/customer/workspaces`로 정상 이동.
- Overview, Workflows, 저장 목록·검색, Templates, Provider connections, Members & invitations, Plan & credits, Account, Support의 진입·데이터 표시 확인.
- 제공자 연결에서 실제 에이전트 검색 및 OAuth 안내를 확인했다. 새 키 저장·OAuth 승인·자격증명 검증 전송은 하지 않았다.
- 멤버 변경·초대 발송·지원 문의 전송·요금제 변경·계정 삭제는 수행하지 않았다. 로그인·메뉴 점검의 범위를 넘어서는 변경은 없다.

주요 화면: [로그인 상태](operating/01-signed-in.jpg), [개요](operating/13-overview-loaded.jpg), [템플릿](operating/09-workspace-templates.jpg), [OAuth 안내](operating/20-provider-oauth-guidance.jpg), [멤버](operating/35-members-readonly.jpg), [크레딧](operating/36-credits-after-qa.jpg), [계정](operating/38-account-loaded.jpg), [지원](operating/39-support-loaded.jpg), [로그인 주소 재진입](operating/40-authenticated-signin-redirect.jpg).

## 실제 워크플로우와 다운로드 앱

사용자의 검증 크레딧 사용 승인에 따라 다음 항목 1개를 저장했다.

- 이름: **QA Verification 2026-10-26 - External Sources**
- 템플릿: Software Licensing Reference Pack
- 입력: React와 Lodash 패키지명, 공개 질의 `open source software licensing`, 문헌 최대 3개.
- 사용 크레딧: **1개**. 잔액 99,977 → 99,976. 저장 이후 실행·다운로드·다운로드 앱 실행에서 추가 차감이 없는 것을 확인했다.
- 워크스페이스 실행: Manual Trigger와 실제 에이전트 단계 3개가 모두 `succeeded`.
- Chrome에서 `my-workflow.zip` 다운로드 완료. 6개 파일, 6,235바이트, 새 QA 이름과 패키지 동일성 확인. 자체 점검 폴더에 안전하게 추출했다.
- 다운로드한 `index.html`을 로컬 Chrome에서 열고 **Run Workflow**를 직접 클릭했다. 역시 3개 에이전트 단계 모두 성공했다. npm 메타데이터와 Crossref의 문헌·DOI 출처를 표시했다. 응답 일부는 표시된 정책대로 fresh cache를 사용했으며 이를 모든 호출이 새 원본 조회였다고 표현하지 않는다.

[저장 후](operating/26-new-qa-saved.jpg), [실행 전 입력 확인](operating/27-new-qa-run-review.jpg), [실행 중](operating/28-new-qa-running.jpg), [단계별 성공](operating/30-new-qa-all-steps-succeeded.jpg), [다운로드 완료](operating/31-download-requested.jpg), [패키지 동일성](download-verification.json), [다운로드 앱 성공](operating/34-downloaded-app-succeeded.jpg).

## 기존 QA 항목의 별도 제한

`QA Live Verification 2026-10-20 - Battery Research`는 그대로 보존했다. 이 항목은 실행 준비 단계에서 접근 오류가 발생했다.

읽기 전용 대조에서 연결 버전·기존 승인은 유지됐지만, 문서 검색 계약 검증이 약 34시간 전에 만료됐음을 확인했다. 로그인된 최고관리자 화면의 **기존 승인 계약 테스트**에 공개 연구 질의를 실제 전송해 성공 증거를 갱신했다. **새 계약 승인·권한 변경은 하지 않았다.**

그 뒤에도 저장 당시 변환기 `implementation_hash`와 현재 구현이 달라 실행 준비가 차단됐다. 이는 이전에 검토한 구현과 다른 코드를 묵시적으로 실행하지 않는 안전 조건이다. 기존 워크플로우 핀을 DB에서 바꾸거나 검증 조건을 완화하지 않았다. 이 기존 항목을 다시 사용하려면 현재 구성으로 다시 검토·저장해야 한다. 새 검증본의 성공과 이 기존 항목의 미완료 상태를 구분한다.

[기존 오류](operating/07-qa-execution-review.jpg), [계약 만료](old-qa-contract-expiry.json), [실제 계약 재검증 성공](operating/24-existing-contract-verified.jpg), [승인 유지·구현 차이](old-qa-adapter-diff.json), [재검토 전 차단 유지](operating/25-qa-prepare-after-verification.jpg).

추가 UI 개선 후보: 이 경우의 일반적인 접근 오류 문구를 연결 재검토 안내로 구체화할 필요가 있다. 다운로드 앱의 구조화된 출력도 일반 사용자가 읽기 쉬운 표시로 개선할 여지가 있다. 이번 검색 수정과 실행 점검의 범위를 확대해 이 두 UI를 재개발하지 않았다.

## 회귀·보안 검증과 범위

최신 테스트 식별자 기준으로 중복 제거한 **격리 회귀 352개가 통과**했다. 검색·권한·서명·버전 변경·중복 통보·실행 재시도 방지·API/Chromium 로그인 보안 범위를 포함한다. 합성 Google/GitHub 제공자 회귀를 실제 OAuth 인증 성공으로 간주하지 않는다.

[Worker·검색](r2-worker-search.xml), [전송·API·브라우저](r2-delivery-security.xml), [Worker 최종·동시 통보](r2-worker-final.xml), [로그인 최신 UI 동선](auth-browser-refreshed.xml). 이전 로그인 회귀의 모바일 로그아웃 실패 2개는 현재 메뉴 동선으로 갱신한 최신 결과로 대체했으며 원본 로그는 보존했다.

정적 F/E9/S 검사 통과, 공개 콘텐츠 290개·위반 0개, SQL 카탈로그 재생성 일치, 실제 PostgreSQL 읽기 전용 계획 확인을 완료했다. 전체 외부 제공자, 유료 실행·결제, 새 OAuth/API 키 연결, 장기 부하·전역 동시성 품질 보증은 이번 완료 범위가 아니다.
