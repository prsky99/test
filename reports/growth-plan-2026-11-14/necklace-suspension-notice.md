# 목걸이 정지 공지 (4단계 대응, PM 11-14, 헌장 0절) — 성장·유통 설계안

자체 대체(외부 대체 → AgentValCon 대체 최대 2개)까지 실패하면 워크플로우 팀이 목걸이를 정지하고 새 목걸이로 바꾼다. 성장·유통은 그 목걸이를 쓰던 사람과 에이전트가 알 수 있게 공지 문구와 안내 화면, 알림 자리를 맡는다.
- 옛 워크플로우 번호 안내와 같은 틀을 쓴다(워크플로우 팀 합의, 251ecffa): "no longer runs; use necklace <slug>", 30일 안내, 301 이동.
- **메일 같은 외부 발송은 하지 않는다.** 필요하면 사용자 승인을 받는다. 공지는 우리 화면, 응답, 공개 피드에서만 한다(사람과 에이전트가 가져가는 방식).
- 공개 문구는 영어로, 사실만 쓴다. 측정값이 없는 칸은 숨긴다. "guaranteed/always/sorry for any inconvenience" 같은 상투어는 쓰지 않는다.

## 1. 데이터 (워크플로우 스냅샷에서 읽기만)

| 필요한 값 | 스냅샷 필드 | 없으면 |
|---|---|---|
| 정지 여부 | `status` = `retired`(새 목걸이로 대체) 또는 `held`(일시 정지) | 공지 없음 |
| 정지 이유 | `held_reason` 코드 7개(no_member, delta_nonpositive, completion_low, quality_low, security, stale_retest, manual) | "manual"과 같은 일반 문장 |
| 새 목걸이 | `replaced_by`(slug) → 그 목걸이의 name, `/necklaces/<slug>` | 새 목걸이 줄을 숨기고 "No replacement yet" |
| 정지 시각 | `replaced_at`(retired), 정지 시각 필드(held용, 워크플로우 팀에 요청) | 시각 줄을 숨김 |
| 30일 기간 | `replaced_at + 30일` | 기간 안내를 숨김 |

- 워크플로우 팀 반영(9f4f02df)
  - `held_at`: 보류가 시작된 시각. 같은 보류가 이어지는 동안 바뀌지 않는다.
  - 최상위 `events`: [{slug, kind: launched|held|resumed|retired, at, reason, replaced_by}], 최근 60일. 한 번도 live였던 적이 없는 목걸이의 보류는 공개 사건이 아니다.
  - 항목별 `stage` {slots, failed, max}. 4단계 보류는 held_reason `stage4`.

## 2. 정지 이유 문구 (코드 → 한 문장, 사실만)

| held_reason | 문구(영어) |
|---|---|
| no_member | One step has no working agent left, including its fallbacks. |
| delta_nonpositive | In recent tests it no longer did better than the best single agent for this task. |
| completion_low | Recent test runs did not reach the last step often enough. |
| quality_low | Recent test answers fell below our quality threshold. |
| security | A security check on one of its agents did not pass. |
| stale_retest | It has not been retested recently, so we stopped it until it is. |
| manual | Our operators stopped it for review. |
| stage4 | Every agent for one step failed, including its fallbacks, so it stopped (step 4 of our recovery plan). |

- 숫자를 붙일 수 있으면 붙인다. 예: "Completed 18 of 30 test runs (since 2026-11-20)". 값은 스냅샷의 completion·quality에서만 가져온다.

## 3. 공지 문구 (영어)

### 3-1. 대체됨(retired → replaced_by)
> **This necklace has stopped.** {reason sentence} It stopped on {YYYY-MM-DD HH:MM} UTC.
> Use **{new name}** instead: {base}/necklaces/{new slug}
> (This notice stays here until {replaced_at + 30 days, YYYY-MM-DD}.)

### 3-2. 일시 정지(held, 대체 없음)
> **This necklace is paused.** {reason sentence} Paused on {YYYY-MM-DD HH:MM} UTC. It will run again when it passes its next retest.

### 3-3. 에이전트가 받는 한 줄 (MCP·A2A·run_workflow 응답, 기계가 읽기 쉽게)
- 대체됨: `Necklace {slug} no longer runs ({reason code}, stopped {ISO time}); use necklace {new slug}: {url}`
- 일시 정지: `Necklace {slug} is paused ({reason code}, since {ISO time}); try again after its next retest.`
- structuredContent: `{"necklace_status": "retired"|"held", "reason": "<code>", "stopped_at": "<ISO>", "replaced_by": {"slug", "url", "until"} | null}`
- 옛 워크플로우 번호 안내(`no longer runs; use necklace <slug>`)와 같은 꼴이다.

## 4. 화면

