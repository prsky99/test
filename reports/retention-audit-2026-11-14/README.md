# 개인정보 보관 약속 감사와 워크플로우 14일 정리 켜는 안 (운영·SRE, 2026-11-14 04시, PM 08:0x)

**읽기 전용 감사다. 운영 DB에는 아무것도 쓰거나 지우지 않았다.** 지금 기한을 넘긴 데이터를 지우는 일은 데이터 삭제라 사용자 승인이 필요하다(PM이 모아서 묻는다).

- 기준 문구: 공개 처리방침 `https://agentconcierge.biz/new/en/privacy.html`(11-14 04시에 받은 운영 페이지)
  - 저장소의 `new/html/privacy.html`에는 아래 6~9번 문구가 없다. 운영 페이지가 더 새것이다.
- 코드 위치: 읽기 전용 코드 조사(file:line)
- 행 수: 운영 PG 읽기 전용 집계
  - 개인정보 값은 출력하지 않았다. IP·UA는 모양(숫자를 기호로 바꾼 형태)과 길이로만 셌다.

## 1. 약속별 결과

| # | 약속(공개 문구 요약) | 데이터·정리 코드 | 정기 실행 | 기한 넘긴 행 | 판정 |
|---|---|---|---|---|---|
| 1 | 작업 갱신 알림 90일 만료 | `agent_task_watches.expires`(`task_updates.py:28` WATCH_TTL), 만료 처리 `maintain` `:485` | jobs Scheduler → `TaskUpdates.run_due` → `events.tick` 뒤 `maintain`(`task_updates.py:546-547`), 약 30초마다 | 0 (전체 4건: active 3, revoked 1) | 지켜짐 |
| 2 | 확인 1시간 만료 | `code_expires`(`:29` CODE_TTL), `maintain :485`, 미확인 행 24시간 뒤 삭제(`:494-500`) | 위와 같음 | 0 | 지켜짐 |
| 3 | 만료·실패·중지 알림의 복구 정보 삭제 | `maintain :485-486`(sealed·code_hash·task·protocol·baseline 비움) | 위와 같음 | 0 | 지켜짐 |
| 4 | 갱신 이벤트 최대 30일 | `agent_task_events`(`maintain :487`), `adoption_changes`(`events.tick` `events.py:245`, 처리 끝난 행만, 한 번에 100행) | 위와 같음 | 0 (`adoption_changes` 가장 오래된 행 10-25 → 첫 대상 11-24) | 지금은 지켜짐. **주의**: 대기(pending) 행은 30일이 지나도 지우지 않는다. 피드 밀림이 30일을 넘으면 약속을 어긴다(지금 지연 약 98시간, 안 A2로 따라잡는 중) |
| 5 | 목적 선택 기록 최대 24개월 | `agent_task_permissions`·`agent_marketing_permissions`, `maintain :488,:490,:501`(730일) | 위와 같음 | 0 (가장 오래된 10-17) | 지켜짐(첫 대상 2028-10) |
| 6 | AD Coin 보안 기록: 짧은 네트워크 주소·일반 클라이언트 종류, 90일 뒤 삭제 | `ad_coin_v2.adc2_audit_log`, `AuditLogger.prune`(`security_guards.py:189-199`, 90일) | AD Coin 데몬(launchd `adcoin-worker`, 실행 중)이 1시간마다 prune, 로그에 `pruned` 기록 | 0 (전체 23행, 가장 오래된 11-11, client_ip가 채워진 행 0) | 지켜짐(첫 대상 2027-02-09) |
| 7 | 결제 기록 5년 보관 뒤 삭제 | `ad_coin_v2.adc2_paid_bookings` 등 | **삭제 코드 없음** | 0 (결제 행 0, USDC 스위치 꺼짐) | 지금은 문제 없음. **2031년 전까지 5년 삭제 작업을 만들어야 함** |
| 8 | 포인트 365일 미사용 만료 | `points.py:103-125` `expire_inactive_points`(삭제가 아니라 만료 계정으로 옮김) | AD Coin 데몬, 1시간마다(포인트 모드일 때) | 0 (원장 가장 오래된 11-11) | 지켜짐(첫 대상 2027-11-11) |
| 9 | 11-10 전 기록에 IP·UA가 남아 있을 수 있어 삭제 검토 중 | `security_events.ip/user_agent`, `admin_audit_logs.ip`, `agent_visitors.user_agent`, `needs.ip`, `agent_hits.user_agent` | 11-10 일회성 정리(`deploy/privacy/scrub-*-2026-11-10.sql`) | **원본 IP 0건, 원본 UA 0건**(아래) | 이미 정리됨. 공개 문구를 고칠 수 있음 |

