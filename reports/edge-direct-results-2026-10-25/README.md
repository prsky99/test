# Worker 직접 결과 전달 확장

이번 작업은 **개발과 배포 후보 준비**다. 운영 Worker 업로드, Route 변경, 설정 활성화, 서버 교체는 수행하지 않았다. 새 설정은 기본 비활성으로 두었다.

## 적용한 정책

지원 프로필의 실행 결과는 작은 응답도 큰 응답도 Edge를 먼저 사용한다. 결과 용량에 따라 Origin을 선호하는 분기를 만들지 않았다. Edge 가용성·무료 한도·승인 프로필·안전 제한을 충족하면 직접 전달하고, 전달이 불가능하면 같은 저장 결과를 복구한다. Provider가 실행됐을 가능성이 있는 요청은 자동 재실행을 막는다.

## 구현 내용

- **공개 MCP `/mcp`**: 기존 Handler의 방문자·계정·입력 검사를 사용하는 서명된 준비 단계를 추가했다. Worker가 Provider를 호출하고 결과를 전달한다. Origin의 기존 공개 데이터 필터·응답 형식·피드백·대체 Agent 안내는 저장된 결과로 마무리한다. 확정 실패와 실행 여부 불명확을 구분하고, 최종화는 한 번만 처리한다. 유료·인증 입력·자체 로컬 Agent 등 미지원 경로는 원래 계정 인증을 유지하며 기존 처리로 연결한다.
- **Native 실행**: Worker가 결과를 Origin으로 POST하고, 기존 계약 검증과 저장은 계속 수행한다. Native 호출의 응답은 작은 영수증으로 바꾸고 같은 저장소에서 결과를 읽는다. 성공 결과가 이미 저장된 경우 ACK가 유실돼도 저장 결과를 회수한다. Workflow·Workspace 일반 실행·Typed Flow의 부모 실행과 연결했다.
- **결과 응답**: 기존 Handler가 권한을 검사하고 공개 범위로 정리한 JSON을 작은 참조 명세로 변환한다. Worker는 이미 받은 결과 또는 암호화 캐시로 최종 JSON을 조립한다. 일반 Workflow, 두 Workflow App 버전, 두 Workspace 배포 앱, Customer Workspace 일반 실행·Typed Flow·템플릿 실행 이력, 동기 POST 결과를 포함한다.
- **템플릿 이력**: 외부 응답에 숨기는 내부 Workflow ID는 요청별 수집 컨텍스트로만 전달한다. 권한 검사가 끝난 원래 응답을 그대로 구성하며, 내부 ID를 공개 응답에 추가하지 않는다. 요청 사이의 컨텍스트 분리와 threadpool 전달을 검사했다.
- **확장 Route의 주변 기능**: 취소·동의·준비·SDK·다운로드·CORS 등 직접 결과 처리 대상 외 요청은 기존 Handler로 연결한다. Admin 경로를 새 공개 Worker Route에 포함하지 않는다.

## 장애와 보안 경계

기존 실행권·Registry 버전·입력 pin·부모 fence·일일 무료 한도·health 검사를 유지한다. 원천 Provider에는 Cookie·Visitor Token·플랫폼 Secret을 전달하지 않는다.

결과 수신은 기존 HMAC·nonce 검증과 실행/시도 ID를 사용한다. 결과 hash와 변경 불가능한 서명 영수증을 확인한다. 이미 claim한 결과는 신규 직접 전달을 비활성화하는 전환 중에도 저장할 수 있다. 기존 `workflow_checkpoints`를 사용하며 신규 테이블이나 DB migration은 없다. 기존 7일 Edge 보존 기간의 정리 배치와 함께 영수증을 정리한다.

캐시는 기존 키에서 분리한 키로 AES-GCM 암호화하며 TTL은 10분이다. 조회 주소도 HMAC으로 만든다. 캐시의 정확한 주소를 알아도 공개 HTTP로 데이터를 읽는 경로는 제공하지 않는다. 매번 원래 Handler의 현재 권한을 확인한 뒤 캐시를 사용한다. 참조 명세는 제한된 연산만 지원하고 깊이·개수·결과 크기를 제한한다.

캐시 유실·변조·지원하지 않는 projection은 같은 저장 결과의 GET으로 복구한다. POST 처리 결과가 불명확하면 두 번째 POST를 보내지 않고 검토 대기 응답을 반환한다. 이미 실행된 Provider를 호출해 결과를 다시 만드는 경로는 추가하지 않았다.

## 적용 범위와 비용 해석

