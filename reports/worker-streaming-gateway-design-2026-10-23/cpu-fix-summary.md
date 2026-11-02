> 후속 전체 Provider 검증에서 CPU10ms 초과와 완료 callback 보완 사항이 추가로 확인되었습니다. 최신 진행 상태는 [전체 검증 기록](../edge-provider-validation-2026-10-23/README.md)을 확인합니다. 아래는 이전 단일 Provider 표본의 기록입니다.

# MCP Edge 안정화 적용 기록

이 작업은 남아 있던 Free CPU 초과 원인을 논문·SNS·공식 문서와 실제 프로파일로 확인하고, MCP 제어와 결과 경로를 분리하여 개선한 운영 기록이다. 모든 Provider 개별 적합성이나 Free CPU의 모든 요청 준수를 보장하는 문서가 아니다.

## 조사에서 적용한 판단

[New Kids 논문](https://arxiv.org/html/2604.15916v1)은 7개 serverless 플랫폼의 구조와 실측을 비교한다. 짧은 Edge 처리에 적합한 구조라는 설명은 설계 참고 자료로 사용했다. 논문의 응답 지연 수치를 우리 Worker CPU나 비용 절감 실적으로 사용하지 않았다.

[Cloudflare 사용자 SNS 논의](https://www.reddit.com/r/CloudFlare/comments/1r6gcna/how_can_i_measure_cpu_time_in_a_cloudflare_worker/)에서는 자체 타이머와 한도 초과 후에도 성공하는 일부 요청의 해석 문제가 제기됐다. SNS 사례는 가설이며 실제 정책은 [공식 CPU 제한](https://developers.cloudflare.com/workers/platform/limits/#cpu-time)과 [CPU 프로파일 방법](https://developers.cloudflare.com/workers/observability/dev-tools/cpu-usage/), [운영 프로파일](https://developers.cloudflare.com/workers/observability/profiling-in-production/)을 기준으로 확인했다. 성공 또는 오류 0건만으로 10ms 준수를 확정하지 않는다.

[MCP 공식 SDK](https://php.sdk.modelcontextprotocol.io/client/connecting/)의 프로토콜 버전 지정 동작에 따라 이미 관측된 handshake 버전에는 중복 server/discover를 생략했다. 미확인 버전의 기존 자동 탐색은 유지한다.

[Cloudflare 내장 EventSource](https://developers.cloudflare.com/workers/runtime-apis/eventsource/)의 from(stream)은 새 연결 없이 기존 응답을 해석한다. 누적 frame 문자열의 반복 정규식 검사와 일부 줄바꿈 처리 문제를 내장 파서로 교체했다. 별도 guard로 64KB raw bytes와 fatal UTF-8 제한을 적용한다.

## 실제 변경

알려진 handshake MCP는 Origin이 initialize·initialized·tools/list와 실시간 Schema 및 입력·안전 검증을 수행한다. Worker가 tools/call을 1회 직접 실행하고 결과를 받아 플랫폼 URL 투영·비밀 필드 제거 후 사용자에게 출력한다. Origin은 Tool 결과 본문을 받지 않는다.

Origin이 발급한 cleanup 권한은 run·attempt·endpoint·프로토콜·세션·만료에 묶은 도메인 분리 HMAC으로 보호한다. Worker는 기존 완료 callback에 이 권한만 반환한다. Origin이 서명을 확인한 뒤 세션 DELETE를 수행하므로 Worker의 별도 teardown HTTP 호출도 줄였다. 새로운 DB DDL·Secrets·유료 서비스는 추가하지 않았다.

JSON 단일 chunk의 복사와 출력 객체의 중간 배열 할당도 줄였다. 입력/출력 크기, strict UTF-8, Provider Redirect 금지, 브라우저 자격 증명/IP의 Provider 전송 금지, durable 1회 실행권과 이미 시작한 요청의 자동 재실행 금지는 유지한다.

## 검증과 운영 범위

Python/API/Chromium181개, Worker35개 테스트 통과. 서명 위조·대상 변경·실행 간 재사용, Schema 변경, 만료, 중복 실행 금지, fragmented UTF-8, CR/LF/CRLF, 알림과 응답 혼재, EOF를 닫지 않는 SSE, 크기 초과·잘못된 UTF-8을 검사했다. Bandit0건, public frontend249개/위반0건.

Frontend·Admin은 각각 최신 활성 릴리스를 복제하여 Edge 관련4파일만 덮어썼다. Admin 리뉴얼의 다른 파일 해시를 보존했다. Jobs·Execution 릴리스/PID는 동일하다. Public UI 파일은 변경하지 않았다. Cloudflare5개 fail-open Route, encrypted Secrets, Free와 자동 Origin 보호 정책을 유지한다.

실측 JSON·CPU profile·배포 manifest는 같은 디렉터리에 보존했다. 실제 일일 무료 한도를 고의로 소진하거나 지속 부하 테스트는 수행하지 않았다. 결과 본문 egress를 줄이되 제어 metadata·기존 서버 비용·Provider 사용료는 각각 존재하며, Origin fallback에서는 기존 본문 출력 비용이 적용된다.

최종 배포와 CPU 실측은 아래에 기록한다.

## 최종 확인

Worker `ce8cc419-54e2-4a45-9521-e8f7c2f2d3b0` 100% 배포 완료. Frontend `edge-control-frontend-20261023-215325`, Admin `edge-control-admin-20261023-215325`로 A/B 반영 완료했으며 Jobs·Execution 릴리스/PID는 유지했다.

최종 SiteKrs MCP의 Gateway2회·Testbench1회 모두 Worker에서 성공했다. 실제 결과 바이트는 Gateway1,522/1,522, Testbench4,176으로 완료 기록과 일치한다. Gateway 결과 SHA256은 변경 전과 동일하다. 표본 응답에 Provider 호스트 노출이 없었다.

Cloudflare 최종 관찰 구간2026-10-23 13:04:01–13:06:19UTC의7개 Worker 요청에서 최대 CPU8.7ms(원값8.676ms), runtime 오류0건을 확인했다. MCP3회 외 health/보안 요청이 포함된 구간이다. 이전 MCP 검증 구간 최대17.0ms, 단순 최적화15.9ms, 제어/결과 분리12.6ms를 기록했으며 최종 내장 SSE 파서 적용 구간에서는 모두10ms 안이었다. 이전 실패 표본도 별도 JSON에 보존했다.

이는 하나의 실제 Provider에 대한 제한된 성공 표본이다. 전체 카탈로그·긴 출력·지속 부하의 CPU10ms 상시 충족을 확정할 수는 없으므로 현재 Free와 사용량/서명 health/런타임 오류 감지에 따른 신규 요청의 Origin 보호를 유지한다. 이미 실행권을 취득한 요청은 자동 재실행하지 않는다.

결과 경로를 분리하면서 협상 지연은 Origin 네트워크의 영향을 받는다. 최종 실제 클라이언트 wall time은 약3.4–3.9초였고, 이전 전부 Worker 협상 표본은 약1.2–2.3초였다. CPU 절감과 응답 지연은 별도 지표이며 이 변경을 모든 요청의 속도 개선으로 표시하지 않는다. 대용량/바이너리/유료·인증 흐름과 별도 Workspace/Workflow 서버 실행 API는 기존 적용 범위다.

실운영 보안 확인: 공개 MCP preflight204, 서명 없는 내부 완료401, 타 Origin SDK 요청403. 이 검사에서 Provider Tool을 실행하지 않았다. 최종 검증: Python/API/Chromium181, Worker35, Bandit0, public frontend249개/위반0.
