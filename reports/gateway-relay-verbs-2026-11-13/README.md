# 게이트웨이 중계 허용 동사 확대 검토 (2026-11-13, 검색과 RAG)

## 결론
- 접두어가 붙은 조회 도구도 게이트웨이가 중계하게 하는 규칙을 만들고, 운영 도구 목록으로 표본 검토를 네 번 했다(PM 11-13 결정 1).
- 1~3차 표본에서 실행 성격이 섞여 나와 그때마다 규칙을 좁혔다. 4차 표본 220개에는 쓰기·삭제·전송 성격이 없다.
- collector 시험 호출 범위(`usage.is_safe_tool`, `pick_trial`)는 바꾸지 않았다. 중계 판정만 새 함수 `usage.is_relay_safe_tool`를 쓴다.
  - 쓰는 곳: `execution_policy.safe_registered_tool`, `proxy._execute_mcp`
- 배포 전 결정이 하나 남았다. 바뀐 두 파일(`collector/usage.py`, `concierge/execution_policy.py`)이 탐색 문서 정책 해시(`explore_documents.policy_hash`)에 들어 있다. 그래서 배포하면 탐색 문서 약 30만 개를 다시 만든다(11-04 실측 분당 약 2,600건, 약 2시간). 이 코드는 공유 브랜치에 넣지 않고 `rag/relay-allow-1113`에 두었다.

## 규칙 (중계 판정 전용)
1. 아래는 지금처럼 먼저 적용한다.
   - destructiveHint=true 제외
   - 개인정보 필수 인자 제외
   - readOnlyHint=true는 허용, readOnlyHint=false는 제외
   - 이름과 설명 앞 200자에 거부 목록이 있으면 제외
2. 동사로 시작하는 이름은 동사 뒤에 단어 경계가 있어야 한다.
   - 단어 경계: 끝, `_`, 숫자, 대문자(camelCase)
   - `.`과 `-`는 `_`처럼 구분자로 본다.
   - 어미 s·es·ed·ing은 인정한다. summar는 뒤에 소문자가 이어져도 된다.
   - 이 경계가 기존 오탐을 막는다: browser_drag, browser_control, checkout_link, checkpoint_put, counter_offer.
3. 접두어가 한 단계만 붙은 이름은, 다음을 모두 만족할 때만 인정한다.
   - 접두어 뒤가 허용 동사다.
   - 접두어 자체가 동사 줄기로 시작하지 않는다(counter_, checklists_, calculator_ 제외).
   - 접두어가 동작 단어가 아니다(refresh, record, load, save, store, put, leave, join 등).
   - 접두어 뒤의 단어가 version·quote·recommend·suggest가 아니다.
   - check_in·check_out이 아니다.
   - 설명이 조회 동사로 시작한다(Get, List, Search, Return, Extract 등).
   - 설명 앞 200자에 판매·사람에게 맡김·전달 같은 동작 표현이 없다.
4. 비영어 조회 동사(listar, lister, lista, calcular, comparer, analyser)는 지금까지 우연히 통과했다. 이 경우는 그대로 둔다.

## 운영 도구 목록 대비 효과
기준: 11-13 11시 운영 읽기 전용, 활성·정상 MCP 26,062개, 도구 402,352개.

| 항목 | 값 |
|---|---|
| 지금 중계되는 도구 | 219,706 |
| 바뀐 뒤 | 217,873 |
| 새로 들어옴 | 1,171 (서버 402개) |
| 빠짐 | 3,004 (readOnlyHint=false 409개 포함) |
| 중계 도구가 처음 생기는 서버 | 254 |
| 중계 도구가 0개가 되는 서버 | 139 |

- 빠지는 도구 상위 항목
  - browser-url-ok: 2,339개. "Check whether a URL can be opened"인 조회 도구지만 'browse' 접두 일치로 통과하던 것이다. 이 서버들은 다른 중계 도구가 있다.
  - calculator_describe 60, checker_answer 51, checker_tree 46
  - counter_quote 11, checkout_link 5
- 처음 사례 mcp/56920(InvoiceOracle)
  - invoice_parse_text와 invoice_validate가 새로 중계된다. invoice_summary는 설명이 조회 동사로 시작하지 않아 빠진다.
  - invoice_ocr는 'ocr'가 허용 동사가 아니라 여전히 빠진다. 동사 목록은 넓히지 않았다.

## 표본 검토 (원자료 `sample-review.json`)
- 각 회차는 새로 들어오는 도구에서 이름·설명이 겹치지 않는 것을 무작위로 뽑았고, 이전 회차 표본과 겹치지 않는다.

| 회차 | 표본 | 섞인 것 | 고친 규칙 |
|---|---|---|---|
| 1 | 220 | armory_version_bumper(버전 올리기), 애매 3건(gpu_quote 수수료 견적, gf.quote 거래 결과, request_quote) | 접두어 뒤 version·quote·recommend·suggest 제외 |
| 2 | 220 | agentlux_list_item(판매 등록), me_compare(사람에게 비교를 맡김) | 접두어 경우 설명의 동작 표현 제외 |
| 3 | 220 | screen_show, record_view_results, haven_check_out, refresh_prices, loop_check_step, artifacts_get_version(load=true), shelf_get(되쓰기) | 설명이 조회 동사로 시작해야 함, 동작 접두어·check_in/out 제외 |
| 4 | 220 | 없음 | - |

- 최종 규칙으로 들어오는 고유 도구는 1,105개다. 그중 1~3차에서 이미 본 366개와 4차 220개를 합쳐 586개(53%)를 검토했다.
- 섞인 것으로 표시한 도구는 최종 규칙에서 모두 빠진다(`tests/test_relay_safe_tool.py`).
- 참고(쓰기 아님, 민감한 읽기): applehealth__sleep_read(risk:medium), clerk.list_api_keys가 있다. 공개 중계는 인증이 필요한 서버를 `admit`에서 거부하므로 그대로 둔다.

## 시험
- `tests/test_relay_safe_tool.py`
  - 허용 예: invoice_parse_text, acc_list_issues, validate.bic, getWeather
  - 거부 예: invoice_delete, scratchpad_checkpoint, browser_drag, counter_quote, 각 회차의 섞인 도구
  - annotation이 먼저 적용되는지
  - collector 시험 호출 범위가 그대로인지
- 관련 모듈을 쓰는 기존 시험 69개 파일을 통과했다.
  - 실패 2건은 `test_storage_inventory`의 이름 규칙 문제로 이 변경과 무관하다. 다른 팀 폴더 `concierge/claude_plugin/.claude-plugin`, `ad_coin/v2/contracts/out`이 원인이다.

## 함께 넣은 것 (공유 브랜치, P1 묶음)
- 카드 사유 칸 `connection_reason`
  - action_tool: "This tool performs an action, so ..."
  - not_verified_read_only: "The Agent Concierge gateway has not verified this tool as read-only, ..."
  - invoice_ocr 같은 조회 도구에 "performs an action"이 붙던 문구가 고쳐진다.
- user_slo 연결 표본의 `reason` 칸
  - 값: policy_blocked, unverified_tool, unrelayed(사유 칸이 없는 옛 카드), connect_failed, no_gateway_endpoint
  - 표본은 빼지 않는다(PM 결정 2).
