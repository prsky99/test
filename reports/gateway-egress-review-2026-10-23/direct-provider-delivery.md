# Agent Concierge: 원천 Provider 직접 응답 설계 검토

기준일: 2026년 10월 23일 · 설계 및 문헌 검토 · 서비스 변경 없음

후속 확정 방향: 원천 실행 주소를 Client에 전달하지 않기 위해 [Worker streaming Gateway 설계](../worker-streaming-gateway-design-2026-10-23/architecture.md)를 새로 작성했다. 아래 문서는 원천 직접 호출 대안의 검토 기록이다.

## 결론

**Gateway가 연결과 실행 권한을 미리 위임하고, SDK가 원천 Provider를 직접 호출하는 구조를 권고한다.** 작은 텍스트부터 큰 파일까지 같은 직접 전달 원칙을 적용한다. Gateway가 결과를 받은 다음 크기나 내용을 분석해 경로를 고르는 단계를 제거한다.

전체 운영비는 인증·서버·정산·원천 실행 비용에 따라 남는다. 달성할 수 있는 정확한 목표는 **Agent Concierge 클라우드의 결과 본문 중계 송신량 0 byte, 그 본문에 대한 중계 egress 비용 0원**이다. 원천 Provider의 전송·실행 비용과 부담 주체는 별도 계약으로 정한다. Provider가 Agent Concierge 소유 클라우드에서 실행되거나 전송료를 플랫폼에 청구하면 플랫폼 전체 비용에 다시 포함된다.

이 문서는 앞선 일반 검토의 ‘작은 JSON 중계·큰 결과 분리’보다 직접 전달에 집중한 후속 권고다. 현재 코드에서 가능한 범위와 신규 설계가 필요한 범위를 구분했다. 지연 시간 개선율·Provider 지원 비율·실제 청구액은 측정 전이다.

## 실행 전 준비하고, 요청 즉시 Provider로 전달

### 로그인·Workspace 진입·Workflow 준비 시점

1. Gateway가 등록된 Provider의 공식 공개 Endpoint, protocol, 배포 버전, 직접 응답 지원, 인증 방식, 허용 Origin을 확인한다. 이 호환성 판단은 사전 등록·검증 시 수행한다.
2. 사용자가 허용한 작업 범위와 구독 자격을 확인하고 제한된 사용량을 예약한다. SDK에 짧은 유효기간의 Provider별 실행 권한과 승인된 연결 정보를 발급한다.
3. SDK는 유효한 연결 정보를 세션에 보관한다. Provider는 Gateway 공개 검증키를 미리 보관한다. 브라우저의 CSP connect-src와 Provider CORS를 승인된 Endpoint에 맞춰 배포한다. 다운로드 Web App의 배포 Origin도 등록한다.
4. 알려진 Endpoint의 DNS·연결 준비는 개인정보·사용자 동의를 고려해 선택적으로 수행한다. 사전 준비만으로 모든 브라우저의 TLS·CORS 왕복이 없어지는 것은 아니므로 첫 요청과 재사용 연결을 각각 측정한다.

### 준비가 끝난 뒤 실제 요청

`사용자 SDK → 원천 Provider: 입력 + 제한된 실행 권한`

`원천 Provider → 사용자 SDK: 결과 또는 지원되는 streaming 응답`

Provider가 권한을 로컬에서 검증하고 실행한다. Gateway에 매번 권한 조회를 보내지 않도록 설계한다. 결과의 수신·크기 판별·본문 분석·JSON 재구성·재전송을 Gateway의 동기 실행 경로에서 제외한다. SDK는 검증된 전송 형식과 안전한 화면 렌더링을 담당한다.

`원천 Provider → Gateway: 서명된 작은 실행 영수증, 비동기 전송`

영수증에는 실행 식별자·완료 상태·사용량·중복 방지 식별자 등 필요한 최소 정보만 넣는다. 파일·원문·응답 복사본을 포함하지 않는다. 영수증 수신을 사용자 결과 출력의 선행 조건으로 두지 않는다.

### 처음 방문했거나 권한이 만료된 요청

SDK가 Gateway에서 작은 연결·권한 응답을 받은 뒤 Provider를 호출한다. 이 경우 제어 요청 1회가 추가된다. 무기한 실행 권한을 배포하는 대신, 유효기간 안에서 재사용 가능한 제한 권한을 준비해 반복 요청의 Gateway 왕복을 줄인다. 실시간으로 새 Agent를 추천받는 작업은 그 추천 요청 비용과 지연을 별도로 갖는다.

