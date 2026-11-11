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
- 팀 사이 조율은 `logs/ops/status-board.md`(운영 현황판)로 한다(11-10 사용자 결정).
  - 작업·배포 전에 읽는다.
  - 운영 중인 버전, 배포 잠금, 고치는 파일, 넘기는 일을 여기에 적는다.
  - 세션 메시지는 결정·승인·긴급, 그리고 과제를 끝냈을 때의 PM 보고에 쓴다.
  - 팀 세션은 과제를 끝내거나 막히면 현황판 자기 줄을 고치고 PM 세션 `프론트앤드`에 한 번 보고한다(11-10 사용자 지시).
    - 사용자에게 직접 묻지 않는다. 승인이나 사용자가 할 일은 PM이 모아서 묻는다.
    - 보고한 뒤 다음 과제로 넘어간다. 할 일이 없거나 PM 결정만 남았으면 "대기"로 보고하고 멈춘다.
- 운영 DB 구조 변경(표·인덱스·트리거·함수·마이그레이션 도구)은 아래 순서를 지킨다(11-10 05:38 트리거 장애, `deploy/DATABASE_OPERATIONS.md`).
  1. `scripts.db_change_rehearsal run`으로 사본에서 운영 버전 연결까지 통과시킨다.
  2. 복구 SQL을 준비한다.
  3. 사용자 승인을 받는다.
  4. 실행 직전 `check`가 0이 아니면 실행하지 않는다.
- 저장소는 공개다. 키·지갑·`deploy/gateway.env`는 커밋하지 않는다.
- GitHub은 외부 유입 채널로 쓰지 않는다(사용자 결정 2026-11-10 "깃허브 공개하지 않음"). 다음은 하지 않는다.
  - 소개용 저장소 만들기
  - README 홍보
  - awesome 목록 PR
  - 저장소 이름 바꾸기
- 지출은 0이다(사용자 결정 2026-11-10 "수익이 발생하지 않은 상태에서 지출 없음"). 유료 등록·광고·유료 플랜·가스비·유료 API는 쓰지 않는다. 무료 경로만 쓴다.
- 수익과 지출은 코인으로만 한다(사용자 결정 2026-11-10, 11-11 갱신).
  - 달러·원화 같은 법정화폐로는 거래하지 않는다.
  - **11-11 사용자 결정: 운영비를 위해 수익 먼저, USDC on Base로 광고 상품값을 받는다.** 예약 1건 = 결제 1건이다.
    - 하지 않는 것: 선충전 잔액, AD Coin 판매·전환, 고객 자산 보관, 환전, 송금 대행, 자동 송금, ETH 등 다른 코인으로의 전환.
    - 서버는 받기만 한다. 받는 지갑의 개인키는 서버에 두지 않는다. 환불 송금은 사용자가 직접 한다.
    - 무료 안전장치를 둔다: 제재 주소 대조, 결제마다 원화 환산과 거래 해시 기록(월별로 내보내기).
    - 결제 스위치는 사용자 승인 뒤에만 켠다. 출시 가격은 하루 1칸 5 USDC다.
    - 법률·세무 자문과 신고는 수익이 커진 뒤에 한다(사용자 결정). 정기 세금 신고용 기록은 처음부터 남긴다.
  - AD Coin은 무상 크레딧이자 내부 관리 단위다. 유료(USDC) 장부와 섞지 않는다. AD Coin으로 생긴 수익은 성장을 위해 언제든 쓸 수 있다.
  - 경계(헌장 1절): AD Coin을 돈이나 코인을 받고 팔거나, 돈으로 바꾸거나, 법정화폐와 교환하는 경로는 만들지 않는다. 광고 상품을 USDC로 파는 것은 이 경계 밖이다(11-11).
  - 지갑의 USDC 같은 실제 자산 송금은 이 결정에 들어가지 않고 사용자가 직접 한다.
