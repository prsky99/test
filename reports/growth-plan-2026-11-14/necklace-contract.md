# 목걸이 공개 표면의 데이터 계약 (초안, 성장·유통 → 검색과 RAG·운영·SRE, PM 11-14 04:3x 2번)

목걸이 웹 페이지·MCP 도구·A2A 기술은 **목걸이 판정 결과를 읽기만** 한다.
- 판정은 검색과 RAG가 하고(전략 6절 2·3번), 재시험·교체는 운영·SRE가 한다(5번).
- 표면 쪽은 판정을 다시 하지 않는다.
- 운영 DB 구조를 바꾸지 않도록(바꾸면 리허설·승인 필요) 첫 판은 **스냅샷 JSON 한 개**로 주고받는 것을 제안한다.

## 1. 파일

- 위치: `gateway-data/necklaces/necklaces.json`(git 제외). jobs가 판정 뒤에 쓰고, frontend가 읽는다(task-pages.json과 같은 방식: 원자적 교체, 크기 상한).
- 갱신: 판정·재시험이 끝날 때마다. 표면은 파일 수정 시각으로 캐시를 무효화한다.

## 2. 항목 하나

```json
{
  "slug": "trip-brief",
  "name": "Trip brief",
  "summary": "Weather, exchange rate and local facts for one city, in one answer.",
  "template_id": 31,
  "status": "live",
  "pearls": [
    {"resource_id": 133020, "role": "weather", "tool": "get_forecast"},
    {"resource_id": 140112, "role": "exchange rate", "tool": "convert"}
  ],
  "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
  "quality": {
    "answer_set": "trip-brief-v1", "cases": 30,
    "success_rate": 0.9, "best_single_rate": 0.7, "delta_pp": 20.0,
    "tested_at": "2026-11-20T03:10:00Z"
  },
  "cost": {"usdc_per_run": 0, "p50_ms": 3200, "p95_ms": 4800},
  "held_reason": null
}
```

| 필드 | 뜻 | 표면에서 |
|---|---|---|
| `slug` | 공개 주소·도구 이름의 바탕(소문자·하이픈, 40자 이하, 바뀌지 않음) | `/necklaces/<slug>`, MCP 도구 `<slug>`(하이픈→밑줄), A2A 기술 id |
| `status` | `live` 또는 `held` | `held`면 페이지는 200으로 남기고 실행 버튼·도구·기술을 막는다. 이유는 `held_reason` |
| `pearls` | 쓰인 진주(외부 에이전트 id·역할·도구) | 진주 카드 링크(`/agent/<id>`) |
| `template_id` | 실행할 공개 워크플로우 | 실행은 기존 공개 실행 경로(run_workflow) |
| `input_schema` | 목걸이 입력 | MCP 도구 inputSchema, 웹 입력 양식, A2A "run" 예시 |
| `quality` | 같은 정답 세트에서 목걸이·최고 단일 진주 성공률과 Δ | 페이지 "단일 대비 Δ", "최근 시험 성공률" |
| `cost` | 1회 비용(지금은 0)과 지연 | 페이지 "1회 비용·지연" |

## 3. 표면이 지키는 것

- 파일에 `status: live`이고 다음 조건을 모두 만족하는 항목만 노출한다. 하나라도 어긋나면 노출하지 않고 오류 기록을 남긴다(판정 쪽 결함을 숨기지 않기 위해).
  - `pearls` 2개 이상
  - `delta_pp > 0`
  - `tested_at`이 48시간 안
- 숫자는 파일 값을 그대로 쓴다. 표면에서 반올림 외의 계산은 하지 않는다.
- 실행 범위는 MCP `call`·A2A run과 같다(읽기 전용 중계, 결제·자격 증명 없음).

## 4. 정할 것 (검색과 RAG·운영·SRE와)

1. 파일 경로와 쓰는 쪽(검색과 RAG 판정 작업인지, 운영·SRE 재시험 작업인지)
2. `slug` 규칙과 첫 목걸이 5개의 이름
3. `held` 전환을 재시험 작업이 바로 쓰는지
