# topic-evidence-brief 공개 실행 순서서 (11-17, 워크플로우 작성 11-16)

PM 11-16 15:42 지시. 2회차 판정이 나온 순간부터 공개까지의 단계를 정리했다. 근거 문서는 `deploy/NECKLACE_GATE.md`(1절 관문 기준·회차 제외 규칙, 5절 판정 기록, 6절 메뉴 적용, 7절 공개 뒤 재시험)다.

- 대상: topic-evidence-brief, 지금 정의 버전(v1). 판정 뒤 web 두 번째 멤버를 넣은 새 버전은 이 순서서 밖이고, 새 관문을 따로 돈다.
- 회차: 1회차 06:00, 2회차 10:00(4시간 간격). 회차 명령은 운영·SRE가 정한 split으로 `retest topic-evidence-brief --split <split> --system gate`로 돌린다.
- 시각은 모두 KST다. 명령은 저장소 루트에서 `.venv/bin/python`으로 실행한다.

## 0. 회차가 끝날 때마다 (1·2회차 공통)

| 단계 | 담당 | 명령 | 되돌리기 |
|---|---|---|---|
| 0-1 회차 결과 보기 | 운영·SRE | `scripts/gate_round.py status topic-evidence-brief --split <split>` | 읽기만 함 |
| 0-2 제외가 있으면 10~60분 사이에 다시 재기 | 운영·SRE | `scripts/gate_round.py rerun topic-evidence-brief --split <split>`(회차에 준 옵션을 똑같이) | 다시 재지 않음. 판정은 첫 줄 기준이라 되돌릴 것이 없음 |
| 0-3 결과 파일 확인 | 운영·SRE | `logs/ops/necklace-gate/round-topic-evidence-brief-v1-<split>-*.json`의 `verdict`, `warning` | — |

- `verdict`는 `pass`, `fail`, `unmeasured`, `rerun_due`(아직 다시 재지 않음), `incomplete`(30건 미만 측정, 판정 아님) 중 하나다.
- `warning`(같은 사례 두 번 측정)이 있으면 판정 전에 원인을 현황판에 적는다. 판정은 첫 줄 기준 그대로 쓴다.

## 1. 2회차까지 통과했을 때 (두 회차 모두 `pass`)

| 단계 | 담당 | 명령·할 일 | 되돌리기 |
|---|---|---|---|
| 1-1 관문 나머지 기준 확인 | 운영·SRE | 합계 57/60, Δ>0(전체·같은 역할), 완주율 57/60, p95 ≤ 5초, 보안 4항목, 지문. 판정 파일 `logs/ops/necklace-gate/topic-evidence-brief-v1.json`과 장부 한 줄 | 하나라도 미달이면 2절 실패 갈래 |
| 1-2 공개 승인 | 운영·SRE | `gateway-data/necklaces/approvals.json`에 `{slug, version: 1, definition_digest, gate_record, state: "approved", at}`를 원자적 교체로 추가 | 같은 항목 `state: "revoked"` → 다음 판정 주기에 `held` |
| 1-3 메뉴 반영 | 워크플로우(jobs 작성기) | `necklaces.json` 작성기가 승인·버전·digest가 맞으면 `status: live`를 씀. 다음 주기를 기다리거나 jobs의 necklaces 단계를 한 번 돌림 | 운영·SRE가 `necklaces.json` 항목을 `held`로 원자적 교체 |
| 1-3a 측정값을 스냅샷으로 | 운영·SRE·워크플로우 | 승인 뒤 다음 매일 요약과 judge(`python -m agent_market.necklaces.judge`)가 돌면, 지난 7일 case 줄(관문 회차 포함)의 `value`가 `necklaces.json` topic 항목의 `comparison`(with와 without의 calls·tokens·seconds·accuracy, 사례 수, 측정 날짜)으로 들어감. 항목에 `comparison`이 null이 아닌지 확인. null이면 요약 단계를 한 번 돌린 뒤 judge를 다시 돌림 | 승인을 `revoked`로 하면 comparison도 빠짐 |
| 1-4 화면·안내 반영 | 성장·유통 | 메뉴 카드, `/necklaces/topic-evidence-brief`, 에이전트용 안내(MCP 도구 목록). 표면 코드가 운영에 이미 있으면 배포 없음. 없으면 frontend(+jobs) 상시 승인 배포(`--no-prune`) | 직전 frontend 버전으로 배포 |
| 1-5 폴백·자체 대체 점검 | 워크플로우 | 자리마다 사슬 확인: `scripts/necklace_gate.py check topic-evidence-brief`(멤버 상태·지문·약관). 자체 대체(wiki-grounding, arxiv-search, wikipedia-summary, gdelt-news)의 승인 상태는 approvals `substitutes`로 확인 | 문제 멤버는 watch가 제외. 필수 자리가 비면 보류(7절) |
| 1-6 공개 주소 확인 | 운영·SRE | 공개 주소·새 연결로: 메뉴와 상세 페이지 200, MCP 도구 목록에 목걸이 도구, 처음 보는 주제로 실제 실행 3건(`X-Agentcon-QA`). 대량 요청 금지(이 맥 IP 차단 위험) | 실행 실패면 1-2를 `revoked` |
| 1-7 감시 등록 | 운영·SRE·워크플로우 | live 목걸이는 jobs의 공개 재시험(03:10~03:48)과 매시 watch에 자동으로 들어감. `gateway-data/necklaces/watch/state.json`에 slug가 보이는지, 다음 매시 watch 줄이 생기는지 확인 | — |
| 1-8 기록 | 운영·SRE | 현황판 '운영 중인 버전' 칸에 한 줄. PM에 보고 | — |

