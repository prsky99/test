# 생산 공정·계약·관문 (생산체계 문서 3·5·6절 원본, 워크플로우 팀 11-14)

README.md가 이 파일의 내용을 요약해 씁니다. 세부 규칙의 기준은 이 파일입니다.

## 1. 공정 9단계

| # | 단계 | 들어갈 것 | 나올 것 | 통과 기준 | 담당 |
|---|---|---|---|---|---|
| 1 | 수요 선정 | 수요 근거(조사 링크·검색어 기록·Chat 질의), 후보 과제군 | 목걸이 개요 1장(과제, 입력, 기대 출력, 왜 여러 출처인가) | 수요 근거 2개 이상(서로 다른 출처), 읽기 전용으로 풀리는 과제, 순차 의존이 자리 안에서만 생김 | 워크플로우(근거는 성장·유통 검색어 기록 참고) |
| 2 | 진주 자리 설계 | 개요 | 자리 목록, 자리별 역할 계약(`contracts/<role>.v1.json`: 입출력 스키마, 검증 규칙, 시험 입력 3개) | 필수 자리 2개 이상 또는 같은 역할 fan-out 2 이상, 자리 사이 데이터 의존 없음 | 워크플로우 |
| 3 | 진주·대체 배정 | 역할 계약, 진주 표(검색과 RAG), 같은 역할 묶음(Neo4j) | 자리별 사슬(주 → 외부 대체 여럿 → Agentcon 최대 2) | **자리 자격 시험**: 멤버마다 계약 시험 3건 모두 통과, 필수 자리마다 외부 2개 이상 + Agentcon 1개 이상, 주 진주는 엄격 기준 진주, 같은 등록 도메인·같은 원천은 한 장애 영역 | 워크플로우(판정), 검색과 RAG(진주 판정·실행 시험) |
| 4 | 조립 | 사슬, 합성 규칙 | 정의 파일(`definitions/<slug>.json`), 템플릿 워크플로우(비공개), 대체 정책 v2(shadow) | 정의 검증 통과(스키마·사슬 순서·Agentcon ≤2·읽기 전용 표시), 장애 드릴: 자리마다 1순위 강제 실패 → 다음 멤버로 완주 | 워크플로우 |
| 5 | 정답 세트 시험(자체) | 정답 세트 90건(조정 30 + 보류 60, 2절) | 시험 결과 JSONL, Δ·완주율·지연·비용·보안 | **4절 품질 관문 전부**. 보류 세트는 조정에 쓰지 않음 | 워크플로우 |
| 6 | 출시 관문 검수 | 넘김 묶음(5절) | 검수 판정, 프론트엔드 워크플로우 메뉴 적용 | 운영·SRE가 같은 묶음을 공개 주소·새 연결로 다시 재서 **품질 95% 이상** 확인 | 운영·SRE |
| 7 | 공개·홍보 | 메뉴에 오른 목걸이, necklaces.json `live` | MCP 도구·A2A 기술·웹 페이지, 홍보 | 표면 계약 3절(Δ > 0, 진주 2개 이상, 재시험 48시간 안) | 성장·유통 |
| 8 | 매일 재시험 | 공개 목걸이, 사슬 전체 | `retest/<date>.jsonl` | 실행 성공·지문 변경 기록 | 운영·SRE(인프라·지문) |
| 9 | 교체·보류·폐기 | 재시험 결과, 지문 변경, 보안 경보 | 사슬 정비, held 전환, 새 버전, 폐기 | 6절 규칙 | 워크플로우(판단) |

생산량 목표
- 11-14~11-28(2주): 수요 후보 15 → 자리 설계 10 → 조립 7 → 관문 제출 5 이상 → 공개 5
- 11-29~12-26(4주): 주당 수요 후보 8 → 조립 5 → 공개 4(누적 20)
- 하루 단위: 자리 자격 시험 2목걸이, 정답 세트 시험 1목걸이(정답 90건 × (목걸이 1 + 단일 진주 n) 호출을 2~3일에 나눔, 같은 호스트 동시 1)
- 버리는 비율을 기록합니다(조립 → 공개 통과율). 이 비율이 50% 아래면 1단계 기준을 다시 봅니다.

