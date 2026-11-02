# Agent Concierge Gateway 네트워크 비용 검토

기준일: 2026년 10월 23일 · 소스 검토와 공식 요금 자료에 따른 설계 제안

후속 확정 방향은 [Worker streaming Gateway 설계](../worker-streaming-gateway-design-2026-10-23/architecture.md)다. 원천 주소를 Client에 전달하지 않고 Worker가 본문을 streaming하며 임대 서버는 제어 정보만 처리한다. 아래 내용과 [Provider 직접 응답 검토](direct-provider-delivery.md)는 앞선 대안 비교 기록이다.

## 판단

Gateway의 인증·권한·사용량·추천·실행 관리 기능을 유지하면서, 결과 본문은 원천 제공자나 별도의 전달 계층이 사용자에게 직접 보내도록 설계할 수 있다. 이때 Agent Concierge의 임대 서버를 통과하는 대용량 출력 트래픽을 제거할 수 있다. 인증·상태·정산 등의 작은 응답, 서버 임대, 원천 API 사용료와 저장·요청 비용은 별도로 남는다.

권고안은 **작은 JSON은 제한된 Gateway 중계, 큰 결과는 Provider 직접 전달 또는 R2 직접 전달**이다. 초기에는 트래픽 포함 VPS나 AWS CloudFront 정액제를 함께 비교하는 것이 개발과 운영의 총비용을 낮추기 쉽다. 브라우저 직접 호출은 협력 Provider부터 적용한다.

클라우드 업체·리전·임대 플랜·현재 청구서·실측 전송량은 이번 검토에 제공되지 않았다. 따라서 아래 금액은 명시한 가정의 비교 계산이며 실제 청구 예측과 구분한다. 서버·공개 Frontend·SDK·배포 설정은 변경하지 않았다.

## 현재 구현에서 확인한 비용 경로

1. `concierge/managed_gateway.py`는 등록된 Provider를 서버에서 호출하고 응답을 가공해 반환한다. 현재 흐름은 `사용자 → Gateway → Provider → Gateway → 사용자`다. 마지막 응답 본문은 Gateway의 외부 송신에 포함된다.
2. 공개 Workflow 다운로드 SDK `concierge/workflow_app.js:65`의 기본 상태 조회 간격은 700ms다. 연결형 SDK 1.3 `gateway/webapp/sdk-v13.js:106`은 750ms다. 각각의 현재 소스 범위에 대한 확인이다.
3. 공개 상태 API `concierge/front.py:2808`은 `public_outcome(front.workflows.get(...))`를 반환한다. 실행 중 저장된 노드 결과가 상태 응답에 포함될 수 있다. 완료 결과에는 `node_results`, `step_results`, `results`가 겹쳐 담긴다. `public_outcome`은 입력과 `final_deliverable` 등을 제거하지만 이 세 목록은 남긴다.
4. 동일 결과의 문자열·구조화 표현과 반복 조회는 전송량·직렬화·DB 조회를 늘릴 수 있다. 다만 `front.py:2119`에 GZip middleware가 이미 있다. JSON의 중복 배수와 과금되는 압축 전송량의 배수는 다르므로 wire byte를 측정해야 한다.
5. `workflows.py:25`의 노드 출력 제한은 48,000 byte이고 입력·출력 검사에도 사용한다. A2A 공개 경로에는 65,536 byte 응답 한도가 있다. 공통 bounded HTTP client 기본 한도는 1MiB이나 경로마다 다르다. 현재 제품의 제한된 텍스트 경로와 향후 대용량 파일·영상 서비스를 구분해야 한다.
6. 현재 다운로드 Web App은 실행을 플랫폼에 맡긴다. 앱을 사용자 서버에 배포해도 이 실행 경로의 응답 비용은 플랫폼에 남는다. 고객 설치형 BFF도 Gateway를 호출해 결과를 전달하므로 자체적으로 직접 실행 구조가 되는 것은 아니다.

## 비용이 생기는 지점