‘요청은 반드시 매번 Gateway에 먼저 도착해야 한다’는 요구를 유지하면 작은 제어 왕복은 남는다. 실행 시 Gateway 왕복까지 제거하려면 SDK가 사전에 위임받은 Gateway 정책을 적용해 Provider로 바로 요청하게 한다. 두 방식 모두 결과 본문 직접 응답이 가능하다.

### Gateway가 매번 실행 요청을 받아야 하는 경우

브라우저와 Provider 사이에 인증된 SSE·WebSocket 또는 결과 조회 채널을 먼저 만든다. 사용자가 Gateway에 작은 실행 지시를 보내면 Gateway는 Provider에 승인된 작업 ID와 입력 참조만 전달하고, 사용자에게 접수 상태를 반환한다. Provider는 준비된 직접 채널로 사용자에게 결과를 출력한다.

`실행 지시: Client → Gateway → Provider`

`결과: Provider → Client의 별도 직접 연결`

큰 입력은 미리 Provider에 직접 업로드하고 Gateway에는 한정된 참조만 보낸다. 결과 전송 채널의 작업 ID·사용자 권한 결속, 연결 복구·이벤트 순서·재수신 범위를 Provider가 처리해야 한다. Gateway가 받은 HTTPS 요청의 연결은 Gateway가 응답하고, 결과는 Provider와 Client의 별도 연결로 전달한다. Client가 지정한 임의 callback URL로 Provider가 접근하는 방식은 사용하지 않는다.

이 방식도 결과 본문 중계 비용을 제거하지만 Gateway의 지시 전달·제어 응답과 관련 지연은 남는다. **Gateway의 요청 접수 유지는 이 방식, 실행 지연 최소화는 사전 위임 SDK 직접 호출**로 요구를 구분해 선택한다.

## 논문에서 확인한 설계 원리

### Google File System — 데이터 전달과 중앙 제어의 분리

Ghemawat·Gobioff·Leung의 SOSP 2003 논문은 Client가 Master에서 위치 정보를 얻어 캐시하고 Chunkserver와 직접 데이터를 주고받는 구조를 설명한다. 특히 2.4절은 파일 데이터를 Master를 통해 읽고 쓰지 않는다고 명시한다. 중앙 제어가 전체 데이터 전송의 병목이 되는 것을 피하는 근거다.

**Agent Concierge에 대한 설계 추론:** Gateway는 Provider 연결·권한 정보를 제공하고 SDK와 Provider가 본문을 직접 교환한다. GFS의 파일 시스템 성능 수치를 AI 서비스의 지연 개선 수치로 전용하지 않는다.

