# 첨부 전략 분석 기반 개선 설계 · v2.0

2026-10-25 · 문서/검토 자료 작성 · 제품 구현·운영 변경 없음

v2는 관련 소스 21개·논문 9편·공식 기술 문서 1개·SNS 논의 4건을 대조했다. 잠재 위험/보존할 방어 14개와 후속 실험 8개를 기존 IMP-01~08에 연결했다. 소스 확인·순수 함수/메서드 표본·운영 미측정을 구분한다.

- [상세 설계서](../../docs/AGENT_CONCIERGE_BUSINESS_PRODUCT_IMPROVEMENT_2026-10-25.md): 근거 검토, 포지셔닝, 공통 작업 계약, 품질·권한·실행·UX·수익화, 개선 검토 묶음과 수용 기준.
- [구조화 데이터](design-data.json): 핵심 주장 16개, 개선 검토 묶음 8개, 화면군 9개와 v2 위험·연구·실험. Canvas에 동일하게 포함.
- [연구 원장](research-ledger.json): 논문/문서/SNS의 적용 판단·한계·확인일. 논문 공개 초록/요약 중심이며 전 논문 본문 재현 아님.
- [소스 대조](source-review.json): 관련 파일의 선언 위치·내용 hash. 전체 저장소 감사 아님.
- [위험·실험](upgrade-plan.json): SR01~14·EX01~08·기존 IMP 연결. 후속 실험은 이번에 모두 실행한 결과가 아님.
- [격리 표본](offline-probes.json): 네 helper 표본·한 method-spy와 통계 계산. 전체 파이프라인·운영 장애 재현 아님.
- [문서 검증](verification.json): 로컬 참조, 근거 소스 fingerprint, 의존관계, Canvas 데이터 일치.
- [Canvas 검증](canvas-verification.json): TSX 문법 컴파일, 필터·선택·가정 계산의 컴포넌트 로직 확인. 실제 Canvas 호스트 렌더링 검증은 아님.

핵심 설계 변경은 filtered ANN/exact 비교, 선택 조건 전달, 실제 Fast Chat 경로, 업무 목표 검증, 연결 저장과 인증 실행의 구분, OAuth 만료/재연결, 현재 typed compiler와 증적/권한 gate의 재사용이다. 모델 16슬롯과 서비스 동시성을 같은 숫자로 취급하지 않는다.

Canvas: `~/.cursor/projects/Users-<user>-workspace-A2A_Discovery/canvases/agent-concierge-business-product-improvement-2026-10-25.canvas.tsx`

기존 마감·승인·보류를 덮어쓰지 않는다. `IMP-01~08`은 새 실행 대기열이 아니라 현행 기능과 대조할 검토 ID다. 후속 구현은 차이와 승인 범위를 확정한 뒤 기존 계획에 편입한다.

시장 전망·보도·공급자 사례는 실제 고객 성과와 분리했다. 업무 성공률·지연·첫 가치 목표와 단위 경제성은 제안/가정이며 현재 실적이 아니다. 사용자 제공 Chat 지침과 저장소 현행 정책의 차이는 설계 6.3에 별도 기록했다.
