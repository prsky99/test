# 오늘의 운세 목걸이: 수집 목록 후보 표 (검색과 RAG, 2026-11-17)

## 조사 방법과 한계

- **자료**
  - 등급 A·healthy·중계 안전 MCP 도구 스냅샷: `exports/pearl-scout/grade_a_tools-20261117.jsonl`, 11-17 09:11
  - A2A·x402 목록: 운영 DB를 `prod_ro_sql`로 읽기 전용 조회(등급 A·B, healthy·reachable)
- **시험 호출은 하지 않았다.** 그래서 아래 판단은 모두 목록과 도구 설명에 근거한 추정이다.
  - 헬스: 수집기의 24시간 확인 횟수이고, 형식은 성공/전체다.
  - 결정론: 도구 설명을 읽고 추정했다. 계산이라고 밝힌 도구는 "결정론(추정)", 날짜마다 발행된 글을 주는 도구는 "날짜 기준 고정(추정)"으로 적었다. 실제 재현성은 시험으로 확인해야 한다.
- **약관**: `member_terms.json` 판정을 따랐다. 아래 후보는 모두 unknown(미판정)이다. 목걸이 멤버로 쓰기 전에 에이전트 팀이 판정해야 한다.
  - prohibits는 1곳이다: 56022 macalculatriceenligne.com.
- **음력 기준이 다르다.** 수집된 음력·달력 도구는 모두 중국 음력(자금산천문대 계산) 기준이다. BRIEF 3절이 요구하는 한국천문연구원(KASI) 기준이라고 밝힌 도구는 없다.
  - 한국과 중국 음력은 같은 해에도 일부 날짜(초하루가 하루 어긋나는 달)가 다르다. 그래서 calendar 자리의 채점 기준(KASI)을 외부 멤버만으로는 맞출 수 없다.
  - 이 자리는 자체 대체(KASI 표)가 1순위다.
- 스냅샷에 든 관련 MCP 도구는 137개, 목록으로는 62개다.
  - 검색어: horoscope, zodiac, astrology, lunar, saju, bazi, four pillars, 八字, 사주, 음력, 운세, 절기 등
  - 아래 표에는 자리에 맞는 것만 넣었다. 타로, 베다 점성술, 기문둔갑, 수비학, 상품 소개 도구는 뺐다.

## 1. calendar 자리 (calendar.lunar_convert.v1): 양력↔음력, 윤달

| id | 호스트 | 도구 | 필수 인자 | 헬스 | 약관 | 결정론 | 메모 |
|---:|---|---|---|---|---|---|---|
| 57935 | totallytarot.net | convert_chinese_lunar_date | 없음(date 또는 lunar, leap) | 3/3 | unknown | 결정론(추정) | 양방향이고 윤달을 표시한다. 중국 음력이다 |
| 36240 | ainetcafe.com | lunar_calendar | 없음(date) | 2/2 | unknown | 결정론(추정) | 양력→음력만 된다. 干支·절기도 준다. 중국 음력이다 |
| 263031 | mcp.fatetell.com | get_almanac | 없음(start_date, days) | 2/2 | unknown | 결정론(추정) | 음력 날짜, 절기, 년·월·일주를 준다. 중국 음력이다 |
| 47298 | d8ly.app | get_daily_almanac | date | 3/3 | unknown | 결정론(추정) | 일주와 음력 날짜를 준다. 중국 음력이다 |
| A2A 307128 | LogiGrain | (기술 미확인) | | 운영 DB A, healthy | unknown | 결정론이라고 밝힘 | 설명은 "Deterministic astronomy, calendar, divination … Four Pillars"다. 기술 목록 확인이 필요하다 |

- 뺀 것
  - 178763 xiaodaox.com bazi_chart: 음력·윤달 입력을 받지만, 필수 인자에 `sex`가 있다. 개인정보 인자라 뺐다.
  - x402: 31994 api.cn402.com/lunar, 249609 chinese-culture.x402tookit.com/lunar-date. 호출마다 결제가 필요하다.

## 2. western 자리 (astro.western_sign.v1): 태양궁과 오늘 흐름