9번 세부(모양 집계)
- `security_events` 10,533행
  - IP는 모두 줄인 형태다: IPv4 `/숫자` 8,543, IPv6 `::/숫자` 1,988, `unknown` 2.
  - UA는 모두 20자 이하의 종류 값이다(10,515).
  - 11-10 이전 행 3,101건도 같은 형태다.
- `admin_audit_logs`: IP 76건 모두 `/숫자` 형태다.
- `agent_visitors.user_agent`: 77건 모두 종류 값이고, 11-13 이후 행이다.
- `needs.ip` 0건, `agent_hits.user_agent` 0건이다.

**처리방침 밖이지만 함께 볼 것**: `security_events`(공개 기능 전체의 보안 기록)
- 11-11 사용자 결정은 90일 보관이다(`workspace_admin_retention.py:20-22`, 한 번에 최대 10,000행).
- 그런데 운영에 보존 정책 행이 없다(`workspace_admin_state`에 `admin_retention:policy` 없음). 그래서 **90일 삭제가 꺼져 있다.**
- 가장 오래된 행이 10-15라 첫 대상은 2027-01-13이다. 그 전에 정책을 켜야 한다. 정책 켜기는 삭제 정책이라 사용자 승인이 필요하다.

## 2. 워크플로우 실행 본문 14일 정리

| 실측(14일 지난 완료 실행 135건) | 건수 | 끝난 날 |
|---|---|---|
| 이미 정리됨(요약만 남음) | 40 | 10-18~10-24 |
| 결과 불명이라 설계상 보존(`unknown_outcomes_retained`) | 49 | 10-17~10-24 |
| **정리 대상인데 본문이 남음** | **46** | 10-24~10-29 |

- 단계별 입력·출력(`workflow_node_runs.input/output`)은 실행 95건, 287행에 남아 있다(보존 49 + 남은 46).
- PM 메시지의 "127건에 결과가 남음"은 정리된 실행도 `result`에 요약(`retained_summary`)을 남기기 때문에 실제보다 많게 보인 수치다.
- **정기 실행 없음.** `Maintenance.run`(`workflow_maintenance.py:34-108`)을 부르는 곳은 두 개뿐이고, 스케줄러·launchd·jobs에는 없다.
  - 관리자 API `POST /admin/api/workflows/maintenance`(`dashboard.py:887-892`, 실행자 id를 남김)
  - CLI `python -m agent_market.workflow_maintenance --apply`(실행자 0)
- **오늘 밤 두 번 수동 실행됨**
  - 01:58과 03:26에 20건씩, 실행자 0이다. CLI로 운영에 직접 돌린 것으로 보인다.
  - 누가 돌렸는지는 DB와 로그로 확인할 수 없다.
  - 기한 넘긴 데이터의 삭제(되돌릴 수 없음)이니, PM이 실행한 팀을 확인하기 바란다.

### 켜는 안 (승인 전에는 꺼 둔 채로 배포)
1. **어디서**: jobs Scheduler(`gateway/server.py`의 summaries 단계와 같은 자리)에 1시간마다 한 번 `workflows_runtime.maintenance.run(apply=True, limit=20, actor=0)`을 넣는다.
   - 환경 변수 `WORKFLOW_RETENTION_SCHEDULE`(기본 `0`)일 때는 dry-run만 하고 대상 수를 로그에 남긴다.
   - 사용자 승인 뒤 `1`로 바꾼다(gateway-data/agentcon.env, jobs 재배포).
