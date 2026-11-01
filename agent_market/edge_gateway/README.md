# Workers Free streaming Gateway 운영 안내

실행 정책을 통과한 등록 Provider의 A2A 0.3·1.0, MCP 도구 실행, x402 결제 없는 조회 결과를 Cloudflare Worker에서 직접 받아 전달한다. 기존 애플리케이션 서버는 실행 승인·실행권·결과 상태 메타데이터를 관리한다. 무료 한도 여유나 Worker 정상 동작을 확인하기 어려우면 새 실행은 기존 서버의 Origin 경로를 사용한다.

이 기능은 기본 비활성 상태다. 최초 구현 이후의 실제 배포 상태는 `reports/worker-streaming-gateway-design-2026-10-23/deployment-checkpoint.md`에 별도로 기록한다. 소스 업로드와 운영 Route·Provider 활성화는 구분한다.

## 적용 범위

- 원천 응답은 `application/json`과 `text/event-stream`을 모두 처리하며, 사용자에게는 동일한 플랫폼 SSE 계약을 제공한다. 승인 설정의 `request_mode`는 `stream`(기본값, `message/stream`) 또는 `json`(`message/send`, `blocking: true`)이다. Agent Card와 실제 검증 결과를 확인한 운영자가 사전에 선택하며, 실행 도중 메서드를 추측해 재호출하지 않는다. 모드도 준비된 입력 해시에 고정한다.
- HTTP 200 내부의 JSON-RPC 오류는 성공으로 처리하지 않는다. 지원하지 않는 메서드, 잘못된 입력, 호출 주소의 404, 인증 요구와 한도 오류를 고정된 안전 코드로 구분한다. Provider의 원문 오류·주소·디버그 데이터는 공개 응답이나 완료 기록에 복사하지 않는다. JSON Task가 아직 `working`이면 결과 불명으로 보존하고 자동 재실행하지 않는다.
- 기존 개별 승인 프로필 `a2a-03-informational-stream-v1`과 카탈로그 자동 승인 프로필 `catalog-public-v1`을 지원한다. 자동 승인은 `catalog_protocols`에 명시한 프로토콜에만 적용하며, 매 실행마다 현재 활성 상태·보안·인증·가격 정책과 capability version을 확인한다. Provider 인증키를 요구하는 호출은 기존 공개 실행 정책에 따라 거부한다.
- Worker 입력 8 KB, 메시지 2,000자, SSE 프레임 16 KB, 원천 응답 총 64 KB, 출력 텍스트 총 48 KB, 실행 8초로 제한한다. 임의 대용량 파일·바이너리·x402 결제·복합 Workflow는 이 Edge 프로필 범위 밖이다. 큰 MCP discovery 계약은 실행권 취득 전에 기존 Origin으로 전달한다.
- Origin은 기존 `ManagedGateway`의 제한된 실행 결과를 최종 SSE 이벤트로 감싼다. Origin으로 전환하면 기존 서버의 처리·출력 네트워크 비용이 발생한다.
- 신규 A2A SDK와 기존 `/api/gateway/a2a/*`, `/api/gateway/mcp/*`, `/api/gateway/x402/*`, `/api/test/execute`가 대상이다. 공개 stateless Gateway는 외부 웹앱의 CORS를 허용하며 credentials를 허용하지 않는다. MCP initialize/list/ping은 기존 Origin 메타데이터를 유지하고 tools/call의 원천 응답만 Worker로 전달한다. 계속 실행·다른 실행 API·별도 Workflow/Workspace 서버 실행은 기존 경로를 유지한다. 다운로드 앱은 이 공개 Gateway를 호출하는 경우에 적용된다.
- 현재 정보성 호출에는 기존 과금·Credit 정책을 추가하지 않았다. 유료 다른 Provider 재시도 기능과 인프라 전달 경로 복귀는 별개다.

기존 JSON Gateway/Testbench의 정상 JSON 응답은 공통 A2A 검증 후 직접 직렬화한다. 중간 SSE 생성·재파싱을 생략하고 승인·실행권 취득을 한 번의 인증 callback으로 묶어 Free CPU 사용량과 통신을 줄인다. SSE Provider와 신규 SDK는 기존 증분 전달을 유지한다.

