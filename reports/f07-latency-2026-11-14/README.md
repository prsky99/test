# F07 지연 기록 (검색과 RAG, 2026-11-14)

현황 검토 F07(서버 지연과 전송 꼬리 지연을 함께 줄이기)의 검색과 RAG 몫 기록입니다. 표본은 지우지 않고 모두 적습니다. 원서버 몫(server, Server-Timing)과 원서버 밖(TLS, 엣지→터널, 대기)을 나눕니다.

- 측정 조건: 공개 주소, 처음 보는 질의, 새 연결, 한국에서 잼(Cloudflare LAX 경유).
- 원자료: `logs/ops/user-slo.jsonl`, `logs/ops/public-full-check.jsonl`, 검색과 RAG scratchpad `f07-1630.json`.

## 표본

| 시각 | 경로 | 질의 | 전체 | 원서버 | 원서버 큰 구간 | TLS | 원서버 밖 나머지 | 판단 |
|---|---|---|---|---|---|---|---|---|
| 15:34 | /api/agent/v1/openapi.json | - | 9.54초 | 0.01초(로컬) | 생성 비용 없음(5.7KB, gzip 1.6KB) | - | 거의 전부 | no-store라 매번 터널 통과. 3b889408로 발견 문서 캐시(1시간)로 바꿈. Cloudflare 캐시 규칙 경로 목록에도 추가해야 HIT |
| 16:2x | /api/agent/v1/openapi.json | - | 1.27·2.10·6.58초 | 0.01초 | - | 0.49·1.33·1.98초 | 0.8~3.5초 | 위와 같음 |
| 15:34 | /api/agent/v1/discover | (점검기 질의) | 2.77초 | 기록 없음 | Server-Timing 없음 | - | - | 아래 16:2x 재현 참고 |
| 16:2x | /api/agent/v1/discover | web search 849 | 4.37초 | 1.48초(로컬 별도 질의) | 추천 경로 | - | 약 2.9초 | discover에 Server-Timing이 없어 구간을 못 나눔 → 다음 frontend에서 붙일 것 |
| 16:2x | /api/agent/v1/discover | weather forecast 100 | 5.60초 | 1.83초(로컬 별도 질의) | 추천 경로 | - | 약 3.8초 | 같음 |
| 15:34 | /api/explore | web search 593 | 2.73초 | 기록 없음 | - | - | - | 아래 재현 참고 |
| 16:2x | /api/explore | web search 252 | 3.17초 | 1.10초 | ann 0.30·documents 0.29·projection 0.09 | - | 약 2.1초 | 원서버 1.1초 중 문서 읽기가 재생성 영향(평소 0.13초) |
| 16:2x | /api/explore | code review 793 | 7.20초 | 0.62초 | ann 0.27·projection 0.26·documents 0.19 | - | 약 6.6초 | 원서버 밖이 거의 전부 |
| 16:05 | /api/explore | 번역 for my team 626 | 6.13초 | 1.14초 | ann 0.53·documents 0.42·relax 0.34·projection 0.20 | 0.49초 | 약 4.5초 | TLS는 0.49초뿐이고 나머지 4.5초는 엣지→터널·대기 |
| 16:05 | /api/explore | news headlines with history 189 | 5.81초 | 1.61초 | documents 0.70·ann 0.52·admission 0.22 | 3.42초 | 약 0.8초 | TLS가 대부분 |
| 16:05 | find_agents | code review bulk 802 | 7.00초 | 3.11초 | step_search 2.23(ann 0.57·admission 0.70·projection 0.36·resource_read 0.27·registry 0.23)·step_prepare 0.82 | 3.04초 | 약 0.85초 | 서버 3.1초 + TLS 3.0초. split·narrow 없음('bulk'가 0건을 만들지 않음) |
| 16:25 | find_agents | code review bulk 851 / code review 560 / code review bulk 996 | 3.67 / 4.73 / 2.53초 | 2.68 / 1.90 / 1.23초 | step_search 2.56 / 1.72 / 0.92 | - | 1.0~2.8초 | 'bulk' 유무보다 처음 보는 질의(차가운 ann)의 차이가 큼 |

## 원서버 몫 1.1초를 줄일 수 있는가 (탐색)

