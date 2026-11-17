# 진주 우선: 추천과 Explore의 순서 설계안 (검색과 RAG, 2026-11-18)

PM 과제(11-18, 설계안 마감 11-19 12:00, 배포 11-20 00:30 묶음)에 대한 한 장 설계안이다. 코드는 아직 바꾸지 않았다.

## 1. 결론

- **가산 위치는 정책 해시 밖의 두 곳이다.** 추천은 `gateway_exposure.order_key`, Explore는 `hybrid_explore.explore`의 마지막 정렬(544행)이다. 둘 다 `explore_documents.policy_hash()` 목록(selection, task_requirements, explore_search, execution_policy, capability_registry, collector/usage, postgres_capability_text)에 없다.
  - 따라서 탐색 문서 재생성이 없고, 밤 칸 없이 낮 frontend 묶음으로 낼 수 있다. 11-20 00:30을 기다릴 필요가 없다.
  - selection.py의 순위 키(1096행)에 넣는 안은 2단계로만 둔다. 측정에서 진주가 후보 창 밖에 머무는 것이 확인될 때만 밤 칸에 쓴다.
- **역할 일치는 후보 쪽에서 판정한다.** 이 카드가 고른 도구(`tools[0]`)가 공개 진주 목록에서 그 자원의 진주 역할 도구(`tool`)와 같을 때만 가산한다. 질의 문장에서 역할을 추론하지 않는다(role_catalog 패턴은 도구 이름용이다). 판정이 안 되면 가산하지 않는다.
- **새 DB 조회는 없다.** 공개 진주 파일(`pearls_public.load`, 파일 시각으로 캐시)만 읽는다. 요청 경로의 추가 비용은 사전 조회 몇 번이다.

## 2. 추천 (find_agents·Chat·A2A)

지금 `order_key(item)` = (access_note 있음, standing<0, region_limited, standing<=0)이다. 정렬은 안정 정렬이라 그 뒤는 selection의 순서(실행 성공 여부 → 실행 기록 → 성공 시각 → 최근성 …)를 그대로 따른다.

- 다섯째 칸으로 `pearl_rank`를 더한다. final 0, verified 1, 나머지 2이다. 그러면 무료·실패 아님·지역 조건·최근 실제 성공 다음, 최근성 앞에 놓인다. PM이 지정한 자리와 같다.
- 가산 조건
  - `pearls_public.pearl_of(id)`의 역할 가운데 `tool`이 카드 `tools[0]`와 같은 항목이 있어야 한다.
  - `relayed: False`(제공자 약관 prohibits)이면 가산하지 않는다. 중계 가능한 후보 아래, 지금 자리에 그대로 둔다. 약관이 `unknown`인 9건은 중계 판정을 기존 경로(connection_reason)에 맡긴다.
- Chat도 같은 `order_key`를 쓴다(fast_chat 911·925·939행). 그래서 함께 바뀐다. 그 뒤의 `subject_first`·`condition_first` 재정렬은 판정(주제어·조건 위반)이 다른 후보 사이에서만 순서를 바꾸므로, 진주 가산을 뒤집는 것은 주제나 조건이 덜 맞을 때뿐이다. 이것은 의도한 동작이다.
- 한계: exposure는 selection이 넘긴 limit+3(EXTRA)개 안에서만 순서를 바꾼다. 창 밖의 진주는 끌어오지 않는다. 그래서 3절의 측정에 "진주가 창 안에 있었는가"를 함께 센다.

## 3. Explore

- 544행 정렬 키 (rank(row), 지역 불일치)에 셋째 칸 `pearl_rank`를 더한다. 같은 관련성 단계(이름 일치, 앞 문장 일치 …) 안에서만 진주가 앞선다. 관련성이 낮은 진주가 관련성이 높은 일반 후보를 넘지 않는다.
- Explore 카드에는 추천처럼 고른 도구가 없다. 그래서 역할 일치는 관련성 단계로 대신하고, 가산은 rank(row) ≤ 4(이름이나 앞 문장이 과제를 말함)일 때만 한다.
- `pearls=1` 필터: 공개 진주 목록의 자원 id(final·verified, 지금 43개 자원 가운데 해당분)만 남긴다. 페이지 넘김을 단순하게 하려고, 검색 결과를 거르는 대신 진주 목록에서 바로 카드를 만드는 탐색 모드(`verified` 둘러보기와 같은 길)로 한다. 질의가 있으면 그 안에서 위 rank로 정렬한다.
- prohibits 진주는 Explore에서도 가산하지 않는다. 배지와 "직접 연결" 안내(1b821fb3)는 그대로 보인다.

## 4. 측정 (배포 전후, 공개 주소·처음 보는 질의·새 연결·표본 제외 없음)

| 지표 | 기준 | 멈춤 조건 |
|---|---|---|
| user_slo connect | 배포 전 3회 평균 | 1건이라도 떨어지면 되돌림 |
| Chat 정답 비교 110문항 | 직전 값 | 1문항이라도 떨어지면 원인 확인 전 배포 보류 |
| real_task_score | 직전 회차 | 떨어지면 보류 |
| 진주 역할 질의 20개 1위 비율 | 배포 전 값 | 오르지 않으면 2단계(selection) 검토 |
| 진주가 후보 창(limit+3) 안에 있었던 비율 | 같은 20개 | 낮으면 2단계 근거 |

- 진주 역할 질의 20개는 역할 27개 가운데 final이 있는 역할에서, 역할 이름이 아닌 사용자 말투로 만든다. 측정 표본은 처음 보는 질의로만 쓴다.
- 탐색·추천 응답 시간은 user_slo 정시 측정으로 같이 본다. 가산은 사전 조회라 시간 변화가 없어야 한다.

## 5. 시험

- `order_key`: 같은 standing의 두 후보 중 역할 도구가 맞는 final 진주가 앞선다. 도구가 다르면 그대로이다. relayed False는 그대로이다. 공개 파일이 없으면 기존 순서와 같다.
- Explore: 같은 rank 단계 안에서만 진주가 앞서고, 단계를 넘지 않는다. `pearls=1`은 목록의 id만 낸다.
- gateway_exposure·hybrid_explore를 부르는 시험 파일을 grep해 모두 돌린다(6개 이상이면 heavy_slot 1회).
- conftest의 `_no_live_pearl_list` 덕분에 기존 시험은 진주 없이 돈다. 진주 시험은 자기 파일을 만든다.

## 6. 일정 (PM 11-18 승인: 지금 시작, 11-19 낮 묶음 배포)

1. 11-18: 코드·시험(작업본이 아니라 worktree), PM에 diff. 배포 전 기준값(user_slo connect, Chat 110, real_task_score, 진주 역할 질의 20개의 1위·창 안 비율)을 오늘 잡는다.
2. 11-19 낮 frontend 묶음: 정책 해시 밖이라 낮 배포.
3. 배포 뒤 24시간 측정 → 11-20 보고. 진주가 창 밖에 머무르면 2단계(selection 1096행, 정책 해시 밤 칸)를 제안한다.
