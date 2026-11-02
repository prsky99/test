# 자율형 Agent 서비스 설계 — 완료

사용자 요청: 방문 검증의 공백을 기반으로 논문·SNS를 조사해 적극적 자율형 Agent 이용의 통합 설계. 범위 완료, 운영 구현·배포는 요청하지 않았고 수행하지 않음. 하위 Agent 사용 없음.

산출물: README.md(통합 설계·32개 핵심 방안에 대응하는 전체 여정), RESEARCH.md(논문5+공식7+SNS3), IMPLEMENTATION.md(기존 소스10개 통합 지점·신규 제안 API·Task·권한·Edge·Admin·평가·복구), discovery.schema.json, contract-examples.json, acceptance-cases.jsonl, design-validation.json, design-manifest.json. 빌드·검사 스크립트 포함.

검증: 설계 Schema 유효, 정상7/거부10의 합성 예시17 기대 일치, compact 예시 byte 한도·다음 동작·source labeling 확인, 인수 조건60개는 planned_not_executed이며 이름·범주·상태 검사. 기존 연결 소스 경로10개와 문서 내부 링크 확인. Canvas esbuild 번들 통과; UI 렌더 성공을 주장하지 않음.

핵심 결정: 빠른 lexical/규칙 경로+모호성 때만 확장; 현재 템플릿3개는 작은 색인+노드·동의어; 단일 Agent 추천의 A2A 기본·명시 selector·최신 성공/활동/등급 유지; 공통 Task Router와 작은 고정 MCP profile; Task Passport/의미 delta; 공개 저위험 정책은 익명 세션 실행 가능, Workspace·대체 Provider/비용 위임은 별도; prepare 무실행, unknown 무재시도, 7일 보존 한계 명시; Credit 작성 주기와 실행 비용·구독 권한 구분; Origin MCP wrapper가 결과 bytes를 통과시키는 사실 명시, direct Ticket/Worker ingress는 제안; MCP Tasks experimental·A2A 버전별 적합성 검사가 필요. 이전 heap/CPU·24시간 실패는 열린 출시 조건.

기간·95% 등 수치는 제안 목표이며 성과 아님. 핵심 여정2~3주/전체8~12주는 1인 범위 추정, 6단계 검증 게이트 우선. Provider 호출·운영 DB/설정·worker/process·서버·Registry 게시·외부 메시지 변경0. 기존 방문 보고서/자동화 untouched.

Canvas: ~/.cursor/projects/Users-kingstonelee-workspace-A2A_Discovery/canvases/agent-concierge-autonomous-service-design.canvas.tsx
남은 작업: 최종 전달. 후속 구현을 하려면 두 번째 단계의 Workflow 발견+첫 안내부터 진행할 수 있음. 현재 목표는 설계이며 구현 성과로 표현하지 말 것.