## 카탈로그 자동 라우팅

`catalog_protocols: ["a2a", "mcp", "x402"]`를 owner-only 설정에 추가하면 개별 ID 목록 밖의 등록 Provider에도 현재 실행 정책으로 Edge 경로를 선택한다. 기존 `providers` 핀은 우선 적용한다. 각 Provider를 미리 실행 검증했다는 플래그를 만들지 않으며, 신규/변경 capability는 실제 실행 전에 현재 버전으로 고정한다.

- A2A 0.3은 blocking message/send, 1.0은 SendMessage를 사용한다. 완료된 Task의 artifacts, agent status.message/history와 typed data를 처리한다. 미완료 Task는 성공으로 만들지 않는다.
- MCP는 Worker에서 새 프로토콜 세션의 metadata를 조회한다. 전체 등록 입력 Schema를 Origin에서 먼저 검증하고 원격 full Schema 해시가 일치하면 추가 검증 callback을 생략한다. 비교를 확정할 수 없으면 기존 서명된 서버 Schema 검증을 사용한다. 전체 등록 입력 Schema 검증에 통과하고 원격 full Schema 해시가 고정값과 일치한 안전한 도구만 한 번 실행한다. 해시를 확정할 수 없으면 기존 서명된 서버 비교로 확인하며, 실제 불일치 시 실행을 거부한다. 발견된 Schema 변경은 실제 실패 근거로 기록한다. 브라우저 Cookie·Authorization·세션을 Provider에 복사하지 않는다.
- x402는 GET probe만 수행한다. 402 challenge의 버전·금액·수신처·리소스 구조를 검증하며 Payment-Signature를 생성하거나 전달하지 않는다. 유효한 402는 결제 요청이며 실행 성공과 구분한다.
- 승인 URL·원천 Origin은 플랫폼 Gateway 주소로 투영하고, 비밀 필드와 토큰은 제거한다. 독립된 인용 URL은 유지한다. 도구 실행 결과 본문은 제어 서버에 업로드하지 않는다. MCP 해시 비교를 확정할 수 없는 경우에만 Schema 메타데이터를 제어 서버에서 추가로 확인한다.
- 인증·위험 도구·격리·기존 Schema 실패는 거부한다. 미지원 URL/프로필·큰 MCP 계약·무료 한도/health 사유는 실행 시작 전에 Origin으로 돌아간다. 이미 실행권을 취득한 실패·시간 초과는 중복 실행하지 않는다.

이 설정은 적격 요청의 자동 라우팅 정책이다. 전체 카탈로그가 개별 실측을 완료했다는 의미로 사용하지 않는다. Free CPU는 protocol별 실제 표본으로 확인하고 운영 관찰을 유지한다. A2A의 증분 SSE와 달리 MCP/x402 및 JSON 응답은 제한 크기까지 검증 후 전달한다.

## 어드민 리뉴얼과 연결

`/admin/api/v2/gateway/edge-delivery`는 개인 관리자 세션과 기존 `X-Dashboard` 검증을 사용하는 읽기 전용 API다. `superadmin`, `admin`, `operator`만 조회할 수 있다. 공유 machine token·개발용 우회·viewer는 허용하지 않는다.

반환 항목은 현재 경로/사유, 승인 범위·활성 프로토콜, UTC 사용 창, Cloudflare 계정 집계, 보수적 로컬 예약, 최근 24시간 경로별 실행 수·상태·출력 본문 바이트다. Provider 주소·키·방문자 식별자·입력/출력 본문은 반환하지 않는다. 바이트는 압축 전 플랫폼 응답 본문이며 Cloudflare 청구 바이트와 구분한다.

리뉴얼의 레이아웃·탭·JS 파일은 수정하지 않았다. 화면 연동은 이 독립 API를 사용하면 된다. 운영 변경은 아래 host CLI로 분리했다.