| id | 호스트 | 도구 | 필수 인자 | 헬스 | 약관 | 결정론 | 메모 |
|---:|---|---|---|---|---|---|---|
| 167374 | unifiedreading.com | calculate_birth_date_profile | date | 3/3 | unknown | 결정론(추정) | 태양궁, 띠, 생명수를 준다. 167560은 같은 제공자의 다른 목록이다 |
| 36467 | asternym.com | asternym_zodiac | date | 2/2 | unknown | 결정론(추정) | 태양 황경으로 계산하고, 경계일을 해결하지 않고 그대로 표시한다. BRIEF 원칙과 맞다 |
| 188781 | skyandsigns.com | get_horoscope | sign | 2/2 | unknown | 날짜 기준 고정(추정) | 별자리별 오늘 운세와 평점(-2~+2)을 준다 |
| 188782 | morgenhimmel.de | get_horoscope | sign | 3/3 | unknown | 날짜 기준 고정(추정) | 188781과 같은 엔진이다(같은 설명·도구). 다른 등록 도메인이라 폴백으로 쓸 수 있다 |
| 39264 | mcp.mellowmountainradio.com | get_horoscope | 없음(sign, period) | 2/2 | unknown | 미확인 | 일·주·월 운세를 준다 |
| A2A 61187 | Astro Agents | (기술 미확인) | | 운영 DB B, healthy | unknown | "no LLM, reproducible SHA-256"이라고 밝힘 | 서양·베다 점성술이다. B등급이라 진주 후보 밖이다 |

- 뺀 것
  - 38345 mcp.hankookilbo.com get_daily_horoscope: 운세 내용 없이 제목·링크만 준다.
  - 214979 finportal.mk: 마케도니아어다.
  - x402 운세: 9554, 4663 등 여러 곳이 결제가 필요하다.
  - 4663, 28993: 장난 운세다.

## 3. saju 자리 (saju.pillars.v1): 년·월·일주(+시주)와 오늘 일진

| id | 호스트 | 도구 | 필수 인자 | 헬스 | 약관 | 결정론 | BRIEF 규칙과 맞는가 |
|---:|---|---|---|---|---|---|---|
| 35054 | wenbu.app | calculate_bazi | date | 2/2 | unknown | 결정론(추정), "No prediction" | 맞음. 시간을 모르면 시주를 내지 않는다(삼주). 시간대와 일 경계를 지정할 수 있다 |
| 405618 | getchineseastrology.com | get_bazi_chart | birthDate | 3/3 | unknown | 결정론(추정) | 맞음. 시간은 선택이다 |
| 36467 | asternym.com | asternym_bazi | date | 2/2 | unknown | 결정론(추정) | 일간, 장간, 십신까지 준다. synthesis 규칙 입력으로 좋다 |
| 263031 | mcp.fatetell.com | cast_bazi_chart | birth | 2/2 | unknown | 결정론(추정) | 사주와 오늘의 주(include_today)를 함께 준다. "saved chart"라는 말이 있어 저장 여부(쓰기)를 확인해야 한다 |
| 286759 | bazitools.com | calculate_bazi_four_pillars | year, month, day | 3/3 | unknown | 결정론(추정) | 진태양시 보정을 한다. BRIEF는 보정하지 않는다. longitude를 주지 않을 때의 동작을 확인해야 한다 |
| 191767 | qimena.com | bazi_pillars | birth_datetime, timezone | 3/3 | unknown | 결정론(추정) | 시간이 필수이고 진태양시 보정을 한다. 시간 없는 입력에는 맞지 않는다 |
| 36240 | ainetcafe.com | bazi_chart | datetime | 2/2 | unknown | 결정론(추정) | 시간이 필수다(时柱 포함). 절기 경계를 쓴다 |

- 일진만 따로 필요하면 263031 get_almanac, 47298 get_daily_almanac, 36240 lunar_calendar가 날짜의 일주를 준다.
- 뺀 것
  - 47298 get_daily_bazi_guidance: 출생 시각과 위도·경도가 필수다.
  - x402: 31985 api.cn402.com/bazi, 249612 x402tookit bazi.

## 4. synthesis 자리 (fortune.daily.v1)

- 수집 목록에는 BRIEF 3절(규칙 기반, LLM 문장 금지, 재현성)에 맞는 외부 멤버가 없다.
  - 263031 fatetell get_daily_fortune은 저장된 chart_id가 필요하다(상태가 있다).
  - 39493 mythsensus는 26개 점술을 합친 자체 점수다.
- 자체 대체(규칙 표)가 맞다.

## 5. 띠 (참고)

- 167374 unifiedreading get_chinese_zodiac_year(year), 405618 get_zodiac_year: 결정론(추정).
- 56022 calculate_chinese_zodiac: 약관이 prohibits라 뺐다.

## 6. 정리와 권고

