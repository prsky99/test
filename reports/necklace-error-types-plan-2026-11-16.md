# 목걸이 시도 결과를 타입으로 다루기 — 공개 뒤 과제 계획 (워크플로우, 2026-11-16)

PM 11-16 소스 검토 지시 ③. 오늘은 최소 수정만 했다(`agent_market/necklaces/refusals.py`: 우리 쪽 거절 코드를 한 곳에 모음). 이 문서는 그다음 정리의 계획이다.

## 왜 하나
- 지금은 시도 결과가 문자열(`error_class`) 하나다. 실행기·관문·공개 서비스·가치 측정이 각자 "이 문자열이면 무엇"을 판단한다.
- 그래서 같은 종류의 결함이 반복됐다.
  - 11-16 c815d333: 앞 멤버의 예산 거절이 "문서 없음" 판정을 깸
  - 11-16 소스 검토: 공개 경로의 `provider_cap`이 어느 목록에도 없음
- 새 거절 코드가 생길 때마다 다섯 곳을 고쳐야 하는 구조가 원인이다.

## 바꿀 모양
시도마다 결과 타입 하나를 정하고, 모든 판단은 타입으로 한다.

| 타입 | 뜻 | 예 |
|---|---|---|
| answered | 멤버가 계약에 맞는 답을 줌 | 정상 답 |
| not_found | 멤버가 "그런 기록 없음"이라고 답함 | 자체 대체의 not_found, 문서 없음 |
| identity_mismatch | 답은 왔지만 다른 대상에 관한 것 | 다른 회사 문서 |
| unmeasured | 우리 쪽이 막았거나 제공자가 쉬라고 함. 멤버를 평가할 근거가 아님 | budget_*, provider_cap, quota_exhausted, capacity, relay_throttled, PROVIDER_429 |
| member_failed | 멤버가 실패함 | 시간 초과, HTTP 오류, 계약 위반, 예외 |

- `Attempt`에 `outcome` 칸을 더한다. 처음 기록할 때 한 번만 정하고, `error_class`는 세부 사유로 남긴다.
- 자리 판정: 답이 있으면 answered다. 없을 때 not_found나 identity_mismatch 근거가 있고 나머지가 모두 unmeasured면 not_found다. 그 밖에는 failed다.
- 관문 제외: 실패한 필수 자리의 시도가 모두 unmeasured일 때만 제외한다(지금 규칙 그대로, 타입으로 표현).
- 가치 측정의 "보내지 않은 호출"은 unmeasured 가운데 요청이 나가지 않은 것으로 센다(`not_sent`).

## 순서 (공개 뒤)
1. `Attempt.outcome`을 추가하고 `refusals.py`에서 타입을 정하는 함수 하나를 만든다. 옛 기록은 `error_class`로 다시 읽는다.
2. runner의 `no_article`, retest의 `unmeasured_failure`·`not_measured`, service의 `capacity_failure`, value의 호출 수를 타입으로 바꾼다. 결과가 같은지 지난 회차 원자료로 재생해 대조한다.
3. 실행 기록과 관문 기록에 `outcome`을 함께 남긴다. 화면과 보고서는 그 뒤에 바꾼다.
4. 새 거절 코드를 추가하는 곳을 `refusals.py` 하나로 정하고, 정해지지 않은 코드가 나오면 시험이 실패하게 한다(목록 밖 코드 검사).

## 지키는 것
- 관문 회차 사이에는 판정 코드를 바꾸지 않는다.
- 바꾸기 전과 뒤의 판정이 같은지 지난 회차 원자료로 확인한 뒤 배포한다.
