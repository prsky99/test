# A2A Discovery — Claude 작업 안내

AI 에이전트(A2A)·MCP 서버·x402 유료 API를 키 없이 수집·헬스체크·평가하고, 요청한 에이전트에게 가장 좋은 것을 소개·재소개하는 게이트웨이. 사용자 문서는 한국어, 에이전트가 읽는 텍스트(사용 안내·프론트 응답)는 영어.

## 구조 (세부는 README.md와 각 문서)
- `agent_market/collector/`: 수집 에이전트
  - `agent.py`: 루프
  - `health.py`: 헬스체크
  - `capabilities.py`: MCP 도구 조사·시험 호출
  - `auth_discovery.py`: 인증 방법
  - `usage.py`: 사용 안내
  - `evaluation.py`: 품질 평가
  - `a2a.py`: A2A 조사
  - `registries.py`: ERC-8004·well-known 수집
  - `server.py`: 조회 API :8300
- `agent_market/gateway/`: 게이트웨이 :8200
  - `store.py`: SQLite·FTS5
  - `classify.py`: 14개 카테고리 분류
  - `ranking.py`, `service.py`
  - `dashboard.*`: 관리 화면 `/admin/ui`
  - `sns.py`
- `agent_market/concierge/`: 에이전트 전용 프론트 :8400 (영어 전용, 로컬 LLM은 선택)
- `agent_market/broker/`: 카테고리 정의(`categories.py`), SSRF 검사(`discovery.check_public_url`)
- 결제·지갑: `payments.py`, `chain.py`, `wallet.py`, `buyer.py` (x402, USDC on Base)
- 문서
  - `COLLECTOR.md`: 수집·평가·A2A, 실측
  - `AGENT_BROKER.md`: 카테고리·요청 조건
  - `AGENT_FRONT.md`, `AGENT_MARKET.md`, `deploy/DEPLOY.md`
  - `reports/`: 조사 보고서

## 실행·테스트
```bash
.venv-tests/bin/python -m pytest -q    # 전부 통과해야 커밋
COLLECTOR_DB=gateway-data/collector.sqlite3 .venv/bin/python -m agent_market.collector.server
GATEWAY_DB=gateway-data/collector.sqlite3 .venv/bin/python -m agent_market.gateway.server
```
- 시험은 `.venv-tests`로 돌린다. `.venv`에는 pytest가 없다(11-02 확인).
  - 정적 검사: `.venv-tests/bin/python -m pyflakes agent_market tests` (11-02 설치, `requirements-dev.txt`). 경고 약 3,700건은 대부분 쓰지 않는 import다. 정의되지 않은 이름은 `tests/test_pyflakes_undefined_names.py`가 막는다.
- frontend 릴리스는 배포 전에 `.venv-tests/bin/python -m scripts.release_gate <release>`로 사본 시험을 한다(`deploy/DEPLOY.md`).
- 이 맥은 운영 서버이기도 하다. 큰 테스트(전체 pytest, playwright)는 낮은 우선순위로 돌린다(사용자 결정 2026-11-02).
  - 예: `nice -n 10 .venv-tests/bin/python -m pytest -q`
  - 11-01에 여러 세션이 테스트를 동시에 돌려 CPU를 300% 쓰자, 탐색 서버 시간이 0.96초에서 2.59초(중앙값)로 늘었다.
- 수집 DB `gateway-data/`와 스냅샷 `exports/`는 git에 넣지 않는다.
- 실행 중인 수집기 끄기: `for p in $(ps -eo pid,args | grep "[p]ython -m agent_market" | awk '{print $1}'); do kill $p; done`
  - `pkill -f`는 쓰지 않는다. 자기 셸까지 죽인다.

## 규칙 버전 (바꾸면 올리기, 올리면 시작할 때 다시 처리됨)
- `gateway/classify.py` `VERSION`: 전체 재분류
  - 지금 5
  - agent_infra 정확도 회귀 테스트: `tests/test_classify_agent_infra.py`, 판정 데이터 `tests/data/agent_infra_labels.json`
