# Agent Concierge — Cloudflare Worker streaming Gateway 설계

작성일: 2026년 10월 23일 · 구현을 위한 설계안 · 운영 환경 변경 없음

최신 운영 정책: **Workers Free 우선 → 무료 한도 접근·소진 시 기존 Origin Gateway 복귀 → 한도 초기화와 상태 확인 후 Worker 재개**. 상세 전환·중복 방지·호환 범위는 [무료 플랜 fallback 설계](free-plan-fallback.md)를 따른다. 이전 유료 우선·장애 시 무조건 차단 가정은 아래 최신 내용으로 대체했다.

## 1. 확정할 구조와 완료 기준

**기존 Gateway는 인증·실행 승인·사용량·정산을 관리하고, 무료 사용 가능 시 Cloudflare Worker가 원천 Provider를 직접 호출해 사용자에게 streaming한다.** 무료 한도 접근·소진 시 기존 Origin Gateway가 같은 승인 작업을 중계한다. 브라우저의 실행·상태·파일 host는 두 경로 모두 `agentconcierge.biz`다. 기존 서버는 Worker 모드에서는 본문을 중계하지 않고 Origin 복귀 중에는 현재 방식으로 본문을 처리한다.

- 결과 크기를 받은 뒤 전달 경로를 선택하지 않는다. 무료 가용량·CPU 적합성·두 backend의 사전 호환성을 기준으로 실행 전에 Worker 또는 Origin을 정한다.
- Worker에서 대용량 응답 전체를 모아 AI 분석·요약·품질평가하거나 임대 서버로 복사하지 않는다.
- 원천 Endpoint·API key·원천 파일 URL은 서버 측 연결 정보로 관리한다. Client에는 platform ID와 platform 경로만 발급한다.
- 비용 목표는 **Workers Free 0달러 + Worker 모드에서 기존 서버 본문 egress 제거**다. Origin 복귀 시에는 기존 서버 송신료가 다시 발생한다. 원천 실행·송신료와 관리 서버·DB는 별도 원가이며 유료 플랜 자동 전환은 두지 않는다.
- 주소 보호 목표는 **서비스가 전달하는 접속 주소·protocol 연결 정보·오류·파일 링크에서 원천 실행 주소를 노출하지 않는 것**이다. Provider의 공개 정체성이나 인터넷에 이미 공개된 주소까지 비밀로 만들겠다는 보장은 하지 않는다.

중요한 적용 조건: 임의의 Provider 본문을 무검사로 그대로 전달하면서 그 안의 모든 주소까지 숨기는 절대 보장은 성립하지 않는다. 빠른 전달과 주소 보호를 함께 제공하려면 사전 승인된 출력 계약을 적용한다. 해당 계약을 만족하는 Provider·결과 유형부터 활성화한다.

## 2. 구성 요소와 책임

### 사용자 Frontend·다운로드 Web App

사용자는 기존 서비스에서 실행을 준비하고, 앱은 승인받은 platform 경로로 요청한다. 원천 Provider URL·장기 key·원천 오류를 받지 않는다. SDK의 브라우저 `redirect: 'error'` 경계는 유지한다. SSE가 필요한 경우 Authorization header를 사용할 수 있는 `fetch()` stream reader를 사용한다. Token을 query string에 넣는 기본 EventSource 방식은 채택하지 않는다.

### 기존 Gateway의 제어 API

Agent 선택·등록 상태·검증 근거·tool/schema 버전·동의·구독 자격·한도를 확인한다. 실행별 예약을 원자적으로 만들고 두 backend가 검증할 짧은 실행 권한을 발급한다. 기존 DB를 실행 상태·중복 방지·정산·전달 모드의 기준으로 사용한다. 제어 API는 작은 정보만 처리하며 Origin fallback Adapter는 승인된 본문 중계만 별도 수행한다.

### Edge Gateway Worker

실행 권한을 로컬 검증한 후 관리 서버에 작은 원자적 실행 claim을 요청한다. 승인된 비공개 binding을 조회하고 원천 Provider를 직접 호출한다. 응답 header와 protocol 참조를 platform 계약으로 만들고 body를 streaming한다. 동기 경로에서는 LLM·전체 결과 평가를 수행하지 않는다.