- documents(search_document) 0.19~0.70초: 평소 0.13~0.23초입니다. 오늘 낮 탐색 문서 재생성(정책 해시 5d3d8f6a, 13:5x 끝 예정)의 쓰기 부하로 늘었습니다. 재생성이 끝나면 돌아오는지 14·15·16시 user_slo로 확인합니다. 앞으로 재생성은 늘 같은 속도(19394c46, 분당 1,200개, 낮은 우선순위)로 돕니다.
- ann 0.27~0.82초: 처음 보는 주제에서 DB 그래프 페이지를 읽는 비용입니다(06:3x 보고: shared_buffers 2GB에 HNSW 1.6GB와 resources 773MB가 함께 들어가지 않음, 적중률 90.3%). 줄이는 안은 shared_buffers 상향 또는 pg_prewarm인데, DB 설정 변경이라 사용자 승인이 필요합니다(PM 결정 대기).
- relax 0.34초('번역 for my team'): 검색 결과가 적을 때 조건을 푸는 두 번째 검색입니다. 성격 낱말('for my team')을 처음부터 조건으로 받는 C 묶음(11-16 밤)이 이 두 번째 검색을 없앱니다.
- projection 0.09~0.36초: 후보 행 읽기라 ann과 같은 버퍼 문제입니다.

## 추천(find_agents) 몫

- step_search 0.92~2.56초가 대부분입니다. 처음 보는 질의에서는 후보 문구 임베딩(semantic)과 ann이 큽니다. 줄이는 안(06:3x 보고 (a)): jobs가 등급 A 후보 문구 벡터를 미리 만들어 두고 frontend가 시작할 때 읽게 하면, 처음 보는 질의의 semantic 0.16~0.44초가 빠집니다(PM 결정 대기).
- 'code review' 추천 품질 문제: 1위가 Front-End Checklist, 다음이 Rooms by Aurmada·No Niner Data Tools로 과제와 맞지 않습니다. F06(실제 과제 추적)에 넣습니다.

## 원서버 밖 몫

- TLS가 0.44~3.42초로 크게 흔들리고, TLS 뒤 엣지→터널 구간이 0.8~4.5초입니다. 엣지 HIT 페이지도 8초가 나온 것(15:34 /agents/best)으로 보아 맥 밖 경로(한국→LAX) 문제입니다. 운영·SRE 몫(엣지 캐시 확대, 터널 상태)입니다.
- 검색과 RAG가 할 수 있는 것: 캐시할 수 있는 응답을 no-store로 내보내지 않기(openapi.json처럼). 같은 문제가 있는 경로를 찾아 이 표에 더합니다.

## 17:43 MCP search 서버 3.42초 (운영·SRE 18:2x 넘김)

- 원인은 측정 방식 변경입니다. 16:29부터 전수 점검이 MCP 도구마다 처음 보는 질의를 따로 씁니다(877faf38). 그 전에는 search가 chat 뒤에 같은 질의로 불려 데워진 캐시를 썼습니다(00:18 1.34초·11:28 1.14초·15:34 0.65초). 17:43이 바뀐 뒤 첫 회차라, search가 처음으로 차가운 값을 냈습니다.
- 재생성·벡터 그래프 쪽은 원인이 아님: 탐색 문서 재생성은 끝났고(5d3d8f6a 423,252개, 대기열 0), 벡터 색인 매시간 기록(15·16·17·18시)에 튀는 값이 없습니다(half_a2a 시간당 65~82만 블록, 공용 그래프 검색 0·유지 읽기 26~28만 블록).
- 18:2x 재현(공개 주소, 처음 보는 질의 → 같은 질의 다시): MCP search도 같은 추천 경로(step_search·semantic·ann·admission_loop)라 차가운 서버 1.28~3.38초, 데워진 0.68~2.84초. 큰 몫은 cpu 0.37~1.10·ann 0.45~0.78·admission_loop 0.16~0.91·semantic 0.10~0.45초입니다.
- 결론: 회귀가 아니라 '처음 보는 질의 추천' 비용이 search에서도 보이게 된 것입니다. 줄이는 순서는 위 '추천(find_agents) 몫'과 같습니다(후보 벡터 미리 계산, admission_loop·registry 분석, 공용 그래프 삭제로 버퍼 경쟁 줄이기).
