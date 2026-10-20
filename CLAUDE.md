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
.venv/bin/python -m pytest -q          # 전부 통과해야 커밋
.venv/bin/python -m pyflakes agent_market tests
COLLECTOR_DB=gateway-data/collector.sqlite3 .venv/bin/python -m agent_market.collector.server
GATEWAY_DB=gateway-data/collector.sqlite3 .venv/bin/python -m agent_market.gateway.server
```
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
- 남의 서버에 자격 증명·결제를 보내지 않는다.
- 파괴적 도구는 호출하지 않는다. 시험 호출은 읽기 전용만.
- 사설 주소는 막는다(`check_public_url`).
- 저장소는 공개다. 키·지갑·`deploy/gateway.env`는 커밋하지 않는다.
- 개발 브랜치: `claude/hopeful-darwin-i3qj6n`
  - 사용자가 맥에서도 푸시한다.
  - 푸시 전에 `git fetch` 후 `git rebase`한다(남의 커밋을 덮어쓰지 않기).
- 새 기능에는 테스트를 붙이고, 실제 데이터로 한 번 돌려 본 뒤 문서(COLLECTOR.md 등)에 결과를 남긴다.

## 토큰 절약 작업 방식 (한 세션을 오래 쓰므로)
- 명령 출력은 필요한 만큼만 본다.
  - `| tail -20`, `| head`, `grep -c`, `pytest -q | tail -3`
  - 큰 결과(DB 표본, 목록, 로그)는 scratchpad 파일로 쓰고 요약만 출력한다.
- 넓은 탐색·조사·대량 판정은 서브에이전트에 맡기고 요약만 받는다.
- 이미 읽은 파일을 다시 통째로 읽지 않는다. 필요한 부분만 `sed -n`이나 `grep -n`으로 본다.
- 답변은 짧게: 결과, 수치, 남은 문제만.
- 기다릴 때는 백그라운드 실행과 알림을 쓴다. 짧은 간격의 폴링 루프는 쓰지 않는다.

## Compact instructions
압축할 때 남길 것:
- 진행 중인 작업과 다음 단계
- 최근 사용자 요청과 결정
- 실패했던 시도와 원인
- 실행 중인 프로세스
- 미커밋 변경

버릴 것: 이미 반영된 명령 출력, 표본 데이터, 끝난 조사의 세부 내용(보고서는 `reports/`에 있음).