### Provider와 Provider 소유 저장소

Provider가 실행 결과를 생성한다. 장기 작업·재다운로드가 필요하면 Provider의 작업 ID·저장소를 사용한다. 결과가 관리 서버로 되돌아오지 않도록 한다. Provider 응답에 연결 주소를 포함하지 않는 출력 계약을 요구한다. 인증·public internet 접근이 맞으면 Provider의 브라우저 CORS 지원은 필요하지 않다. Worker가 서버 측에서 호출하기 때문이다.

## 3. 도메인과 Route

공개 경로는 설계상 다음으로 제안한다. 현재 제공되는 API라는 뜻이 아니다.

- `POST /api/gateway-execution/v1/runs` — 기존 제어 API. 실행 승인·예약과 Edge 권한 발급.
- `GET /api/gateway-execution/v1/runs/{run_id}` — 작은 상태·정산 확인. 본문 없음.
- `POST /api/edge-gateway/v1/runs/{run_id}/stream` — Worker. 원천 실행 및 결과 streaming.
- `GET /api/edge-gateway/v1/runs/{run_id}/events` — Worker. 지원되는 원천 작업의 결과 재연결. 재실행과 구분.
- `GET|HEAD /api/edge-gateway/v1/artifacts/{artifact_id}` — Worker. 권한이 있는 파일 다운로드·Range.
- `POST /api/edge-gateway/v1/runs/{run_id}/cancel` — Worker. 지원되는 Provider의 취소 요청.
- `POST /api/origin-gateway/v1/runs/{run_id}/stream` — 기존 Origin의 호환 실행 Adapter.
- `GET /api/origin-gateway/v1/runs/{run_id}/events` — 지원되는 같은 작업의 Origin 재연결.
- `GET|HEAD /api/origin-gateway/v1/artifacts/{artifact_id}` — 양쪽 기능 검증 후 활성화할 Origin 파일 경로.
- `POST /api/origin-gateway/v1/runs/{run_id}/cancel` — Origin 취소 Adapter.

Worker Route는 `agentconcierge.biz/api/edge-gateway/v1/*`로 제한한다. 나머지 Home·탐색·Chat·Workspace·관리 API와 명시적 Origin 경로는 이 Route 밖에 둔다. Zone의 proxied DNS·Route 적용 상태는 배포 단계에서 확인한다. Worker 모드에서는 기본 Origin을 호출해 본문을 받지 않고 Provider를 직접 호출한다.

전용 Route는 Origin 독립 인증·공통 claim·호환 Adapter 시험 후 **fail open**으로 설정한다. 일일 한도 초과로 Worker가 생략되면 Origin이 같은 신규 prefix를 처리한다. 사전 전환된 새 실행에는 Worker를 거치지 않는 `/api/origin-gateway/v1/*`를 발급한다. Provider 실행이 이미 시작되었거나 불명확한 작업은 상태 조정 없이 재실행하지 않는다. 원천 주소 redirect는 두 경로 모두 사용하지 않는다.

