# topic-evidence-brief 공개 실행 순서서 (11-17, 워크플로우 작성 11-16)

PM 11-16 15:42 지시. 2회차 판정이 나온 순간부터 공개까지의 단계를 정리했다. 근거 문서는 `deploy/NECKLACE_GATE.md`(1절 관문 기준·회차 제외 규칙, 5절 판정 기록, 6절 메뉴 적용, 7절 공개 뒤 재시험)다.

- 대상: topic-evidence-brief, 지금 정의 버전(v1). 판정 뒤 web 두 번째 멤버를 넣은 새 버전은 이 순서서 밖이고, 새 관문을 따로 돈다.
- 회차: 1회차 06:10, 2회차 10:10(4시간 간격, PM 승인: 정각 측정과 겹치지 않게). 현황판 리허설 전용 창 06:10~07:50·10:10~10:50이라 회차 명령은 heavy_slot을 거치지 않고 직접 돌린다(heavy_slot이면 이 창에 막힘). 회차 명령은 운영·SRE가 정한 split으로 `retest topic-evidence-brief --split <split> --system gate`로 돌린다.
- 시각은 모두 KST다. 명령은 저장소 루트에서 `.venv/bin/python`으로 실행한다.

## 0. 회차가 끝날 때마다 (1·2회차 공통)

| 단계 | 담당 | 명령 | 되돌리기 |
|---|---|---|---|
| 0-1 회차 결과 보기 | 운영·SRE | `scripts/gate_round.py status topic-evidence-brief --split <split>` | 읽기만 함 |
| 0-0 회차 명령 | 운영·SRE | split: 1회차 `holdout-r3`(37건 중 파일 앞 30건), 2회차 `holdout-r5`(PM 17:36 확정, 빌더가 고정 순서 앞 30건만 만듦). `--limit`은 주지 않음(기본 30). 1회차는 `--singles`, 2회차는 단일 없이(11-17 몫). 단일은 papers 외부 멤버 4곳을 과제 전체로 채점함(6a83390d). 본 실행에서 이미 불린 34550·34807은 같은 사례의 답을 다시 써서(CaseAnswers.wrap(reuse=True)) 새 호출이 없고, 새로 불리는 것은 39577·47151뿐. **1회차 single 줄의 `reused` 값으로 재사용을 확인하고, 0이면 바로 워크플로우에 알림** | — |
| 0-2 제외가 있으면 10~60분 사이에 다시 재기 | 운영·SRE | `scripts/gate_round.py rerun topic-evidence-brief --split <split>`(회차에 준 옵션을 똑같이) | 다시 재지 않음. 판정은 첫 줄 기준이라 되돌릴 것이 없음 |
| 0-3 결과 파일 확인 | 운영·SRE | `logs/ops/necklace-gate/round-topic-evidence-brief-v1-<split>-*.json`의 `verdict`, `warning` | — |

- 단일 줄(type single)은 회차 판정에 들어가지 않는다. `gate_round`는 case와 excluded 줄만 센다.
- 몫 메모(운영·SRE와 정함, PM 승인 대기): 11-17 gate 보류 cutgpt 60, openkrill 60(본 실행 두 회차), nobleblocks 35, caseyjhand 40(1회차 단일 30과 폴백 몇 회).
- 시간: 사례당 중계 요청은 본 실행 8(web 0, papers 2, background 1, news 1, 각 2회)에 단일 4를 더해 12다. 중계 분당 9회라 1회차는 약 40분(06:10~06:50)이고, 다시 재기는 07:10~07:50(:55~:10은 gate_round가 스스로 피함)이다. 2회차는 단일 없이 약 30분(10:10~10:40), 다시 재기는 10:50~10:55·11:10~11:40이다. 밤 세트 만들기는 06:00~08:00·10:00~12:00에 쉰다.
- `verdict`는 `pass`, `fail`, `unmeasured`, `rerun_due`(아직 다시 재지 않음), `incomplete`(30건 미만 측정, 판정 아님) 중 하나다.
- `warning`(같은 사례 두 번 측정)이 있으면 판정 전에 원인을 현황판에 적는다. 판정은 첫 줄 기준 그대로 쓴다.

## 1. 2회차까지 통과했을 때 (두 회차 모두 `pass`)