직접 전달용 조회·동기 실행 경로는 `planned-routes.json`에 정리했다. 기존 배포 자료의 fail-open Route 5개를 유지하고, 끝에 wildcard를 쓰는 추가 Route 7개를 검토하는 구성이다. 아직 Cloudflare에 적용하지 않았다. Cloudflare는 경로 중간 wildcard를 지원하지 않으므로, 포함 범위의 비실행 요청을 Origin으로 전달하는 회귀 검사를 추가했다. [Cloudflare Routes](https://developers.cloudflare.com/workers/configuration/routing/routes/)

무료 구성의 Cache API는 데이터센터별로 분리된다. Native의 Origin→Worker 호출과 사용자의 결과 조회가 서로 다른 데이터센터에 도착하면 캐시가 없을 수 있다. 이런 경우는 저장 결과를 Origin에서 복구한다. MCP의 현재 응답은 같은 Worker 호출 안의 결과도 활용한다. [Cloudflare Cache API](https://developers.cloudflare.com/workers/runtime-apis/cache/)

Origin 전송 비용 절감은 최종 사용자 결과의 실제 Edge 전달 비율과 제어 응답을 합쳐 측정해야 한다. 40KB 결과를 220 bytes 미만의 영수증으로 처리한 검사는 전송 계약 검증이다. 그 영수증은 Worker→Origin 방향이므로 해당 수치를 그대로 Origin 출력 비용 절감율로 사용하지 않는다. 제어 응답·기존 저장 결과 복구에는 Origin의 출력이 남는다.

기존 승인 프로필의 총 출력 48,000 bytes, 개별 프레임·문자열 제한 16,384 bytes 등 안전 제한을 유지했다. 최종 참조 조립도 제한된 크기와 개수 안에서 수행한다. 로컬 자체 Agent, 인증정보 바인딩, 유료 실행, 미지원 프로토콜/Schema와 비공개 Admin UI의 기존 전달 방식은 유지한다. 공개 Customer Workspace와 배포 앱의 실행 결과 전달을 확장한 것이다.

## 검증 자료

Worker **66개**, 최종 영향 범위 API **103개**, Customer 권한 **28개**, 격리 Chromium **19개**가 통과했다. 실제 후보 패키지 검사는 Frontend·Admin 각각 **67개**, Jobs·Execution 각각 **24개** 통과다.

최종 수치는 `validation-summary.json`과 다음 로그에서 확인한다. 중복 실행·권한·CSP/XSS·Cookie/CSRF 보존·캐시 변조·ACK 유실·확정 실패·아주 짧은 결과·40KB 결과를 검사했다.

- `final-affected-subset.log`: 최종 영향 범위 API·Native·MCP·결과 전달 검사.
- `customer-authority-tests.log`: 실제 Customer 일반·Typed·Runtime 권한 회귀.
- `worker-final-tests.log`: 실제 workerd/Miniflare의 Worker 모의 네트워크 검사.
- `browser-security-tests.log`: 격리 Chromium CSP/XSS·SDK·다운로드 앱 검사.
- `content-check.log`: 공개 문구 정책과 embedded HTML 동기화.
- `worker-dry-run.log`: Wrangler 배포용 bundle 생성. 실제 업로드는 수행하지 않았다.
- `staged-*-tests.log`: 실제 후보 패키지를 import한 검사.

개발 도중 넓은 회귀 276개도 통과했다. 이후 변경에는 최종 영향 범위와 Customer 권한 검사를 적용했다. 서로 겹치는 검사와 후보 패키지 검사를 합산해 전체 고유 검사 수로 표현하지 않는다.

Jobs의 이전 활성 패키지에는 로컬 자체 Agent의 Edge 진입 방지 코드가 빠져 있었다. 후보 검사에서 두 사례를 재현했고 해당 보호 코드만 보충해 재검증했다. 초기 실패는 `staged-jobs-tests-initial.log`에 보존했다. 나머지 역할과 Admin 리뉴얼 파일은 각 활성 패키지 기준으로 보존했다.

상위 보안 Middleware는 Cache-Control을 `no-store`로 통일한다. 테스트도 동일한 저장 금지 계약을 확인하도록 조정했다. 정확한 문자열 형식 차이로 발생한 초기 후보 검사 로그는 `staged-*-cache-header-initial.log`에 보존했다.

## 배포 후보와 활성화 순서

`staged-releases.json`은 역할별 기준 릴리스·후보 경로·변경 파일·보존 파일 수를 기록한다. Frontend의 현재 공개 HTML과 자산은 유지했다. 웹 역할에는 변경 제품 파일 11개, Queue 역할에는 필요한 파일 7개만 반영했다. 후보는 검증용 패키지이며 현재 운영 프로세스를 가리키도록 바꾸지 않았다.

1. 현재 활성 릴리스와 후보 기준이 같은지 다시 확인한다. 달라졌으면 기존 변경을 보존해 재구성한다.
2. Worker 새 코드를 `DIRECT_RESULTS_ENABLED=false`로 배포하고 기존 Secret·무료 플랜·5개 Route를 보존한다.
3. Origin/Queue 새 코드를 기존 운영 교체 절차로 반영한다. 신규 직접 전달 설정은 비활성으로 유지한다.
4. 추가 Route는 fail-open으로 구성하고 권한·주변 기능·서명된 제어 경로를 확인한다.
5. 실제 무료 CPU 한도와 데이터센터별 결과 회수율을 검증한 뒤 Worker와 Origin 설정을 순서대로 활성화한다. 진행 중인 실행의 수신을 먼저 준비하고 신규 실행을 연다.
6. 복구 시 신규 직접 전달부터 닫고 진행 중인 결과 수신을 마친 뒤 기존 릴리스로 복원한다. DB나 Secret을 되돌리는 migration은 필요하지 않다.

Cloudflare Free의 CPU 한도는 요청당 10ms다. 로컬 workerd 검사와 빌드 성공은 이 운영 한도의 증명이 아니므로 실제 프로파일링을 활성화 조건으로 남겼다. 이전 장기 검증의 heap 중단과 24시간 미완료 상태는 이번 작업에서 해결 완료로 변경하지 않았다. [Cloudflare 한도](https://developers.cloudflare.com/workers/platform/limits/)

새 Provider 실호출, 운영 DB 검증 데이터, 결제, 유료 저장소, 기존 부하 캠페인 변경은 모두 수행하지 않았다. 기존 hourly 읽기 전용 추적도 그대로 유지했다.
