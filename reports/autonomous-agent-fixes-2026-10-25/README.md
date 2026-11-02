# 자율형 Agent 호환성·Edge 실행 수정 결과

완료일: 2026-10-25, Asia/Seoul. 최초 검토에서 재현한 호환성 문제 2건과 기존 회귀 검사 1건을 해결했다. 지원되는 공개 MCP의 실행도 기존 Edge Ticket 경로에 연결해 Frontend·Admin에 반영했다.

## 무엇을 해결했는가

### 공개 안내와 실행 Schema 불일치

`mcp_contract.py`의 단일 도구 정의에서 공개 manifest와 실제 `tools/list`를 생성한다. 두 입구의 11개 도구와 입력 Schema가 일치한다. 검색의 표준 입력은 `task/kind`이며 이전 안내를 사용하던 Agent의 `query/protocol`도 수용한다. 충돌·잘못된 자료형·빈 작업은 명확한 입력 오류로 처리한다. 명시적 Any Protocol도 Schema에 포함했다.

manifest의 전송 안내는 실제 POST JSON 응답형에 맞춰 `streamable-http`로 수정했다. GET의 405 응답은 이 전송 규격에서 허용된다.

### 실행 실패를 성공으로 표시하던 문제

MCP `call` 실패는 `isError=true`로 반환한다. 구조화된 실행 상태와 표준 MCP 오류 신호를 일치시켰다. 실패 사실을 보고하는 `report` 요청 자체가 성공한 경우에는 성공 응답을 유지한다.

Provider가 실패했다고 확인된 경우 적격 대체 후보를 제시한다. 전송 중 응답 손실·시간 초과 등으로 실행 결과가 불확실하면 `retry_safe=false`로 표시하고 자동 대체·재실행을 멈춘다. 이 경우 Provider 실패 피드백과 도구 전이 이력을 잘못 기록하지 않도록 수정했다.

### MCP 실행의 Edge 연결

지원되는 무료 공개 MCP 도구는 기존 실행권 발급 → Worker 호출 경로를 사용한다. 무료 한도 등으로 Origin을 사용하더라도 동일한 Ticket과 실행 점유 절차를 적용한다. 유료·인증 입력·내부 소유 도구·미지원 Profile은 Ticket 발급 전에 기존 승인된 경로를 사용한다.

Ticket을 발급한 뒤 전달 실패가 생기면 기존 프록시로 재전송하지 않는다. 동일 Visitor와 `idempotency_key`에 대해 입력 변경·Ticket 만료·응답 손실·설정 롤백이 발생해도 새 호출로 우회하지 않는 시나리오를 검사했다. 키는 같은 Visitor 문맥과 동일한 입력으로 재사용해야 한다. 현재 실행 기록 보존 기간은 7일이다. 중복 방지 범위는 이 기록 보존과 Ticket 경로에 한정되며, 외부 Provider의 임의 부작용을 포함한 무조건적인 exactly-once 보장을 주장하지 않는다. 이미 완료한 요청의 중복 호출은 새 실행 대신 검토가 필요한 상태를 반환한다.

도구 Schema·Registry 버전과 입력을 실행권에 결합한다. HTTP 전달에는 임시 실행권만 사용하고 Visitor token·Cookie·공유 Secret을 Provider에 전달하지 않는다. 공개 MCP의 기존 프록시 경로도 public 네트워크 정책을 명시해 개발 환경의 private-network 허용 설정을 상속하지 않게 했다. 다음 도구 힌트의 주소도 플랫폼 Gateway 주소로 투영했다.

### 기존 대체 후보 검사 실패

기존 fixture에는 같은 작업의 대체 Provider가 없었다. 관련성 기준을 낮추는 대신 동일 작업에 적격한 두 번째 Provider를 fixture에 추가했다. 확인된 도구 오류는 정상 MCP `isError=true`로 모의하고, HTTP 500·응답 손실은 불확정 결과 검사로 분리했다. 기존 실패·대체 후보 검사를 통과했다.

## 논문·SNS 조사에서 적용한 판단