## 2. 정답 세트

- 목걸이마다 두 세트를 둡니다(선택 편향 방지, 2407.01502·2507.02825).
  - **조정 세트 30건**: 자리·사슬·합성 규칙을 고르고 고칠 때 씁니다.
  - **보류 세트 60건**: 관문 판정에만 씁니다. 조정에 쓰지 않고, 파일도 `gold/<slug>/holdout.jsonl`로 따로 둡니다. 분기마다 새 문항으로 바꿉니다.
- 구성: 절반 이상은 같은 역할 대조 과제(단일 진주 대 fan-out)이고, 나머지는 여러 측면 과제입니다. 여러 측면 과제만으로는 Δ가 저절로 커지므로 섞습니다. 단일 진주가 이미 90% 넘게 맞히는 과제만 모이면 Δ 유의성을 보일 수 없으니, 출처마다 빠지는 항목이 있는 과제(재현율 과제)를 넣습니다.
- 정답 원천: 공개 원천(OSV, NVD, CISA KEV, World Bank, ECB, Open-Meteo, Crossref·OpenAlex, 정부 면허 기록 등)을 만든 날 받아 **고정 스냅샷**으로 저장하고, 만든 날짜와 원천 URL을 기록합니다. 시간에 따라 바뀌는 정답(날씨·환율·뉴스)은 실행 시각에 같은 원천을 함께 받아 비교합니다.
- 채점: 결정적 검증(값·id·날짜·HTTPS)을 우선합니다. 열린 답(관련성)만 LLM 채점을 씁니다. 그 채점기는 사람 판정 30건과 80% 이상 일치해야 쓰고(2306.05685), 운영 중에도 20%는 사람이 확인합니다. LLM 채점은 Anthropic 키 하루 4달러 상한 안에서 씁니다.
- 반복 신뢰도: 보류 세트 중 10건은 3번씩 돌려 pass^3를 기록합니다(τ-bench 2406.12045). 한 번 성공률이 0.95여도 3연속 성공 확률은 0.857입니다.
- **통계(Wilson 95% 하한, CLT 구간 금지 2503.01747)** — 공개 화면은 "검증된 95%"를 누적 110건 중 실패 1건 이하일 때만 쓰고, 그 전에는 실제 수치("29/30 passed on 11-20")만 씁니다(PM 07:5x)

| 결과 | 하한 |
|---|---|
| 29/30 | 83.3% |
| 57/60 | 86.3% |
| 60/60 | 94.0% |
| 99/100 | 94.6% |
| 109/110, 196/200 | 95.0% |

  - 관문 한 번(60건)으로는 "하한 95%"를 증명할 수 없습니다. 그래서 둘로 나눠 적습니다.
    - **출시 관문(점추정)**: 보류 60건을 4시간 간격 30건씩 두 번, 합계 57건 이상(95%)이고 각 회 28건 이상(PM 07:5x).
    - **품질 주장(하한)**: 공개 뒤 매일 재시험을 누적해 110건 중 실패 1건 이하(하한 95%)가 되면 공개 화면에 "검증된 95%"를 씁니다. 그 전에는 측정값과 하한을 그대로 보여 줍니다. 하한이 90% 아래로 내려가면 보류 조건(6절 4번)입니다.
- **Δ 유의성**: 같은 문항으로 목걸이와 최고 단일 진주를 짝지어 정확 McNemar 검정을 합니다(2411.00640). 관문은 Δ > 0입니다. 유의 여부(양측 p < 0.05)는 공개 수치 옆에 표시하고, 유의하지 않으면 "Δ +n%p (유의하지 않음)"로 씁니다. 참고로 단일 진주만 맞힌 문항이 0개일 때, 목걸이만 맞힌 문항이 6개 이상이어야 유의합니다(1개면 8개, 2개면 10개).
- 남의 서버 부하: 보류 60건 × (목걸이 1 + 단일 기준선 n)회를 하루에 몰지 않습니다. 같은 호스트에는 동시 1건, 60초 간격, 하루 상한을 두고, 429가 오면 그날 그 호스트를 멈춥니다(검색과 RAG 실행 시험 규칙과 같음). 그래서 정답 세트 시험은 2~3일에 걸쳐 돕니다.