- **calendar**: KASI 기준 외부 멤버가 없다. 자체 대체(KASI 표)를 1순위로 한다. 외부(57935, 36240)는 중국 음력이라 다른 날짜가 있음을 밝히는 폴백으로만 쓴다.
- **western**
  - 태양궁: 36467(경계일 표시)과 167374. 둘 다 계산이다.
  - 오늘 운세 글: 188781과 188782(같은 엔진). 날짜 기준 글이라 같은 날 같은 답일 가능성이 높다.
- **saju**: 35054 wenbu(시간 없으면 삼주)가 BRIEF 규칙과 가장 잘 맞는다. 다음은 405618과 36467이다.
  - 진태양시 보정을 하는 286759와 191767은 보정 끄기를 확인하기 전에는 쓰지 않는다.
- **synthesis**: 자체 대체.
- 모든 후보의 약관이 미판정이다. 멤버로 쓰기 전에 에이전트 팀이 판정해야 한다. 우선순위는 35054, 36467, 405618, 188781, 188782, 167374, 57935다.
- 진주 시험 대기열에는 아직 넣지 않았다. 계약이 동결 중이라(11-20 뒤 반영) 역할이 없기 때문이다. 역할이 생기면 위 후보를 시드로 넣는다.

## 7. 후속 결정과 역할 과제 초안 (11-17 밤)

- **워크플로우 결정**
  - 계약 필수 칸은 answer와 source다. 기존 계약과 같다.
  - 계산 구조 칸은 선택이다. calendar_basis 값은 "korean_kasi" 또는 "chinese"다.
  - 188781과 188782는 같은 엔진이라 하나만 넣는다.
  - 263031은 쓰기 여부를 확인하기 전까지 넣지 않는다.
- **역할 과제 초안**: `role_tasks_draft.jsonl`, 5건이다.
  - 정답이 계산으로 정해지는 것만 넣었다. 약관 판정이 나오고 역할이 생기면(11-20 뒤) 진주 시험 과제로 옮긴다.
  - saju.pillars 3건: 출생일 일주와 오늘 일진.
    - 위키백과 "Sexagenary cycle" 일 단위 표로 2000-01-01이 戊午임을 다시 계산해 확인했다.
    - 이것은 (JDN + 49) mod 60(0 = 甲子)과 같아서, 이 공식으로 계산했다.
  - astro.western_sign 2건: 경계에서 먼 날짜만 골랐다.
    - 물고기자리 2/19~3/20, 염소자리 12/22~1/20. 위키백과 해당 문서를 다시 열어 확인했다.
    - 사자자리 과제는 출처 문장을 찾지 못해 뺐다.
- **장부**: 위키백과 확인 6회는 adhoc 몫이다.
  - 1회는 예약 없이 먼저 보내서 바로 뒤에 사후 기록했다.

## 8. 약관 판정 (에이전트 팀, 11-17 밤; member_terms 기록은 11-18 21:50 동결이 끝난 뒤)

| id | 판정 | 근거 요약 | 자리 영향 |
|---:|---|---|---|
| 35054 wenbu.app | allowed | 합리적 사용이면 된다. 상업 이용 제한이 없다 | saju 1순위를 유지한다 |
| 405618 getchineseastrology.com | allowed | 무료, 읽기 전용, 저장하지 않음. 요청은 "링크 남기기"뿐이다 | saju 2순위다 |
| 188781 skyandsigns.com / 188782 morgenhimmel.de | silent | 약관 페이지가 없다 | western 오늘 글. 둘 중 하나만 쓴다 |
| 167374 unifiedreading.com | silent | 약관 페이지가 없다 | western 태양궁 |
| 36467 asternym.com | prohibits | 자동 요청을 금지하고(11절), 허락 없는 상업 이용을 금지한다(12절) | western·saju 모두에서 뺀다 |
| 57935 totallytarot.net/mcp | prohibits | 앱의 자동 접근을 금지한다. /mcp는 약관 어디에도 없다 | calendar 폴백에서 뺀다. 등록된 /api/public 계산 엔드포인트를 쓰는 멤버라면 allowed가 될 수 있다 |
| 263031 fatetell cast_bazi_chart | 쓰기 아님 | "Deterministic; nothing stored" | 약관 판정 뒤 saju 후보로 다시 본다 |

- 정리된 순서
  - **calendar**: 자체 대체(에이전트 팀 agent-team/fortune 4a066387, KASI 날짜와 대조함)를 1순위로 한다. 외부 폴백은 36240(중국 음력, 약관 unknown)만 남는다.
  - **western**: 167374(태양궁), 188781 또는 188782(오늘 글).
  - **saju**: 35054, 405618.
  - **synthesis**: 자체 대체.
