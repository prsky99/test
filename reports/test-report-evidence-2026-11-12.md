# 시험 결과 보고서 16건 증거 확인 (2026-11-12, 운영·SRE)

PM 11-12 지시: 게시한 16건(#21473~#21488)이 바탕으로 삼은 수집기 시험 호출이 실제로 `tools/call`을 보내 정상 결과를 받았는지 확인.

## 확인 방법

- 수집기 시험 호출(`agent_market/collector/capabilities.py` `_trial`)은 실제 `tools/call`을 보낸다. 다음을 모두 만족할 때만 `ok`로 기록한다.
  - HTTP 2xx
  - JSON-RPC id가 맞음
  - 결과가 비어 있지 않음
  - `isError`가 아님
- 결과 크기(`output_chars`)와 결과 요약(`sample_output`)도 함께 남긴다.
- **시각이 정확히 같은 이유**: `_trial`이 시작 시각(`at`)과 끝 시각(`finished_at`)을 한 번만 재서 `trial_info`에 저장하고, 같은 값을 `Registry.record(started=…, finished=…)`에 그대로 넘긴다. 같은 값을 두 곳에 쓴 것이라 기록 정밀도와는 관계없이 같다.
- 표의 칸
  - 증거 줄: 같은 시작·끝 시각을 가진 `capability_evidence` 실행 기록의 결과와 수
  - 결과 해시: `sample_output`의 sha256 앞 12자

| 보고서 | 자원 | 등급 | 도구 | 시험 ok | 보고서와 시각·도구 일치 | 증거 줄 | 결과 크기 | 지연(ms) | 결과 해시 | 판정 |
|---|---|---|---|---|---|---|---|---|---|---|
| #21473 | 367249 | A | latest_incidents | True | True | succeeded 1 | 665 | 391 | 83673c47d212 | 정상 |
| #21474 | 224120 | A | application_link | True | True | succeeded 1 | 382 | 165 | d5a67237efc8 | 정상 |
| #21475 | 242746 | A | grid_carbon_and_price_now | True | True | succeeded 1 | 3630 | 1363 | fd3eed7b5754 | 정상 |
| #21476 | 252258 | B | find_assets | True | True | succeeded 1 | 5872 | 5220 | d9bb117d73b1 | 정상 |
| #21477 | 278531 | A | search_signals | True | True | succeeded 1 | 3038 | 295 | c22d08a6da51 | 정상 |
| #21478 | 289014 | A | find_music_guides | True | True | succeeded 1 | 261 | 254 | adedc5263648 | 약함: 빈 목록(guides: []) |
| #21479 | 33328 | A | rssa_board_changes | True | True | succeeded 1 | 1244 | 374 | ba4e5e754424 | 정상 |
| #21480 | 38634 | A | num_list_destinations | True | True | succeeded 1 | 20183 | 165 | b1105c0354cb | 정상 |
| #21481 | 392189 | B | analyze_hsk_vocabulary_level | True | True | succeeded 1 | 380 | 355 | e9f141d2259c | 정상 |
| #21482 | 40164 | B | calculator_describe | True | True | succeeded 1 | 3420 | 453 | c22139a54765 | 정상 |
| #21483 | 41855 | B | describe_household_schema | True | True | succeeded 1 | 1847 | 283 | 766c3bedb08c | 정상 |
| #21484 | 47538 | A | list_festivals | True | True | succeeded 1 | 7922 | 239 | 0fb423af77ee | 정상 |
| #21485 | 52999 | B | browser-url-ok | True | True | succeeded 1 | 57 | 184 | 38667e60226b | 약함: 도구가 {"ok":false}로 답함 |
| #21486 | 54555 | B | browser-url-ok | True | True | succeeded 1 | 57 | 135 | 38667e60226b | 약함: 도구가 {"ok":false}로 답함 |
| #21487 | 54820 | B | browser-url-ok | True | True | succeeded 1 | 57 | 140 | 38667e60226b | 약함: 도구가 {"ok":false}로 답함 |
| #21488 | 85893 | B | genmc_docs | True | True | succeeded 1 | 8381 | 766 | 5de66bf73b3a | 정상 |

## 결론

- 16건 모두 실제 `tools/call`이 2xx·정상 응답으로 끝났다. 보고서의 실행 시각·도구는 시험 호출과 같고, 같은 시각의 성공 실행 증거가 1건씩 있다.
- 그중 4건(#21478, #21485, #21486, #21487)은 도구가 실패를 알리거나 빈 결과를 돌려줬다. 과제를 해냈다는 증거로는 약하다.
  - 운영 DB에 공개 여부 칸이 없어서, 비공개로 돌리는 방법은 삭제뿐이다.
  - 삭제 스크립트: `deploy/ops/run-withdraw-weak-reports-20261112.sh`
  - 백업: `gateway-data/backups/weak-reports-20261112`
  - 되돌리기: `deploy/ops/restore-weak-reports-20261112.sql`
  - 실행은 사용자 승인 뒤에 한다(데이터 삭제).
- 재발 방지: 초안 생성기가 결과에 `ok`/`success: false`가 있거나 목록이 모두 빈 시험 호출은 쓰지 않는다(`empty_or_refused`). 위 16건에 적용하면 정확히 이 4건만 걸린다.
