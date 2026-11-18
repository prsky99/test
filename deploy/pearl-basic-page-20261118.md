# 증거 스냅샷에 없는 진주 에이전트의 페이지 (성장·유통, PM 11-18 11:4x 결함 보고)

## 결함
- 진주인데 증거 스냅샷(task-pages.json의 catalog)에 없는 에이전트는 `/agent/<id>`에서 기본 페이지(`growth_catalog._render_basic`)가 열려 "No recorded evidence yet"라고 쓰고 진주 표시가 없었다(예: 32931 BenchGecko, package.risk 최종 진주 89.7점, 2일 확인). 진주 시험 기록이 있는데 "기록된 증거 없음"이라고 쓰는 것은 사실과 반대였다.
- 센 결과: 공개 진주 60개 에이전트 중 **34개**가 이 분기에 걸린다(나머지 26개는 증거 페이지). 서버가 쓰는 읽기 함수 `growth_pages.Snapshot.read()`를 코드로 불러 세었다(요청 없이): `task-pages.json`의 `catalog` 목록에는 8,768개뿐인데, `read()`가 task 페이지에 나오는 에이전트 288개를 catalog에 더해 9,056개로 만든다. 원본 목록만 보면 진주 47개가 빠지는 것으로 보이지만 `read()` 기준으로는 34개다. 처음에는 원서버에 60건을 요청해 같은 34를 얻었는데, 대량 요청 금지 규칙 위반이라 이 방법으로 바꿨다. 목록은 같은 폴더의 `cloudflare-purge-urls-pearl-basic-20261118.txt`(34개 주소)에 있다.

## 고친 것
- 기본 페이지도 `pearl_blocks(rid)`를 부른다: 제목 줄 배지("Final pearl, #1 for …"/"Verified pearl", 약관 금지이면 직접 연결 문구), 맨 위 "Verified role tasks" 카드(역할별 통과 수·서로 다른 날·마지막 확인·방법 링크), 설명과 카드 아래 문장이 "No recorded evidence yet" 대신 "Evidence: the role task results above. A full evidence page appears once a test report or a recent successful check is recorded."가 된다. 진주가 아닌 에이전트의 기본 페이지는 그대로다.
- 시험: `tests/test_pearl_badge.py::test_a_pearl_without_an_evidence_page_is_not_shown_as_having_no_evidence`.

## 퍼지
- 기본 페이지는 `BASIC_TTL` 10분 메모에 엣지 6시간(5a30dca0)이 겹친다. 배포 직후 34개 주소를 퍼지하면 바로 바뀐다(30개와 4개 두 번, 실행 PM). 퍼지하지 않으면 엣지의 옛 사본이 최대 6시간 남는다.
