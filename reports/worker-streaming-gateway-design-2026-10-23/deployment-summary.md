# Current catalog rollout — 2026-10-23

Remaining eligible public Providers now use catalog-policy Edge routing. Current deployed Worker77241c53, Frontend/Admin193728, all five Routes fail-open. CPU10ms compliance remains unverified (final MCP14.8ms, runtime errors0). See [current deployment record](catalog-rollout-summary.md). Earlier sections below are historical.

# 실제 Provider 전달 활성화 완료

2026-10-23 현재, **CHS Backflow(resource 145303) 1개 Provider**를 실제 Worker 전달 경로로 활성화했다. 해당 Provider의 결과 본문은 Provider → Cloudflare Worker → 사용자로 전달한다. 기존 서버는 승인·버전 검증·실행권·완료 상태 메타데이터를 관리한다.

적용 경로는 신규 Edge SDK, 같은 Origin의 기존 `/api/gateway/a2a/*` 및 `/api/test/execute`다. 기존 응답 계약을 보존했다. 다운로드 앱도 해당 Gateway를 같은 Origin에서 호출하는 경우 적용된다. 다른 Provider·MCP/x402·외부 Origin 요청·다른 Workspace/Workflow 실행 API는 기존 경로를 유지한다. 전체 Provider를 일괄 전환한 상태와 구분한다.

공개 Gateway와 Testbench의 실제 신규 소개 작업을 각각 실행했고, 두 작업 모두 `backend=worker`, `succeeded`로 기록됐다. 최적화 버전에서는 완료 기록의 출력 바이트가 실제 사용자 응답 본문 바이트와 일치했다. 두 응답에서 Provider 호스트 주소가 노출되지 않았다.

첫 공개 검증에서 CPU가 26.3ms와 12.2ms로 측정돼 새 요청을 잠시 Origin으로 보냈다. 승인·실행권 callback 통합, 공통 검증 후 직접 JSON 출력, 중간 SSE 재파싱 제거와 minify를 적용했다. 최종 공개 검증 시간대의 CPU P99 최대값은 **8.6ms**, runtime 오류는 **0건**이었다. 이는 이번 소규모 검증 결과이며 모든 출력 크기·동시 부하의 상한을 보증하는 수치와 구분한다.

현재 정책은 `auto`, `worker_ready: true`, 승인 Provider 1개이며 운영자 전용 시험 제한은 해제했다. 계정 사용량·서명 health의 주기 관찰이 동작한다. 3개 Route 모두 `request_limit_fail_open: true`다. 무료 한도 여유 부족·관찰 실패·runtime 차단 시 Origin 복귀 정책을 유지한다. 실제 100,000회 소진 시험은 수행하지 않았다.

Worker 최종 버전은 `669a4e2c-3d07-4887-a615-afcadbc7a91d`(100%)다. Frontend/Admin은 `edge-cpu-20261023-175748`로 반영했고 readiness가 정상이다. 어드민 리뉴얼의 기존 파일을 보존했고 Jobs/Execution은 변경하지 않았다. 새 DB 마이그레이션은 필요하지 않았다.

Python/config/deployment 92개, Chromium 6개, workerd 22개가 통과했다. CPU 최적화 후 영향받은 Python 36개를 재검증했고 Bandit 지적은 0건이다. 공개 콘텐츠 248개 파일의 위반은 0건이다.

현재 검증의 원본은 `activation-validation.json`, `activation-optimized-public-results.json`, `activation-optimized-cpu.json`, `activation-routes.json`, `activation-post-services.json`이다. 이전 배포와 측정 기록은 아래에 보존한다.

---

# JSON/SSE 호환성 수정 배포 완료

2026-10-23 후속 수정에서 Worker의 SSE 전용 제한을 해소했다. 현재 Worker 버전은 `9fe85806-7cd5-46e0-944d-0a18d2447373`이며 트래픽 100%에 적용했다. Frontend/Admin은 최신 리뉴얼 Release를 기반으로 한 `edge-json-20261023-171808`에 배포했고 readiness를 확인했다. 기존 Route, fail-open, 암호화 Secret과 Jobs/Execution을 보존했다.

