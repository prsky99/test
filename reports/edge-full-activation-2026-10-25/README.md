# Frontend·Admin Edge 우선 운영 반영

2026-10-25 반영과 운영 확인을 완료했습니다. 결과 크기로 경로를 선택하지 않습니다. 지원되는 외부 Agent는 Edge가 먼저 실행·전달하고, Edge 준비 실패·할당량·장애 또는 해당 전달 계약을 지원하지 않는 요청은 기존 승인된 Origin 경로를 사용합니다.

## 운영 상태

- Cloudflare Worker: `f0775054-132c-4a11-97ab-6b6d9c86d342` (100% 배포).
- Route: 기존 fail-open 5개 유지, 공개 실행·결과 계열 7개 추가, 합계 12개. Admin Route는 공개하지 않았습니다.
- `native_node_delivery=true`, `direct_result_delivery=true`.
- 실제 관찰: `preferred_backend=worker`, `reason=free_available`, 무료 플랜, 자동 유료 전환 비활성, Worker 오류 보호 차단 없음. 확인 시 계정 집계 633건.
- 새 Secret 0개, DB 마이그레이션 0개. 기존 Secret은 Cloudflare 내부 상속으로 유지했습니다.

## 반영 경로

- 공개 Gateway·Testbench: A2A·MCP·x402 probe의 기존 승인·입력 검증 후 Edge를 우선 사용합니다.
- MCP `call`: 기존 `/mcp`에서 준비·실행·최종 결과 조립을 분리해 Provider 결과를 Edge에서 전달합니다.
- Workflow·Workspace·다운로드 웹앱: 부모 실행 권한과 노드별 중복 방지를 유지하고 Edge 결과 Receipt를 저장합니다. 기존 결과 조회 권한을 확인한 뒤 작은 조립 명세를 Edge에 전달합니다. 작은 결과도 같은 우선순위를 적용합니다.
- 기존 Admin: 개인 세션은 내부에 유지하고, 짧게 유효한 Origin·입력 고정 Ticket으로 브라우저가 공개 Edge에 연결합니다. 서버 API 호환 호출도 Provider IO는 Edge를 우선 사용합니다.
- 리뉴얼 Admin: 공통 API 모듈의 단일 실행을 같은 직접 전달 경로로 연결했습니다. 준비·완료의 개인 세션, 실행 사유, 기존 감사 기록과 세션 변경 후 응답 폐기 정책을 유지합니다. CSP는 지정된 공개 Edge Origin만 추가 허용합니다.

## Origin 복구와 안전 경계

- 실행 전 Edge 준비 실패·무료 사용량 보호·미지원 계약은 Provider IO 전에 Origin으로 전환합니다.
- Edge가 이미 실행을 접수한 경우에는 같은 실행의 상태·Receipt·저장 결과만 확인합니다. 결과 불확실 상태에서 Provider를 다시 호출하지 않습니다.
- Edge 캐시 누락은 동일한 저장 결과를 Origin에서 읽어 복구합니다. 전 세계 모든 지역에서 Origin egress가 항상 0이라는 주장은 하지 않습니다.
- 로컬 자체 Agent와 명시적 비공개 Credential 바인딩은 기존 승인된 Origin 실행을 유지합니다. x402는 결제 없는 probe만 Edge 대상으로 하며 실제 결제 권한은 기존 경로에 유지합니다.
- 기존 입력·출력 크기, Schema, 개인정보, SSRF, 동시 실행, 무료 사용량·CPU 보호 제한을 유지했습니다.

## 실제 활성 릴리스

- frontend: `edge-full-frontend-20261025-141509`
- admin: `edge-renewal-admin-20261025-142200`
- jobs: `edge-full-jobs-20261025-141509`
- execution: `edge-full-execution-20261025-141509`

다른 작업에서 배포한 최신 Frontend Workflow Library 화면·자산을 보존했습니다. 네 역할 모두 운영 중인 패키지에 검토한 변경만 병합했으며, 리뉴얼 Admin 후속 변경도 기존 Admin 패키지의 다른 파일 1,201개를 보존했습니다.

## 검증

- 핵심 API·권한·실패 복구 검증: 106개 통과. 이후 x402 도전 응답 보존, 리뉴얼 감사, 금지 입력의 403 처리를 추가 검증했습니다.
- Worker: 70개 통과.
- 기존 Edge·보안 Chromium: 22개 통과. Admin 직접 전달 모듈 최종 Chromium: 7개 통과(기존 검사 일부 중복).
- 실제 첫 배포 패키지: Frontend 78개, Admin 77개, Jobs 25개, Execution 25개 통과. 리뉴얼 Admin 최종 패키지의 관련 API 검증 24개 통과.
- 공개 Frontend 내용 검사: 267개 파일, 위반 0개.
- 운영 확인 12개 통과: 양쪽 화면·자산, 공개 메타데이터·MCP tools/list, 공개 Admin 차단, Ticket 경로 CORS, 리뉴얼 모듈 게시, 비인증 실행 차단.
- 실제 Worker 서명 검증 3개 통과: 상태 확인과 2바이트·40KB 합성 결과의 암호화 캐시·조립·전달. Provider 실호출은 0회입니다. 전체 등록 Provider의 성공을 검증한 결과로 해석하지 않습니다.

별도 광범위 검사에서 기존 공개 문구 `One best agent`를 요구하는 오래된 assertion과, 기존 Admin 패키지의 specialist 패널 조회 기대 불일치를 확인했습니다. Specialist 실패는 수정 전 패키지에서도 동일하게 재현했습니다(`preexisting-specialist-test.log`). 이와 별개로 브라우저 fixture가 필요한 무관한 패널 검사는 최종 관련 API 검사에서 제외했습니다. 이번 Edge 관련 최종 검사에는 실패가 없습니다.

## 운영·복구 자료

- `validation-summary.json`, `final-services.json`: 최종 상태.
- `live-verification.json`, `live-synthetic-probes.json`, `runtime-refreshed.json`: 운영 증거.
- `cloudflare-before-upload.json`, `cloudflare-upload.json`, `cloudflare-route-changes.json`: 이전 Worker·Route와 변경 기록.
- `staged-releases.json`, `renewal-staged.json`, `deployed-source.patch`: 역할별 보존·변경 증거.
- `activate.py`, `activate-renewal.py`: 기존 A/B 및 안전 종료·교체 경로와 실패 시 복구 로직.

Wrangler의 계정 조회와 실제 도메인 계정이 달라 공식 REST API로 Zone·계정·배포를 대조한 뒤 반영했습니다. 이후 Worker 작업은 이 폴더의 `cloudflare-release.py`처럼 도메인 계정 검증을 거쳐 수행해야 합니다. 공식 API: https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/versions/methods/create/

기존 Provider 캠페인·장기 부하 검증·heartbeat 결과 파일은 변경하지 않았습니다.