- 일반적인 외부 Provider → 우리 서버 수신은 인터넷 ingress이며 무료인 플랜이 많다. 우리 서버 → 사용자 본문은 internet egress다. 계약별 정책을 확인한다.
- 단계 A의 큰 결과를 단계 B로 우리 서버가 보내면 Provider 방향 송신도 과금 대상이 될 수 있다. 사용자에게 마지막 결과만 직접 보내는 설계는 중간 단계 비용을 남긴다.
- NAT Gateway의 byte 처리료, Load Balancer 처리료, 리전·가용영역 간 전송, 로그 수집·보관, 백업 복제는 internet egress와 다른 항목이다. AWS 공식 VPC 예시에는 NAT 처리료 GB당 4.5센트와 시간 요금이 있으며 internet egress가 별도로 붙는 경우를 설명한다. 금액은 해당 문서의 리전 예시다.
- Collector·Health Check·품질평가도 별도 작업량이다. 큰 본문을 수신할 때 internet ingress가 무료여도 NAT를 통과하면 처리료가 생길 수 있다.

## 선택 가능한 전달 구조

### 1. Provider 직접 전달 — 대용량 본문을 우리 서버에서 제거

흐름:

1. 사용자 또는 Web App이 Gateway에 사용 자격과 실행 범위를 요청한다.
2. Gateway가 해당 Provider·작업·입력·만료에 묶인 제한 Capability를 발급한다.
3. SDK가 승인된 Provider 공개 전달 Endpoint를 직접 호출한다.
4. Provider가 결과를 사용자에게 직접 보낸다.
5. Provider가 작은 서명 영수증과 상태를 Gateway에 알린다.

이 구조에서 대용량 본문은 `Provider → 사용자`로 흐른다. Provider가 작업을 먼저 받아 비동기로 수행하는 경우에도 Gateway는 작업 ID·상태·결과 위치만 관리할 수 있다.

필수 조건은 Provider의 협력이다. 기존 Provider가 우리의 Capability를 검증하지 않거나 CORS를 지원하지 않으면 임의로 적용할 수 없다. 원천 API의 장기 비밀키와 비공개 연결 주소를 브라우저에 노출하는 방식은 사용하지 않는다. 고객이 소유한 API의 OAuth·제한된 위임 자격을 사용하는 경우는 별도 지원 프로필로 설계한다.

현재 SDK는 `redirect: 'error'`이고 공개 연결은 검증·가공된 Gateway Endpoint를 사용한다. 단순 302/307 전환으로 변경할 수 있는 구조가 아니다. 명시적인 전달 계약과 SDK 호출 단계가 필요하다. 일반 HTTP 요청을 Gateway가 받은 뒤 다른 서버가 그 연결의 응답을 대신 보내게 하는 기능도 기존 HTTP 중계의 대체 수단이 아니다.

직접 전달에서는 중앙 서버가 전체 결과를 읽으며 수행하던 가공·민감정보 제거·내용 검토의 일부를 Provider, Edge 또는 사용자 실행 계층으로 옮겨야 한다. 검증 책임의 위치를 문서화하고 중앙 검토가 필수인 업무는 중계를 유지한다.

### 2. Provider → R2 → 사용자 — 파일·문서·이미지·영상 전달

Gateway는 결과별 업로드 권한과 결과 참조를 만든다. Provider가 결과를 R2에 직접 업로드하고 사용자는 짧은 수명의 다운로드 권한으로 R2에서 직접 받는다. 플랫폼 서버는 객체 키·크기·해시·상태를 보관한다.

