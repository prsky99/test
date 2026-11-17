# 운세 외부 멤버 3개의 계약 대응표 (에이전트 팀, 2026-11-17 22시대, PM 배정)

- 읽은 자료: 우리 운영 DB에 저장된 도구 정의(`resources.usage_full_tools`)만 읽었다. `scripts.prod_ro_sql`로 SELECT 3회를 했다.
- 외부 서버에는 한 번도 호출하지 않았다.
- 시험은 11-20 뒤에 하고, 이 문서는 계획만 적는다.

## 1. 결론

| 자리(계약) | 35054 wenbu.app (allowed) | 405618 getchineseastrology.com (allowed) | 167374 unifiedreading.com (silent) |
|---|---|---|---|
| calendar (calendar.lunar_convert.v1) | **쓰지 않음**: 변환 도구가 없음. calculate_bazi 출력에 음력 문자열이 있지만 중국 음력 기준(기본 시간대 Asia/Shanghai) | **쓰지 않음**: MCP에 음력 변환 도구가 없음 | **쓰지 않음**: 변환 도구 없음 |
| western (astro.western_sign.v1) | 쓰지 않음(해당 도구 없음) | 쓰지 않음(해당 도구 없음) | **후보(예비)**: calculate_birth_date_profile → Sun sign. silent라 자체 대체(western-sign) 다음 예비로만 둔다(PM 21시대 결정 5) |
| saju (saju.pillars.v1) | **후보**: calculate_bazi | **후보**: get_bazi_chart | 쓰지 않음(사주 도구 없음, 띠만 있음) |

calendar 자리에는 쓸 수 있는 외부 멤버가 없다. 이 자리는 자체 대체 korean-lunar만 둔다. 워크플로우 초안(34c1e638)과 같은 결론이다.

## 2. saju 자리 대응표

| 계약 칸 / 성질 | 35054 calculate_bazi | 405618 get_bazi_chart |
|---|---|---|
| 필수 인자 | `date` (YYYY-MM-DD) | `birthDate` (YYYY-MM-DD, 1901-02-19 ~ 2100-02-08) |
| 생시 | `time` "HH:MM" 선택. 없으면 시주 없음("Unknown time returns no hour pillar") | `time` "HH:MM" 선택. 없으면 시주 없음, 정오 기준("read at midday") |
| 시간대 | `timezone` (IANA 또는 오프셋). 없으면 Asia/Shanghai로 가정하고 그렇다고 밝힘 | `timeZone` (IANA). 없으면 Asia/Shanghai |
| 날 경계 | `dayBoundary` "midnight" 또는 "zi"(기본 midnight) | 설명에 없음. 시험에서 확인한다 |
| 진태양시 | `solarTime` 기본 false, `longitude` 선택 | 없음 |
| 년주 기준 | 출력 calendar.zodiacConvention이 "lunar-new-year"이다. 이는 띠(zodiac) 표기 규칙이고, 기둥은 입춘 기준인지 정의에서 확정되지 않는다. **시험에서 확인한다** | 정의 밖 근거: 같은 서버의 get_zodiac_year가 "Li Chun date"와 "Chinese New Year와 Li Chun이 다른 띠를 주는지"를 따로 보고한다. 기둥은 입춘 기준으로 보이지만 **시험에서 확인한다** |
| 출력 → year/month/day/hour_pillar | `pillars[]` {key: year\|month\|day\|hour, value}: value는 한자 두 글자로 보이며, 시주 없음은 null | `item.pillars[]` {name, chinese, characters, stem{character}, branch{character}, provisional}: characters는 한자. 경계 판단에는 provisional을 쓸 수 있다 |
| day_master | `dayMaster` | `item.dayMaster` |
| today_day_pillar | **없음**(생일만 계산) | **없음** |
| 입력 매핑 | birth_date → date, birth_hour h → time "hh:00"(시 단위라 :30이 아님. 우리 자체 대체의 :30 기준과 다르다), timezone "Asia/Seoul", dayBoundary "midnight", solarTime false | birth_date → birthDate, birth_hour → time "hh:00", timeZone "Asia/Seoul" |

### 판정과 조건
- 두 서버 모두 계약의 계산 칸(년·월·일·시주, day_master)은 채울 수 있다. 시간대를 Asia/Seoul로 넘기면 절입 경계가 KST로 계산된다.
- 오늘 일진(today_day_pillar)은 두 서버 모두 주지 않는다. 그래서 저희 synthesis가 받을 today_day_pillar는 다음 둘 중 하나로 채워야 한다.
  - (a) runner의 정규화기가 자체 계산 함수(fortune_calc.day_pillar, 오프라인)로 채운다.
  - (b) 같은 도구를 today 날짜로 한 번 더 부른다(호출이 두 배가 됨).
  - 제안은 (a)다. 일진은 날짜만으로 정해지는 사실이고 외부 호출이 필요 없다.
