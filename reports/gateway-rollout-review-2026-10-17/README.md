# 전면 게이트웨이화 적용 결과 검토

2026-10-17 · 현재 작업 소스·격리 API/DB/Mock provider·선별 Chromium 회귀 기준

**개선이 필요하다. 실제 연결 준비, 공통 공개 응답, Testbench 실행 제한을 우선 보완해야 한다. 기존 회귀 통과만으로 G0 완료를 판단할 수 없다.**

사용자가 서버 재시작을 완료했다고 알려준 상태를 기준으로 검토했다. 운영 서버에 대한 공격·제공자 호출·쓰기 테스트는 수행하지 않았다. 아래 404·노출·정책 문제는 현재 소스로 만든 격리 앱에서 재현한 결과이며 운영 배포의 별도 프록시 설정·구동 버전을 직접 검증한 것은 아니다. 서버 재시작으로 누락된 handler나 검증 정책이 생기지는 않는다.

## 확인한 기존 동작

- 첨부의 기존 회귀 93개를 재실행하여 모두 통과했다.
- 공개 workflow 웹앱 다운로드·다른 호스팅 실행 등 추가 회귀 6개가 통과했다.
- 공개 콘텐츠 검사 48개 파일에서 위반 0건이며 front.py의 embedded HTML과 extracted_html.txt가 일치했다.
- 상세·Explore·일부 목록·Testbench 표시 주소의 치환은 적용되어 있다.
- 기존 /mcp에는 discovery 외에 tools/call의 `call` wrapper도 있다. 이 계약을 올바르게 안내하거나 공통 admission 아래 재사용할 수 있다. 새 /api/gateway/{proto}/{id}가 자동으로 구현되었다는 뜻은 아니다. A2A per-agent 지원과도 구분해야 한다.

## 우선순위별 개선사항

P1은 출시/기본 신뢰성 전에 우선 수정할 항목, P2는 이어지는 정합성·경계 보완이다. CVSS 점수나 외부 보안 인증 등급이 아니다. 기존부터 있던 Testbench 문제와 이번 주소 치환의 직접 영향을 구분했다.

### F01 · P1 · 표시·복사되는 새 게이트웨이 주소가 호출되지 않음

**확인:** 현재 소스로 만든 격리 앱에서 각 종류의 유효한 resource ID를 등록한 뒤 표시 URL에 GET과 POST를 보냈다. 세 종류 모두 404였다. 첨부의 주소 치환 검사에는 이 경로의 실제 호출 검증이 없다.

**영향:** Copy URL·Calling details를 이용해 연결하려는 고객/에이전트가 사용할 수 없는 주소를 받는다. Testbench 자체 /api/test/execute가 동작하는 것과 별개다.

**권장 변경:** 실제 per-agent handler와 명확한 MCP/A2A/JSON wrapper profile을 구현하거나, 준비 전에는 연결 준비 중으로 표시한다. 기존 /mcp의 tools/call→name=call(resource_id,tool,arguments)은 재사용 가능한 별도 계약이며 원본 tool 이름을 그대로 호출하는 endpoint와 구분한다.

**완료 기준:** 광고하는 각 연결 URL로 실제 protocol handshake/허용 호출/오류/취소를 검증하고 미지원 profile을 광고하지 않는다. 단순 gateway 문자열 검사를 수용 기준으로 삼지 않는다.

관련성: 이번 주소 생성 정책과 직접 관련 · 기존 설계 연결: G0 · AC-13

소스: [front.py:427](<저장소>/agent_market/concierge/front.py:427), [extracted_html.txt:6552](<저장소>/extracted_html.txt:6552), [front.py:2993](<저장소>/agent_market/concierge/front.py:2993)
재현 기록: `missing_gateway_handler` — observations.json 및 audit_gateway_result.py.

### F02 · P1 · Chat·MCP·A2A의 실제 응답에 원본 연결 URL이 남음

**확인:** 동일 합성 MCP weather 에이전트를 세 채널로 검색했다. 세 응답 모두 https://audit-weather.example/api 원본 주소를 포함했다. 상세 API와 일부 카드의 변환 함수는 공통 추천 직렬화에 적용되지 않았다.

**영향:** 개발자 도구나 머신 클라이언트는 여전히 원본 연결 주소를 읽을 수 있다. 전면 비노출 정책의 적용 범위가 화면 및 일부 API에 한정된다.

**권장 변경:** 서버 공통 public recommendation/connection DTO를 만들고 REST Chat·MCP structuredContent·A2A data part·상세·알림에 적용한다. 내부 resources.url과 실제 호출 바인딩은 유지한다.

**완료 기준:** 각 채널의 원시 HTTP JSON과 중첩 text/data에 합성 upstream 주소가 없는지 검증하고 gateway ref·도구 schema는 유지한다.

