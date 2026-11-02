# 날씨·뉴스 적격 후보 복구 검증

2026-10-26. 소스 수정·검증 후 사용자 운영 반영까지 확인 완료. 에이전트는 운영 프로세스를 교체하지 않았음. 최종 결과는 `post-deploy/REPORT.ko.md`에 기록함.

## 결론

후보가 모두 사라진 원인은 데이터 수 부족만이 아니었다. 실제 조회에서 뉴스 후보 595개, 날씨 후보 402개를 찾았지만 기존 추천은 0건이었다. 기존 운영자 뉴스도 검색 후보에 포함되어 있었다.

수정된 코드로 운영 카탈로그를 읽기 전용 비교한 결과, 한국어·영어 표본 8개 모두 적격 후보를 반환했다. 실제 등록된 공개 도구 3개는 정상 실행했고, 해당 연결 버전의 실제 성공 근거를 기존 실행 기록 경로로 남겼다. 성공 근거를 임의 생성하거나 기존 보고서를 덮어쓰지 않았다.

## 원인과 수정

1. `search_technology_news`의 밑줄을 마지막 관련성 검사에서 단어 경계로 처리하지 않았다. 실제 검색 기능이 있어도 `search`가 없다고 판단하던 오류를 수정했다.
2. MCP 안내용 도구 목록을 원본 계약보다 먼저 사용했다. 안내용 목록만으로 스키마를 검사하면서 원본에서는 유효한 도구가 탈락했다. 저장된 전체 계약을 사용하고 원본 해시와 축약 관측의 일치 여부를 검사한다. 파라미터 경계·중첩 스키마를 보존하며, 불일치·잘못된 계약은 거부한다. 원본이 없는 기존 기록을 임의로 완전한 계약으로 표시하지 않는다.
3. 원격 `tools/list`의 도구 순서만 바뀌어도 스키마 변경으로 오인했다. 원본 계약 해시 및 저장된 축약 핀 검증을 유지하면서, 정의가 동일한 순서 변경만 허용한다. 기존 핀을 새 순서로 수정하지 않는다. Edge 실행 경로도 축약 핀과 전체 계약을 구분하도록 맞췄다.
4. 전체 계약을 사용해 후보를 복구하자 기상 베팅 도구와 미국 지역 한정 도구가 일반 날씨 후보에 섞이는 사례가 드러났다. 개별 도구의 업무·지역 제약을 적용하고 대소문자를 정규화했다.
5. 기술 뉴스와 세계·스포츠 뉴스의 범위를 구분한다. 회사 조사 도구의 부수적인 뉴스 언급만으로 일반 뉴스 검색을 충족시키지 않는다. MCP는 실제 주제 입력 계약을 확인하고, A2A의 자연어 메시지 입력은 별도 방식으로 유지한다.

기존 프로토콜 선택, 최근 성공 검증 우선 정렬, 관련성·보안 검사와 공개 응답의 자격 증명 마스킹은 유지한다. 모델·벡터 DB·외부 제공자를 임의로 교체하지 않았다.

## 논문·SNS 조사와 적용 판단

