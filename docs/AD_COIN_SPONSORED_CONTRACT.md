# Sponsored 영역 API 계약 (탐색·Chat 공용, 2026-11-11 확정)

- **결정:** 사용자 결정 11-11(PM 전달). Sponsored 영역은 탐색과 Chat 모두에 둔다.
  - AD Coin 팀: API 계약, 노출 집계
  - 성장·유통 팀: 메인 화면 구현
- **코드:** `agent_market/ad_coin/v2/sponsored.py`, `sponsored_http.py`
- **시험:** `tests/test_ad_coin_v2_sponsored.py`

## 1. 요청

```
GET /api/ad-coin/v2/sponsored?placement=explore&category=web_search&limit=1
```

| 매개변수 | 필수 | 값 | 설명 |
|---|---|---|---|
| `placement` | 아니오(기본 `explore`) | `explore` 또는 `chat` | 어느 화면에 그리는지. 노출 집계에 쓴다 |
| `category` | 예 | 메인 카테고리(아래 표) 또는 v2 분류(`general, technology, research, commerce, productivity, creative`) | 결과나 질의의 대표 카테고리 하나. 질의 원문은 보내지 않는다 |
| `limit` | 아니오(기본 2) | 1~2 | 그릴 칸 수 |
| `region` | 보내지 않음 | — | 서버가 Cloudflare `CF-IPCountry`에서 나라만 읽는다(US, KR, JP, GB, DE). 저장하거나 기록하지 않는다 |

**메인 카테고리 → v2 분류**

| v2 분류 | 메인 카테고리 |
|---|---|
| technology | agent_infra, ai_models, dev_tools, network_ops, security, database_analytics, data_utility |
| research | web_search, docs_knowledge, health_science, education_culture, public_legal |
| commerce | commerce_marketing, finance_crypto, trading_derivatives |
| productivity | productivity, communication_messaging |
| creative | media_generation, social |
| general | travel_maps_weather |

## 2. 응답

```json
{"label": "Sponsored",
 "disclosure": "Sponsored by the advertiser. Ads never change which agents are recommended.",
 "reward": null, "placement": "explore",
 "cards": [{"id": "<campaign id>", "label": "Sponsored", "advertiser": "Research Agent Co", "text": "…"}]}
```

- `cards`에는 **그날(UTC) 예약된 칸만** 들어간다. 코인 예약과 USDC 예약(확정된 것)이 모두 해당한다.
- 예약이 없거나, 나라가 판매 지역 밖이면 `cards: []`다. **이때 화면에는 아무것도 그리지 않는다**(규칙 5).
- 카드 순서는 분 단위로 돌아간다(공정 노출). 사람별 정보는 쓰지 않는다.
- 응답 헤더: `Cache-Control: private, max-age=60`, `Vary: CF-IPCountry`
- 오류: 분류, 위치, 칸 수가 틀리면 422다. 그 밖의 오류도 화면은 아무것도 그리지 않고 넘어간다.
- 스위치가 꺼져 있으면 경로가 404다. `AD_COIN_V2_ENABLED`가 꺼진 경우가 그렇다. 이때도 그리지 않는다.

## 3. 메인 화면 구현 규칙 (PM 11-11, 성장·유통)

1. 카드에 "Sponsored" 라벨(`label`)과 `disclosure` 문구를 붙인다. 추천 결과와 시각적으로 분리한다.
2. 추천과 탐색의 순위·내용을 바꾸지 않는다. 결과 목록 안에 끼워 넣지 않는다.
3. Chat 답변 본문에는 광고나 가격을 넣지 않는다. 답변 아래 별도 영역에만 둔다(11-05 결정).
4. 결과가 다 나온 뒤에 따로 부른다. 탐색과 추천 응답 시간에 영향이 0이어야 한다. 실패하거나 느리면 무시하고, 제한 시간은 1.5초를 권장한다.
5. `cards`가 비면 아무것도 그리지 않는다. 자리 표시나 빈 상자 없이 CLS 0을 지킨다(카드가 오면 결과 아래에 붙인다).
6. 기능 스위치로 끄고 켤 수 있게 한다(메인 쪽 스위치, 기본 꺼짐 권장).
7. 개인정보를 보내지 않는다. 질의 원문, 사용자 id, 세션을 붙이지 않는다. 카테고리 하나만 보낸다.

## 4. 노출 집계 (PM 승인 설계: 하루·칸별 노출 수, 클릭 없음)

- 서버는 응답에 넣은 카드마다 다음 키로 "보낸 수"를 센다: (UTC 날짜, 캠페인, 분류, 나라, 위치)
- 사람, IP, 질의, 세션은 남기지 않는다. 클릭은 세지 않는다(리디렉트 없음).
- 프로세스 메모리에 모았다가 60초마다 표에 더한다.
  - 표가 없으면 쓰지 않고 메모리에 둔다(최대 5만 키).
  - 기록에 실패해도 응답은 그대로 나간다.
- 표 `ad_coin_v2.adc2_sponsored_impressions`
  - 열: day_ms, campaign_id, task_category, region, placement, served
  - 기본키: 앞의 다섯 열
  - 표는 1개이고 트리거는 없다. public 스키마에는 아무것도 만들지 않는다.
- 생성: `scripts.ad_coin_v2_migrate migrate-impressions --i-have-approval`(앱 검사 전후 실행)
- **운영 적용 절차(사용자 승인 뒤)**

```bash
.venv/bin/python -m scripts.db_change_rehearsal run --command "python -m scripts.ad_coin_v2_migrate migrate-impressions --dsn-file {dsn_file} --key-file {key_file} --i-have-approval"
```

- **복구 SQL**(표가 비어 있거나 집계를 버려도 될 때)

```sql
DROP TABLE IF EXISTS ad_coin_v2.adc2_sponsored_impressions;
```

- **광고주 보고서:** 등록된 SQL `sponsored_impressions_for_advertiser`로 광고주의 최근 날짜별·위치별 노출 수를 Reports 화면에 보여 준다. 표 적용 뒤에 연결한다.