- 생시를 "hh:00"으로 넘기면 입춘이 그 시간 안에 든 경우(예: 2025-02-03 23시)에 우리와 결과가 다를 수 있다. 관문 정답은 이런 사례에서 년·월주를 채점하지 않으므로(PM 21:5x 규칙) 문제가 되지 않는다.
- 년주의 입춘 기준 여부가 정의만으로는 확정되지 않는다. 시험 표본에 입춘 경계 사례를 넣어, 입춘 기준이 아니면(음력 설 기준이면) 그 멤버를 saju 자리에서 뺀다.
- 기본 시간대가 Asia/Shanghai(+8)라서, 매핑에서 Asia/Seoul을 반드시 넘긴다. 빠지면 절입 시각이 1시간 어긋난다.

## 3. western 자리 대응표 (167374, 예비)

| 계약 칸 / 성질 | 167374 calculate_birth_date_profile |
|---|---|
| 필수 인자 | `date` (YYYY-MM-DD, 1900 이후) |
| sign | 출력 스키마가 비어 있다(outputSchema 없음). 답 글에서 Sun sign을 읽어야 하므로 정규화기에 별자리 이름 12개 매칭이 필요하다 |
| element | 없음. 정규화기가 별자리에서 정한다 |
| cusp | 표시 없음(날짜만 받으므로 경계일에 어느 쪽으로 정하는지 알 수 없다) |
| 판정 | 약관 silent(약관 페이지 없음)라 PM 결정대로 자체 대체 western-sign 다음의 예비로만 둔다. 출력 스키마가 없어 정규화 부담이 있다. 경계일 사례에서는 우리와 다를 수 있다 |

## 4. 쓰지 않는 도구와 이유
- 35054 get_daily_card: 타로 카드라 계약에 맞는 자리가 없다.
- 35054 calculate_ziwei, cast_iching, draw_tarot: 자리 없음.
- 405618 get_zodiac_year: 띠와 입춘 날짜만 주고, 기둥 넷이 아니다. 시험에서 입춘 기준을 확인하는 보조 자료로만 쓴다.
- 405618 count_five_elements, get_kua_number, get_flying_stars, get_zi_wei_chart, check_animal_compatibility, cast_i_ching: 자리 없음.
- 167374 get_chinese_zodiac_year, get_unified_reading_options: 자리 없음.

## 5. 읽기 전용 시험 계획 (11-20 v4 판정 뒤, 실행은 PM 승인 후)
- 장부
  - 도메인마다 system `substitute_tests`로 예약하고, 거절되면 그 자리에서 멈춘다.
  - 403·429를 받으면 note를 남기고 멈춘다.
  - wenbu.app과 getchineseastrology.com은 각 6회, unifiedreading.com은 3회를 쓴다. 15회 안이다.
- 표본: tuning 세트(scripts/gold_fortune_tuning.py)의 사주 사례에서 고른다. holdout은 보지 않는다.
  1. 2000-01-01, 생시 없음: 기묘·병자·무오, 시주 null.
  2. 1990-05-15 14시: 경오·신사·경진·계미(시주 오서둔).
  3. 2024-02-04 15시: 계묘·을축. 입춘 17:27 전이다.
  4. 2024-02-04 19시: 갑진·병인. 입춘 뒤다. 3·4번이 입춘 기준 확인용이다.
  5. 2025-02-04 01시: 을사·무인.
  6. 2001-12-25: 일주 임술.
  - 6건 × 2개 서버 = 12회다.
  - western 예비(167374)는 1990-03-05 Pisces, 2001-01-05 Capricorn, 1985-07-30 Leo 3건이다.
- 판정
  - 계산 칸이 정답과 모두 같으면 통과다. 3·4번에서 입춘 기준이 아니면 saju 자리에서 제외한다.
  - 시간대 인자를 무시하는 징후가 보이면 제외한다. 예: 출력의 timezone이나 utcOffset이 +08:00으로 돌아오는 경우.
  - 쓰기 도구 호출은 없다. 모든 도구가 readOnlyHint true이고 destructiveHint false다.
- 기록: 결과는 reports/ 아래 날짜 폴더에 둔다. 판정은 워크플로우 정의의 멤버 상태(planned → active)로 넘긴다.