## 3. 공개 스냅샷 계약 확정 (성장·유통 초안 3c3591df 기준, PM 05:4x 요청)

### 3-1. 파일 경로와 쓰는 쪽
- 경로: `gateway-data/necklaces/necklaces.json`(git 제외). 성장·유통 초안 그대로입니다.
- 쓰는 쪽: **워크플로우 팀의 jobs 작업 `necklace_judge` 하나뿐**입니다. 다른 팀은 이 파일을 쓰지 않습니다.
  - 입력: 정의 파일(git), 정답 세트 시험 결과(워크플로우), 매일 재시험 `gateway-data/necklaces/retest/<date>.jsonl`(운영·SRE), 진주 표(검색과 RAG, `reports/pearls-*/pearls.json` 또는 그 팀이 정하는 경로), 운영·SRE 승인 파일 `gateway-data/necklaces/approvals.json`(deploy/NECKLACE_GATE.md 형식: `{slug, version, definition_digest, gate_record, state: approved|held|revoked, at}`)
  - 실행: 재시험 파일이나 approvals.json이 바뀌면 바로(파일 수정 시각 감시, 수 초 안), 그 밖에는 10분마다
  - **두 열쇠(PM 07:3x)**: `live`는 approvals.json에 같은 slug·`version`·`definition_digest`인 `state: approved` 항목이 있을 때만 씁니다. 항목이 없거나, version·digest가 다르거나, state가 `held`·`revoked`면 `held`로 쓰고 `held_reason`에 `not_approved`·`approval_mismatch`·`gate_held`·`approval_revoked`를 적습니다.
  - 쓰기: 임시 파일 → rename(원자적 교체), 1MB 상한, 실패하면 이전 파일 유지
- 최상위 형식(초안에 추가하는 것):
```json
{"schema": "agentcon-necklaces-v1", "generated_at": "2026-11-20T03:12:00Z", "judge_commit": "abc1234",
 "necklaces": [ { …초안 항목… } ]}
```
- 항목에 더하는 필드(모두 선택, 표면이 몰라도 됨):
  - `version`(정의 버전), `definition_digest`, `gate_passed_at`(approvals의 approved 항목 `at` = 워크플로우 메뉴에 오른 시각, 없으면 null. 성장·유통 요청). 홍보 대상은 `status: live`이고 `gate_passed_at`이 있는 항목입니다
  - `replaces_templates`(이 목걸이가 대체한 옛 template_id 목록)와 `replaced_at`(대체 시각). 성장·유통이 옛 template_id로 온 run_workflow·workflow_details에 `replaced_by {slug, url, until = replaced_at + 30일}`를 붙이는 데 씁니다. 대체된 옛 템플릿은 is_active=0이라 **더 실행되지 않습니다**. 안내 문구는 "no longer runs; use necklace <slug>"입니다.
  - `quality.delta_significant`(McNemar p < 0.05), `quality.lower_bound`(누적 재시험 Wilson 하한), `quality.delta_by_type`({"same_role": …, "multi_facet": …})
  - `pearls[].pearl`(엄격 기준 진주 여부), `pearls[].alternates[].same_source_as`(같은 원천을 쓰는 멤버)
  - `held_reason` 코드: `no_member`, `delta_nonpositive`, `completion_low`, `quality_low`, `security`, `stale_retest`, `not_approved`, `approval_mismatch`, `gate_held`, `approval_revoked`
  - `status: "retired"`와 `replaced_by`(대체한 목걸이 slug). 표면은 모르는 상태를 노출하지 않는다는 초안 규칙 그대로입니다. retired는 페이지를 `replaced_by`로 안내하는 데만 씁니다.