## 무료 한도와 자동 복귀

1. Cloudflare 계정 전체의 당일 요청 수와 특정 Worker 오류를 읽기 전용 GraphQL로 관찰한다. 기본 관찰 주기는 60초다.
2. `관찰된 계정 요청 + 오늘 누적 로컬 예약`이 기본 90,000 이상이면 새 실행은 Worker Route 밖의 `/api/origin-gateway/v1/`로 발급한다. 누적 예약은 지연 집계와 중복 계산할 수 있어 실제 90,000보다 일찍 전환할 수 있다.
3. 관찰 또는 서명된 Worker health가 기본 300초보다 오래되거나 실패하면 Origin을 선택한다. 설정·계정 관찰 권한이 없을 때도 Origin이 기본이다.
4. 계정당 100,000회/UTC 일 무료 한도에 도달한 경우에 대비해 Cloudflare Worker Route의 **fail open**을 별도로 설정한다. Origin은 Worker와 같은 URL에서도 독립적으로 인증·정책·원자적 실행권을 검증한다.
5. Worker 오류는 같은 날 오류 집계에 포함되는 동안 보수적으로 차단한다. 다음 UTC 일(한국 09:00)에도 runtime 차단은 유지되며, 수정 검증 후 명시적으로 해제하고 새 health 확인을 받아야 한다. 일일 사용량 사유만 새 관찰로 자동 회복한다.

SDK는 최초 전송에 실패하면 소유자 권한으로 상태를 확인한다. 아직 `prepared`인 동일 실행에만 Origin 실행권을 발급한다. `dispatch_reserved`·성공·실패·결과 불명 상태에서는 재실행하지 않는다. 180초가 지난 미확정 예약은 `outcome_unknown`으로 보존하며 자동 재시도하지 않는다. 실행 ID·입력 해시의 중복 방지는 7일 보관 범위다. 동일 키로 다른 입력은 거부한다.

로컬 예약은 악성 요청·다른 Worker의 급증·Cloudflare 집계 지연까지 완전히 예측할 수 없다. 무료 플랜의 최종 한도와 fail-open 검증이 비용/가용성 경계를 보완한다. 자동 Paid 업그레이드나 유료 저장소는 설정하지 않는다.

## 적용 순서

### 1. 기존 DB에 추가 테이블 준비

운영 백업·배포 절차에서 다음 명령을 명시적으로 실행한다. SQLite 도구는 기존 파일만 열며 다른 애플리케이션 테이블을 초기화하지 않는다.

```sh
.venv/bin/python -m agent_market.edge_gateway.migrate --sqlite /absolute/path/to/existing.db
```

PostgreSQL은 기존 `APPLICATION_STORE_BACKEND=postgresql`, owner-only `APPLICATION_POSTGRES_DSN_FILE`, `APPLICATION_WORKFLOW_KEY_FILE` 설정을 그대로 사용한다. 이 경우 `--sqlite`는 기존 실행 인터페이스를 위한 인자이며 PostgreSQL이 선택된다. 운영 DSN을 명령행에 직접 쓰지 않는다.

### 2. Provider와 설정 파일 준비

프로필의 개인정보/주소 투영, 기존 Origin 호환성, 실제 Cloudflare Free CPU 10ms 이내 처리를 사전 검증한다. 검증 전에는 Worker를 활성화하지 않는다. `providers[].version_id`는 실제 Registry의 현재 `cv_…` 값을 사용한다. Schema가 바뀌면 기존 핀은 거부된다.

owner-only JSON 파일(권한 `0600`, 서비스 사용자 소유)을 준비하고 `AGENT_EDGE_GATEWAY_CONFIG`에 절대 경로를 설정한다. 아래는 **자리표시자 예시**다. 공유 비밀은 새로 생성한 32바이트를 Base64로 인코딩하고 서버 파일과 Worker secret에만 저장한다.

