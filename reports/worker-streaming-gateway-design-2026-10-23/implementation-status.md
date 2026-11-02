# Workers Free Gateway 개발 결과

2026-10-23 기준, 승인된 A2A 0.3 정보성 텍스트 작업을 위한 opt-in 구현과 격리 검증을 완료했다. 운영 설정은 기본 비활성 상태다.

## 구현한 내용

- Worker의 Provider 직접 호출·점진적 SSE 전달, backpressure, UTF-8 프레임 처리, 완료 확인, 시간/크기 제한.
- 플랫폼 실행권, 입력 해시·capability version 고정, 명시적 실행/공유 권한, 내부 HMAC·nonce 재사용 방지.
- SQLite/PostgreSQL의 공통 원자적 실행권. Worker와 Origin 중 한 경로만 같은 작업을 실행하며 불명확한 결과는 재실행하지 않는다.
- 계정 요청 관찰, 보수적인 90,000 기본 전환선, stale/실패 health의 Origin 복귀, 일일 초기화와 runtime 차단 분리.
- `/api/origin-gateway/v1/` 명시적 복귀와 `/api/edge-gateway/v1/` 동일 경로의 인증된 Origin 어댑터.
- 신규 opt-in SDK의 상태 확인 후 미실행 요청에 한한 Origin 복귀.
- 개인 관리자 세션 전용 읽기 API `/admin/api/v2/gateway/edge-delivery`. 실행 상태·집계·본문 바이트만 제공한다.
- 별도 host CLI의 명시적 추가 마이그레이션, revision 검증 제어·audit. SQLite에서는 다른 애플리케이션 테이블 초기화가 발생하지 않는다.

리뉴얼 UI 파일은 수정하지 않았다. 기존 공개 HTML·기존 SDK·Workflow 앱 실행 경로는 이번 구현에서 자동 교체하지 않았다.

## 범위 구분

현재 구현한 공개 API는 실행 준비·상태 조회·Worker/Origin stream·서명 health다. 내부 API는 claim/complete다. 초기 Worker 출력 계약은 제한된 A2A 0.3 SSE의 텍스트 부분만 지원한다. Origin은 기존 제한 실행의 결과를 terminal SSE로 제공한다.

앞서 설계한 `events` 재연결, 파일 `artifacts`/Range, Provider cancellation, 대용량 opaque/NDJSON 프로필, 인증키가 필요한 Provider, MCP/x402, 결제·Credit 정산 확장, 외부 도메인 웹앱 배포 권한은 아직 이 프로필에 구현하지 않았다. 기존 서비스의 해당 기능은 기존 경로를 유지한다. `contracts.json`은 이 미래 범위를 포함하는 설계 문서다.

## 검증

최종 Python 통합 77개, Chromium 11개, 실제 workerd 8개가 통과했다. 별도 임시 PostgreSQL 두 연결에서 중복 claim, 반복 준비/완료, 한도 예약 및 동시 실행 경합을 검증했다. 새 Python 패키지 Bandit 검사는 0건, 공개 콘텐츠 248파일 검사는 0건이었다. 세부 근거는 `development-validation.json`, JUnit 파일과 `bandit.json`에 있다.

브라우저 검증은 CSP가 적용된 실제 Chromium과 격리된 TestClient를 사용했다. Worker 검증은 Miniflare/workerd와 통제된 outbound Mock을 사용했다. 외부 Provider·운영 서버·운영 DB에 실행 요청을 보내지 않았다.

## 운영 적용 경계

실제 Cloudflare 계정의 GraphQL 권한/응답, Free CPU 10ms, 일일 quota 초과와 Route fail-open, 운영 reverse proxy와 DNS/egress 경계는 배포 환경에서 검증해야 한다. 로컬 workerd 테스트는 이 계정 제한의 증명이 아니다. staging 완료 전에는 Worker 활성화 플래그를 유지한다.

Provider 연결 URL·Redirect·원천 오류·헤더는 투영/차단한다. 임의 출력 문자열에 포함된 모든 주소를 완전히 은닉하는 기능은 Provider 출력 계약에 의존한다. 독립적인 출처 인용 링크는 보존한다.

Worker 정상 경로는 결과 본문을 제어 서버에 복사하지 않는다. Origin 복귀 시 기존 서버의 본문 egress 비용이 발생한다. Provider·기존 서버·제어 메타데이터 비용은 각각 존재하며 자동 Paid 업그레이드는 없다.

적용과 롤백의 구체적 절차는 `agent_market/edge_gateway/README.md`에 정리했다. 운영 DB·Cloudflare 설정을 변경하거나 사용자의 서버를 재시작하지 않았다.