- x402는 실제 결제 시험이 가능할 때까지 수집하지 않는다(사용자 결정 2026-11-10).
  - 실제 시험 조건: x402 결제에 쓰는 USDC(AD Coin 아님) 보유량이 10만 이상일 때, 보유량의 1/1000만 쓴다. USDC 지출은 그때 사용자 승인을 따로 받는다.
  - 그 전에는 연결 확인만 한다. 수집은 A2A와 MCP만 한다(`COLLECT_X402=0`이 기본값).
  - x402 자원 등급은 B가 상한이다(품질 정책 v2). 결제 없는 402 응답은 전송 증거다.
- 로그 오류와 엣지 게이트웨이의 오류·실패는 생기면 바로 고친다(사용자 결정 2026-11-10).
  - 직접 해결이 안 되면 논문과 SNS(GitHub issues, Reddit, HN, X, 공식 포럼)를 검색해 해결한다.
  - 운영·SRE 팀의 상시 임무다.
- 외부 등록의 연락 메일은 사이트에 공개된 `contact@agentconcierge.biz`를 쓴다(11-10).
- 일이 느려도 멈추지 않는다(11-10). 팀은 과제를 끝내면 다음 과제를 스스로 골라, 목표를 향해 조금씩이라도 계속 진행한다.
- 배포는 상시 승인이다(사용자 결정 2026-11-10 "배포에 대해서는 무조건 승인함").
  - 범위: frontend·admin·jobs·execution
  - 조건: 게이트를 통과하고 활성 판 위에 겹쳐 만든 릴리스면 묻지 않고 배포한 뒤 결과를 보고한다.
  - 팀 세션이 운영 배포를 막히면 총괄 PM 세션이 base와 diff를 확인하고 대신 배포한다.
  - 계속 먼저 묻는 것: DB 스키마·함수 변경, DB 재시작, 데이터 삭제, 외부 게시, 지출, 게이트 실패 배포.
- 개발 브랜치: `claude/hopeful-darwin-i3qj6n`
  - 사용자가 맥에서도 푸시한다.
  - 푸시 전에 `git fetch` 후 `git rebase`한다(남의 커밋을 덮어쓰지 않기).
- 새 기능에는 테스트를 붙이고, 실제 데이터로 한 번 돌려 본 뒤 문서(COLLECTOR.md 등)에 결과를 남긴다.

## 응답 시간 정책 (사용자 결정 2026-11-10 18시 상향, 11-11 19시 추천·페이지 재상향, 모든 세션 적용)
- 목표(사용자 기준)
  - 탐색: 2초 안에 결과 표시, 결과 0건 없음
  - 추천(Chat·find_agents·A2A): 2초 안 (11-11 19시, 이전 3초)
  - 페이지(공개 화면 응답): 1초 안 (11-11 19시, 이전 2초)
  - 복잡한 답변: 5초 안
  - 품질 목표는 100%다. 품질은 실제로 연결해 과제를 할 수 있는 비율로 잰다.
- 측정(11-10 사용자 지적 "캐시에 저장돼서 다음엔 빠릅니다, 목표 달성" 금지)
  - 공개 주소에서, 처음 보는 질의로, 새 연결에서, 결과를 받을 때까지 잰다. 표본은 빼지 않는다.
  - 내부 수치(쿼리 하나, 서버 안 시간)는 목표 달성의 근거가 아니다. 쓸 때는 "내부 수치"라고 밝힌다.
  - 기준 측정은 `scripts/user_slo.py`(매시간, logs/ops/user-slo.jsonl)다. 미달이면 현황판에서 담당 팀으로 넘긴다. 한국에서 잰 값은 그렇다고 표시한다(Cloudflare 무료 플랜의 LAX 경유).
- 데이터는 실시간이 아니어도 된다. 스냅샷과 캐시로 답해도 되지만, 처음 보는 질의도 목표 안이어야 한다.
- 속도와 실시간성이 부딪치면 속도를 고른다. 요청 경로에 실시간 DB 재확인을 새로 넣지 않는다.
- 목표를 어기는 변경은 하지 않는다. 필요하면 먼저 사용자에게 묻는다.

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