```json
{
  "profile": "a2a-03-informational-stream-v1",
  "shared_secret": "REPLACE_WITH_BASE64_OF_32_RANDOM_BYTES",
  "public_origin": "https://agentconcierge.biz",
  "worker_ready": false,
  "soft_limit": 90000,
  "max_inflight": 4,
  "usage_max_age_seconds": 300,
  "providers": [{
    "resource_id": 123,
    "version_id": "REPLACE_WITH_CURRENT_REGISTRY_VERSION",
    "endpoint": "https://approved-provider.example/a2a",
    "privacy_reviewed": true,
    "origin_compatible": true,
    "free_cpu_verified": true
  }]
}
```

Review 플래그는 실제 검증 결과를 나타낸다. 미검증 Provider는 설정에 추가하지 않는다. 입력에 URL을 받아 임의 Provider를 호출하는 기능은 제공하지 않는다.

실제 Free CPU 검증을 위한 제한 시험에는 owner-only 설정의 `canary_principal`을 무작위 64자리 hex로 지정할 수 있다. 이때만 `free_cpu_verified: false` 후보를 허용하며, 해당 principal의 준비·실행권만 승인한다. 공개 Gateway 연결은 Origin을 유지하고 일반 visitor의 신규 준비와 기존 비시험 실행권을 거부한다. 운영자가 로컬에서 시험 실행을 준비해 실제 Worker로 검증한 후에만 CPU 플래그를 true로 바꾸고 `canary_principal`을 제거해 일반 활성화한다. Provider의 개인정보·Origin 호환 검토는 시험 전에도 필수다.

Provider 검증 전의 인프라 준비에는 `worker_ready: false`, `providers: []`를 사용할 수 있다. 이 상태에서는 실행 대상이 승인되지 않는다. `catalog_protocols`도 비어 있으면 빈 목록으로 Worker 실행을 활성화하는 설정은 거부한다.

관리형 배포에서는 기존 `agentcon.env`를 유지하고 owner-only `gateway-data/edge-gateway.env`에 아래 세 경로/식별자만 기록한다. 새 Release의 Frontend/Admin이 이 파일을 읽으며, 이전 Release는 무시해 롤백 호환성을 유지한다. 비밀값 자체는 이 파일에 넣지 않는다.

```text
AGENT_EDGE_GATEWAY_CONFIG=/absolute/path/to/edge-gateway.json
AGENT_EDGE_CLOUDFLARE_ACCOUNT=REPLACE_WITH_ACCOUNT_ID
AGENT_EDGE_CLOUDFLARE_TOKEN_FILE=/absolute/path/to/analytics.token
```

### 3. Worker staging 검증과 Route 준비

Worker 소스·설정은 `cloudflare/edge-gateway/`에 있다. 공식 Wrangler 4.152.0을 해당 패키지의 개발 의존성으로 고정했다. 운영 도구에서 다음 값을 설정한다.

- `PUBLIC_ORIGIN`: `https://agentconcierge.biz`.
- encrypted secret `SHARED_SECRET`: 서버 설정과 동일한 Base64 비밀.
- encrypted secret `CONTROL_ORIGIN`: 내부 claim/complete API에 도달하는 HTTPS Origin. Worker Route를 다시 통과하지 않는 서버 주소여야 한다. 주소는 브라우저에 제공하지 않는다.
- Worker 이름: `agentconcierge-edge-gateway` — 관찰 쿼리의 이름과 동일하게 유지한다.

`wrangler.toml`에는 운영 Route·계정·키가 없다. staging에서 Origin의 동일 경로 인증, Origin 직접 경로, Schema 거부, SSE 첫 응답·완료, 연결 중단, CPU 제한을 검증한 뒤 `agentconcierge.biz/api/edge-gateway/v1/*` Route를 연결한다. 다른 제어 API와 `/api/origin-gateway/v1/*`는 이 Route 밖에 둔다. reverse proxy가 두 경로를 기존 앱에 전달하는지 확인한다.

Route의 fail-open은 Cloudflare에서 명시적으로 설정한다. 일일 quota 우회와 CPU 초과 오류는 구분한다. 실제 quota 초과·Route 우회는 배포 환경에서 확인해야 한다.

