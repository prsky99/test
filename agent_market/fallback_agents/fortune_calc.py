"""Facts for the daily-fortune-brief substitutes (PM 11-17, user request): Korean lunar date, Western Sun sign and
today's Moon sign, and the Four Pillars (saju). Pure computation on almanac.py; no network, nothing stored.

Conventions (stated in every answer):
- Times are Korean standard time; no true-solar-time correction for the hour pillar.
- The year pillar changes at Ipchun (Sun at 315 degrees), the month pillar at each "jeol" solar term (Sun at 315 +
  30k degrees), not at the lunar new year. Without a birth hour these are decided at 12:00 on the birth date; when a
  boundary term falls on the birth date the answer says the pillar depends on the birth time.
- The day changes at 00:00 (no "night Ja-si" split); the hour pillar's stem follows the day's stem (the five-rat rule).
- Sun signs by the Sun's apparent longitude at 12:00 on the date (30-degree tropical signs); a date on which the Sun
  changes sign is marked as a cusp.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import almanac

STEMS = [("Gap", "甲", "wood", "yang"), ("Eul", "乙", "wood", "yin"), ("Byeong", "丙", "fire", "yang"),
         ("Jeong", "丁", "fire", "yin"), ("Mu", "戊", "earth", "yang"), ("Gi", "己", "earth", "yin"),
         ("Gyeong", "庚", "metal", "yang"), ("Sin", "辛", "metal", "yin"), ("Im", "壬", "water", "yang"),
         ("Gye", "癸", "water", "yin")]
BRANCHES = [("Ja", "子", "water", "Rat"), ("Chuk", "丑", "earth", "Ox"), ("In", "寅", "wood", "Tiger"),
            ("Myo", "卯", "wood", "Rabbit"), ("Jin", "辰", "earth", "Dragon"), ("Sa", "巳", "fire", "Snake"),
            ("O", "午", "fire", "Horse"), ("Mi", "未", "earth", "Goat"), ("Sin", "申", "metal", "Monkey"),
            ("Yu", "酉", "metal", "Rooster"), ("Sul", "戌", "earth", "Dog"), ("Hae", "亥", "water", "Pig")]
ELEMENTS = ["wood", "fire", "earth", "metal", "water"]          # each produces the next, controls the one after next
SIGNS = [("Aries", "fire"), ("Taurus", "earth"), ("Gemini", "air"), ("Cancer", "water"), ("Leo", "fire"),
         ("Virgo", "earth"), ("Libra", "air"), ("Scorpio", "water"), ("Sagittarius", "fire"),
         ("Capricorn", "earth"), ("Aquarius", "air"), ("Pisces", "water")]
TEN_GODS = {  # (relation to the day master, same polarity) -> name; neutral glosses as in necklaces.fortune_rules (workflow 11-17)
    ("same", True): ("Bigyeon 比肩", "Peer"), ("same", False): ("Geopjae 劫財", "Rival"),
    ("output", True): ("Siksin 食神", "Expression"), ("output", False): ("Sanggwan 傷官", "Bold voice"),
    ("wealth", True): ("Pyeonjae 偏財", "Opportunity"), ("wealth", False): ("Jeongjae 正財", "Steady effort"),
    ("officer", True): ("Pyeongwan 偏官", "Challenge"), ("officer", False): ("Jeonggwan 正官", "Order"),
    ("resource", True): ("Pyeonin 偏印", "Insight"), ("resource", False): ("Jeongin 正印", "Support"),
}
KST = timezone(timedelta(hours=9))


def _at(day: date, hour: float) -> datetime:
    off = almanac.korea_offset(day)
    return datetime(day.year, day.month, day.day, tzinfo=timezone(off)) + timedelta(hours=hour)


def pillar(stem: int, branch: int) -> dict:
    s, b = STEMS[stem % 10], BRANCHES[branch % 12]
    return {"name": f"{s[0]}-{b[0].lower()} {s[1]}{b[1]}", "stem": f"{s[0]} {s[1]}", "branch": f"{b[0]} {b[1]}",
            "stem_element": s[2], "stem_polarity": s[3], "branch_element": b[2], "animal": b[3],
            "stem_index": stem % 10, "branch_index": branch % 12}


def day_pillar(day: date) -> dict:
    jdn = day.toordinal() + 1721425           # Julian Day Number at noon
    k = (jdn + 49) % 60                        # 2000-01-01 (JDN 2451545) is Mu-o 戊午, index 54
    return pillar(k % 10, k % 12)


def element_relation(me: str, other: str) -> str:
    """How OTHER relates to ME: same, output (I produce it), wealth (I control it), officer (it controls me),
    resource (it produces me)."""
    d = (ELEMENTS.index(other) - ELEMENTS.index(me)) % 5
    return ["same", "output", "wealth", "officer", "resource"][d]


def ten_god(day_master: dict, other_stem: int) -> dict:
    o = STEMS[other_stem % 10]
    rel = element_relation(day_master["stem_element"], o[2])
    hanja, english = TEN_GODS[(rel, o[3] == day_master["stem_polarity"])]
    return {"name": hanja, "english": english, "relation": rel}


def _jeol_index(moment: datetime) -> tuple[int, int]:
    """(saju year, month index 0 = In 寅 month) at MOMENT, by the Sun's longitude (Ipchun at 315 degrees)."""
    jd = almanac.jd_from_datetime(moment)
    lon = almanac.sun_longitude(jd)
    month_index = int(((lon - 315.0) % 360.0) // 30.0)            # 0: 315-345 In month ... 11: 285-315 Chuk month
    ipchun = almanac.solar_term_jd(moment.year, 315.0)
    year = moment.year if jd >= ipchun else moment.year - 1
    return year, month_index


def _boundary_on(day: date) -> str | None:
    """The jeol term (or Ipchun) that falls on DAY, if any."""
    a = almanac.sun_longitude(almanac.jd_from_datetime(_at(day, 0)))
    b = almanac.sun_longitude(almanac.jd_from_datetime(_at(day, 24)))
    for k in range(12):
        lon = (315.0 + 30.0 * k) % 360.0
        if ((lon - a) % 360.0) < ((b - a) % 360.0):
            return "Ipchun (Sun at 315 degrees)" if k == 0 else f"a jeol solar term (Sun at {lon:g} degrees)"
    return None


def four_pillars(birth: date, birth_hour: int | None = None) -> dict:
    moment = _at(birth, (birth_hour + 0.5) if birth_hour is not None else 12.0)
    year, mi = _jeol_index(moment)
    ys = (year - 4) % 10
    yb = (year - 4) % 12
    first_month_stem = ((ys % 5) * 2 + 2) % 10                      # Gap/Gi years start with Byeong-in 丙寅
    month = pillar(first_month_stem + mi, 2 + mi)
    dayp = day_pillar(birth)
    out = {"year": pillar(ys, yb), "month": month, "day": dayp, "day_master": f"{dayp['stem']} ({dayp['stem_element']}, {dayp['stem_polarity']})"}
    if birth_hour is not None:
        hb = ((birth_hour + 1) // 2) % 12
        hs = ((dayp["stem_index"] % 5) * 2 + hb) % 10
        out["hour"] = pillar(hs, hb)
    else:
        out["hour"] = None
    boundary = _boundary_on(birth)
    if boundary:
        out["boundary_note"] = (f"{boundary} falls on the birth date, so the "
                                + ("year and month pillars" if boundary.startswith("Ipchun") else "month pillar")
                                + (" were decided at the given birth hour." if birth_hour is not None
                                   else " depend on the birth time; 12:00 was used."))
    return out


def sun_sign(day: date) -> dict:
    lon = almanac.sun_longitude(almanac.jd_from_datetime(_at(day, 12)))
    i = int(lon // 30)
    start = int(almanac.sun_longitude(almanac.jd_from_datetime(_at(day, 0))) // 30)
    end = int(almanac.sun_longitude(almanac.jd_from_datetime(_at(day, 24))) // 30)
    out = {"sign": SIGNS[i][0], "element": SIGNS[i][1], "sun_longitude": round(lon, 2)}
    if start != end:
        out["cusp"] = f"The Sun moves from {SIGNS[start][0]} to {SIGNS[end % 12][0]} on this date (Korean time)."
    return out


def moon_today(day: date) -> dict:
    jd = almanac.jd_from_datetime(_at(day, 12))
    lon = almanac.moon_longitude(jd)
    sign = SIGNS[int(lon // 30)]
    elong = (lon - almanac.sun_longitude(jd)) % 360.0
    phase = ["new moon", "waxing crescent", "first quarter", "waxing gibbous", "full moon", "waning gibbous",
             "last quarter", "waning crescent"][int(((elong + 22.5) % 360.0) // 45)]
    out = {"moon_sign": sign[0], "moon_element": sign[1], "moon_longitude": round(lon, 2), "phase": phase}
    a = int(almanac.moon_longitude(almanac.jd_from_datetime(_at(day, 0))) // 30)
    b = int(almanac.moon_longitude(almanac.jd_from_datetime(_at(day, 24))) // 30)
    if a != b:
        out["moon_sign_change"] = f"The Moon moves from {SIGNS[a][0]} to {SIGNS[b % 12][0]} during the day (Korean time)."
    return out