관련성: 전면 적용 범위의 누락 · 기존 설계 연결: G0 · AC-00

소스: [selection.py:164](<저장소>/agent_market/concierge/selection.py:164), [selection.py:187](<저장소>/agent_market/concierge/selection.py:187), [recommendation_security.py:99](<저장소>/agent_market/concierge/recommendation_security.py:99)
재현 기록: `discovery_raw_upstream` — observations.json 및 audit_gateway_result.py.

### F03 · P1 · Testbench가 공통 실행 제한을 통과하지 않음

**확인:** 네 조건을 각각 등록하고 MockTransport에서 outbound 요청을 기록했다. /api/test/execute는 모두 tools/call을 1회 전달하고 HTTP 200, ok=true를 반환했다. McpProxy.execute는 호출되지 않았다. 실제 외부 제공자나 파괴적 작업은 실행하지 않았다.

**영향:** Testbench가 플랫폼의 schema pinning·안전 도구·active/quarantine 정책과 다른 실행 경로가 된다. URL 비노출과 SSRF 방어가 남아 있어도 도구 실행 권한 검증을 대체하지 못한다.

**권장 변경:** Testbench·workflow·MCP call·새 gateway handler를 공통 ExecutionAdmission에 연결한다. active/격리·허용 도구·타입/schema hash·인증·예산을 검사하고 정책 거절은 제공자 호출 전에 확정한다.

**완료 기준:** 각 거부 조건에서 provider 호출 0회, 정상 read-only 조건에서만 호출·정제 결과 반환. schema drift·인증 미승인·잘못된 입력도 같은 매트릭스에 추가한다.

관련성: 기존 Testbench 경로에서 확인한 문제; 주소 치환이 새로 만들었다고 단정하지 않음 · 기존 설계 연결: G0 · AC-13

소스: [front.py:2468](<저장소>/agent_market/concierge/front.py:2468), [front.py:2488](<저장소>/agent_market/concierge/front.py:2488), [proxy.py:41](<저장소>/agent_market/concierge/proxy.py:41), [workflows.py:367](<저장소>/agent_market/workflows.py:367)
재현 기록: `testbench_admission_bypass` — observations.json 및 audit_gateway_result.py.

### F04 · P1 · 광범위한 URL 치환이 뉴스·문서 출처와 결과를 훼손

**확인:** 합성 provider가 반환한 https://news.example/story/2026-10-17이 output에서 gateway URL로 바뀌었다. 저장 테스트 리포트의 [Source documentation](https://docs.example/reference/weather)도 같은 실행 URL로 바뀌었다.

**영향:** 근거 확인·뉴스 최신성·문서 검증·다운스트림 링크 활용이 불가능해지고, 원본 응답과 다른 내용을 실제 결과로 보여준다.

**권장 변경:** 원본 실행 endpoint·credential 필드만 공개 projection에서 제외하고 뉴스/논문/문서 출처·정상 업무 링크는 보존한다. provider output 전체의 모든 https 문자열을 치환하지 않는다.

**완료 기준:** 민감 endpoint는 사라지고 정상 출처 URL·Markdown·구조화 데이터는 그대로 유지되는 양성/음성 검사를 함께 둔다.

관련성: 추가된 광범위 문자열 치환과 직접 관련 · 기존 설계 연결: G0 · AC-00

소스: [front.py:436](<저장소>/agent_market/concierge/front.py:436), [front.py:2650](<저장소>/agent_market/concierge/front.py:2650), [extracted_html.txt:6562](<저장소>/extracted_html.txt:6562)
재현 기록: `citation_and_wire_corruption`, `report_citation_corruption` — observations.json 및 audit_gateway_result.py.

### F05 · P2 · Raw Wire가 실제 전송 구간과 일치하지 않음

**확인:** 실제 브라우저 요청은 /api/test/execute + resource_id/tool/arguments, 실제 server outbound는 audit-weather.example/api + tools/call이다. 반환 request_wire는 /api/gateway/mcp/1 + upstream tools/call body였다.

**영향:** 고객이 패킷을 재현하거나 latency·endpoint·실패 원인을 판단할 때 잘못된 근거가 된다.

**권장 변경:** 공개 Inspector는 inspection_scope=client_to_gateway로 실제 method/path/body를 정제해 제공한다. upstream trace는 별도 관리자 권한으로 분리하고 마스킹된 요약이면 Raw가 아닌 Sanitized trace로 표시한다.

**완료 기준:** 관측 구간의 실제 HTTP 기록과 화면/세션 export를 대조하고 Gateway/Provider/Total latency 의미를 분리한다.

