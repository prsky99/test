# 가격 명시 목록의 price_usdc 일괄 수정 검토 (2026-11-12 01:4x, 검색과 RAG)

PM 지시 ⑦: 가격이 적힌 목록의 price_usdc 0을 운영 DB에서 null로 바꿀지 판단하기 위한 범위·영향·복구 자료.

## 범위 (운영 읽기 전용, 01:3x)
- price_usdc=0인 행: 247,117건
- 그중 이름·설명에 가격이 적힌 행(`price_status.stated_price`, 0원 금액 제외): **1,620건**
  - 활성·정상(healthy·reachable): MCP 699, A2A 400 → 1,099건
  - 활성·기타 39건, 비활성 482건
- 11-11에 센 1,745건은 0원 금액("$0 per call")을 빼기 전 규칙 기준이다.
- 대상 id 목록: scratchpad `price_scope_ids.json`(실행 직전에 다시 뽑는다)

## 이미 해결된 부분 (DB 변경 없음, f2f3520b)
에이전트 응답(find_agents·search·탐색 API·상세)·Chat 문구·알림·Free 배지는 응답을 만들 때 같은 규칙으로 판단한다. 가격이 적힌 목록은 `price_usdc: null`, `price_status: "paid_or_unknown"`이다. DB 값이 0이어도 사용자와 에이전트에게는 0이나 Free로 보이지 않는다.

## DB를 바꾸면 생기는 일 (운영 트리거 본문 확인)
`resources`의 price_usdc가 바뀌면 행마다 다음 일이 생긴다.
1. `application_vector_invalidate`: `vec_resources` 행을 지우고 세대를 올린다. 다시 임베딩될 때까지 그 목록은 벡터 검색에서 빠진다. 1,620건을 다시 임베딩해야 한다.
2. `application_observation_generation`: 세대를 올리고 `capability_eligibility` 행을 지운다. 다시 계산될 때까지 추천 자격이 비어 있다.
3. 탐색 문서는 원천(이름·설명·도구)이 같으므로 0bc58599 뒤에는 세대만 올린다. 재작성은 없다.

수집기도 고쳐야 한다. MCP는 늘 0, A2A는 가격 정보가 없으면 0을 쓰기 때문에, DB만 바꾸면 다음 수집에서 다시 0이 된다. 그런데 수집기가 null을 쓰게 바꾸면 `Store._upsert`는 이를 내용 변경으로 본다. 그러면 `cap_checked_at`·`eval_at`이 지워져 1,620건 모두 기능 조사와 품질 평가를 다시 한다. 막으려면 `_activity_only`가 "가격 0↔null만 바뀐 경우"를 활동 변경으로 보게 해야 한다.

## 선택지
- **A(권장): DB는 그대로 둔다.** 응답 규칙(f2f3520b)으로 표시는 이미 맞다. 남는 영향은 옛 `ranking.py`의 가격 가중치 0.07뿐이다(0은 1.0, null은 0.5). 필요하면 여기에도 같은 규칙을 쓴다(코드만, DB 변경 없음).
- **B: DB를 바꾼다.** 순서는 다음과 같다.
  ① jobs 코드: 수집기가 가격 명시 목록에 null을 쓰고, `_activity_only`가 0↔null 변화를 재조사 없이 처리한다.
  ② 사본 리허설로 재임베딩과 자격 재계산에 걸리는 시간을 잰다.
  ③ 승인을 받는다.
  ④ 낮은 시간대에 100건씩 나눠 바꾼다.

## B의 SQL (실행 전 사본에서 확인)
```sql
-- 적용: 대상 id만, 지금 0인 행만
UPDATE resources SET price_usdc = NULL WHERE id = ANY(%(ids)s) AND price_usdc = 0;
-- 복구: 같은 id 중 null인 행만 0으로
UPDATE resources SET price_usdc = 0 WHERE id = ANY(%(ids)s) AND price_usdc IS NULL;
```
복구 SQL을 실행해도 트리거가 한 번 더 움직인다(재임베딩·자격 재계산).

## 사본 결과
아직 없다. 01:00~08:00은 새벽 DB 창(리허설·적용)과 사본을 같이 쓰기 때문에 돌리지 않았다. B를 고르면 08시 묶음 확인 뒤 `scripts.db_change_rehearsal`로 사본에서 돌리고 결과를 덧붙인다.