- 바뀌지 않는 것: 초안의 노출 조건(`live`, 진주 2개 이상, `delta_pp > 0`, `tested_at` 48시간 안, Agentcon 대체는 자리당 2개 이하·맨 뒤). 판정 작업도 같은 조건으로 스스로 검사하고, 어기면 `live`로 쓰지 않습니다.

### 3-2. slug 규칙
- 소문자 영문·숫자·하이픈, 영문으로 시작, 3~40자, 하이픈 연속 금지(`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`)
- 과제를 말하는 영어 명사구로 짓습니다(예: `package-risk-audit`). 진주·제공자 이름은 넣지 않습니다(진주가 바뀌어도 이름은 그대로).
- 한 번 `live`가 된 slug는 바꾸지 않고, 폐기한 slug도 다시 쓰지 않습니다. 버전이 올라가도 slug는 같습니다.
- 표면 이름: 웹 `/necklaces/<slug>`, A2A 기술 id `necklace-<slug>`, MCP 도구 이름 `necklace_<slug의 하이픈을 밑줄로>`
  - 초안은 MCP 도구 이름을 `<slug>`로 했습니다. 기존 도구(`find_agents`, `run_workflow` 등)와 겹치지 않게 `necklace_` 접두를 붙이자고 제안합니다(64자 상한 안). 성장·유통 확인이 필요합니다.

### 3-3. held 전환 주체
- **판단은 워크플로우 팀(`necklace_judge`)** 이 합니다. PM 의견과 같습니다. 운영·SRE 재시험 결과는 입력입니다.
- 자동 held 조건(6절)이 하나라도 맞으면 다음 판정 때 `held`로 씁니다(최대 10분, 재시험 파일이 들어오면 바로).
- 긴급 개입: 운영·SRE는 approvals.json의 그 항목을 `held` 또는 `revoked`로 바꿉니다. 판정 작업이 파일 변경을 감시해 수 초 안에 `held`를 씁니다. 그래서 `necklaces.json`을 직접 고칠 필요가 없습니다(직접 고쳐도 다음 판정 때 approvals 기준으로 다시 씀). PM 요청 보류도 운영·SRE가 approvals로 합니다. 별도 overrides 파일은 두지 않습니다.
- held에서 live로 돌아가는 것은 판정 작업만 합니다. 원인이 해소되고 재시험이 통과해야 합니다.

## 4. 품질 관문 (생산 공정의 합격선, PM 06:2x로 95%)

워크플로우 팀은 자체 시험에서 아래를 **모두** 넘긴 것만 운영·SRE에 제출합니다.

| 항목 | 기준 | 잼 |
|---|---|---|
| 종단 성공률 | 보류 세트 60건 중 57건 이상(95%, 점추정). 조정 세트 30건 중 29건 이상 | 정답 세트, 채점기 커밋 기록. 공개 뒤 누적 하한은 2절. 운영·SRE 관문(PM 07:5x 확정): **보류 60건을 4시간 이상 간격으로 30건씩 두 번** 나눠 돌려, 합계 57/60 이상이고 각 회 28/30 이상이어야 통과. 조정 30건은 워크플로우 자체 시험에만 씀 |
| Δ | 목걸이 성공률 − 최고 단일 진주 성공률 > 0. 같은 역할 과제만 따로 셌을 때도 > 0 | 같은 정답 세트로 사슬의 외부 진주 각각을 단독 실행 |
| 완주율 | 95% 이상(필수 자리가 모두 채워진 비율) | 같은 실행 |
| 외부만 완주율 | 70% 이상(Agentcon 대체 없이 완주) | 같은 실행 |
| 지연 | p95 5초 안(복잡한 답변), 공개 주소·새 연결·처음 보는 입력, 표본 제외 없음 | 운영 사본이 아닌 공개 경로. 한국에서 잰 값은 그렇다고 표시 |
| 보안 | ① 모든 멤버: readOnlyHint=true가 **명시**됨(추정으로 채우지 않음), destructiveHint≠true, 우리 중계 판정 `collector/usage.py:144 is_relay_safe_tool` 통과(실행·결제 동사 제외), 자격 증명·결제·x402·쓰기 없음. 멱등 표시가 없는 멤버는 사슬 정의에 `resend_safe: false`로 적고, 실행 1회당 같은 제공자 재시도는 하지 않음(PM 06:3x 결정 ②) ② 도구 정의 지문 고정 ③ 출력 주입 시험: 정답 세트 입력 중 5건에 지시문이 든 출력을 흉내 낸 응답을 끼워 넣었을 때 합성 결과가 지시를 따르지 않음 ④ 자격 증명·결제·사설 주소 0 | 보안 시험 스크립트 |
| 비용 | 1회 USDC 0, 호출 수 기록 | 실행 기록 |