R2는 인터넷 egress가 무료이고 저장·요청 횟수가 과금 기준이다. Standard 저장료는 GB-month당 1.5센트, 월 무료 제공량은 저장 10 GB-month·쓰기류 100만 회·읽기류 1,000만 회다. 만료 삭제와 재다운로드 정책으로 보관 비용을 통제한다. [공식 R2 요금](https://developers.cloudflare.com/r2/pricing/)

우리 AWS 서버가 전체 결과를 받아 R2로 재업로드하면 AWS에서 R2로 나가는 송신 비용은 발생한다. 처음부터 Provider가 R2로 보내거나, 해당 데이터 경로를 별도 저비용 계층에 배치해야 이 비용을 줄일 수 있다.

R2 presigned URL은 만료까지 재사용할 수 있는 bearer 권한이다. 1회용 다운로드와 즉시 철회가 필요하면 별도의 상태 관리·검증 계층이 필요하다. 브라우저 CORS를 구성해야 하며 R2 S3 API용 presigned URL을 custom domain URL로 그대로 바꿔 사용할 수 없다. 브랜드 도메인은 Worker의 R2 binding 등을 활용한 별도 인증 경로로 설계한다. [공식 권한 URL 문서](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)

### 3. Edge가 직접 Provider 중계 — 기존 Provider 호환성 유지

`사용자 → Cloudflare Worker → Provider → Worker → 사용자`로 데이터 경로를 옮긴다. Gateway의 Python 서비스는 권한·정책·실행 관리만 작은 메시지로 제공한다. 브라우저 CORS 문제와 장기 Provider 비밀키 보호를 Edge에서 다룰 수 있다.

Workers Standard는 egress·bandwidth 별도 요금이 없고, 유료 플랜 최소 월 5달러와 요청·CPU 사용량에 따라 계산한다. 월 요청 1,000만 회와 CPU 3,000만 ms가 포함되며 초과 요청은 100만 회당 0.3달러다. 이 수치는 Workers에 관한 것이며 Cloudflare Containers에는 별도 egress 요금이 있다. Python 앱을 Containers로 옮기는 것과 구분한다. [공식 Workers 요금](https://developers.cloudflare.com/workers/platform/pricing/)

Worker가 다시 우리 임대 서버에 전체 본문을 요청하면 임대 서버의 egress는 남는다. 데이터 본문이 임대 서버를 지나지 않도록 실제 호출 주체를 옮겨야 한다. Edge 이전에는 현재 등록 Endpoint·Schema pinning·SSRF 방지·권한 철회·명시적 실행 승인·비용 한도를 동등하게 검증해야 한다.

### 4. 트래픽 포함 VPS — 초기 변경량을 최소화

현재 Gateway와 Worker 구조를 유지하면서 월 포함 송신량이 큰 임대 플랜을 선택한다. 포함량 안에서는 추가 byte 요금을 피하고 임대료 중심으로 운영할 수 있다.

예를 들어 Hetzner 공식 Traffic 문서는 EU CX·CPX·CAX에 20TB, US·Singapore에 플랜별 다른 포함량을 안내한다. 지역별 지연·데이터 위치·지원과 함께 실제 주문 플랜을 비교해야 한다. Cloud 플랜 초과분은 청구되며 알림이 자동 차단을 의미하지 않는다. [공식 Traffic](https://docs.hetzner.com/robot/general/traffic/), [공식 과금 FAQ](https://docs.hetzner.com/cloud/billing/faq/)

현재처럼 작은 JSON을 제한해서 제공하는 단계에서는 Provider 위임 개발보다 이 방법의 총비용이 낮을 수 있다. 단일 서버 용량·가용성과 운영 인건비까지 비교한다.

### 5. AWS를 선택한다면 CloudFront 정액제도 비교

AWS 공식 페이지 기준 CloudFront Free는 월 0달러, Pro는 distribution당 월 15달러다. 공식 개발 문서상 Free는 월 요청 100만 회·100GB, Pro는 1,000만 회·50TB의 사용 허용량을 안내한다. AWS Origin에서 CloudFront로 가는 데이터 전송 면제와 정액제를 함께 검토할 수 있다. 지속적으로 허용량을 크게 넘으면 전달 성능 조정 또는 플랜 상향 검토가 필요하다.

이것은 Origin 서버·DB·NAT·Load Balancer·원천 API 전체가 무료라는 의미가 아니라 해당 전달 비용을 정액으로 관리하는 선택지다. 인증된 동적 API에는 캐시를 끄고 Cookie·Authorization·Capability header·CORS·POST 전달을 검증한다. 공개 사이트의 Cloudflare Tunnel/DNS 경로를 쓰고 있다면 직접 CloudFront 경로를 설계하고 우회 접근과 이중 중계를 점검한다.

[CloudFront 가격](https://aws.amazon.com/cloudfront/pricing/), [사용 허용량·제한](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html), [API 전달 설정](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesCacheBehavior.html)

## 적은 변경으로 먼저 줄일 전송량

1. **상태와 결과를 분리:** 상태 조회는 `run_id, state, revision, progress` 정도만 반환하고 결과 본문은 완료 후 별도 권한 요청으로 가져온다. 기존 API 소비자와 SDK를 위해 새 버전으로 추가한다.
2. **결과 중복 정리:** 새 응답 계약은 결과 목록을 한 곳에 두고 표시용 문자열과 구조화 데이터 중 필요한 표현만 선택한다. 기존 응답의 호환 필드를 바로 삭제하지 않는다.
3. **변화가 있을 때만 조회:** revision 기반 조건부 조회 또는 인증된 짧은 상태 이벤트를 검토한다. 간격을 작업 단계에 맞게 늘리고 이미 시작된 작업의 재실행은 방지한다. 장기 연결의 서버 자원·요청 요금도 비교한다.
4. **압축 유지·검증:** GZip은 이미 있으므로 압축 후 응답 byte와 실제 전송량을 확인한다. 원천 응답의 압축·해제 제한을 무작정 완화하지 않는다. SSE·WebSocket·streaming은 그 자체로 총 byte를 줄이지 않는다.
5. **Artifact 참조 우선:** base64 본문 대신 허용된 객체 참조·서명 다운로드를 사용한다. 다음 Agent도 참조를 받아 원천에서 직접 읽게 해야 중간 단계의 큰 송신을 줄일 수 있다.
6. **공개 정적 자산만 캐시:** 정적 JS·CSS·이미지·공개 카탈로그 요약과 사용자별 실행 결과를 분리한다. 인증된 결과와 Capability를 공용 캐시에 저장하지 않는다. 무료 CDN을 앞에 붙여도 cache miss의 Origin 송신량은 남는다. AWS→CloudFront 전송 면제는 해당 업체의 별도 정책이다.

## 비용 예시와 측정 공식

계산은 decimal KB·MB·GB와 **가정 단가 GB당 9센트**, 무료 제공량·할인·구간 할인·세금 제외 기준이다. 9센트는 AWS 공식 VPC 예시에도 사용된 단가이나 실제 선택 리전의 견적은 별도로 확인한다. MB 단위 결과는 현재 48KB 제한의 텍스트 Workflow 경로를 확장하는 미래 시나리오다.

- 월 100만 회 × 전송 결과 50KB × 본문 전달 1회 = 50GB → 약 4.5달러.
- 월 1,000만 회 × 50KB × 1회 = 500GB → 약 45달러.
- 월 100만 회 × 1MB × 1회 = 1,000GB → 약 90달러.
- 월 100만 회 × 10MB × 1회 = 10,000GB → 약 900달러.
- 10MB 결과를 모두 직접 전달하고 Gateway 응답이 4KB 메타데이터라면, 위 마지막 시나리오의 결과 관련 서버 송신은 약 4GB → 약 0.4달러로 줄어든다. 원천 요청·상태 조회·다단계 전송 등 다른 트래픽은 이 계산에서 제외했다.

실제 월 과금 대상 byte는 다음을 합산해야 한다.

`사용자에게 보낸 압축 응답 + 반복 상태 응답 + Provider에게 보낸 입력 + 재시도 + 객체 업로드·복제 + 정적 자산 + 수집·평가 등 서비스 작업`

여기에 각 네트워크 경로의 과금 정책과 무료 제공량을 적용한다. AWS의 일반 인터넷 egress 100GB 무료 제공은 계정 내 여러 서비스·리전 사용량을 합산하는 조건이 있으므로 제품별 독립 무료량으로 중복 계산하지 않는다. [EC2 공식 요금 조건](https://aws.amazon.com/ec2/pricing/on-demand/), [VPC 처리료 예시](https://aws.amazon.com/vpc/pricing/)

추천 계측 항목은 route·protocol·tenant별 송신 byte, 압축 전/후 크기, 실행당 조회 횟수, 전체 결과 조회 횟수, 원천 요청 크기, Artifact 크기·보관 기간, fallback·실패율이다. JSON 직렬화 길이와 실제 wire byte를 구분하며 프록시·클라우드 전송량과 대조한다. 토큰·원문 결과·사용자 정보는 비용 로그에서 제외한다.

## 위임 구조에서 유지할 제어

- 승인된 공개 Provider와 Delivery Endpoint만 허용한다. 임의 URL 입력으로 open proxy가 되지 않게 한다.
- Capability는 Provider audience·작업/배포 버전·입력 hash·허용 동작·만료·재사용 정책에 묶는다. 요청 Origin 검사는 브라우저 정책일 뿐 인증을 대체하지 않는다.
- 실행 승인은 검증 가능한 Provider 영수증·실행 ID와 대조한다. 브라우저의 성공 보고만으로 사용량 확정·정산·품질 인증을 처리하지 않는다.
- 토큰을 짧게 유지하고 중앙 사용량 예약·중복 방지·철회를 연결한다. 오프라인 토큰 검증만으로 즉시 철회까지 보장하려면 추가 상태 검증이 필요하다.
- 내용 검토·프라이버시·Schema 검증 책임을 전달 모드별로 정의한다. 결과 본문을 중앙에서 보지 않는 업무의 품질평가는 별도 승인·표본 방식으로 운영한다.
- Unknown·중간 실패·연결 끊김 시 동일 작업을 무조건 다시 실행하지 않는다. 읽기 작업에도 외부 과금 중복을 확인하고 Fallback을 적용한다.
- 대용량 결과를 다시 Gateway로 내려받아 검사·로그·다음 단계 입력으로 사용하면 절감 효과가 줄어든다. 검증 위치와 데이터 이동을 함께 설계한다.
- 공개 외부 Provider를 직접 소개하는 방식과 플랫폼의 검증·정산·지원 계약을 묶은 서비스를 구분한다. 사용·지급 조건은 Provider 협약으로 확보한다.

## 적용 순서

**우선:** 실제 전송량을 7일 정도 관측하고 공개 SDK·상태 API·압축·중복 표현을 확인한다. 트래픽 포함 VPS와 AWS CloudFront 정액제의 총비용을 비교한다. 현재 작은 텍스트 경로는 유지한다.

**다음:** 결과 참조와 전달 모드를 새 API·SDK 계약으로 정의한다. 큰 파일은 원천 직접 전달을 우선하고 저장·재다운로드가 필요하면 R2를 사용한다. 가격·플랜별 저장 기간·전달 한도·외부 실행 예산을 함께 정한다.

**확장:** 협력 Provider 한 곳에 Capability·서명 영수증·철회·CORS·정산을 적용해 시험한다. 협력이 어려운 Provider는 제한 중계로 유지하거나 Edge 직접 호출을 검증한다. 팀·기업은 고객 환경 Runner도 선택지로 제공하되 자격 증명과 실행 결과 검증을 유지한다.

검증 완료 기준: 기존 제한과 승인 유지, SDK 호환·CORS·CSP 확인, 결과·상태·정산 일치, 재시도/재다운로드/Unknown 측정, 실제 과금 경로별 byte 대조, tenant별 일·월 예산 한도와 제한 동작 확인.

**Agent Concierge의 유료 가치는 탐색·검증·실행 관리·Workflow·Workspace·정산·지원에 둘 수 있다. 대용량 본문 전달을 분리하면서도 이 기능들은 Gateway에서 관리할 수 있다.**
