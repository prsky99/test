# 운영 계보 eb28348f를 개발 브랜치에 병합 (2026-11-16, 검색과 RAG)

PM 11-16 09:3x 최우선 지시에 따른 기록이다.

## 왜 했나

운영 frontend·jobs는 `bc1116e-*-20261115-g3` 버전(eb28348f)으로 돈다. 이 커밋은 `rag/bc-1116e` 계보에서 만든 묶음이다. 그런데 이 계보는 개발 브랜치 `claude/hopeful-darwin-i3qj6n`에 한 번도 합쳐진 적이 없었다.

- 공통 조상은 1b25f22f(11-13 15:33)다.
- 운영에만 있는 커밋이 129개, 브랜치에만 있는 커밋이 752개였다.
- 그래서 운영·SRE가 브랜치 끝으로 낮 묶음을 패키징하면, 운영 기능 일부(selection.py의 수식어 처리 등)가 빠지는 상태였다.

## 한 일

- **방식:** 별도 worktree에서 merge 커밋(`954fb93f`)으로 합쳤다. rebase·기록 다시 쓰기는 하지 않았고, 누구의 커밋도 빼지 않았다. 공유 작업본은 건드리지 않았다.
- **커밋 2개:**
  - `954fb93f` 병합: 정책 해시 파일이 운영 eb28348f와 바이트까지 같다.
  - `b5300dd0` 287f7c9d 다시 얹기(밤 전용): 낮 릴리스에서는 이 커밋을 되돌림으로 빼고, 11-18 00:30 밤 배포 때는 그대로 쓴다.

## 충돌 105개 파일과 해결 원칙

충돌은 양쪽에서 새로 만든 파일 63개와 양쪽에서 고친 파일 42개였다. 원칙은 "운영 쪽의 고유한 변경만 가져오고, 브랜치가 이미 더 새로 만든 것은 되돌리지 않는다"이다.

| 분류 | 파일 수 | 해결 |
|---|---|---|
| 운영 판 = 브랜치의 예전 판(묶음이 개발 파일을 복사한 것) | 90 | 브랜치 판 유지 |
| 브랜치 판 = 운영의 예전 판 | 1 | 운영 판(tests/test_chat_parallel_parts.py) |
| 양쪽이 다르게 바뀜 | 14 | 운영 판의 출처인 가장 가까운 브랜치 판을 기준으로 3방향 병합한 뒤 한 줄씩 확인 |

14개 파일은 이렇게 정리했다.

- **운영 변경을 가져옴(7개):**
  - application_store_sql.json: 양쪽 문장 합집합
  - fast_chat.py, hybrid_explore.py: Chat 수식어 목록을 Explore와 공유
  - front.py: usage_guide.tools_ref
  - 시험 3개: test_explore_relaxation, test_postgres_ann, test_gateway_exposure(지오코딩 시험 2개 추가)
- **브랜치에 이미 들어 있어 더할 것 없음(4개):** necklace_surface.py, fallback_agents/agents.py, tests/conftest.py, tests/test_fallback_agents.py
- **브랜치 판 유지(3개):** 운영 쪽 변경이 나중에 추가된 코드를 모르는 옛 코드뿐이었다.
  - edge_gateway/service.py: PROVIDER_RATE_LIMITED
  - scripts/release_gate.py: 그대로 합치면 `import time`이 빠져 깨진다.
  - tests/test_ad_coin_v2_paid_audit.py: 밤 리허설 시험
- **시험에서 찾아 브랜치 판으로 되돌림(1개):** tests/test_ad_coin_v2_sponsored.py. git이 자동 병합하면서 운영 쪽의 `Vary: CF-IPCountry, Prefer, Ads, X-Ads`를 가져왔다. 그런데 브랜치는 a4625fab에서 광고 끄기를 없앴다(사용자 결정 11-15). 그래서 지금 코드의 Vary는 `CF-IPCountry`이고, 시험도 그에 맞게 되돌렸다.

운영이 공통 조상 이후 바꾼 402개 파일은 모두 반영되거나 대체됐다.

| 상태 | 파일 수 |
|---|---|
| eb28348f와 같음 | 266 |
| 브랜치에 더 새 판이 있음 | 120 |
| 위 표의 수동 병합 | 12 |
| git 자동 병합(collector/capabilities.py, collector/health.py, gateway_exposure.py, explore_document_reader.py) | 4 |

## 확인한 숫자

- **policy_hash():** 병합본과 eb28348f 모두 `8e4768d8c461651542fad4ee3b0313d1e3ef9cf0562fc2b580de728fac588510`
- **정책 해시 파일 8개:** 병합본이 eb28348f와 바이트까지 같다(selection.py 포함, 287f7c9d 제외 상태).
- **등록 SQL:**
  - application_store_sql.json: 운영 쪽 값과 브랜치 쪽 값이 하나도 빠지지 않았다. source_manifest 해시는 예외다. `--check`가 보지 않는 값이고(11-12), 브랜치 끝에서도 이미 32개가 어긋나 있었다. 병합 뒤에는 28개다.
  - ad_coin/sql_registry.json: 운영 605개 문장이 모두 들어 있다(합계 625개).
  - 목록을 통째로 다시 만들지 않았다.