[Google Research 논문 소개](https://research.google/pubs/the-google-file-system/) · [논문 원문, 2.4절](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)

### Macaroons — 제한된 권한의 분산 위임

NDSS 2014 논문은 사용 목적·상황·대상 등을 제한한 권한 위임을 다룬다. 매번 중앙 서버가 전체 작업을 수행해야만 권한을 통제할 수 있다는 전제를 벗어나는 연구 근거다. 추가 제3자 검증이 필요한 권한 조건은 해당 검증의 왕복을 별도로 고려해야 한다.

**Agent Concierge에 대한 설계 추론:** Provider가 검증할 수 있는 제한 권한을 사전에 발급한다. 첫 구현에는 Provider 간 서명 권한 분리를 위해 비대칭 서명의 JWT Access Token 프로필을 우선 검토한다. Macaroons를 구현 완료 기능으로 표현하지 않는다.

[NDSS 2014 발표 정보](https://www.ndss-symposium.org/ndss2014/ndss-2014-programme/macaroons-cookies-contextual-caveats-decentralized-authorization-cloud/) · [논문 원문](https://www.ndss-symposium.org/wp-content/uploads/2017/09/04_3_1.pdf)

## SNS·개발자 커뮤니티에서 확인한 사례

- **Reddit, 2024년 12월 3일:** PocketBase 플러그인 작성자는 서버에서 S3 파일을 받아 재전송하는 대신 접근 권한 확인 후 presigned URL로 302 redirect하는 구현을 소개했다. 게시물의 대역폭 절감 동기는 이 검토와 일치한다. 비용·속도 주장은 작성자 경험이며 독립 검증된 벤치마크와 구분한다. [원 게시물](https://www.reddit.com/r/pocketbase/comments/1h5k8v6)
- **GitHub Discussions, 2024년 5월 6일:** 개발자는 S3 → PocketBase → Client 경로의 지연·VPS 대역폭 문제를 설명하고 서명 URL로 redirect하는 코드를 공개했다. Redirect를 따르지 않는 Client의 호환성 문제도 직접 언급한다. [공개 구현 논의](https://github.com/pocketbase/pocketbase/discussions/4871)
- **Hacker News, 2024년 8월 15일:** Signed Asset URL 전환 운영 사례에 대한 토론은 서명 검증 위치, 앱 서버 부하, 호스팅·전송 비용의 절충을 다룬다. 게시물 제목의 처리량은 Agent Concierge의 성능 예상치로 사용하지 않는다. [운영 사례와 토론](https://news.ycombinator.com/item?id=41260098)

공통 시사점은 **접근 제어와 본문 전송을 분리하는 방식이 실제 구현에 사용된다**는 점이다. 파일 GET 사례를 임의의 AI API 실행에 바로 대입할 수는 없다. AI 실행에는 아래 Provider 인증·protocol 계약이 추가로 필요하다. Presigned URL의 제한된 객체 접근 권한은 [AWS 공식 문서](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html)로 교차 확인했다.

## Redirect와 DSR보다 명시적 SDK 직접 호출을 우선하는 이유

### HTTP Redirect

파일 다운로드는 Gateway가 작은 redirect 응답만 보내고 원천에서 본문을 받게 할 수 있다. 다만 302는 POST의 메서드 보존에 적합한 일괄 전환 수단이 아니다. 307은 메서드를 보존하지만 최초 Gateway 왕복과 원천 재요청이 필요하다. 다른 Origin으로 이동할 때 브라우저는 Authorization header를 제거하며, CORS와 원천용 인증을 별도로 해결해야 한다.

현재 두 Web App SDK는 `redirect: 'error'`를 사용한다. 이 설정만 풀면 실행 권한·Endpoint 검증 경계가 달라진다. 명시적 SDK 계약으로 승인된 Provider에 그 Provider 전용 권한을 보내는 방식이 적합하다. 큰 입력까지 처음부터 Gateway에 POST한 뒤 redirect하면 입력 전송·업로드 시간도 중복될 수 있다.

[RFC 9110, 307](https://www.rfc-editor.org/rfc/rfc9110.html#name-307-temporary-redirect) · [WHATWG Fetch, HTTP redirect fetch](https://fetch.spec.whatwg.org/#http-redirect-fetch)

### Direct Server Return

DSR은 요청을 전달하는 Load Balancer를 응답 경로에서 제외하는 실제 네트워크 기술이다. Cilium 문서는 Backend가 Service IP·port를 출발지로 사용해 직접 응답하는 조건과 cloud routing 제약을 설명한다.

공유 서비스 주소·패킷 경로·Backend 설정을 통제할 수 있는 환경에서 검토할 수 있다. 임의의 외부 HTTPS Provider에는 이 제어권이 없으므로, 현재 Gateway가 종료한 TLS 연결에 다른 업체가 임의로 응답하는 대체 기능으로 사용할 수 없다. 외부 Provider 연동에는 Application 계층의 직접 호출을 우선한다.

[Cilium 공식 DSR 문서](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/#direct-server-return-dsr)

## Provider 호환성 조건

- **협력 Provider:** 우리의 제한 권한을 로컬 검증하고, 공식 공개 Endpoint로 직접 결과를 전달한다. Provider 측 Adapter가 필요하면 Provider Infra에 배포하고 부담 주체를 계약한다. 플랫폼 서버에 Adapter를 두고 본문을 중계하면 목표 비용이 다시 생긴다.
- **사용자 OAuth·사용자 소유 자격으로 직접 호출 가능한 Provider:** 공식 인증·public client 지원·CORS·이용 조건이 맞을 때 적용한다. 플랫폼 장기 API key를 브라우저에 전달하지 않는다.
- **CORS가 없는 Provider:** 브라우저 JS에서 결과를 읽는 경로는 제한된다. 사용자가 운영하는 Runner에서 직접 호출하는 대안을 검토한다. 별도 Origin의 파일 다운로드가 가능해도 JS 결과 처리는 다른 조건이다. `no-cors`는 결과를 읽는 해법이 아니다.
- **Server-side secret만 허용하는 비협력 Provider:** 무중계 직접 호출 지원 대상으로 표시하지 않는다. 결과 본문 중계 0 모드에서는 해당 Provider를 사전에 제외하거나 직접 전달 지원을 요청한다.
- **MCP·A2A:** protocol 이름만으로 직접 실행 지원을 판단하지 않는다. Transport·인증·session·streaming·브라우저 지원을 Provider별로 검증한다. 로컬 stdio MCP는 사용자 Runner에서 실행한다.
- **x402:** 결제 승인·지출 한도·지갑 주체를 별도로 검증한다. 현재 공개 Gateway의 probe·challenge를 자동 유료 실행 지원으로 확대 해석하지 않는다.

Browser DevTools에는 실제 접속 Provider Endpoint가 보인다. 비공개 주소는 발급하지 않고 공식 공개 Delivery Endpoint를 등록한다. Provider 주소 비공개가 필수인 계약은 직접 호출 지원 여부를 별도로 판단한다.

## 속도와 비용을 유지하면서 필요한 제어

**로컬 권한 검증:** Provider는 issuer·audience·signature·expiry·허용 작업·배포 버전을 검증한다. 공개키를 캐시하고 키 변경을 배포·갱신 경로에서 처리한다. JWT 자체가 사용량 한도를 집행해 주지는 않으므로 Provider의 원자적 카운터와 중복 방지가 필요하다. [RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html)

**사전 승인과 동적 입력:** 실행 전에 입력이 확정되면 해당 작업의 입력 hash를 권한에 묶을 수 있다. 동적 입력은 허용 tool·schema·대상·사용량 범위로 사전 승인하고 Provider가 입력을 검증한다. 전체 파일을 Gateway로 보내 hash를 계산하거나 검토하면 사전 직접 호출의 이점이 줄어든다.

**토큰 탈취·재실행 방지:** 가능하면 Client key에 묶인 DPoP와 Provider 측 replay 검증을 적용한다. DPoP는 HTTP method·URI와 token 사용 주체를 묶으며 요청 본문의 무결성까지 보장하지 않는다. 본문 결속이 필요한 작업은 TLS와 별도 서명 envelope·입력 hash 계약을 검토한다. [RFC 9449, 11.7절](https://www.rfc-editor.org/rfc/rfc9449.html#section-11.7)

**사용량·Credit:** Gateway가 Provider별로 분할한 제한 사용량을 미리 예약하고 Provider가 로컬에서 한도를 집행한다. 같은 잔액을 여러 Provider에 중복 배분하지 않는다. Credit 예약·최종 확정은 기존 상품 정책에 맞춘다. 1개 Workflow 완성에 대한 Credit과 개별 node·수정 시도 횟수를 혼동하지 않도록 분리한다. 유료 AI 자동 생성·유료 fallback 자격도 위임 범위에 포함한다.

**정산·철회:** 서명 영수증을 중복 제거해 비동기로 반영한다. Provider 서명은 발행 주체를 증명하며 결과 품질·사용자 실제 수신까지 증명하지는 않는다. 정산 분쟁에는 최소 Client 수신 확인과 독립 표본 검증을 조합한다. 짧은 만료·Provider별 예약 한도·철회 목록 전파로 노출 범위를 줄인다. 실시간 중앙 잔액·즉시 철회가 매번 필요한 작업은 제어 왕복을 추가하는 별도 정책으로 제공한다.

**품질·보안:** 사전 Provider 검증과 주기적 품질평가를 사용자 결과 출력 경로와 분리한다. Gateway가 전체 본문을 읽지 않으면 중앙의 결과 가공·민감정보 제거·본문 검열을 같은 방식으로 보장할 수 없다. Provider 또는 고객 환경에서 필요한 처리를 수행하고 직접 전달 지원 프로필에 책임을 명시한다. 브라우저에서는 안전한 text rendering·파일 취급을 유지한다. 중앙 본문 검토가 필수인 업무는 직접 전달 전용 대상에서 제외한다.

**실패·fallback:** 결과가 불명확할 때 동일 작업을 자동 재실행하지 않는다. Provider 실행 ID와 idempotency key로 상태를 확인한다. 다른 Provider로 전환할 때에도 남은 권한·구독 자격·중복 실행 위험을 확인하고 본문은 직접 전달한다. 직접 전달이 실패했다고 플랫폼 중계로 몰래 전환하는 동작은 두지 않는다.

## Workflow 전체의 본문 경로도 분리

최종 다운로드만 직접 전달하면 중간 단계의 플랫폼 송신 비용이 남을 수 있다. 다음 두 실행 위치를 우선한다.

1. **브라우저·고객 Runner:** Workflow 실행 순서를 SDK 또는 고객 Runner가 관리하고 각 Provider와 직접 통신한다. 브라우저 종료 시 지속 실행이 필요한 작업은 고객 Runner 또는 Provider의 비동기 작업으로 넘긴다.
2. **Provider 간 전달:** Provider A가 결과를 원천 저장소에 저장하고 Provider B에 한정된 읽기 권한을 발급한다. B가 직접 읽는다. Gateway에는 승인된 참조·상태만 전달한다. 원문을 URL query에 넣거나 무제한 객체 주소를 공유하지 않는다.

Workspace는 Workflow 편집·실행 준비·권한 예약·배포·구독·사용량을 관리한다. 실행 결과의 대용량 저장·렌더링·재다운로드는 Provider 또는 고객 환경에서 담당한다. 플랫폼에 결과 요약·AI 분석을 추가 요청하는 기능은 사용자가 명시적으로 선택하는 별도 실행으로 분리한다.

## 비용과 지연을 어떻게 검증할 것인가

목표 비용 범위:

`플랫폼 결과 본문 중계 egress = 0 byte`

`플랫폼 전체 송신 = 연결·권한 응답 + 작은 영수증 응답 + 상태·관리·정적 자산 + 기타 서비스 작업`

큰 입력도 SDK → Provider로 직접 보내면 플랫폼의 입력 중계 송신을 함께 제거할 수 있다. 영수증·로그·재다운로드·중간 Workflow 결과가 본문을 복제하지 않는지 확인한다. Provider의 egress는 Provider 청구 항목이며 사전 합의한 요금 조건을 적용한다.

지연 시간의 구조:

- 준비 완료: `Client↔Provider 통신 + Provider 권한 검증·실행·전송 + Client 표시`
- 권한 준비 필요: `Gateway 연결·권한 왕복 + 위 직접 호출 시간`
- 현재 중계: `Client↔Gateway + Gateway↔Provider + Gateway 결과 처리·재전송 + Client 표시`

이는 경로 설명이며 밀리초 단위 벤치마크가 아니다. 네트워크 위치에 따라 직접 경로가 항상 빠른 것은 아니다. DNS·TLS·CORS preflight·연결 재사용·streaming 지원 여부를 같은 조건에서 측정한다. 제거 대상은 Gateway의 본문 처리와 본문 중계다.

실증 수용 기준:

1. 작은 텍스트·큰 텍스트·파일·streaming 각각에서 Client가 원천 Provider로부터 본문을 수신하는지 확인한다. 대용량 항목은 현 API 한도 확장이 필요한 시험 시나리오다.
2. 결과 크기를 늘려도 Gateway의 송수신량·메모리·JSON 파싱·본문 로그가 결과 크기에 비례해 증가하지 않아야 한다. 작은 고정 제어량은 별도로 측정한다.
3. SDK·Reverse Proxy·cloud flow/egress 계측을 대조해 Gateway에 결과 본문이 한 번도 들어오지 않는지 확인한다. Client 단위 HAR와 서버 로그에는 token·본문 등 민감정보를 제거한다.
4. 첫 요청·연결 재사용 요청의 첫 응답 시간·완료 시간 p50·p95, 실패율을 현재 중계와 비교한다. 결과가 나오기 전에 속도 개선 배수를 약속하지 않는다.
5. 만료·철회·중복 실행·다중 Provider quota 경쟁·영수증 누락·Client 종료·CORS 실패·유료 fallback 자격을 검증한다. 미지원 Provider에서는 원천 실행과 자동 중계가 시작되지 않아야 한다.

## 현재 소스와 적용 순서

현재 `agent_market/concierge/managed_gateway.py`의 `_execute_bounded`와 `_execute`는 서버에서 Provider를 호출하고 결과를 반환한다. `agent_market/concierge/workflow_app.js:17`과 `agent_market/gateway/webapp/sdk-v13.js:26`은 플랫폼 Origin을 호출하고 redirect를 거부한다. 따라서 현재 구조만으로 결과 본문 중계 0을 달성할 수 있는 상태는 아니다.

권고 개발 순서:

1. 공식 공개 Endpoint를 가진 협력 Provider 1곳에서 직접 전달·권한 검증 계약을 확정한다.
2. 버전이 있는 연결·권한 발급 API와 Provider 로컬 검증을 추가한다. 실행 입력·출력을 받는 기존 Gateway API와 구분한다.
3. SDK에 사전 준비·원천 직접 실행·원천 상태 조회를 추가한다. CSP·CORS·배포 Origin·안전한 렌더링을 함께 검증한다.
4. 작은 비동기 영수증·사용량 예약·정산·idempotency·철회를 연결한다. 모든 결과 크기에 같은 직접 경로를 적용한다.
5. Workflow 실행 위치를 Client·고객 Runner·Provider 간 전달로 확장하고 위 수용 기준을 통과한 Provider만 활성화한다.

서비스 코드·배포·서버는 이번 검토에서 변경하지 않았다. 문헌과 현재 코드가 뒷받침하는 설계이며 실제 비용·성능 확인은 해당 직접 전달 프로필의 통합 시험으로 완료한다.