- [MCP 공식 오류 처리](https://ts.sdk.modelcontextprotocol.io/v2/servers/errors)는 도구 실행 오류의 `isError` 반환 근거다. [공식 HTTP 전송 규격](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)을 기준으로 manifest 전송 안내도 정리했다.
- [ExoFlow, OSDI 2023](https://www.usenix.org/conference/osdi23/presentation/zhuang)는 실행과 복구를 분리하는 설계를 제시한다. 이로부터 기존 durable Ticket이 실행 소유권을 유지하게 하는 방식을 선택했다. 응답 손실 뒤 Origin으로 무조건 다시 호출하지 않는 것은 이 시스템에 적용한 보수적 설계 판단이다.
- [ToolEmu 논문](https://arxiv.org/abs/2309.15817)은 위험한 Agent·도구 상황을 격리 환경에서 검사하는 접근을 다룬다. 이번에는 실제 Provider와 결제 대신 결정적인 모의 응답으로 실패·응답 손실·권한 경계를 재현했다. ToolEmu 자체나 논문의 성능 수치를 구현·재현한 결과는 아니다.
- SNS의 [MCP outputSchema 사용 경험 토론](https://www.reddit.com/r/mcp/comments/1tauwhg/outputschema_in_mcp_useful_feature_or_token_tax/)과 [Schema 문맥 부담 토론](https://www.reddit.com/r/mcp/comments/1x2u6sb/i_got_tired_of_mcp_tool_schemas_eating_my_context/)에서 클라이언트별 처리 차이를 조사했다. 글과 댓글은 경험 자료로만 사용했다. 구체적인 클라이언트 결함·토큰 수치를 검증 사실로 인용하지 않고, 단일 Schema와 이전 별칭 호환·실제 HTTP handler 검사로 해결 방향을 검증했다.

## 검증 결과

- 자율형 Agent 여정: **12개 모두 통과**. 처음 10/12에서 두 호환성 실패를 해결했다.
- API·Agent·Edge 관련 회귀: **202개 통과**. 기존 OpenAPI Operation ID 중복 경고 1건이 남아 있다.
- Machine 자동화·권한·REST·Gateway 관련 회귀: **155개 통과**.
- Frontend API 보안: **22개 통과**.
- 격리 Chromium 보안: **11개 통과**.
- 추가 중복 실행 경계 등을 보강한 최종 경로 검사: **47개 통과**.
- 실제 Frontend·Admin 배포 후보를 각각 import한 격리 검사: **각 47개 통과**.
- 공개 Frontend 콘텐츠 검사: **263개 파일, 위반 0건**. embedded HTML과 `extracted_html.txt`를 보존했으며 변경한 Python 파일의 컴파일과 Canvas 번들 검사도 통과했다.

앞의 네 회귀·보안 그룹은 390개다. 12개 여정은 관련 API 그룹에 포함되며, 최종 경로·패키지 재검사는 중복이 있어 합산하지 않았다. 로그는 이 디렉터리의 `*-tests*.log`, `final-path-checks-2.log`, `frontend-content-check-final.log`에 보존했다. Bandit은 환경에 설치되어 있지 않아 실행하지 않았고, 소스 보안 검토와 위 동적 회귀 검사를 수행했다.

## 운영 반영

기존 활성 패키지에서 수정한 제품 파일 3개만 반영했다. Frontend의 다른 manifest 파일 1,203개, Admin의 1,196개를 보존했다. 진행 중인 Admin 리뉴얼과 다른 작업의 변경을 섞어 배포하지 않았다.

- Frontend: `agent-mcp-fixes-frontend-20261025-073530`
- Admin: `agent-mcp-fixes-admin-20261025-073530`

기존 승인된 A/B 절차로 교체했고 이전 슬롯을 복구용으로 유지했다. 준비 상태, 페이지·자산, 관리자 API 접근 차단, 패키지 무결성을 확인했다. 로컬 활성 입구와 `https://agentconcierge.biz` 양쪽에서 manifest와 `tools/list`의 11개 도구가 일치하며 Any Protocol·중복 실행 방지 입력·Streamable HTTP 안내도 확인했다. 확인 내용: `live-verification.json`.

기존 설정의 `native_node_delivery=true`, `worker_ready=true`, canary 비활성, A2A·MCP·x402 catalog 설정을 읽기 전용으로 확인했다. Secret 내용은 보고서에 기록하지 않았다. Jobs·Execution의 PID와 릴리스가 전후 동일하다. Cloudflare Worker 업로드·새 Secret·운영 DB 마이그레이션은 없었다.

## 유지한 권한 경계와 남은 확장

게시 Workflow는 기존 HTTP API로 승인한 입력을 실행하고 실행 키로 결과를 조회한다. 새 Workflow 생성·편집은 Workspace 권한을 유지한다. 목적·기간·건수가 제한된 Machine 알림과 장기 Task도 기존 권한을 유지하며, 기본 비활성 worker를 일괄 활성화하지 않았다.

추가 MCP Workflow 전용 도구와 범용 Agent용 Workspace 위임은 별도 확장 항목이다. 이번 실패 원인과 기존 공개 Workflow 사용을 구분했다. 권한 없이 새 그래프를 만들거나 사람의 비용·실행권을 대신 사용하는 기능을 추가하지 않았다.

실제 Provider 업무 호출·결제·운영 채팅은 실행하지 않았다. 운영에서는 공개 메타데이터만 조회했다. 격리 검사의 성공을 실제 Provider 전체의 성공률이나 24시간 장기 부하 완료로 해석하지 않는다. 기존 Provider 캠페인·메모리 부하 실패 기록과 읽기 전용 추적은 이번 수정 범위와 분리해 보존했다.
