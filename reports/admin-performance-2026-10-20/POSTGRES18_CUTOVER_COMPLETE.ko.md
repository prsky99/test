# PostgreSQL 18 + pgvector 운영 전환 완료

확인 시각: 2026-10-20T19:47:29.095865+09:00

- 운영 설정: PostgreSQL 18.6 (Homebrew), pgvector 0.8.2.
- 정지된 SQLite 원본 최신 데이터: 228개 논리 테이블, 10,316,444행. 복사 시 전체 정규화 데이터 다이제스트와 ID 시퀀스를 검증했고, 실제 원본으로 준비·활성화 단계에서 다시 대조했다. 활성화 후 테이블 건수 불일치 0개.
- 에이전트 124,308건, 헬스체크 7,823,639건, 테스트 보고서 854건, 워크플로우 실행 70건.
- 벡터 75,658건. HNSW와 GIN 인덱스 유효성 및 실제 검색을 확인했다.
- PostgreSQL 쓰기와 롤백, 서명된 SQLite 쓰기 종료 장치와 실제 쓰기 거부를 확인했다. 기존 DB·설정·키의 복구 자료는 비공개 전환 폴더에 보존했다.
- 미확정 워크플로우 8건·연관 시도 13건·서명된 종료 워크스페이스 실행 1건은 원래 상태 그대로 이전했다. 수동 조회 알림 8건도 유지했다. 성공 처리나 재실행·외부 발송은 하지 않았다. 실행 중 작업·외부 발송 대기는 새 경로에서도 차단한다.
- 큰 제공자 계약이 포함된 검색의 8MiB 응답 한도 오류를 수정했다. 원문을 보존하면서 크기에 따라 조회를 분할하며, 쿼리별 8MiB와 전체 자원 조회 64MiB 제한을 유지한다.
- 고유 회귀 검사 209개 통과. 최종 전환 코드 204개 일괄 검사 후 조회 보완의 영향 검사와 대용량·필터 보안 검사를 재실행했다. 중복 실행을 합산하지 않았다.
- 실제 전환 DB로 내부 GET API 8개가 200을 반환했다. 어드민 개요 2.581초, 보고서 탐색 2.853초. 외부 요청 성능 보장은 아니며 TCP 서버·자동 워커를 시작하지 않고 수행한 확인이다.
- `./agentcon check`: 기존 PostgreSQL 연결과 운영 보안 설정 검증 통과. 프로젝트의 8200/8400 리스너는 정지 상태다.

이제 프로젝트 폴더에서 `./agentcon start`로 시작한다. 이 실행기는 갱신된 비공개 환경 파일을 읽는다.

운영 전환 뒤 되돌려야 하는 경우 서버와 워커를 정지하고 현재 PostgreSQL 변경분을 포함하는 검증된 `rollback_activation(..., capture_changes=True)` 절차 및 새로운 명시적 승인으로 진행한다. SQLite 설정만 되돌리는 방식은 원본 쓰기 차단 장치 때문에 허용되지 않는다.

근거: `postgres-cutover-summary.json`, `postgres-cutover-verification.json`, `final-load-and-indexes.json`, `cutover-final-all.xml`, `cutover-large-resource-regression.xml`, `cutover-search-admin-final.xml`, `cutover-large-resource-security.xml`, `cutover-security-review.json`.