| 곳 | 안내 | 규칙 |
|---|---|---|
| 목걸이 페이지 `/necklaces/<slug>` | 제목 바로 아래 **페이지 안 안내 영역**(디자인 시스템 `notice` 부품). 3-1 또는 3-2 문구. 실행 버튼은 숨기고 그 자리에 새 목걸이 링크 버튼("Open {new name}") | **가운데 팝업 금지**(화면 정책). 페이지는 200으로 남긴다(근거·완주 기록은 계속 보임). 30일이 지나면 retired 페이지는 새 목걸이로 301 |
| 워크플로우 메뉴 카드 | 카드 오른쪽 위 상태 표시 "Stopped" / "Paused"(기존 상태 표시와 같은 부품), 카드 아래 한 줄 "Replaced by {new name} →" | 30일 동안. 뒤에는 카드가 빠지고 새 목걸이 카드만 남음 |
| llms.txt "Necklaces you can run" | 정지한 목걸이는 목록에서 빼고, 30일 동안 아래에 "Stopped: {slug} → {new slug}" 한 줄 | 손으로 쓰지 않음(스냅샷에서 생성) |
| MCP tools/list·A2A 카드 기술 | 정지한 목걸이 도구·기술은 목록에서 뺀다. tools/call·A2A run은 30일 동안 3-3 응답(실행 안 함) | subscribe 숨김과 같은 방식(목록에서 빼고 처리기는 답함) |

- 접근성: 안내 영역은 `role="status"`이고 제목 수준을 지킨다. 색만으로 상태를 나타내지 않는다(글자 "Stopped"를 함께 쓴다).
- 로딩: 페이지 안내는 HTML에 바로 들어간다(고정 내용). 별도 요청이 없다.

## 5. 공개 변경 피드

- 지금 있는 `/api/feed/verified.json`(JSON Feed, 검증 변경)과 나란히 **`/api/feed/necklaces.json`**(JSON Feed 1.1)을 둔다.
  - 항목: 목걸이 출시(메뉴 적용), 정지, 대체, 재개
  - 필드: `id`(slug+사건+시각), `title`(3-1 첫 문장), `content_text`(3-1 전체), `url`(목걸이 페이지), `date_published`, `_necklace`(3-3 structuredContent)
- 노출 위치
  - 홈과 워크플로우 페이지 head의 `<link rel="alternate" type="application/feed+json">`
  - llms.txt "Necklaces you can run" 아래
  - A2A 카드 documentationUrl 옆 설명
- 캐시: 공개 읽기 1분(verified.json과 같은 규칙). 요청 경로에 실시간 DB 확인을 넣지 않고 스냅샷에서 만든다.
- 이 피드는 우리 서버의 공개 파일이라 외부 발송이 아니다. 에이전트가 가져간다.

## 6. 로그인 사용자 알림

- 자리: 워크스페이스 **알림 페이지**(`/new/en/notifications.html`, 기존 화면)의 목록 맨 위와 헤더 알림 점.
- 대상: 지난 30일 안에 그 목걸이(또는 그 목걸이가 대체한 옛 템플릿)를 실행한 계정. 실행 기록의 계정 기준이다.
- 문구: 3-1/3-2와 같다. 링크는 새 목걸이 페이지로 간다.
- 만드는 쪽: **워크플로우 팀**(9f4f02df 회신). 판정 작업이 `gateway-data/necklaces/notices.json`({계정 번호: [{slug, kind, at, replaced_by}]}, 30일)을 쓴다.
  - 로그인 실행의 내부 계정 번호(메일 아님)는 실행기가 30일만 남긴다.
  - 옛 템플릿 사용자는 workflow_runs.actor로 찾는다(읽기 전용, 대체하는 날 한 번).
  - 표면(성장·유통)은 현재 로그인 계정의 항목만 읽어 알림 페이지에 보여 준다. DB 구조 변경은 없다.
- 익명 사용자와 에이전트에게는 계정이 없어 개별 알림을 보내지 않는다. 대신 다음 세 가지로 알린다.
  - 다음 호출 때의 응답(3-3)
  - 공개 피드(5)
  - 목걸이 페이지 안내(4)
- 메일, 웹훅, A2A 푸시처럼 우리가 먼저 보내는 것은 하지 않는다(사용자 승인 필요). 기존 `/api/task-updates` 구독 경로가 있지만, 쓰려면 승인을 받는다.

## 7. 시험 (구현 때)

- retired·held 스냅샷 각각에 대해 확인한다.
  - 페이지: 200, 안내 영역 있음, 실행 버튼 없음, 새 목걸이 링크
  - 메뉴 카드 상태 표시
  - tools/list에서 빠짐, tools/call은 3-3 응답이고 실행하지 않음
  - A2A run도 같음
  - 피드 항목
- 값이 없는 칸은 숨긴다(정지 시각이 없으면 시각 줄이 없다).
- 30일 경계: 31일째 retired 페이지는 301, 메뉴 카드는 사라짐.
- 문구 금지어(guaranteed, always, sorry)가 없는지 확인한다.

## 8. 일정

- 목걸이 공개 표면 1주 차 틀과 같이 만든다. 정지 상태는 그 틀의 한 상태다.
- 브랜드 배포 다음 순서로 시작한다.