| 단계 | 담당 | 명령·할 일 | 되돌리기 |
|---|---|---|---|
| 1-1 관문 나머지 기준 확인 | 운영·SRE | 합계 57/60, Δ>0(전체·같은 역할), 완주율 57/60, p95 ≤ 5초, 보안 4항목, 지문. 판정 파일 `logs/ops/necklace-gate/topic-evidence-brief-v1.json`과 장부 한 줄 | 하나라도 미달이면 2절 실패 갈래 |
| 1-2 공개 승인 | 운영·SRE | `gateway-data/necklaces/approvals.json`에 `{slug, version: 1, definition_digest, gate_record, state: "approved", at, gate_splits: [<1회차 split>, <2회차 split>]}`를 원자적 교체로 추가. `gate_splits`가 있어야 r11 전에 쓴 회차 줄이 측정값(value)에 들어감 | 같은 항목 `state: "revoked"` → 다음 판정 주기에 `held` |
| 1-2a 정의 status live | 워크플로우·운영·SRE | judge는 정의 파일 status가 live/held/retired일 때만 공개 항목을 만듦(judge.build_entry). 미리 만든 ref `workflow/topic-live-1117`(67dd6080, status만 candidate→live, digest 밖이라 승인 digest 그대로)를 **통과했을 때만** r11에 넣어 jobs·frontend 배포. 실패·측정 불가면 넣지 않음 | status를 candidate로 되돌리는 커밋·배포 |
| 1-3 메뉴 반영 | 워크플로우(jobs 작성기) | `necklaces.json` 작성기가 승인·버전·digest가 맞으면 `status: live`를 씀. 다음 주기를 기다리거나 jobs의 necklaces 단계를 한 번 돌림 | 운영·SRE가 `necklaces.json` 항목을 `held`로 원자적 교체 |
| 1-3a 요약·측정값을 스냅샷으로 | 운영·SRE·워크플로우 | 순서: ① r11 배포 확인(value 거르기: 지금 정의 버전의 관문 회차·다시 재기·공개 뒤 매일 재시험만) → ② `daily.run`을 손으로 한 번 실행(예약은 하루 한 번 05:20 뒤뿐이라 공개 당일에는 돌지 않음. 요약이 없으면 judge가 stale_retest로 보류) → ③ `python -m agent_market.necklaces.judge`. topic 항목의 quality(tested_at, delta_pp>0)와 comparison이 채워졌는지 확인. delta_pp는 회차를 `--singles`로 돌렸을 때만 생김(멤버당 같은 날 10쌍 이상). r11 배포 전에는 ②를 돌리지 않음 | 정의 status를 candidate로 되돌리는 커밋·배포, 또는 approvals `revoked` |
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
  - 공개는 이 빈칸 때문에 늦추지 않는다.
- 공개는 r11 배포에 묶인다(1-2a, 1-3a). 2회차 다시 재기가 11:40까지 갈 수 있어 판정과 r11 패키징은 그 뒤에 하고, 공개 시각은 12:30~13:30으로 본다(PM 16:14, 16:2x). 없는 숫자는 비워 둔 채 공개하고, 공개 뒤 따로 잰다.

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
- 공개 목걸이의 매일 재시험은 06~22시 가운데 정해진 한 시간에 5건이고, 하나라도 틀리면 그날 30건 전체를 돈다. 그날 성공률이 80% 아래면 다음 매일 요약과 judge에서 보류된다(`quality_low`). 즉시 보류 조건(보안 실패, 지문 변경, 쓰기·결제 도구 발견)은 NECKLACE_GATE 7절 그대로다. "95% 아래면 2시간 안에 다시 돈다"는 아직 구현되지 않았다.
- r11 워크플로우 묶음(PM 16:21 확정): topic status live(통과했을 때만, ref `workflow/topic-live-1117`), value 거르기(ref `workflow/r11-1117` 3363d228), 지문 보류 완화(e7ed586d), 정답 세트 주소 검사(53d7d67c). web 출력 어댑터 연결과 topic v2 정의(44568, 276982 제거)는 넣지 않는다: 44568·39422가 멤버+어댑터 평가 0/10이라 web 자리는 당분간 wiki-grounding 하나이고, 276982 제거는 진짜 두 번째 web 멤버가 생길 때 다음 정의 버전과 함께 한다.