승인 설정의 `request_mode`에 따라 호출 전에 `message/stream` 또는 `message/send`를 선택한다. 원천의 JSON/SSE 응답을 동일한 플랫폼 SSE로 전달하며, HTTP 200 내부 오류와 미완료 Task를 성공으로 표시하지 않는다. 같은 실행의 메서드 변경·자동 재호출을 차단한다. 새 DB 마이그레이션은 필요하지 않았다.

Python 90개, Chromium 6개, workerd 17개가 통과했다. Bandit 지적 0건, 공개 콘텐츠 248개 파일 위반 0건이다. 운영 Worker 서명 health, 잘못된 실행의 401 거부, 새 완료 기록 API의 미등록 시도 409 거부를 검증했다.

Rosentic은 추가로 확인한 표준 `message/send`에도 JSON-RPC `-32601`을 반환했다. Antigravity의 공개 Card는 404가 나오는 기존 주소를 계속 안내하며 인증·결제 관련 기능도 선언한다. 두 Provider는 활성화 대상에서 제외하며 `providers: []`, `worker_ready: false`를 유지한다. 실제 Provider 정상 출력·Free CPU 검증과 실사용 출력 비용 절감은 아직 확인하지 못했으며 사용자 실행은 기존 Origin이 처리한다.

연구 근거: [상호운용성 조사 논문](https://arxiv.org/abs/2505.02279), [A2A 0.3 공식 규격](https://a2a-protocol.org/v0.3.0/specification/), [공식 SDK의 전송 형식 불일치 사례](https://github.com/a2aproject/a2a-python/issues/1089), [MCP/A2A 운영 경험 SNS 논의](https://www.reddit.com/r/mcp/comments/1x4q8t1/mcp_for_tools_a2a_for_agent_to_agent_is_anyone/). 구체적인 구현 판단은 공식 규격을 기준으로 했으며 SNS는 현장 문제를 파악하는 참고 자료로 사용했다.

현재 검증 근거는 `dual-response-validation.json`, `dual-response-live-validation.json`, `dual-response-host-validation.json`, `provider-card-recheck.json`, `provider-json-recheck.json`에 있다. 아래는 앞선 최초 인프라 배포 당시의 기록이다.

---

# Cloudflare Gateway 인프라 배포 결과

2026-10-23 기준, Worker 인프라와 운영 Origin의 연결·인증 검증을 완료했다. 실제 Provider 작업 전환은 호환 검증을 통과한 대상이 없어 보류했으며, 기존 서비스는 Origin 실행을 유지한다.

## 운영에 적용한 항목

- Worker `agentconcierge-edge-gateway`, 최종 버전 `b7abb4fb-f43c-4c47-b7d2-a940567a9375`를 100% 적용했다. Free 플랜을 유지한다.
- Route `agentconcierge.biz/api/edge-gateway/v1/*`를 Computer Use로 연결했다. API에서도 `request_limit_fail_open: true`를 확인했다. workers.dev와 preview URL은 비활성이다.
- `SHARED_SECRET`, `CONTROL_ORIGIN`을 암호화 Secret으로 저장했다. 같은 키와 운영 설정은 Git에서 제외된 owner-only 파일로 보관한다.
- Computer Use로 단일 계정의 `Account Analytics: Read` 전용 Token을 생성했다. 실제 API에서 활성 상태와 집계 조회를 검증했다. 권한에 설정 변경 기능은 없다.
- 별도 `edge-gateway.env`를 통해 Frontend/Admin에만 새 설정을 반영했다. 이전 Release가 새 설정을 무시하도록 분리해 롤백 호환성을 보존했다.
- 승인받은 PostgreSQL 추가 테이블 6개·인덱스 2개·초기 정책 행을 적용했다. 기존 애플리케이션 테이블의 구조와 데이터는 이 마이그레이션에서 수정하지 않았다.
- 기존 활성 Release에 이번 Gateway 변경만 덧붙인 `edge-20261023-150028`로 Frontend와 Admin을 A/B 전환했다. 두 프로세스의 readiness가 정상이다. 이전 Release를 유지했고 Jobs·Execution 설정은 변경하지 않았다.

## 실환경에서 검증한 동작

Worker가 반환한 health의 HMAC·nonce를 검증해 실제 Worker 응답임을 확인했다. Worker에서 Origin으로 보내는 내부 claim도 HMAC 검증을 통과했고, 미등록 실행 ID와 위조 실행권은 401로 거부했다. 별도 Origin 경로도 미등록 실행을 거부했다. 이 검증에서는 Provider 작업을 만들지 않았다.

배포 과정에서 내부 callback이 공유 Worker IP로 인식돼 기존 Origin IP 차단에 걸리는 문제를 발견했다. 같은 Origin의 제어 요청에 Cloudflare가 부여한 출처 IP만 전달하도록 수정했다. 브라우저의 forwarding 헤더는 신뢰하지 않으며 Provider에 사용자 IP를 전달하지 않는다. HMAC·nonce·기존 IP 차단은 유지한다. workerd에서 해당 경계의 추가 테스트를 포함해 10개가 통과했다.

최종 관찰 시 전용 Token으로 계정 요청 6회와 Worker runtime 오류 0회를 조회했다. 실제 애플리케이션 observer를 1회 실행해 Analytics 조회·서명 health·신규 정책 기록도 확인했다. 현재 dormant 상태에서는 주기적 observer가 시작되지 않으며, Provider 활성화 후 주기 관찰이 동작한다.

영향받은 Python·설정 테스트 76개, Chromium 테스트 4개가 통과했다. 앞선 어드민 리뉴얼 포함 preflight 87개도 통과했다. 새 Python 패키지 Bandit 검사와 공개 콘텐츠 248개 파일 검사에서 지적 사항은 없었다.

## 실제 Agent 전환을 보류한 이유

승인받은 소개 질문을 각 1회 전송한 결과 Rosentic은 HTTP 200의 JSON 응답을 반환했고, Antigravity는 HTTP 404를 반환했다. 두 대상 모두 현재 구현한 A2A 0.3 SSE 계약을 만족하지 않았다. 따라서 `providers: []`, `worker_ready: false`를 유지하며 검증 완료 플래그를 사실과 다르게 설정하지 않았다.

현재 일반 사용자 요청과 기존 SDK·Workflow 앱의 결과 본문은 기존 Origin 경로를 사용한다. 이번 배포로 해당 실사용 출력 비용이 감소했다고 주장할 수 없다. Worker를 통한 실제 Provider 전달은 프로토콜·Origin 호환성·출력 개인정보/주소 계약·Cloudflare Free CPU 검증을 통과한 대상이 추가된 뒤 활성화한다.

실제 100,000회 quota 소진, Provider streaming의 Cloudflare CPU 10ms 제한, 대용량 파일·MCP·x402·외부 도메인 웹앱은 이번 실환경 검증 범위에 포함하지 않았다.

근거는 `deployment-validation.json`, `live-worker-preflight.json`, `live-monitor-preflight.json`, `live-route-verification.json`, `post-deployment-services.json`과 `worker-route-active.png`에 보관한다. 비밀값은 보고서에 기록하지 않았다.

## 후속 적용과 복귀

승인된 Provider를 추가할 때는 실제 현재 capability version을 고정하고, 프로토콜·출력·Origin·실제 Free CPU 검증을 먼저 수행한다. 그 후 `worker_ready`를 활성화하고 Frontend/Admin에 정상 배포 절차로 반영한다. 기존 SDK와 앱은 신규 SDK 통합을 별도로 진행해야 한다.

기존 실행 경로 유지는 현재 활성 상태다. 향후 Worker 실행을 켠 상태에서 복귀가 필요하면 host 제어의 `origin` 모드를 사용해 새 실행을 Origin으로 유도한다. 이미 실행권을 취득한 작업과 결과 불명 작업은 다시 실행하지 않는다. Cloudflare Route를 해제해도 인증된 Origin 어댑터가 같은 경로를 처리한다.