- 홍보 문구(토큰 절약·속도·정확도)는 관문에서 잰 값만 쓴다. 재지 않은 숫자는 쓰지 않는다.
- 관문이 실제로 재는 것과 재지 않는 것(PM 15:47 질문, `agent_market/necklaces/value.py`)
  - 잼: 목걸이 쪽 호출 1회, 걸린 시간(요청부터 답까지), 정답 여부(채점기).
  - 같은 실행에서 계산함: 목걸이 없는 쪽의 호출 수(실제로 보낸 멤버 호출), 시간(같은 단계 멤버 시간 중 최댓값의 합), 문자 수.
  - 따로 재지 않는 것
    - 토큰: 실제 토크나이저가 아니라 문자 수 ÷ 4 추정이다. 화면에 "추정"으로 밝히거나 비워 둔다.
    - 목걸이 없는 쪽의 정확도: 따로 실행하지 않는다. "목걸이가 맞았고 모든 필수 자리를 첫 멤버가 답했다"로 대신한다. 단일 기준선(singles)은 회차에 `--singles`를 줄 때만 잰다.
    - 찾기·합치기 비용(`without_full`의 find_agents·tools_list): 추정값이고 `estimated`로 표시된다. 검색과 RAG가 실측하기 전까지 화면에 쓰지 않는다.
  - 공개는 이 빈칸 때문에 늦추지 않는다. 없는 숫자는 비워 둔 채 공개하고, 공개 뒤 따로 잰다.

## 2. 실패했을 때 (어느 회차든 `fail`)
- 공개하지 않는다. 판정 파일과 장부에 `fail`과 이유를 적고, 현황판 '넘기는 일'에 워크플로우 앞으로 남긴다.
- 워크플로우가 실패 사례를 보고 고친다(정의·멤버·채점). 고친 뒤에는 **새 holdout**으로 1회차부터 다시 돈다(1절 규칙 5).
- 1회차가 실패면 2회차는 돌리지 않는다(같은 버전으로는 통과할 수 없음).

## 3. 측정 불가일 때 (`unmeasured`)
- 공개하지 않는다. 판정은 '측정 불가'로 적고, 오답과 섞어 보고하지 않는다.
- 원인(장부 몫, 중계 속도, 우리 용량, 제공자 멈춤)을 현황판에 적는다.
- 정의·하네스·멤버·대체 에이전트 코드가 그대로면 같은 holdout을 **새 split 이름**(`<split>-b`)으로 다시 돈다. 하나라도 바뀌었으면 새 holdout을 쓴다.
- 1회차가 측정 불가이고 2회차가 통과여도 공개하지 않는다. 1회차를 `-b`로 다시 재서 통과해야 한다(4시간 간격은 지금 계산 그대로).

## 4. 아직 판정이 아닐 때 (`incomplete`, `rerun_due`)
- `incomplete`: 회차가 멈췄거나 도는 중이다. 원인을 보고, 이어서 돌리지 않는다. 같은 split에 줄을 더하면 첫 줄만 세므로, 다시 돌릴 때는 `-b`를 쓴다.
- `rerun_due`: 0-2를 한다. 60분이 지나면 다시 재지 않으며, 제외 사례는 통과로 세지 않는다.

## 5. 공개 뒤 첫날
- 공개 재시험(03:10~03:48)이 95% 아래면 2시간 안에 한 번 더 돈다. 두 번째도 95% 아래면 운영·SRE가 보류한다. 즉시 보류 조건(보안 실패, 지문 변경, 80% 미만, 쓰기·결제 도구 발견)은 7절 그대로다.
- 판정 뒤(r11) 넣을 변경: 지문 보류 완화, web 출력 어댑터 연결, 정답 세트 주소 검사, 276982 제거. 정의를 바꾸는 것(web 두 번째 멤버, 276982 제거)은 새 버전이라 공개 중인 v1과 따로 새 관문을 돈다. 그사이 공개는 v1로 한다.