운영 Route가 콘솔에서 관리되는 상태의 코드 갱신에는 `wrangler versions upload --keep-vars`와 명시적 version ID의 `wrangler versions deploy`를 사용한다. 트리거 배포는 별도 변경이다. 갱신 후 `request_limit_fail_open: true`와 Secret 이름의 보존을 다시 확인한다.

### 4. 읽기 전용 관찰과 활성화

- `AGENT_EDGE_CLOUDFLARE_ACCOUNT`: 계정 ID.
- `AGENT_EDGE_CLOUDFLARE_TOKEN_FILE`: 필요한 계정 Analytics Read만 부여한 API token 파일. 서비스 사용자 소유, `0600` 또는 `0400`. 값은 로그·명령행·브라우저에 넣지 않는다.
- staging 검증 완료 후 `worker_ready: true`를 적용한다.
- 사용자가 운영하는 서버는 사용자의 배포 절차로 재시작한다. 이 개발 과정에서는 실행 중인 서버를 조작하지 않았다.

새 프로세스는 정상적인 계정 관찰과 실제 Worker의 서명된 health를 확인하기 전까지 Origin을 유지한다. Origin이 반환하는 `backend: origin`은 Worker health로 인정하지 않는다. Cloudflare 응답 파싱 실패·오류·계정 접근 실패도 Origin으로 복귀시킨다.

### 5. opt-in SDK 연동

`/sdk/agentconcierge-edge-v1.js`를 기존 CSP에 맞는 외부 script로 로드하고, 기존 visitor 세션을 메모리에서 전달한다. 토큰·실행권은 URL·DOM·스토리지에 출력하지 않는다. 아래 예제는 개발 문서용이다.

```js
const client = AgentConciergeEdge.createClient({visitorToken});
const handle = await client.prepare({
  resourceId,
  message,
  idempotencyKey: crypto.randomUUID(),
  runAuthority: true,
  sharingAuthority: true
});
const result = await client.run(handle, {
  onDelta: text => outputElement.append(document.createTextNode(text))
});
```

`runAuthority`와 `sharingAuthority`는 해당 실행·선택한 Provider로의 전송에 대한 명시적 승인을 받은 후 전달한다. 같은 작업에 네트워크 재시도가 필요할 때는 같은 idempotency key를 유지하고 기존 실행 상태를 확인한다. SDK는 한 handle에서 실행을 한 번만 시작한다.

## 운영 제어와 롤백

현재 revision을 조회한 뒤 변경한다. 관찰 프로세스와 경합해 revision이 바뀌면 다시 조회한다. 변경 사유·호스트 uid를 별도 audit에 저장한다.

```sh
.venv/bin/python -m agent_market.edge_gateway.control --sqlite /absolute/path/to/existing.db status
.venv/bin/python -m agent_market.edge_gateway.control --sqlite /absolute/path/to/existing.db origin --revision 12 --reason 'Controlled Origin rollback'
.venv/bin/python -m agent_market.edge_gateway.control --sqlite /absolute/path/to/existing.db auto --revision 13 --reason 'Validated delivery restored'
.venv/bin/python -m agent_market.edge_gateway.control --sqlite /absolute/path/to/existing.db clear-runtime-block --revision 14 --reason 'Corrected profile validated' --validated-profile
```

위 revision 숫자는 예시다. runtime 차단 해제는 health도 초기화한다. 관찰되는 당일 Worker 오류가 남아 있으면 다시 차단한다. 즉각적인 전체 비활성화는 설정 제거/`worker_ready: false` 후 기존 배포 절차로 반영한다. Route를 해제해도 동일 경로의 Origin 인증 어댑터가 남는다. 실행 중인 작업을 새 작업으로 다시 시작하지 않는다.

## 보안·비용 경계

실행권은 120초 이내의 opaque run ID·Origin·audience로 제한하며, 내부 제어 요청은 별도 HMAC·시각·일회 nonce로 보호한다. SQLite와 PostgreSQL에서 동일 실행의 실행권은 한 경로만 취득한다. PostgreSQL에서는 별도 연결의 무료 예약과 동시 실행 제한도 직렬화한다.