- [Multi-Field Tool Retrieval](https://arxiv.org/abs/2602.05366): 도구 기능·입력 조건·출력 형식의 구분을 참고했다. 이 작업에서는 기존 원본 계약과 조건 검사를 정확히 연결했다. 논문의 학습 모델이나 성능 수치를 재현했다는 의미는 아니다.
- [ToolRet](https://arxiv.org/abs/2503.01763): 일반 검색 성능만으로 도구 사용 적합성을 판단할 수 없다는 문제를 참고해, 후보 검색·계약 검사·실제 호출을 각각 검증했다.
- [MCP 공식 도구 명세](https://modelcontextprotocol.io/specification/2025-06-18/server/tools): 도구별 이름·입력 스키마와 실행 응답을 기준으로 검증했다. 원본을 공개 화면에 그대로 노출하지 않고 기존 보안 투영을 거친다.
- [Reddit: Hybrid search and reranking made my RAG worse](https://www.reddit.com/r/Rag/comments/1v7g3oe/hybrid_search_and_reranking_made_my_rag_worse/): 검색 후보 누락과 재정렬 문제를 분리해 보라는 경험담을 참고했다. 이 시스템에서도 먼저 정상 후보가 초기 결과에 있는지 확인했고, 후보 한도를 무작정 늘리지 않았다.
- [Reddit: MCP 운영 경험](https://www.reddit.com/r/ClaudeAI/comments/1tuqqpn/i_ship_ai_agents_in_production_the_mess_is_mcp/): 설명 문구로 엉뚱한 도구가 선택되는 사례를 참고해, 마케팅 설명보다 개별 도구의 계약·목적·지역을 검사했다. SNS 내용은 독립적으로 검증된 성능 근거로 사용하지 않았다.

## 실제 카탈로그와 외부 호출

운영 DB 읽기 전용 검색 표본:

- `technology news search`: Faceabot / Nexus AI News / Technology News.
- `최신 AI 뉴스 찾아줘`: Faceabot / Nexus AI News 등.
- `world news search`: 일반 뉴스 후보 반환. 기술 뉴스 전용 Nexus가 이 표본의 결과에서 제외됨.
- `sports news search`: 스포츠 또는 주제 검색이 가능한 뉴스 후보 반환.
- `weather forecast Seoul`, `서울 날씨 알려줘`, `weather forecast Tokyo`, `weather forecast London`: 첫 번째 후보는 실제 실행으로 확인한 Geocoding & Weather.

8개 요청의 관측 시간은 약 2.57–4.41초. 한 시점의 순차 표본이며 운영 p95나 전체 카탈로그 정확도를 의미하지 않는다. 상세 결과는 `diagnose.json`에 있다.

격리 DB에서 실제 외부 읽기 호출 4종 성공:

- Geocoding & Weather `get_weather`: 서울 좌표·시간대·기온·예보 반환.
- Nexus AI News `search_news`: 제목·출처 링크·발행 시각이 있는 AI 뉴스 반환.
- Faceabot `news_search`: 세계 뉴스 질의에 기사와 출처·발행 시각 반환.
- 운영자 Technology News: Hacker News 원문 링크·발행 시각 반환.

이후 기존 등록 자원 58267, 43828, 143968을 실제 계약으로 각각 실행해 정상 실행 근거를 기록했다. 마지막 관측 실행 시간은 각각 약 2.43초, 2.00초, 5.22초였다. 사용자 워크플로우·권한·결제·크레딧은 변경하지 않았다. 외부 도구 응답의 정확성·이용 조건·지속 가용성을 무기한 보증하는 검증은 아니다. 도쿄·런던은 추천 적합성 확인이며 이번 실제 날씨 호출 위치는 서울이다. 모든 대안 후보를 외부 실행한 것은 아니다.

## 검사와 화면 증적

총 516개 고유 검사 통과:

- API·계약·보안·기존 기능·격리 동시성: 486개.
- Chromium: 28개. 기존/게시 화면, 뉴스·날씨 추천, 상세 열기, 로딩 해제, 모바일 가로 넘침, 출력 보안. 마지막 A2A 수정 후 해당 브라우저 4개를 별도로 재확인했으며 중복 합산하지 않았다.
- 격리 PostgreSQL 18: 2개. 운영 DB와 별도 임시 클러스터 사용.
- 공개 콘텐츠: 296개 파일, 위반 0건.
- 변경 소스 Ruff E9/F/S 검사 통과. SQL 카탈로그 3,801개 문장·232개 테이블 일치 확인.

이 개수는 회귀 검사 수이며 실제 요청 정확도 점수가 아니다. 원격 모델 16병렬 처리량을 새로 측정한 작업도 아니다.

화면 파일은 이 폴더의 `news-*-before.png`, `news-*-after.png`, `news-*-details.png`, `weather-*-before.png`, `weather-*-after.png`, `weather-*-details.png`에 기록했다. 브라우저 증적은 격리 테스트 데이터다.

실행 증적: `check_sources.json`, `verify_registered.json`, `diagnose.json`.
검사 로그: `final-api-security.log`, `browser-tests.log`, `a2a-browser-final.log`, `postgres-tests.log`, `public-content.log`, `secure-coding.log`.

## 운영 반영

준비된 불변 릴리스: `weather-news-contracts-20261026-r1`.

워크스페이스 실행 서비스와 프론트엔드에 같은 계약 검증을 적용한다. 수집/jobs·DB·모델 서버는 이번 변경으로 재시작할 필요가 없다.

```bash
./agentcon worker-deploy execution weather-news-contracts-20261026-r1
./agentcon deploy frontend weather-news-contracts-20261026-r1
```

첫 명령의 실행 서비스 교체 동안 신규 실행 처리가 잠시 대기할 수 있다. 운영 프로세스 교체는 저장소 지침에 따라 수행하지 않았다. 이후 사용자가 두 서비스를 적용했고, 실제 공개 검색·게이트웨이 실행·브라우저 검증을 완료했다. 자세한 최종 증적은 `post-deploy/REPORT.ko.md`에 있다.