차선 목표의 품질 90%와의 관계
- 차선 품질 지표(real_task_score 27/30, 연결 90%, Chat 99/110)는 탐색·추천 품질입니다. 목걸이 관문 95%는 그보다 높은 별도 합격선입니다.
- 목걸이를 real_task_score 과제 묶음에 넣을 때는 목걸이 정답 세트의 보류 과제 5건을 넘깁니다. 목걸이 실패는 차선 품질을 깎는 쪽으로만 셉니다.

## 5. 운영·SRE에 넘기는 묶음 (출시 관문 제출 형식)

- 위치: `gateway-data/necklaces/submissions/<slug>-v<version>-<YYYYMMDDHHMM>/`(git 제외). 현황판 '넘기는 일'에 경로를 적습니다.
- 내용:

| 파일 | 내용 |
|---|---|
| `manifest.json` | slug, version, 정의 커밋, 채점기 커밋, 판정 작업 커밋, 만든 시각, 파일별 sha256, 자체 시험 요약(아래 표의 숫자), 제출자 |
| `necklace.json` | 공개 스냅샷 항목 그대로(3절 형식, status는 `candidate`) |
| `definition.json` | 정의 파일 사본(자리·계약 id·사슬·합성 규칙·예산) |
| `contracts/*.json` | 이 목걸이가 쓰는 역할 계약 |
| `chain.json` | 자리별 사슬과 자리 자격 시험 결과(멤버마다 시험 3건, 지연, 지문, 같은 원천 표시) |
| `gold/tuning.jsonl`, `gold/holdout-r1.jsonl`, `gold/holdout-r2.jsonl` | 정답 세트(입력, 정답, 정답 원천과 받은 시각). 보류 60건을 서로 다른 입력 30건씩 두 파일로 나눔(각각 같은 역할 대조 절반 이상). 운영·SRE 관문 1회차·2회차 전용(`--answer-set`) |
| `results/necklace.jsonl` | 목걸이 실행 60건 원자료(자리별 시도·대체·지연·채점) |
| `results/single-<resource_id>.jsonl` | 단일 진주 기준선 실행 원자료 |
| `results/security.jsonl` | 보안 시험 결과 |
| `policy.json` | 대체 정책 v2 payload(서명 전 내용) |
| `rerun.sh` | 운영·SRE가 공개 주소로 같은 시험을 다시 도는 명령(읽기 전용, heavy_slot 안에서) |

- 운영·SRE 검수가 실패하면 묶음은 그대로 두고 사유를 현황판에 적습니다. 워크플로우 팀은 새 묶음을 만듭니다(덮어쓰지 않음).

## 6. 교체·보류·폐기 규칙

사슬 정비(자동, 보류 아님)
- 멤버 도구 정의 지문이 바뀜 → 그 멤버를 즉시 빼고 다음 순위를 올림. 새 정의를 검토하고 자격 시험을 다시 통과하면 복귀
- 멤버 재시험 2일 연속 실패 → 빼기, 7일 연속 통과하면 원래 순위로 복귀
- 자리별 외부 멤버가 2개 아래 → 경보(운영·SRE), 검색과 RAG에 그 역할 실행 시험 요청
- 한 자리의 Agentcon 대체 사용률 7일 30% 초과 → 그 자리의 외부 진주를 다시 찾음

