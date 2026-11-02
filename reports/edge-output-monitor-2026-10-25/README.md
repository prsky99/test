# Edge·Origin 모니터링 및 출력 경로 점검

2026-10-25 개발·운영 반영·검증을 완료했습니다.

## 화면 위치

리뉴얼 Admin → **워크플로·실행 → Edge·Origin 모니터링**

주소: `/admin/next#/workflows/w08`. 기존 창은 새로고침하면 새 메뉴가 표시됩니다. 최고관리자·관리자·운영자의 개인 세션으로 조회하며, 공개 Frontend에서는 Admin 접근을 계속 차단합니다.

## 적용 기준

**모든 Agent 출력은 Edge Gateway를 먼저 사용하고, 전달 실패 시 Origin으로 복구합니다.** Agent 실행 위치와 출력 전달 위치를 별도로 다룹니다. 로컬 Agent·비공개 인증이 필요한 실행도 결과는 Edge 전달을 먼저 시도합니다.

Edge가 Origin의 결과를 중계하면 Edge 전달로 표시하고 **Origin 중계 건수**를 함께 보여줍니다. 이 경로에는 Origin의 데이터 전송이 남습니다. 실행 위치 원장은 별도 영역에 있어 출력 건수와 합산하지 않습니다.

## 화면 기능

- Edge 전달, Origin 복구, Edge 비율, 전달 오류.
- 시간별 차트, 서비스별 집계, Origin 복구 사유, 최근 50건의 경로·서비스 필터.
- 최근 1시간·6시간·24시간·7일 조회와 수동 갱신.
- 화면이 보이고 네트워크가 연결됐을 때 15초 자동 갱신, 자동 갱신 끄기.
- 갱신 실패 시 이전 값을 유지하고 오래된 데이터와 실패 상태를 표시.
- 무료 Worker 사용량·안전 한도·최근 관측 시각과 현재 준비 상태.

화면 조회는 저장된 관측만 읽습니다. Provider 실행이나 정책 변경을 수행하지 않습니다. 과거 전달 경로는 미관측으로 남기며, 새 계측부터 누적합니다. 수치는 출력 응답·단계 응답·재조회의 관측 건수로, 고유 Provider 실행 횟수와 구분합니다.

## 소스 점검과 보완

1. 공개 `POST /`, `/chat`, `/a2a`의 Worker Route 누락을 보완했습니다.
2. 자체 Agent `/api/owned-data-agents/*`의 출력 경로를 Worker에 연결했습니다. 기존 로컬 실행 바인딩은 결과 전달과 독립적으로 유지합니다.
3. 기존/리뉴얼 Admin 테스트, 저장된 보고서, Workflow·Workspace 실행 결과, 원격 A2A 작업·후속 메시지, AI 제작 결과의 반환 경로에 공통 출력 Relay를 적용했습니다.
4. 별도 fetch를 사용하던 전문 패널·직원 Workspace에도 같은 전달 처리를 연결했습니다.
5. SDK가 준비 단계의 Origin 주소를 바로 사용하던 단축 경로를 제거했습니다. Edge를 먼저 시도하고 실패 후 같은 실행 건의 Origin 복구를 허용합니다.
6. Worker의 Origin 중계와 실제 Origin 응답을 서비스 서명·nonce로 구분해 집계합니다.

원천을 직접 호출하는 실행 코드는 `concierge/proxy.py`, `workflows.py`, `workspace_remote_a2a.py` 등에 남아 있습니다. 실제 사용자에게 반환하는 단계는 위 Edge 전달 경로로 감쌌습니다. 수집·명세 조회·헬스체크, 별도 동의가 필요한 알림·Webhook 발송, 독립 Buyer/Chain CLI 통신은 웹 서비스의 Agent 출력 반환과 별도 분류했습니다. 이 작업에서 알림을 보내거나 발송 정책을 변경하지 않았습니다. 경로별 근거·해시: `source-path-audit.json`.