관련성: gateway URL 치환으로 관측 의미가 변경됨 · 기존 설계 연결: G0 · AC-00 / AC-13

소스: [front.py:2500](<저장소>/agent_market/concierge/front.py:2500), [extracted_html.txt:8336](<저장소>/extracted_html.txt:8336)
재현 기록: `citation_and_wire_corruption` — observations.json 및 audit_gateway_result.py.

### F06 · P2 · 문자열 prefix로 신뢰 origin을 판정

**확인:** details.note에 접미사 도메인·userinfo·8443 port URL을 넣었다. /api/agents/{id}가 세 문자열을 그대로 반환했다. startsWith 검사는 실제 hostname/origin 검사가 아니다.

**영향:** gateway-only 예외 판정이 의도한 origin보다 넓다. 이 재현은 필터 예외를 증명하며 SSRF·코드 실행·credential 탈취를 증명한 것은 아니다.

**권장 변경:** URL parser로 scheme·정규화 host·port·userinfo를 검증한다. 연결 endpoint의 정확한 origin 정책과 정상 출처 링크의 허용 정책을 분리한다.

**완료 기준:** 유사 도메인·userinfo·다른 port·인코딩/대소문자 변형에 대한 경계 검사와 실제 정상 링크 보존을 함께 검증한다.

관련성: 추가된 gateway 문자열 예외와 직접 관련 · 기존 설계 연결: G0 · AC-00

소스: [front.py:444](<저장소>/agent_market/concierge/front.py:444), [extracted_html.txt:6565](<저장소>/extracted_html.txt:6565)
재현 기록: `trusted_origin_prefix` — observations.json 및 audit_gateway_result.py.

### F07 · P1 · 프리셋이 외부 호출 없이 실시간 검증 성공을 표시

**확인:** 외부 HTTP와 McpProxy를 호출하면 실패하도록 바꾼 상태에서도 네 프리셋이 ok=true였다. 서버는 35ms sleep 후 고정 날씨/금융/검증 문구를 만들고 지연에 35ms를 가산한다. UI는 Run Live Test와 real-time round-trip을 설명한다.

**영향:** 실제 연결·가용성·품질·응답 지연·결제 프로토콜 검증의 근거로 오해할 수 있다. gateway 경로를 넣어도 실제 호출 증거는 생기지 않는다.

**권장 변경:** Demo/Simulation으로 명확히 분리하고 quality evidence·live badge·실측 KPI에서 제외한다. 실검증이 목적이면 승인된 read-only endpoint에 실제 호출한 증거만 표시한다. 100% 성공 보장 문구를 제거한다.

**완료 기준:** simulation은 simulated=true·executed=false 등 구분 가능한 상태와 UI 표시를 갖고, live 상태에는 실제 provider 시도와 원시 측정 시간을 요구한다.

관련성: 기존 프리셋 구조의 문제; 이번 전환에서 실행 검증으로 오인하기 쉬움 · 기존 설계 연결: G0/G1 · AC-13 / AC-04

소스: [front.py:2257](<저장소>/agent_market/concierge/front.py:2257), [front.py:2262](<저장소>/agent_market/concierge/front.py:2262), [extracted_html.txt:7760](<저장소>/extracted_html.txt:7760), [extracted_html.txt:2332](<저장소>/extracted_html.txt:2332)
재현 기록: `synthetic_preset_success` — observations.json 및 audit_gateway_result.py.

### F08 · P2 · 프로토콜 응답을 업무 성공으로 과도하게 판정

**확인:** A2A result.status.state=failed 및 working을 각각 반환해도 ok=true/is_error=false였다. x402 branch는 결제 challenge가 전혀 없는 HTTP 402에도 ok=true였다.

**영향:** 접속 성공·유효한 프로토콜 응답·업무 완료가 섞인다. live test의 성공 표시와 이후 품질 판단 근거가 부정확해진다.

**권장 변경:** transport_ok·protocol_valid·task_status·execution_succeeded를 구분한다. A2A 버전별 task/message 형태·중첩 상태·pending/input-required를 처리하고, x402는 지원 버전 challenge를 파싱/검증하되 자동 결제하지 않는다. JSON-RPC ID/오류와 HTTP 상태도 검증한다.

**완료 기준:** A2A failed/working/input-required/완료, 잘못된 response ID, 유효/무효 402 challenge를 고정 fixture로 분리하고 미완료를 업무 완료로 표시하지 않는다.

관련성: 기존 Testbench 프로토콜 판정의 문제; 신규 handler에도 재사용하지 않도록 개선 · 기존 설계 연결: G0/G1 · AC-13 / AC-04