Worker는 Provider Redirect를 따라가지 않고 요청/응답 헤더를 새로 만든다. 승인된 연결 URL은 프레임 단위로 플랫폼 URL로 투영하며 원천 에러는 공개하지 않는다. 별도의 인용 출처 링크는 유지한다. 임의 자연어의 주소·다른 표현·프레임을 가로지르는 문자열까지 완전 은닉하려면 Provider 출력 계약과 별도 프로필 검증이 필요하다. 서버의 DNS 안전성 확인과 운영자 승인을 적용하지만 실제 Worker의 DNS/egress 경계도 staging에서 확인한다.

같은 Origin의 내부 callback에는 Cloudflare가 부여한 `CF-Connecting-IP`를 `X-Real-IP`로 전달해 기존 Origin IP 보안 정책이 실제 요청 출처에 적용되도록 한다. 브라우저가 보낸 forwarding 헤더는 복사하지 않고, 다른 제어 Origin과 Provider에는 이 IP 헤더를 전달하지 않는다. HMAC 인증·nonce·기존 IP 차단은 유지한다. 관련 동작은 [Cloudflare의 Worker subrequest 설명](https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-connecting-ip-in-worker-subrequests)에 따른다.

Worker 경로에서는 결과 본문을 제어 서버에 복사하지 않아 해당 본문의 애플리케이션 서버 egress를 줄인다. 승인 요청·상태·완료 메타데이터, Provider 자체 사용료, 기존 서버 비용은 각각 존재한다. Origin 복귀 시에는 기존 본문 출력 비용이 돌아온다.

공식 정책: [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [Workers streaming](https://developers.cloudflare.com/workers/runtime-apis/streams/), [Workers Analytics GraphQL](https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/). 운영 배포 때 최신 계정 정책을 다시 확인한다.

## MCP Free CPU profile

등록 `usage_guide.protocol_version`이 확인된 handshake 버전이면 내부 HMAC binding에만 전달하여 `server/discover` 실패 왕복을 생략한다. 브라우저 입력을 이 값으로 사용하지 않는다. `initialize`·initialized·실시간 tools/list와 Schema/인자 검증은 유지한다. 알려진 handshake 버전은 Origin에서 이 제어 절차만 수행하고, Worker가 실제 tools/call 결과를 직접 받는다. 세션 정리 권한은 실행·attempt·대상·만료에 묶은 별도 HMAC capsule로 완료 callback에서 Origin에 반환한다. Origin은 검증된 capsule의 DELETE만 수행하며 Tool 결과 본문을 받지 않는다. 알려지지 않은 버전은 기존 자동 탐색을 유지한다. 단일 JSON chunk의 추가 복사와 출력 객체의 중간 배열 생성을 줄였으며 바이트 상한·fatal UTF-8·URL 투영·비밀 마스킹은 유지한다.

프로파일은 wall time과 CPU를 구분한다. Cloudflare Free는 요청당 CPU 10ms이며 소수 요청 성공이나 Error1102 부재만으로 한도 충족을 확정할 수 없다. 운영 CPU 검증 기록은 `reports/worker-streaming-gateway-design-2026-10-23/cpu-fix-checkpoint.md`를 참조한다.
# Native orchestration delivery

Workspace private and typed nodes, Workflow nodes and exported web-app server
runs can use the same ticketed Edge execution path. The owner-controlled
`native_node_delivery` setting defaults to false for a coordinated rollout.
Deploy the compatible Worker and all Native roles before enabling it.

The adapter requires the existing durable dispatch fence, pins the registered
version and input, and sends one short-lived ticket to the platform domain.
Credential-bearing inputs retain their existing authorized Native transport.
Quota/health preflight uses Native transport before dispatch; Cloudflare route
fail-open executes the same ticket once on Origin. Unknown deliveries never
trigger an automatic second execution. The Native runtime still receives node
results for DAG contracts and persistence, so final Origin-to-client egress
remains separate from Provider-to-Edge delivery.

