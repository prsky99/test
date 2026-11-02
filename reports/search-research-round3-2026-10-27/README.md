# 남은 검색 문제: 논문·커뮤니티 조사 후 개선 (2026-10-27)

## 조사 결과

| 문제 | 참고 자료 | 적용 |
|---|---|---|
| 지역 한정 날씨 오답 | 지역 범위 판정(Geographic Scope Resolution) 연구: 일반 지명 사전보다 **분야에 맞춘 지명 사전(focused gazetteer)**이 정밀도가 높다 ([UFMG 학위논문](https://repositorio.ufmg.br/handle/1843/36251)). GeoTxt·HeidelPlace도 지명 사전 기반 판정 ([GeoTxt](https://pure.psu.edu/en/publications/geotxt-a-scalable-geoparsing-system-for-unstructured-text-geoloca/), [HeidelPlace](https://ds.ifi.uni-heidelberg.de/files/Team/aspitz/publications/Richter_et_al_2017_HeidelPlace_An_Extensible_Framework_for_Geoparsing.pdf)) | 카탈로그에 자주 나오는 도시·지역 약 120개를 지역 코드에 연결한 **집중 지명 사전**을 추가했다. 요청한 곳(서울)과 서비스가 다루는 곳(푸껫, 하와이)이 다르면 제외한다 |
| 처음 보는 검색어 지연 | 검색엔진 캐시 연구: 질의 기록의 인기 질의를 **정적 캐시**로 미리 계산하고 나머지는 동적 캐시(LRU)로 처리하는 방식, 그리고 결과보다 중간 계산(포스팅 목록)을 캐시하면 적중률이 높다 ([Baeza-Yates 외 2007](https://publications.cnr.it/doc/91700), [Fagni 외 2006 요약](https://didawiki.cli.di.unipi.it/lib/exe/fetch.php/wma/laweb2008-pastqueries.pdf), [ML 기반 결과 캐시 2017](https://repository.bilkent.edu.tr/bitstream/11693/37374/1/A%20machine%20learning%20approach%20for%20result%20caching%20in%20web%20search%20engines.pdf)) | ① **중간 계산 캐시:** 에이전트별 관련도 판정 캐시를 30초·4,096개에서 10분·32,768개로 늘렸다. 키에 에이전트 내용 전체가 들어가 있어, 내용이 바뀌면 다시 계산한다. ② **정적+동적 결과 캐시:** 칩 24개에 더해, 1시간 안에 3번 이상 들어온 검색어를 미리 계산한다(서버 메모리에서만 집계, 저장·표시 없음, 숫자 5자리 이상·이메일 형식 제외) |
| 여러 도구 묶음 쏠림·근거 없는 순위 | MCP 레지스트리 비교 글: 목록은 쉽고 **순서가 어렵다**. 근거(검증)·최신성·중복 정리가 핵심이고, 1위에 근거가 붙는지가 시험 기준이다 ([DEV Community](https://dev.to/skillselion/mcp-registries-in-2026-compared-one-is-canonical-one-is-huge-and-almost-none-can-tell-you-what-147l), [Glama 레지스트리](https://glama.ai/blog/2025-07-05-mcp-registry-standardizing-server-discovery)). 도구 검색 연구: 의미 유사도만으로는 중복 도구를 고르기 쉽다(COLT, [arXiv 2405.16089](https://fugumt.com/fugumt/paper_check/2405.16089v2)) | 앞서 적용한 주 기능 우선 + 최근 검증 순서 + 제공자 중복 정리가 이 권고와 같다. 이번에는 추가 변경 없음 |
| GitHub 이슈·YouTube 요약 추천 약함 | Re-Invoke(EMNLP 2024): 색인할 때 도구마다 예상 질의를 생성하고, 질의할 때 의도를 추출해 여러 관점으로 비교하면 단일 도구 nDCG@5가 20% 오른다 ([ACL Anthology](https://preview.aclanthology.org/watermark/2024.findings-emnlp.270)) | 조사해 보니 GitHub 이슈는 순위 문제가 아니라 **검증된 GitHub 이슈 도구가 카탈로그에 없는 문제**다. 이슈 도구 없는 저장소 통계 서버, GitHub가 아닌 Gluecron만 있다. Re-Invoke 방식(에이전트별 예상 질의 생성)은 다음 단계로 남긴다 |

## 결과 (운영 카탈로그, 읽기 전용)

| 항목 | 이전 | 이번 |
|---|---|---|
| "서울 날씨" | 푸껫 부동산 서비스의 날씨 도구 포함 | met.no, echorune radar 등 지역 제한 없는 날씨 서비스만 |
| "weather forecast seoul"(탐색) | 하와이·푸껫 전용 서비스 포함 가능 | 지역이 다른 전용 서비스 제외 |
| 같은 검색 재실행(탐색) | weather forecast seoul 5.7초 | 1.5초 |
| | code review 4.6초 | 1.6초 |
| | calendar 4.8초 | 3.0초 |
| 칩 검색 | 서버 11ms(이전 배포) | 그대로, 자주 쓰는 검색어로 범위 확대 |

## 검증
- 새 테스트 8건 추가. `tests/test_search_speed_quality_round2.py`는 총 17건 통과.
- 회귀 테스트 778건(탐색·채팅·추천·워크플로우·등록·지역 제약·수집기), 브라우저 60건 통과. 공개 프론트엔드 검사 위반 0건.
- 스테이징 289건 중 288건 통과. 실패 1건은 다른 작업자의 미배포 기능(MCP `server/discover`) 테스트다. 그 코드는 배포 묶음에서 뺐다.
- 테스트 중 운영 PID 변화 없음.

## 배포 상태
- 패키징 완료: `geo-cache-frontend-20261027-r1`, `geo-cache-admin-20261027-r1`.
- 이번 요청에 배포 지시가 없어 자동 차단되었다. **승인 후 배포 예정.**

## 다음 단계
- **Re-Invoke 방식 색인:** 검증된 에이전트(수천 개)마다 지역 모델로 예상 질의 3~5개를 미리 생성해 검색 색인에 더한다. 처음 보는 검색어의 관련도와 속도를 함께 높일 수 있다. 모델 호출이 많아 별도 작업으로 진행해야 한다.
- **GitHub 이슈 도구 수집:** 공식 GitHub MCP는 인증이 필요해 현재 정책상 추천되지 않는다. 인증 없는 공개 이슈 검색 도구를 수집 대상으로 추가해야 한다.