- **시험:** heavy_slot으로 병합 커밋 상태에서 바뀐 모듈의 시험 181개 파일을 돌렸다. 결과는 아래 "시험 결과"에 적는다.

## 운영·SRE day_bundle_check 결과 (PM 지시, 954fb93f와 b5300dd0)

- **954fb93f(병합):**
  - 정책 해시: 운영 커밋·운영 폴더·병합본이 모두 `8e4768d8c4616515`로 같다(SAME).
  - 계획 커밋 누락: 없음.
- **b5300dd0(287f7c9d 다시 얹음):** 정책 해시가 `a7a9f2f43625bc3d`로 다르다(DIFFERENT). selection.py만 다르고, 예상대로다. 낮 릴리스에서는 이 커밋을 되돌린다.
- **운영 전용 줄:** 병합 전 945줄 가운데 776줄이 병합본에 없다고 나온다. 이 776줄을 한 줄씩 확인했고, 모두 "브랜치의 새 코드로 대체됨"이다.
  - **644줄:** 운영 판 파일 전체가 브랜치의 예전 판과 바이트까지 같은 파일(120개)에 있다. 브랜치가 그 뒤에 고친 줄이다.
  - **132줄:** 병합한 파일 10개에 있다. 각 줄을 그 줄을 바꾼 브랜치 커밋과 대조했다(git log -S). 커밋을 찾지 못한 줄은 병합본에 들여쓰기만 바뀐 채 들어 있다.
  - 대조된 브랜치 커밋의 예:
    - front.py: a4625fab(광고 항상 노출, ads=none 제거, 사용자 결정 11-15), 8ad10128, c6a194bc
    - necklace_surface.py: 5d25bec9, 734c0da9(임시 멤버 공개, 사용자 지시)
    - fallback_agents/agents.py: f88e98f3, 82d1a98d, eefdb282
    - fast_chat.py: bc8c5948, 56174428
    - edge_gateway/service.py: b47872a5, b7632232
  - 공통 조상 판까지 넣어 다시 세면, 776줄 모두 브랜치에 한때 있었고 브랜치가 나중에 바꾼 줄이다. 확인되지 않은 줄은 0줄이다.

## 시험 결과

heavy_slot으로 병합 커밋에서 바뀐 모듈을 쓰는 시험 174개 파일을 돌렸다. 브라우저 시험 7개는 이 환경에 playwright가 없어 뺐다.

- **결과:** 2,472 통과, 13 실패. 실패 13건을 병합 전 브랜치 끝(4ab093ce)과 운영 eb28348f에서도 돌려 비교했다.

| 실패 | 건수 | 판단 |
|---|---|---|
| 병합 전 브랜치 끝에서도 실패 | 8 | 병합과 무관(기존 실패) |
| 운영 eb28348f에서도 실패 | 2 | selection.py를 운영 판에 맞췄기 때문(PM 조건). 운영이 이미 같은 결과다 |
| 병합이 만든 실패 | 1 | 고침(위 test_ad_coin_v2_sponsored) |
| 부하 때문(따로 돌리면 통과) | 2 | test_semantic_first, test_tool_search_benchmark |

- **기존 실패 8건(브랜치 끝):**
  - test_customer_workspace_launch
  - test_explore_retest_fixes 3건
  - test_front_dashboard_menus(영어 전용 검사)
  - test_front_register_chat_security
  - test_search_speed_quality_round2
  - test_workspace_platform_integration
- **운영과 같은 실패 2건:** test_chat_determinism `[task4]`, test_review_ranking_rules `[summarize a pdf research paper]`. 운영 selection은 `document`를 능력 단어에서 뺀다. 두 시험 파일은 양쪽 모두 공통 조상 뒤로 바뀌지 않았다.
- **병합이 새로 만든 실패:** 0건(고친 뒤).

## 다시 생기지 않게 하는 규칙 제안

1. **팀 브랜치로 운영에 배포했으면 그날 안에 개발 브랜치에 merge 커밋으로 합친다.** 배포한 팀이 하고, 현황판 '운영 중인 버전' 줄에 "개발 브랜치 병합: <커밋>"을 함께 적는다.
2. **합치지 못한 채로는 다음 배포를 하지 않는다.** `deploy`나 release_gate가 활성 버전의 커밋이 `origin/claude/hopeful-darwin-i3qj6n`의 조상인지 확인하고, 아니면 경고한다. 도구로 막는 것은 운영·SRE와 상의한다.
3. **밤 전용(정책 해시) 변경은 병합 위에 따로 얹는 커밋으로 둔다.** 그러면 낮 릴리스가 되돌림 한 번으로 뺄 수 있다.