held(자동)
1. 필수 자리에서 쓸 수 있는 멤버 0개 → `no_member`
2. 재시험 Δ ≤ 0이 2일 연속 → `delta_nonpositive`
3. 완주율 95% 아래가 2일 연속 → `completion_low`
4. 누적 성공률 Wilson 하한 90% 아래 → `quality_low`
5. 보안 시험 실패, 멤버가 쓰기·결제·실행 도구로 바뀌거나 사슬에 들어감, 출력 주입 탐지 → `security`(즉시)
7. 하루 종단 성공률 80% 미만 → `quality_low`(즉시, PM 07:3x). 80~95%는 운영·SRE가 2시간 안에 재실행하고 두 번째도 95% 아래면 approvals를 held로 바꿈 → `gate_held`
8. 도구 정의 지문이 바뀐 멤버가 **주 자리**에 있고 대체로 내릴 수 없음 → 즉시 `security`(대체로 내릴 수 있으면 사슬 정비로 처리)
6. 재시험 결과가 48시간 넘게 없음 → `stale_retest`

폐기
- 같은 수요의 새 목걸이가 관문을 통과해 live가 됨 → 옛 목걸이 `retired`, `replaced_by` 기록
- 3주 연속 held → 폐기 검토(PM 보고)

버전
- 사슬 순서·멤버 교체는 같은 버전(정책 revision만 올림). 매일 재시험으로 확인합니다.
- 자리·계약·합성 규칙·입력 스키마가 바뀌면 버전을 올리고 3단계부터 다시 합니다. 관문도 다시 제출합니다.

## 7. 공개 동의 문구 초안 `necklace-v1` (PM 06:3x ⑤, 성장·유통 검토 반영, **PM 07:5x 승인**, 보존 문장만 보류)

공개 실행 버튼 옆 확인란, MCP 도구 설명, A2A 기술 설명에 같은 뜻으로 씁니다. 영어, 사실만, 약속 문구 없음. `{BRAND}`는 서버 BRAND 상수에서 넣습니다(브랜드 이름은 사용자 결정 대기). `{mode}`는 정의의 그래프가 병렬일 때만 " in parallel"이고, 아니면 빈 문자열입니다(PM 07:5x).

- 확인란(웹, 기본 해제, 실행마다 새로 묻고 저장하지 않음):
  > I understand that this necklace sends my input to the verified agents listed below. If one of them fails, the same input may be sent to another verified agent listed for that step, including agents run by {BRAND}. Results come from third-party agents; review them before you rely on them. Do not include passwords, keys, payment details or personal data.
- 목록(확인란 바로 아래, 정의에서 자동 생성, 이름마다 진주 카드 `/agent/<id>` 링크): `Step <role>: <agent name> (<host>), then <alternate name> (<host>), …`
- MCP 도구 설명 끝 문장(세부 도구 이름은 성장·유통 확정 `necklace_details`):
  > Runs several verified read-only agents{mode}. Your input is sent to the agents listed in necklace_details; if one fails, the same input may go to a listed alternate. Results come from third-party agents; review them before you rely on them. No credentials or payments are sent.
- A2A 기술 설명: MCP와 같은 문장
- **보존 문장(사실 확인 필요, 아래 참고)**: "Your input and the results are kept for up to 14 days to check reliability, then deleted." — 실행 본문 정리 작업이 운영에서 돌고 있음을 확인한 뒤에만 씁니다.
- 쓰지 않는 표현: "guaranteed", "always", "private", "secure"(측정 근거 없는 약속)
- 동의 값 이름: 기존 `fallback_notice=readonly-fallback-v1`과 같은 방식으로 `necklace_notice=necklace-v1`(실행마다, 저장 안 함)

**보존 기간 확인 결과(11-14 운영 DB 읽기 전용)**: 코드의 정리 규칙은 실행 본문 14일·메타데이터 90일(`agent_market/workflow_maintenance.py:18-19`)입니다. 그런데 14일이 지난 실행 135건 중 127건에 결과가 남아 있고, 정리 기록은 2건뿐입니다. 정리 작업이 운영에서 주기적으로 돌지 않는 것으로 보입니다. 목걸이 공개 전에 정리 작업을 켜거나(운영·SRE), 실제 보존 기간을 문구에 써야 합니다. PM에 보고했습니다.