## 보호와 복구

- 원래 엔드포인트의 역할·멤버십·실행 사유·감사·입력 검증을 먼저 적용합니다.
- Admin 세션·Cookie는 공개 Edge로 전달하지 않습니다. 브라우저에는 짧게 유효한 Origin·결과 해시 고정 Capability를 제공합니다.
- Edge Cache는 암호화하고 복구본은 무결성 서명과 개인 세션에 연결합니다. 복구 권한은 120초이며 만료 정리는 작은 묶음으로 수행합니다.
- 다른 Edge 지역에서 캐시를 찾지 못하면 서명된 제어 경로로 **기존 결과만** 읽습니다. Provider를 다시 실행하지 않습니다.
- 기존 API 클라이언트는 JSON 계약을 유지하는 호환 Relay로 Edge를 거쳐 반환합니다. 이 호환 경로에도 Origin 데이터 전송은 남습니다.
- 기존 출력 계약·크기 제한을 유지합니다. 공통 Admin Relay의 64KB 계약을 넘는 응답은 전달 준비 실패로 기록하고 원래 결과를 복구합니다. 임의 크기 파일·전 세계 모든 지역의 Origin 전송 0을 보장하지 않습니다.
- 오래된 실행 중·결과 불확실 상태에서 Provider를 자동 재실행하지 않습니다.

## 운영 반영

- frontend: `edge-output-frontend-20261025-153117` (이전: `discovery-three-20261025-r1`)
- admin: `edge-output-admin-20261025-153117` (이전: `discovery-three-20261025-r1`)

Worker: `edf9cefa-7e8e-4358-8cdf-3238c547bd04` (100%). 공개 Route는 기존 12개를 보존하고 4개를 추가해 **16개**입니다. 모두 fail-open을 유지하며 Admin Route는 공개하지 않았습니다. 새 Secret과 DB 마이그레이션은 0개이고 Jobs·Execution은 재시작하지 않았습니다. 같은 저장소의 최신 Discovery Three 화면·기능과 다른 파일 해시를 보존했습니다.

## 검증 결과

- 실제 Frontend·Admin 후보 패키지: 각각 68개 통과.
- Worker: 73개 통과.
- 최종 Chromium: 17개 통과. 별도 전문 패널 브라우저 회귀 검사 14개 통과(검사 일부 중복).
- 보안·권한·기존 결과 복구 회귀 73개 통과(이전 묶음과 일부 중복).
- 공개 내용 검사: 267개 파일, 위반 0개.
- 운영 화면·자산·메뉴·인증 차단·메타데이터 확인: 15개 통과.
- 서명된 실제 Worker 상태·2바이트/40KB 합성 캐시 검증 3개 통과. 신규 출력 게시 API의 합성 데이터 검증 2개 통과.
- 운영 PostgreSQL 집계 읽기 확인 통과. 실제 MCP 메타데이터 응답의 Edge 관측이 집계에 반영됐습니다.
- 실제 외부 Provider 실행 0회. 전체 Provider 성공이나 장기 부하 완료를 주장하는 결과가 아닙니다.

실제 관측 시 Worker 사용 가능·무료 안전 한도 내·런타임 오류 차단 없음으로 확인했습니다. 증거: `live-verification.json`, `live-synthetic-probes.json`, `live-output-publish.json`, `runtime-refreshed.json`, `postgres-readonly-check.json`.

## 복구 자료

`services-before.json`에 이전 웹 릴리스, `staged-releases.json`에 보존 범위, `deployed-source.patch`에 배포 차이를 기록했습니다. Worker 이전 버전·추가 Route ID는 Cloudflare JSON에 보관했습니다. 전체 원복 시 새 Route 4개를 먼저 제거하고, 이전 Worker 및 웹 릴리스를 복원해야 합니다. 기존 Provider 캠페인·장기 부하·heartbeat 결과 파일은 변경하지 않았습니다.