- `collector/evaluation.py`
  - `VERSION`: MCP 재평가, 지금 5
  - `AGENT_VERSION`: A2A 재평가, 지금 4
- `gateway/store.py` `CONSTRAINTS_VERSION`: 언어·지역 다시 추출

## 지켜야 할 것
- 사용자 화면은 `docs/FRONTEND_SCREEN_POLICY.md`를 따른다(11-01 사용자 결정).
  - 고정 내용은 HTML로 바로 보인다.
  - 전체 화면 로딩, 가운데 팝업은 쓰지 않는다.
  - 로딩은 해당 영역에만 표시하고, 데이터는 사용자가 누를 때 불러온다.
  - 독립 요청은 병렬로 보낸다.
- 남의 서버에 자격 증명·결제를 보내지 않는다.
- 파괴적 도구는 호출하지 않는다. 시험 호출은 읽기 전용만.
- 사설 주소는 막는다(`check_public_url`).
- 저장소는 공개다. 키·지갑·`deploy/gateway.env`는 커밋하지 않는다.
- 개발 브랜치: `claude/hopeful-darwin-i3qj6n`
  - 사용자가 맥에서도 푸시한다.
  - 푸시 전에 `git fetch` 후 `git rebase`한다(남의 커밋을 덮어쓰지 않기).
- 새 기능에는 테스트를 붙이고, 실제 데이터로 한 번 돌려 본 뒤 문서(COLLECTOR.md 등)에 결과를 남긴다.

## 응답 시간 정책 (사용자 결정 2026-11-01, 모든 세션 적용)
- 프론트 탐색(Explore)
  - 목표: 검색어 입력, 체크 박스, 정렬·쪽 넘기기 등 어떤 검색 조작이든 3초 안에 결과를 표시한다. 처음 보는 조합도 포함한다.
  - 데이터는 실시간이 아니어도 된다. 주기적으로 갱신한 스냅샷·캐시로 답해도 된다.
  - 속도와 실시간성이 부딪치면 속도를 고른다. 요청 경로에 실시간 DB 재확인을 새로 넣지 않는다.
  - 홈 화면은 지금처럼 실시간 데이터를 쓴다.
- RAG(Chat 검색 답변): 5초 안에 답하고, 정확도 목표는 99%다.
- 복잡한 질문: 정확도 99%를 목표로 10초 안에 답한다. 매우 복잡한 질문은 15초 안에 답한다.
- 이 목표를 어기는 변경(예: 탐색 요청마다 실시간 검증 추가)은 하지 않는다. 필요하면 먼저 사용자에게 묻는다.
- 성능 변경은 처음 보는 검색어로 측정하고, 결과를 문서에 남긴다.

## 토큰 절약 작업 방식
`docs/claude/global-CLAUDE.md`의 6가지 규칙을 따른다(사용자 전역 `~/.claude/CLAUDE.md`와 같은 내용). 이 프로젝트에서 덧붙일 것:
- 작업 기록은 `WORKLOG.md`. 압축 뒤에는 이것부터 보고, 작업이 끝나면 몇 줄 갱신한다.
- 테스트는 바뀐 부분의 테스트 파일 먼저, 커밋 전에 전체 `pytest -q | tail -3`을 한 번.
- 수집 DB 조회는 집계(`count`, `group by`)로 보고, 행 덤프는 scratchpad 파일로.

## Compact instructions
압축할 때 남길 것:
- 진행 중인 작업과 다음 단계
- 최근 사용자 요청과 결정
- 실패했던 시도와 원인
- 실행 중인 프로세스
- 미커밋 변경

버릴 것: 이미 반영된 명령 출력, 표본 데이터, 끝난 조사의 세부 내용(보고서는 `reports/`에 있음).
