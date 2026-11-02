# MCP·x402·403 수정 결과

상태: 사용자 승인으로 두 웹 후보를 운영 적용했습니다. 현재 운영은 protocol-disclosures-frontend/admin-20261029-r1이며, 공개 MCP·페이지·어드민 인증 경계 13개 및 전환 관찰 65/65 HTTP 200을 확인했습니다. 다만 공개 x402 경로가 별도 Cloudflare Worker를 통과하는 추가 원인을 발견해, 그 경로의 수정·배포는 QA10 후속 작업으로 진행 중입니다.

## 수정

- MCP: search·find_agents·whats_new·search_workflows를 실제 읽기 전용 조회로 분리했습니다. readOnlyHint/idempotentHint=true, destructiveHint/openWorldHint=false를 게시합니다. 방문자 생성, 메시지 저장, 기존 검색 조건 덮어쓰기를 하지 않습니다. hello/chat은 상태를 저장하므로 읽기 전용으로 표시하지 않습니다. 공통 MCP 계약을 사용하므로 매니페스트와 tools/list가 일치합니다.
- 호환성: 조회 응답은 visitor=null, conversation_recorded=false입니다. 대화를 이어 가거나 whats_new의 기준 작업을 저장하려면 chat을 사용합니다. whats_new는 이미 저장한 작업만 읽으며, 문맥이 없으면 안내를 반환합니다. 조회 결과에는 상세 조회 경로와 chat으로 이어 가는 정보를 제공합니다. 기존 Chat 추천 순서와 프로토콜 필터는 유지합니다.
- x402: 첫 GET 및 POST probe의 402 응답에 inspection_only=true와 payment_processed/payment_accepted/payment_forwarded/settlement_performed=false를 명시했습니다. 결제 증명을 이 게이트웨이에 제출하지 말라는 안내와 제공자의 약관을 검토하는 다음 행동을 포함합니다. 원래 v1/v2 버전·요구 조건은 보존하며, v2 PAYMENT-REQUIRED 헤더도 본문과 일치합니다. 이미 증명을 제출한 501 거절에도 동일한 처리 범위 안내를 사용합니다. 결제·서명·송금·정산 기능은 활성화하지 않았습니다.
- 403: 보안 검토가 필요한 연결은 POLICY_DENIED와 실제 403을 반환하고, 안전한 설명과 다른 에이전트 선택 경로를 제공합니다. IP 차단은 ACCESS_BLOCKED 및 문의 안내, 부적절한 요청은 REQUEST_POLICY_DENIED 및 요청 검토 안내로 구분합니다. 내부 차단 사유는 응답하지 않습니다. 기존 보안 차단은 유지됩니다.
- 추가로 거절 예외에 correlation_id가 없을 때 500이 발생하던 경로도 보완했습니다.

## 검증

- 관련 기능 회귀 257개 통과.
- 격리 Chromium 공개 메뉴·브라우저 공격 및 API·결제 거절 회귀 103개 통과.
- 최종 MCP/x402/403 분기 검사 23개 통과(이전 회귀에 포함된 19개 및 추가 A2A/x402 분기 4개). 이 중 x402는 최초 GET/POST × v1/v2, 403은 MCP/A2A/x402 × 사전/실행 시점 거절을 확인합니다.
- 차단 상태 코드를 더 엄격히 검사한 관리형 연결 회귀 91개 재통과(앞선 257개에 포함).
- 프론트엔드·어드민 후보 각각 임시 PostgreSQL 18에서 조회 무기록·기존 문맥 보존·주석·첫 402 및 외부 TCP 미사용 통과.
- 공개 콘텐츠 319개 파일 위반 0건, 새 모듈·검증 코드 Ruff 통과. HTML과 extracted_html.txt 일치.
- 두 후보 각각 1,335개 파일 해시 확인. 활성 릴리스 대비 변경 파일은 검토한 런타임 7개 및 생성 SQL 카탈로그뿐입니다.

## 실제 운영 확인 범위

수정 전 운영 tools/list에서 조회 도구 주석이 false인 것을 확인했습니다. 당시 /api/gateway/x402/122024는 비활성 등록으로 400을 반환했고, 한정 검색에서 실행 가능한 x402 후보를 찾지 못했습니다. 따라서 첫 402와 정책 403의 수정 후 검증은 통제된 합성 제공자/격리 DB로 진행했습니다. 실제 결제나 운영 보안 차단 유발은 하지 않았습니다. 운영 반영 후 MCP 주석을 재확인해야 하며, 비활성 등록 ID를 억지로 402로 바꾸지는 않습니다.

## 적용 후보

- protocol-disclosures-frontend-20261029-r1: experience-search-frontend-20261029-r2 기반.
- protocol-disclosures-admin-20261029-r1: experience-search-admin-20261029-r2 기반.
- DB 스키마 변경 없음. jobs/execution/모델 서버 재시작 없음.

## 기준

MCP의 readOnlyHint는 실제 도구 동작에 맞아야 합니다: https://modelcontextprotocol.io/specification/2025-11-25/schema
x402의 버전별 결제 요구 조건은 그대로 보존합니다: https://github.com/coinbase/x402/blob/main/specs/x402-specification-v2.md

## 운영 검증 후 추가 발견

공개 x402 ID 226649에서 실제 402를 받았으나 Worker가 원본 요구 조건을 직접 반환해 검사 전용 표시가 없었습니다. 웹 서버 격리 검사 통과를 공개 Edge 경로의 검증으로 확대할 수 없음을 확인했습니다. Cloudflare 활성 버전 84d45696-dd5c-4eec-9457-19f63d272ef0의 소스맵 원본을 읽어 로컬 원본과 일치함을 검증한 뒤 Worker 수정 및 87개 격리 회귀를 통과했습니다. 이 별도 Worker는 아직 배포하지 않았으며 새 승인 대상입니다. 상세 후속 증적은 reports/qa10-remediation-2026-10-29에 저장합니다.
