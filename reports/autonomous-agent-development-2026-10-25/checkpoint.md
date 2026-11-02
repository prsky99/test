# 자율형 Agent 첫 개발 범위 — 완료, 2026-10-25

요청: 통합 설계 개발 진행. 첫 범위(목적별 Entry/Workflow 목적·노드·한글 검색, Chat/MCP/A2A 추천, 안전한 세션 재방문) 구현·운영 반영 완료. 사용자 추가 교정: 모든 실행 결과 Edge 우선, Edge 사용 불가/실패 시 Origin만; 결과 크기로 정상 Origin 경로 선택 금지. Provider 점유 후 응답 손실은 중복 재실행 대신 receipt/회수 검토. 설계 문서/Canvas 반영. Worker 새 ingress/모든 결과 직접 전달 확장은 미구현 상태이며 완료 주장 금지.

제품 변경11파일: concierge/{workflow_discovery.py(new),agent_entry.py(new),front.py,fast_chat.py,mcp_contract.py,public_metadata.py}, extracted_html.txt, new/en/assets/operating.js, new/en/{index,chat,workflows}.html. 영어copy/escaped inputaliases, 두HTML동기. 기존추천A2A기본·selector·증거순서 유지. MCP기존11+search_workflows/workflow_details=13 단일factory. 기존 public_template 및 제품철회·권한검사재사용. 검색/상세/재방문Provider실행0·새실행권0. Workflow sentinel에기존last_results사용; 잘못된Providerfeedback 방지. 전체Passport아님.

검증: affected-api-tests-final192pass/기존OpenAPI경고1, browser-security19pass, actualstagedfrontend97pass(브라우저포함)/admin78pass(중복합산금지), content265/0, JSsyntax/Pythoncompile/HTMLsync. 신규signedproduct철회검사 포함. 초기expect목록실패는2도구추가로기대갱신; 초기철회fixture는다른defaulttemplates격리해해결. Chrome초기샌드박스2setup오류는격리권한실행으로해소. Bandit미설치.

배포: 기존Frontend/Admin AB승인으로최신각rolebase에reviewed11개파일만3waymerge. Frontend1202/Admin1190 unrelatedmanifest보존. active agent-discovery-frontend-20261025-085641 및 agent-discovery-admin-20261025-085641, previous retained. Jobs/ExecutionPID+release동일. Worker/Route/Secrets/DDL변경0. 최종active상태다시확인완료.

운영: Entry5actions/1474bytes, MCP13manifest parity, papers2/나라지표3/영어뉴스논문Workflow1 검색과공개현재hash확인. ComputerUse Browse templates->papers 실제2카드확인. 다른작업으로템플릿늘어현재개수가8로변했지만전체수량고정주장안함. 검증Provider0/Workflow실행0/결제0. 원본 live-verification.json/browser-live-evidence.json.

README.md에범위·테스트·운영·남은단계정리. 기존방문검토는개발전기록notice추가, designREADME·manifest·Canvas는부분구현state로갱신(전체32개완료아님). Canvas2개esbuildpass. 기존Provider캠페인/soak/readonlyautomation미변경.

남은전체설계: 모든결과Edge직접반환MCPingress/SDK/Task, 다중작업Passport/cursor/compact8-tool profile, 승인Taskprepare/run/status/cancel·부분결과·receipt·구독위임, Registry게시·SDK·holdout·기존heapCPU24h검증. 다음범위는Edge우선사용자정책기준으로계속개발할수있음. 현재첫범위최종전달만남음. 재배포/검사반복불필요.