2. **언제**: 매시 :20~:50 사이(매시 측정 :55~:10과 03:50~05:10 채점 시간은 피함).
3. **한 번에 얼마나**
   - 실행 20건 이하, 0.5초 시간 예산
   - queued·running 실행이나 전달 대기가 있으면 아무것도 하지 않는다(코드 그대로).
   - 지금 밀린 46건은 3번에 끝난다. 그 뒤로는 하루 몇 건 수준이다(지난 4주 완료 실행 약 135건).
4. **SQL**: 새 문장이 없다. `Maintenance.run`의 문장은 이미 등록돼 있고(`application_store_coverage.py:41`), 오늘 밤 운영 PG에서 실제로 돌았다. DB 구조 변경도 없다.

### 되돌릴 수 없는 점
- 14일 정리는 다음을 한다. 남는 것은 서명된 해시 증명(`workflow_run_archives`)뿐이다.
  - `workflow_runs.snapshot`·`result`를 요약으로 바꾼다.
  - `workflow_checkpoints`를 지운다.
  - `workflow_node_runs.input/output/error`를 비운다.
- 90일 정리는 다음을 지운다.
  - `workflow_run_events`, `routing_attempts`, `routing_decisions`, `fallback_shadow`, `run_authority`
  - 쓰지 않는 `workflow_versions`
- 되살리려면 DB 백업(맥미니 SMB 백업)뿐이다. 백업에도 같은 데이터가 백업 보관 기간 동안 남는다.

### 영향 범위
- 14일 지난 실행의 상세 화면은 "Detailed run content has expired under the retention policy."로 바뀐다. 실행 id, 멱등 키, 시도 기록, 전달 id는 남는다(재실행 방지).
- 14일 지난 실행의 본문을 다시 읽는 분석·재현은 할 수 없다. **워크플로우 팀이 기존 워크플로우 분석이나 목걸이 정답 만들기에 옛 실행 본문을 쓰고 있다면 켜기 전에 필요한 집계를 먼저 남겨야 한다.**
- 전달 대기 중인 실행은 건너뛴다. 결과 불명 실행 49건은 계속 남는다(아래 결정 3).

## 3. 사용자 승인이 필요한 것 (PM이 모아서 묻기)
1. 워크플로우 본문 14일 정리를 켜고, 지금 밀린 46건을 정리하기(되돌릴 수 없음)
2. `security_events` 90일 삭제 정책 켜기(11-11 결정대로, 2027-01-13 전까지)
3. 결과 불명 워크플로우 실행(49건, 10-17~10-24)의 상한을 정하기. 지금은 끝없이 남는다.
   - 제안: 90일 뒤 한 번 사람이 확인하고 정리한다.

## 4. 고칠 것 (승인 필요 없음, 담당 제안)
- 처리방침 문구(성장·유통): 9번 "11-10 전 기록에 IP·UA가 남아 있을 수 있음"은 실측상 이미 정리됐으니 고칠 수 있다.
  - 워크플로우 실행 보관 기간(14일, 결과 불명은 예외)을 처리방침에 넣을지도 정한다.
- 결제 5년 삭제 작업 만들기(AD Coin): 지금 결제 행 0, 기한 2031년. USDC 스위치를 켜기 전에 일정에 넣는다.
- `adoption_changes`의 대기 행 30일 상한(운영·SRE): 피드 밀림이 30일을 넘지 않게 경보를 둔다. `feed_record` 지연이 72시간을 넘으면 현황판에 알린다.

## 5. 운영·SRE 다음 일
- 2절 켜는 안의 코드
  - jobs 스케줄 + `WORKFLOW_RETENTION_SCHEDULE=0` dry-run 기록 + 시험
  - 승인이 나면 env를 바꾼다.
  - 정책 해시 파일이 아니므로 jobs만 배포하면 된다.
- 피드 지연 경보(4절)