[Cloudflare Routes](https://developers.cloudflare.com/workers/configuration/routing/routes/) · [fail mode와 런타임 한도](https://developers.cloudflare.com/workers/platform/limits/)

## 4. 실행 순서

1. **사전 준비:** Workspace·SDK가 실행할 Agent·tool·Workflow 버전과 필요한 사용자 동의를 제어 API에 보낸다. 대용량 입력은 보내지 않는다. 작은 입력의 현행 검증이 필요하면 제한된 입력 범위로 처리한다.
2. **승인·예약:** Gateway가 자격·보안 gate·활성 버전·사용량·무료 가용량을 확인해 실행 예약과 전달 모드를 정한다. SDK에는 `run_id`, 선택된 platform `stream_path`, 짧은 Access Token과 만료 시각만 반환한다.
3. **Worker 요청:** SDK가 같은 서비스 도메인의 stream 경로로 입력과 Access Token을 전송한다. 입력 파일은 Worker upload 경로나 승인된 platform artifact ID로 전달한다.
4. **권한 검증·원자적 claim:** Worker가 서명·audience·만료·배포·Origin·작업 범위를 검증한다. 관리 서버의 내부 API가 같은 실행을 두 번 시작하지 않도록 claim을 확정한다. 이 제어 왕복은 v1에 의도적으로 남긴다.
5. **원천 직접 호출:** Worker는 서버 측 binding에서 정확한 원천 URL·method·인증·schema·전달 profile을 읽어 호출한다. 원천 자격은 Worker가 넣는다.
6. **첫 결과 전달:** 승인된 header와 출력 계약을 확인하면 즉시 전달을 시작한다. 완성된 전체 결과를 기다리는 분석 단계는 두지 않는다. Provider 자체가 결과를 한 번에 반환하는 경우 생성 중 token 단위 출력은 해당 Provider의 지원 범위를 따른다.
7. **진행·완료:** protocol의 완료 신호와 전달 상태를 구분한다. 작은 이벤트·영수증을 관리 서버에 반영하고 최종 실행 상태와 예약을 확정한다.

지연 모델은 `Worker 권한 검증 + 작은 실행 claim 왕복 + Provider 통신·실행 + stream 전달`이다. 비용·중복 실행 통제를 유지하기 위해 제어 왕복을 남기며, 대용량 본문 처리를 제거하는 데 우선순위를 둔다. 개선 배수나 ms 수치는 실측 후 정한다.

이는 Worker 모드의 순서다. Origin fallback은 같은 Token·DB claim·정산 규칙을 사용하고 현재 Origin 처리 방식을 따른다. 기존 JSON 결과는 호환 Adapter가 완료 event로 감쌀 수 있으며 token 단위 출력까지 자동 지원하는 것으로 표시하지 않는다.

## 5. Client에 전달하는 정보와 비공개 정보

공개 실행 응답 예시:

```json
{
  "run_id": "platform-generated-opaque-id",
  "stream_path": "/api/edge-gateway/v1/runs/platform-generated-opaque-id/stream",
  "access_token": "short-lived-platform-access-token",
  "expires_in_seconds": 120
}
```

위 만료 시간은 초기 제안값이며 운영 설정으로 조정한다. Token은 SDK 메모리에서만 취급하고 화면·URL·로그에 출력하지 않는다.

서버 측 binding에는 Provider Endpoint, 자격 참조, 허용 method·tool, schema digest, route version, 출력 계약, 원천 artifact Origin, 최대 입력·출력·동시성, timeout, 취소·idempotency·재연결 지원 여부를 넣는다. Client가 원천 URL·임의 header·callback 주소를 지정할 수 없게 한다.

Client용 Token은 공용 platform 실행 Gateway audience, opaque 실행 ID, 작업 scope, 배포·정책 버전, 허용된 fallback 범위, 만료, 필요하면 입력 digest에 결속한다. Worker와 Origin 모두 검증하며 실제 dispatch 소유권은 DB claim으로 정한다. JWT payload는 Client가 읽을 수 있으므로 원천 URL·비밀키·개인정보를 넣지 않는다. 공개 metadata·source map·JS bundle·HTML data 속성·Worker 공개 설정에도 binding을 넣지 않는다.

Provider API key는 Workers Secrets 또는 적절한 secret binding으로 보관한다. 첫 적용은 Provider 1곳과 제한된 secret 수로 시작하고, 대규모 다중 tenant 자격 관리는 별도 vault 설계를 한다. 사용자가 허용한 자격만 해당 tenant·Provider 조합에 사용한다.

[Cloudflare Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)

## 6. 주소 노출 방지 규칙

### 요청·응답 header

원천 요청은 필요한 header만 새로 구성한다. 브라우저 Cookie·platform Authorization·Forwarded·Referer 등을 통째로 Provider에 복사하지 않는다. Provider 전용 자격은 해당 승인 Origin에만 사용한다.

원천 응답도 allowlist로 새로 구성한다. Content-Type은 profile에 맞춰 검증하고, 필요한 경우 안전한 Content-Disposition·Content-Range·숫자형 길이만 허용한다. CORS는 platform이 승인한 Web App Origin으로 생성한다. 기본 응답은 `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`를 사용한다.

Location·Content-Location·Link·Refresh·Set-Cookie·Server·Via·원천 trace/debug header·원천 인증 안내는 그대로 전달하지 않는다. 오류·HTTP reason phrase는 platform이 생성한다. Worker에서 header를 다시 만드는 것으로 본문의 내용까지 검증된 것으로 취급하지 않는다.

### Redirect

원천 `fetch()`는 **`redirect: 'manual'`**을 명시한다. Cloudflare Worker는 브라우저와 달리 `redirect: 'error'`를 지원하지 않는다는 현재 공식 문서에 맞춘다. 기본 실행 경로에서는 원천 3xx를 Client에 넘기지 않고 작은 platform 오류로 바꾼다.

파일 저장소 등 승인된 추가 hop이 필요한 profile만 별도 허용한다. 매 hop에서 Origin·목적·경로·권한을 확인하고 이전 Origin의 자격을 새 Origin으로 복사하지 않는다. Client에는 hop 대상 URL을 전달하지 않는다.

[Worker Request의 redirect 동작](https://developers.cloudflare.com/workers/runtime-apis/request/)

### protocol·파일·상태 참조

Agent Card·MCP session·A2A task·SSE event·파일 metadata에 있는 연결 정보는 platform ID·경로로 투영한다. ID에서 원천 hostname을 복원할 수 없도록 임의 ID와 서버 측 mapping을 사용한다. MCP session 등 기존 protocol에 필요한 동작은 profile별 adapter로 보존하고 임의 문자열 치환으로 protocol을 훼손하지 않는다.

Provider의 서명 파일 URL을 브라우저에 반환하지 않는다. 서버 측 artifact mapping에는 tenant·run·권한·허용 저장소 Origin·만료·객체 참조를 저장하고, Worker가 그 URL을 호출해 전달한다. Provider가 반환한 임의 URL을 곧바로 fetch하는 기능은 두지 않는다. 등록된 저장소와 객체 범위를 검증한다.

연구·뉴스 답변의 독립된 출처·공식 문서 링크는 기존 `connections.py`의 목적별 투영 규칙을 보존한다. 원천 실행 Endpoint를 숨기는 것과 정상 출처를 제거하는 것은 구분한다. 제공자 자체의 공개 홈페이지·공개 정보로부터 연결 주소를 추정하는 행위까지 차단한다고 표현하지 않는다.

### 본문·다운로드의 중요한 경계

빠른 opaque byte 전달은 Provider가 Endpoint·자격·디버그 정보를 본문에 넣지 않는 승인된 profile에서 사용한다. 자유 생성 텍스트·PDF·ZIP·이미지 metadata에 임의 주소가 들어갈 수 있는 결과는 사전 출력 계약·Provider 측 처리 없이 ‘모든 내용의 주소 비노출’을 보장하지 않는다.

엄격한 내용 비노출이 필요한 결과에는 Provider 측 Adapter의 안전한 출력 생성·파일 metadata 처리 또는 Provider 저장소에서 완료된 파일의 사전 검증을 요구한다. 이 처리는 임대 서버의 전체 파일 수신으로 대체하지 않는다. Provider가 이 계약을 지원하지 않으면 엄격 profile에서 활성화하지 않는다.

작은 protocol event를 변환할 때에는 프레임 단위 parser와 제한된 필드 allowlist를 사용한다. UTF-8·JSON escape·URL encoding·chunk 경계를 처리하고 검증되지 않은 프레임은 전송 전에 차단한다. 단순히 네트워크 chunk마다 정규식 치환하는 방식은 사용하지 않는다. 이 검증은 전체 AI 내용 평가와 구분하되 실제 CPU 사용량에는 포함한다.

## 7. Streaming 구현 원칙

- 승인된 opaque body는 `ReadableStream`으로 전달한다. `.text()`, `.json()`, `.arrayBuffer()`로 대용량 전체를 먼저 읽지 않는다. `.clone()`·`tee()`로 본문을 복제해 로그·정산으로 보내지 않는다.
- Backpressure를 유지한다. byte 계측은 제한된 stream 처리로 하고 누적 buffer를 만들지 않는다. 결과 크기에 따른 route 선택이나 전체 결과 hash 계산은 기본 경로에 넣지 않는다.
- SSE·NDJSON은 완성된 작은 event까지만 보관한다. 새 profile의 event 크기·입력 크기 제한은 Provider 계약으로 설정하며 기존 API의 제한을 임의로 해제하지 않는다.
- Provider가 압축한 body를 변경하면 Content-Encoding·Content-Length·ETag·Digest 등 관련 header도 처리 결과에 맞춰 제거·재생성한다. 변환되지 않은 bytes를 다른 형식이라고 표시하지 않는다.
- 연결·첫 원천 header·stream idle·전체 실행에 각각 timeout을 둔다. 원천 생성 특성에 맞춰 profile별로 검증한다. HTTP 활성 연결의 wall time과 CPU time을 구분한다.
- Client 취소 signal과 stream reader 취소를 원천 AbortController에 연결한다. 연결 종료는 Provider 실행·과금 종료와 별개이므로 취소 성공은 Provider 확인 후 표시한다. `enable_request_signal` 호환성 flag와 실제 runtime 동작을 확인한다.
- Header 전송 후 오류가 나면 HTTP status를 바꿀 수 없다. SSE는 platform terminal 오류 event 후 종료하고, binary는 stream을 중단한다. SDK는 완료 신호·크기 등 계약에 따라 부분 결과를 구분한다. 중간에 오류 JSON을 파일 bytes에 덧붙이지 않는다.

[Cloudflare Streams](https://developers.cloudflare.com/workers/runtime-apis/streams/) · [CPU·memory·연결 한도](https://developers.cloudflare.com/workers/platform/limits/) · [Request.signal flag](https://developers.cloudflare.com/workers/configuration/compatibility-flags/#enable-requestsignal)

## 8. 인증·권한·사용량과 중복 실행

v1은 기존 DB의 원자적 예약·claim을 사용한다. 일반 Worker 메모리나 Workers KV만으로 전역 일회성 실행·잔액·분산 lock을 집행하지 않는다. KV의 eventual consistency는 등록 metadata 배포·읽기 cache에만 사용한다. Worker는 claim의 응답에서 최신 허용 버전과 중단 상태를 확인한다.

- 실행 준비: 현재 사용자 자격·동의·배포 버전·Provider 상태를 확인하고 예약한다.
- 실행 claim: `run_id + attempt_id + idempotency_key`를 원자적으로 전이한다. DB commit을 확인한 Worker만 원천 호출을 시작한다.
- 중복 요청: 기존 실행의 상태·재연결 경로를 반환한다. 일회성 권한 재사용이나 Client 재접속을 새로운 실행으로 해석하지 않는다.
- 불명확한 원천 실행: 원천 dispatch 전후에 crash가 나면 exactly-once 실행을 보장할 수 없다. Provider가 idempotency를 지원하면 같은 key로 확인하고, 미지원이면 `outcome_unknown`으로 두어 자동 재실행을 막는다.
- 현재 보안 gate: 등록된 Agent·schema·informational 요청·PII·유료 원천 승인 등 기존 admission 정책을 제어 API와 Worker의 입력 검증에 보존한다. 파일·새 tool을 지원하려고 현행 gate를 우회하지 않는다.
- 구독: AI 자동 생성·다른 Provider로 전환하는 상품 fallback의 유료 자격을 서버에서 확인한다. 같은 Provider의 Worker→Origin 인프라 복귀는 별도 구독을 요구하지 않는다. 1개 Workflow 완성에 대한 Credit과 Provider 호출 횟수를 분리하고 수정·재시험·인프라 전환을 중복 결제로 바꾸지 않는다.

[Workers KV의 일관성](https://developers.cloudflare.com/kv/concepts/how-kv-works/)

서명 검증키는 사전 배포·cache하고 key ID·만료·회전을 확인한다. Origin 검사는 SDK 호출 범위를 보조하며 인증을 대신하지 않는다. 다운로드 Web App은 등록된 Origin만 CORS 허용하고 임의 Origin reflection이나 wildcard credential 접근을 허용하지 않는다. Token은 header로 운반한다.

## 9. 상태·정산·신뢰할 수 있는 완료 처리

기본 상태는 `prepared → dispatch_reserved → running → succeeded / failed / outcome_unknown`이다. `client_disconnected`는 별도 관측값이며 Provider 취소·실패와 동일시하지 않는다. lease 만료만으로 새 Provider 실행을 허용하지 않는다. 실제 실행 여부를 조정한 뒤 재시도를 결정한다.

기존 DB에 시작 claim을 먼저 저장해 crash 후 미완료 예약을 찾을 수 있게 한다. Provider의 작업 ID·idempotency 조회·서명 receipt·작은 상태 조회 중 지원되는 수단으로 사후 조정한다. 관리 서버에서 조회할 상태 API가 큰 본문을 포함하면 해당 profile은 적합하지 않다. Worker가 metadata만 투영해 반환하는 상태 경로를 사용한다.

Worker 관측 이벤트는 run·attempt·중복 방지 event ID, 상태, CPU·시간·byte 수 등 최소 정보만 포함한다. 원문·파일·credential·원천 URL은 분석 로그와 결제 영수증에 넣지 않는다. Origin 복귀 시에도 같은 정산 규칙을 적용한다.

무료 v1은 기존 DB의 시작 claim·outbox와 작은 callback·Provider 상태 조정을 사용한다. `ctx.waitUntil()` 전송은 보조 수단이며 영구 보관·정확한 정산의 유일한 근거로 사용하지 않는다. Worker가 callback 전에 중단되면 시작 기록과 Provider 상태로 조정한다. Provider가 상태 조회도 idempotency도 지원하지 않으면 자동 확정 대신 unknown으로 남긴다.

Cloudflare Queues는 무료 v1의 필수 의존성에서 제외한다. 향후 사용할 경우 at-least-once 전달을 고려해 `event_id`로 중복 제거하고 재전달을 Provider 재실행으로 연결하지 않는다. Worker·기존 제어 API 간 서명·짧은 유효기간·replay 방지는 유지한다.

`succeeded`는 단순 HTTP 200이나 stream 종료만으로 판정하지 않는다. 해당 protocol의 최종 완료 신호·오류 여부와 수금 정책을 반영한다. 전달 완료와 사용자의 실제 확인은 서로 다른 상태다.

[waitUntil 제한](https://developers.cloudflare.com/workers/runtime-apis/context/#waituntil) · [Queues 전달 보장](https://developers.cloudflare.com/queues/reference/delivery-guarantees/)

## 10. 파일·다단계 Workflow·장기 실행

파일은 Client가 platform artifact ID로 Worker에 요청하고 Worker가 원천 저장소를 직접 읽는다. Range·HEAD는 등록된 객체·사용자 권한·허용 범위 안에서만 지원한다. Range 재요청은 파일 읽기이며 Agent를 다시 실행하지 않는다. 안전한 attachment filename을 생성하고 실행 가능한 HTML을 서비스 Origin의 활성 페이지로 전달하지 않는다.

대용량 입력도 Worker를 거쳐 Provider로 streaming하거나 검증된 artifact ID로 Provider가 직접 읽게 한다. 브라우저에 원천 주소를 숨겨야 하는 모드에서는 원천 업로드 URL을 발급하지 않는다. 업로드 크기는 Workers 구독이 아니라 별도 Cloudflare Zone 플랜의 한도도 적용받는다. 그 한도를 넘는 파일은 승인된 multipart 경로나 별도 저장 계약으로 확장한다.

Workflow의 `Provider A → 관리 서버 → Provider B` 본문 경로를 제거한다. 새 실행 profile은 Client orchestration 또는 Provider 간 승인된 artifact 전달을 사용한다. 기존 서버 Workflow 엔진이 node output 전체를 읽는 현재 profile은 이 목표를 충족한 것으로 표시하지 않는다. 중앙 orchestration이 필요하면 opaque 참조·작은 상태만 처리하도록 별도 변경한다.

브라우저가 닫힌 뒤에도 계속 수행해야 하는 작업은 Provider의 비동기 job을 사용하고 Edge는 상태·결과를 재연결한다. 단일 HTTP 연결·`waitUntil()`로 무기한 durable 실행을 보장하지 않는다. Durable Objects·Cloudflare Workflows는 필요가 확인된 범위에서 별도 비용·수명 설계 후 추가한다.

## 11. 무료 우선 비용과 운영 계측

현재 선택은 Workers Free다. 계정 기준 일 10만 요청, 요청당 CPU 10ms를 적용하며 한국 시간 09:00에 일일 요청 window가 바뀐다. 90,000회 사전 전환은 우리 운영 제안값이다. 공유 계정·집계 지연을 고려해 보수적으로 운영하고 공식 한도 초과는 Route fail open으로 Origin이 받는다. 자세한 리셋·CPU 차단·복귀는 [무료 플랜 fallback 설계](free-plan-fallback.md)를 따른다.

Workers 구독료는 무료 범위 0달러이며 Origin 복귀 중 기존 송신·CPU 비용은 발생한다. 실제 원가는 `기존 서버·DB + Origin fallback 송신료 + Provider 실행·송신료 + 선택한 기타 서비스`로 관리한다. 아래 Standard 금액은 향후 비교용이며 자동 유료 전환 계획이 아니다.

기본 Workers Standard는 계정당 월 최소 5달러, 월 1,000만 요청·3,000만 CPU ms를 포함한다. 초과 요청은 100만 회당 0.3달러, 초과 CPU는 100만 ms당 2센트다. 기본 Workers에는 별도 GB egress 항목이 없다. Containers·저장·Queue·로그·DB·Provider 비용은 구분한다.

가정 계산: 모든 유입 요청의 평균 CPU 5ms, 계정의 다른 사용 없음, 부가 서비스·세금 제외.

- 월 100만 Worker 요청: 5달러.
- 월 1,000만 Worker 요청: 5.4달러.
- 월 1억 Worker 요청: 41.4달러.

실제 업무 1회에 인증·stream·재접속·상태·OPTIONS가 여러 번 발생할 수 있으므로 업무 수를 요청 수와 같게 두지 않는다. 원천 응답 대기는 CPU 시간과 구분하지만 event 변환·암호 연산·byte 계측은 CPU에 포함된다. CPU 평균은 실측으로 대체한다.

Provider 자체의 송신·API 요금은 남는다. 자체 Agent가 플랫폼 소유 Infra에서 실행되면 그 송신 비용도 플랫폼 원가다. Cloudflare Worker가 그 비용까지 면제하는 것으로 예산을 작성하지 않는다.

필수 계측: 계정 일일 window·잔여 요청 추정·전환 사유·실행당 요청·Worker CPU·첫 결과 시간·완료 시간·동시 stream·부분 종료·정산 지연·Origin 용량·송신량. 원문 전체나 Token은 계측하지 않는다. Worker 모드의 관리 서버 본문 송수신 0과 Origin 복귀 중 본문 송신을 구분해 확인한다.

[공식 Workers 요금](https://developers.cloudflare.com/workers/platform/pricing/)

## 12. 현재 코드에 연결할 변경 지점

- `agent_market/concierge/managed_gateway.py`: 현재 `_execute_bounded`·`_execute`가 원천을 호출한다. 신규 profile에서는 준비·claim·권한 관리와 Edge 실행 경로를 분리한다. 현재 `result()`의 `public_metadata`·`project` 동작을 버리지 않고 Edge/Provider 출력 계약에 대응시킨다.
- `agent_market/concierge/connections.py`: 원천 binding과 독립 citation을 구분하는 투영 의미를 재사용한다. 신규 공개 metadata에서도 Endpoint를 platform 경로로 투영한다.
- `agent_market/concierge/execution_policy.py`: admission·tool·schema·인증·현재 공용 informational 범위를 보존하고 Edge policy와 버전을 일치시킨다.
- `agent_market/concierge/workflow_app.js`, `agent_market/gateway/webapp/sdk-v13.js`: 신규 버전 SDK에 stream reader·terminal event·취소·동일 실행 재연결을 추가한다. 구버전 JSON polling 계약을 조용히 SSE로 바꾸지 않는다.
- `agent_market/workflows.py`, `agent_market/workspace_sdk_bff.py`: 본문을 기존 서버가 재조회·보관·재전송하는 경로를 새 opaque-reference profile에서 제거한다.
- `agent_market/concierge/front.py`·동기화된 `extracted_html.txt`: 실제 UI 연결 단계에서 영어 copy·CSP·안전 렌더링·접근성·metadata 규칙을 함께 검증한다. 내부 설계 문서의 한글을 공개 source에 붙여넣지 않는다.
- 신규 Worker·배포 설정: 별도 모듈·staging 배포로 구성한다. 실제 Provider URL·secret·내부 관리 Origin을 Git이나 Client bundle에 넣지 않는다. 이 설계에는 실제 비밀값을 수집하지 않았다.

## 13. 단계별 적용과 복구

**첫 단계:** 원천 1곳의 작은 응답·주소 비노출 계약과 현재 Origin의 동일 업무 지원을 확인한다. 무료 한도·새 API·Origin 호환 Adapter·공통 claim을 구현한다. 두 backend의 계약을 충족하지 못하면 무료 fallback 대상에서 제외한다.

**두 번째:** 격리된 fake Provider·테스트 DB·staging Worker로 권한·중복 실행·주소 투영·한도 fallback·CPU 오류·한국 시간 09:00 복귀를 검증한다. Origin 단독 검증이 통과한 후 전용 Route fail open을 활성화한다.

**세 번째:** 승인된 Workflow·SDK 신규 버전에 한해 실행 profile을 opt-in한다. 운영 트래픽 비중과 비용·실패·정산 지표를 관찰한다. 실측 기준은 rollout 전 확정한다.

**네 번째:** 파일·재연결·다단계 opaque 참조를 확장한다. 프로토콜별 독립 검증을 통과한 연결만 활성화한다. x402의 자동 지불은 v1 범위에서 제외하고 별도 승인·결제 설계로 진행한다.

Rollback은 신규 실행의 Origin 우선 모드로 처리한다. 호환·용량·보안 조건이 충족되지 않은 요청은 작은 오류로 제한한다. 원천 URL로 redirect하지 않으며 기존 실행은 Provider 상태를 확인해 조정하고 임의 재실행하지 않는다. Origin 복귀 중 송신 비용은 별도 계측한다.

## 14. 출시 전 수용 시험

- **주소 보호:** DevTools·HAR·JS·HTML·Agent Card·schema·SSE·오류·header·artifact·재연결·캐시에서 가짜 원천 binding과 자격이 드러나지 않아야 한다. 독립 citation은 유지한다.
- **내용 계약:** URL의 event 경계·UTF-8 경계·JSON escape·URL encoding·파일 metadata·원천 오류 삽입 사례를 검증한다. opaque profile은 승인된 Provider 출력 계약의 범위를 별도로 기록한다.
- **본문 경로:** Worker 모드에서는 관리 서버 원문 송수신이 없어야 한다. Origin fallback은 현재 지원 범위에서만 처리하고 발생한 본문 송신을 별도 계측한다. 큰 파일·다단계·Range는 두 backend 지원을 확인한 후 활성화한다.
- **Streaming:** 전체 결과 완료 전 첫 승인 chunk가 전달되어야 한다. 느린 Client에서도 무제한 buffer·본문 복사·메모리 선형 증가가 없어야 한다.
- **보안:** 변조·만료·다른 tenant·다른 배포·다른 artifact·CORS·입력 policy·임의 URL·SSRF·DNS 변경·원천 redirect·credential 전달을 시험한다. 등록 도메인만 검사한 것을 DNS/egress 보안 완료로 취급하지 않는다.
- **정산·복구:** Worker와 Origin의 동일 claim·dispatch 전후 crash·callback 누락·Provider unknown·Client 종료·만료를 검증한다. 인프라 fallback은 같은 실행의 추가 Credit 차감으로 연결하지 않는다. Provider 지원 없는 exactly-once를 약속하지 않는다.
- **운영:** 일일 소진·사전 전환·Route 누락·직접 Origin 호출에서도 독립 인증·권한·공통 claim이 유지되어야 한다. CPU 오류와 일일 리셋은 별도 원인으로 처리하고 Origin 과부하를 bounded admission으로 제어한다.
- **회귀:** 실제 구현 후 공개 frontend content check, 영향을 받는 browser/API 보안 회귀와 Worker runtime 통합 시험을 수행한다. 현재 개발 서버는 사용자 운영 원칙에 따라 임의 재시작하지 않는다.

설계 문서와 Canvas의 문법·계산 검증은 구현 보안 시험을 대신하지 않는다. 이번 결과물은 검토 가능한 설계이며 실제 Worker 배포·서비스 변경은 수행하지 않았다.