소스: [front.py:2579](<저장소>/agent_market/concierge/front.py:2579), [front.py:2603](<저장소>/agent_market/concierge/front.py:2603)
재현 기록: `a2a_state_not_validated`, `unvalidated_payment_challenge` — observations.json 및 audit_gateway_result.py.

## 권장 작업 순서

1. **F03:** 공개 Testbench의 active/quarantine·안전 도구·등록 schema·인증·예산 경계를 먼저 공통화한다. 거절된 요청의 외부 호출 0회를 확인한다.
2. **F01:** 연결 주소마다 실제 handler/profile을 구현하거나 연결 준비 상태로 전환한다. 기존 /mcp call wrapper를 쓴다면 호출 계약을 명확하게 구분한다.
3. **F02·F04·F06:** 공통 공개 DTO를 모든 채널에 적용하고, 원본 실행 주소와 정상 출처를 분류하며 exact-origin 검증을 넣는다.
4. **F05:** 공개 client→gateway 관측과 관리자 upstream trace를 분리하고 화면·세션 다운로드의 의미를 일치시킨다.
5. **F07·F08:** demo/live를 분리하고 프로토콜 응답·task 진행 상태·업무 완료·유효 결제 challenge를 구분한다.
6. 전체 표면/실제 호출/정책 거부/정상 출처/기존 ZIP을 묶은 G0 매트릭스로 재검증한다. 재시도·폴백·AI 자동 합성을 확대하기 전에 통과시킨다.

## 기존 테스트가 놓친 부분

현재 신규 비노출 테스트는 변환된 주소 문자열과 원본 도메인의 부재, 프리셋 성공 응답을 검사한다. 표시 주소의 실제 호출, REST/MCP/A2A 원시 응답, 안전하지 않은 호출의 outbound 0회, 정상 출처 보존은 검사하지 않는다. 다음 수용 기준을 추가한다.

- 광고된 연결 URL → 실제 지원 protocol/operation 실행 성공과 미지원 응답.
- /chat·MCP search/find_agents·A2A data part·상세·알림·metadata의 동일 public projection.
- active/격리/미등록/위험 도구/schema drift/잘못된 입력/인증 미승인 시 외부 호출 없음.
- 원본 실행 URI는 비노출, 뉴스/문서/논문·사용자 검증 수신처는 목적대로 보존.
- 신뢰 origin의 접미사·userinfo·다른 port·인코딩 변형과 올바른 정상 origin.
- Wire/Telemetry/export와 실제 관측 구간 일치; 개인 토큰·upstream 진단은 비노출.
- preset simulation과 실호출 이력 분리; A2A pending/failed와 잘못된 402 challenge의 과도한 성공 판정 방지.
- 기존 public workflow SDK/ZIP·admin 1.1·CSP·영어·접근성 회귀.

## 검증 수치의 의미

기존 회귀는 **99개 통과**다. 추가 감사 probe는 **22개가 모두 문제를 재현**했다. 감사 파일은 관측된 미비점이 존재함을 assert하므로 여기서 PASS는 보안 안전이나 수정 완료라는 뜻이 아니다. 실제 수정 후에는 요구 동작을 assert하는 일반 회귀로 바꿔야 한다. 22개는 22개 독립 취약점이 아니라 8개 개선사항에 대한 프로토콜/조건별 사례 수다.

재현은 합성 .example 주소와 MockTransport만 사용했다. 테스트용 DNS admission을 합성 호스트에 대해 대체했고 실제 HTTP transport는 전부 메모리였다. SSRF 방어를 운영에서 우회했다거나 실제 삭제·결제·외부 수신 전송이 일어났다는 의미가 아니다. 이 검토는 전체 소스/배포에 대한 완전한 침투 테스트가 아니다.

생성 파일: README.md, review.json, observations.json, audit_gateway_result.py, existing-regressions.xml, workflow-regressions.xml, audit-probes.xml, source-snapshot.json. 제품 소스·원래 테스트·운영 DB·서버 설정은 수정하지 않았다.

## 프로토콜 근거

A2A는 Message와 Task를 구분하며 Task는 진행·입력 대기·완료/실패 등 수명주기 상태를 가진다. 따라서 task 접수나 working 상태를 업무 완료와 분리하는 설계를 권고한다. [A2A Life of a Task](https://a2a-protocol.org/latest/topics/life-of-a-task/)

x402의 402 신호는 지원 버전의 결제 요건/형식 검증과 구분해야 한다. 402라는 HTTP 숫자나 임의 L402 문구만으로 유효한 x402 결제·정산 성공을 표시하지 않는다. [x402 v2 specification](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md)

MCP 도구의 schema와 annotation을 검토하되 공급자가 적은 annotation 자체를 안전 보장으로 삼지 않는다. 플랫폼에서 허용 도구·정책을 결정한다. [MCP Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
