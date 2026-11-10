# 시험 결과 보고서 품질 점검 (Claude Opus 5.5, 2026-11-10)

## 방법
- 대상: agent_test_reports 20,998건(A2A 10,276, MCP 10,259, x402 463)
- 표본: 종류·등급·성공 여부·작성 주로 나눈 층에서 고르게 813건
- 모델과 기준: Claude Opus 5.5(effort medium), Message Batches API. 채점 기준은 AQEF-30 5개 영역(근거·정확성·명확성·실행 가능성·안전), 각 20점.
- 실행기: scripts/report_quality_api.py(커밋 53027318)
- 비용: 25.28달러(Batch 50% 할인 적용). 5건 시험에 0.17달러.

## 결과
- 채점 810건(3건은 형식 오류)
  - 중앙값 68점, 하위 10%는 52점, 85점 미만은 810건 전부
  - 종류별 평균: MCP 67.2, A2A 66.6, x402 54.5
- 지적 5,905건: 높음 1,451, 중간 2,741, 낮음 1,713

| 문제 | 건수 | 뜻 |
|---|---|---|
| missing_limitation | 1,037 | 시험하지 않은 범위를 밝히지 않음 |
| unsupported_claim | 998 | 측정 데이터에 없는 주장 |
| vague_language | 582 | 모호한 표현 |
| overclaim_capability | 567 | 기능 과장 |
| stale_or_contradictory | 549 | 앞뒤가 맞지 않거나 오래된 내용 |
| grade_inconsistent | 487 | 등급과 결과 불일치 |
| formatting | 466 | 형식 문제 |
| number_mismatch | 379 | 본문 숫자가 측정값과 다름 |
| upstream_leak | 64 | 내부 정보 노출(게이트웨이 경로 헤더, 내부 표 이름 등) |

- 결론: 문제는 개별 보고서가 아니라 보고서를 만드는 틀에서 반복된다.

## 반영
- 개선본 810건 가운데 708건이 검증을 통과해 11:22에 운영 DB에 반영했다.
  - 검증 기준: 원문·측정값에 없는 숫자 금지, 영어, 모든 항목 존재, pros/cons 배열
  - 원문 백업: logs/ops/report-quality/backup-20261110-112219.jsonl
  - 실행 SQL: logs/ops/report-quality/apply-20261110-112219.sql
- 102건은 원문에 없는 숫자가 들어가 반영하지 않았다.

## 비밀값 노출 전수 검사 (20,998건, 코드 검사)
- 개인 키 형식(0x+64자리): 50건. 모두 예제 자리표시자(0x0123…, 0x0000…)이고 실제 키는 없다.
- JWT 형식: 2건. 가짜 예제 토큰(만료 없음, 가짜 sub)이다.
- PEM 개인 키, sk- 키: 0건.
- 내부 정보: X-Gateway-Route 헤더 32건, 내부 표 이름 agent_workflows 41건, localhost·사설 주소 2건. 다음 개선 배치에서 지운다.
