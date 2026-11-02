# 지역·캐시 배포 확인과 다음 단계 진행 (2026-10-27)

## 1. 배포와 적용 확인
- **배포:** frontend `geo-cache-frontend-20261027-r1`, admin `geo-cache-admin-20261027-r1`.
- **Chat "서울 날씨":** A.U.G.U.R Synapse · World, met.no, echorune radar. 지역 제한 없는 날씨 서비스만 나오고, 푸껫 서비스는 빠졌다.
- **Explore 반복 검색:** 서버 계산 3ms(캐시 적중). 처음 계산은 9.5초(콜드).
- **격리 에이전트 상세:** 404.
- **새로 발견:** Explore "weather forecast seoul" 1위가 "Weather — NOAA Conditions"였다. NOAA는 미국 기상청이므로 미국 전용 판정에 NOAA를 추가했다(이번 패키지에 포함).

## 2. Re-Invoke 방식 색인 (다음 단계 1)
참고: Re-Invoke(EMNLP Findings 2024)는 색인할 때 도구마다 예상 질의를 생성하고, 질의 의도와 비교해 단일 도구 검색 nDCG@5를 20% 높였다.

- **생성:** `scripts/build_query_expansions.py`.
  - 대상: Chat이 추천할 수 있는 에이전트(활성·정상·격리 아님·호출 시험 통과). MCP 16,618개, A2A 11,040개.
  - 지역 모델(gemma4)이 에이전트마다 예상 요청 5개를 만든다.
  - 카탈로그는 읽기 전용으로 읽고, `gateway-data/search/query-expansions.jsonl`에만 쓴다. 내용이 같으면 건너뛰므로 중단해도 이어서 돌릴 수 있다.
  - 생성 결과는 일반 문장만 남긴다. URL·가격·결제·긴 숫자가 있으면 버린다.
- **방문자 성능 보호:** 일괄 생성은 대기(standby) 모델 서버(.25)만 쓴다. 운영 모델 서버(.24)의 Chat·워크스페이스 용량은 줄지 않는다.
- **속도:** 모델 서버 처리량이 한계여서 초당 약 0.65건이다. MCP는 약 7시간, 전체는 약 11시간 걸린다. 백그라운드로 실행 중이다(`gateway-data/search/build.log`, 중지: `pkill -f build_query_expansions`).
- **검색 연결:** `discovery.candidates()`에 세 번째 검색 경로를 더했다. 기존 단어 검색·의미(임베딩) 검색과 RRF로 합친다.
  - 생성된 요청 하나가 핵심어를 충분히 덮어야 후보가 된다. 의도 단위 비교로, 여러 문장에 흩어진 단어는 인정하지 않는다.
  - **생성 문장은 후보를 더할 뿐이다.** 통과 여부(관련도·안전·검증)는 제공자가 직접 쓴 이름·설명·도구로만 판단하므로, 모델 문장이 에이전트를 통과시키거나 순위를 올릴 수 없다.
  - 서버는 파일이 커지는 동안 5분마다 다시 읽는다. 생성이 진행될수록 검색 범위가 넓어진다.

## 3. GitHub 이슈 도구 수집 (다음 단계 2)
- **카탈로그 조사:** GitHub 이슈 도구가 있는 MCP는 4개뿐이다.
  - "Github": 호출 시험 실패(토큰 필요로 보임)
  - "Github_private": 개인 저장소용
  - agentdevx: 이미 3위로 추천됨
  - cypher-mcp: 아직 검사 전
- **결론:** 인증 없이 쓸 수 있는 공개 GitHub 이슈 검색 도구가 카탈로그에 거의 없다. 수집 규칙을 바꾸는 것만으로는 채워지지 않는다.
- **제안:** 이미 운영 중인 자체 데이터 에이전트(Research Papers와 같은 방식)로 "공개 GitHub 이슈 검색"을 만든다. GitHub 공개 검색 API는 인증 없이 분당 10회까지 쓸 수 있다. 외부 API 호출과 운영 정책이 따라오므로, 진행 여부는 결정이 필요하다.

## 4. 검증
- 새 테스트 `tests/test_query_expansion.py` 4건 통과. 생성 문장 검증, 의도 단위 비교, 프로토콜 구분, 파일 재읽기 주기를 확인한다.
- 회귀 테스트 744건 중 736건 통과.
  - 실패 8건(`test_untrusted_identity_never_counts_or_leaks_through_warm_cards`)은 작업 트리에 있는 **다른 작업자의 미배포 변경**(`report_projection.py`의 verdict 필드, `front.py`) 때문이다.
  - 운영 릴리스에 내 변경만 얹은 스테이징에서는 같은 테스트가 모두 통과했다(262건 중 261건 통과, 1건은 저장소 전용 `tools` 폴더가 필요한 환경 문제).
- 테스트 중 운영 PID 변화 없음.

## 6. 배포와 확인 (`query-expansion-*-20261027-r1`)
- 배포 후 오류 없음. 격리 에이전트 상세 404 유지.
- **"weather forecast seoul":** NOAA(미국 전용)가 빠졌다.
- **Chat "YouTube 영상 요약":** **Blumify (public, no sign-in)**(YouTube·팟캐스트 자막과 요약)가 1위. 확장 검색 경로로 새로 찾은 후보다.
- **새로 발견한 오답 2건과 수정**(`query-expansion-*-20261027-r2`로 패키징, 배포 승인 대기):
  - 미국 보딩스쿨 서비스(USAnaru)가 학교 유튜브 영상 목록 도구로 "영상 요약"에 통과했다. 영상·유튜브·팟캐스트 요약 요청은 도구나 서비스 설명에 요약·자막·전사가 있어야 통과하도록 바꿨다.
  - 예측시장 서비스(Foresea Forecasting)가 "weather forecast"의 1위였다. 예측시장(prediction market, Polymarket, Kalshi)을 다루는 서비스는 날씨 요청에서 제외한다.
  - 스테이징 213건 통과.

## 5. 배포 대기 (r1, 배포 완료)
- 패키징 완료: `query-expansion-frontend-20261027-r1`, `query-expansion-admin-20261027-r1`.
- 포함: 확장 검색 경로, NOAA 미국 전용 판정.
- 승인 후 배포. 생성 파일이 아직 작아도 문제없이 동작한다. 파일이 없거나 비어 있으면 기존 두 경로만 쓴다.
