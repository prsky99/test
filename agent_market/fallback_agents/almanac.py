"""Offline almanac for the daily-fortune-brief substitutes (PM 11-17, user request): the Sun's and the Moon's apparent
ecliptic longitude, the 24 solar terms, new moons, and the Korean lunisolar calendar. No network, no data files.

Algorithms (public, textbook): Jean Meeus, Astronomical Algorithms, 2nd ed. (1998)
- the Sun: chapter 25, "low accuracy" series with nutation and aberration (about 0.01 degree, so a solar term to
  within about 15 minutes);
- the Moon: chapter 47, the largest periodic terms of the longitude series (about 0.02 degree here, so a new moon to
  within a few minutes);
- Delta T: Espenak and Meeus polynomial expressions (NASA eclipse web site, "Polynomial expressions for Delta T").

Korean lunisolar calendar (the rules the Korea Astronomy and Space Science Institute, KASI, publishes its almanac by):
- a month begins on the civil date, in Korean standard time, of the new moon;
- the month that holds the winter solstice (Sun at 270 degrees) is the 11th month; when 13 months run from one 11th
  month to the next, the first month that holds no principal term (Sun at a multiple of 30 degrees) is a leap month
  and repeats the number of the month before it.
- Korean standard time history (UTC offsets): +8:30 1908-04-01..1911-12-31, +9 1912-01-01..1954-03-20, +8:30
  1954-03-21..1961-08-09, +9 since 1961-08-10. The day a new moon falls on depends on it, which is one reason Korean
  and Chinese lunar dates sometimes differ (China uses +8).
Supported range: 1912-2100. A new moon or a solar term within minutes of midnight can fall on the other side of the
day boundary than the official almanac; the answer then says the date is near a boundary.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

J2000 = 2451545.0
MIN_YEAR, MAX_YEAR = 1912, 2100


def _sin(deg: float) -> float:
    return math.sin(math.radians(deg))


def jd_from_datetime(dt: datetime) -> float:
    """Julian Day (UT) of an aware datetime."""
    dt = dt.astimezone(timezone.utc)
    return dt.timestamp() / 86400.0 + 2440587.5


def datetime_from_jd(jd: float) -> datetime:
    return datetime.fromtimestamp((jd - 2440587.5) * 86400.0, timezone.utc)


def delta_t_seconds(year: float) -> float:
    """TT - UT (Espenak and Meeus polynomials) for 1900..2150."""
    if year < 1920:
        t = year - 1900
        return -2.79 + 1.494119 * t - 0.0598939 * t ** 2 + 0.0061966 * t ** 3 - 0.000197 * t ** 4
    if year < 1941:
        t = year - 1920
        return 21.20 + 0.84493 * t - 0.076100 * t ** 2 + 0.0020936 * t ** 3
    if year < 1961:
        t = year - 1950
        return 29.07 + 0.407 * t - t ** 2 / 233 + t ** 3 / 2547
    if year < 1986:
        t = year - 1975
        return 45.45 + 1.067 * t - t ** 2 / 260 - t ** 3 / 718
    if year < 2005:
        t = year - 2000
        return 63.86 + 0.3345 * t - 0.060374 * t ** 2 + 0.0017275 * t ** 3 + 0.000651814 * t ** 4 + 0.00002373599 * t ** 5
    if year < 2050:
        t = year - 2000
        return 62.92 + 0.32217 * t + 0.005589 * t ** 2
    return -20 + 32 * ((year - 1820) / 100) ** 2 - 0.5628 * (2150 - year)


def _tt(jd_ut: float) -> float:
    year = 2000 + (jd_ut - J2000) / 365.25
    return jd_ut + delta_t_seconds(year) / 86400.0


def _nutation_lon(t: float) -> float:
    omega = 125.04452 - 1934.136261 * t
    return -0.00478 * _sin(omega)


def sun_longitude(jd_ut: float) -> float:
    """Apparent geocentric ecliptic longitude of the Sun, degrees [0, 360)."""
    t = (_tt(jd_ut) - J2000) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * _sin(m) + (0.019993 - 0.000101 * t) * _sin(2 * m)
         + 0.000289 * _sin(3 * m))
    omega = 125.04 - 1934.136 * t
    return (l0 + c - 0.00569 - 0.00478 * _sin(omega)) % 360.0


# Meeus table 47.A, longitude terms: (D, M, M', F, coefficient in 1e-6 degree); E correction for terms with M.
_MOON_TERMS = (
    (0, 0, 1, 0, 6288774), (2, 0, -1, 0, 1274027), (2, 0, 0, 0, 658314), (0, 0, 2, 0, 213618),
    (0, 1, 0, 0, -185116), (0, 0, 0, 2, -114332), (2, 0, -2, 0, 58793), (2, -1, -1, 0, 57066),
    (2, 0, 1, 0, 53322), (2, -1, 0, 0, 45758), (0, 1, -1, 0, -40923), (1, 0, 0, 0, -34720),
    (0, 1, 1, 0, -30383), (2, 0, 0, -2, 15327), (0, 0, 1, 2, -12528), (0, 0, 1, -2, 10980),
    (4, 0, -1, 0, 10675), (0, 0, 3, 0, 10034), (4, 0, -2, 0, 8548), (2, 1, -1, 0, -7888),
    (2, 1, 0, 0, -6766), (1, 0, -1, 0, -5163), (1, 1, 0, 0, 4987), (2, -1, 1, 0, 4036),
    (2, 0, 2, 0, 3994), (4, 0, 0, 0, 3861), (2, 0, -3, 0, 3665), (0, 1, -2, 0, -2689),
    (2, 0, -1, 2, -2602), (2, -1, -2, 0, 2390), (1, 0, 1, 0, -2348), (2, -2, 0, 0, 2236),
    (0, 1, 2, 0, -2120), (0, 2, 0, 0, -2069), (2, -2, -1, 0, 2048), (2, 0, 1, -2, -1773),
    (2, 0, 0, 2, -1595), (4, -1, -1, 0, 1215), (0, 0, 2, 2, -1110), (3, 0, -1, 0, -892),
    (2, 1, 1, 0, -810), (4, -1, -2, 0, 759), (0, 2, -1, 0, -713), (2, 2, -1, 0, -700),
    (2, 1, -2, 0, 691), (2, -1, 0, -2, 596), (4, 0, 1, 0, 549), (0, 0, 4, 0, 537),
    (4, -1, 0, 0, 520), (1, 0, -2, 0, -487), (2, 1, 0, -2, -399), (0, 0, 2, -2, -381),
    (1, 1, 1, 0, 351), (3, 0, -2, 0, -340), (4, 0, -3, 0, 330), (2, -1, 2, 0, 327),
    (0, 2, 1, 0, -323), (1, 1, -1, 0, 299), (2, 0, 3, 0, 294), (2, 0, -1, -2, 0),
)


def moon_longitude(jd_ut: float) -> float:
    """Apparent geocentric ecliptic longitude of the Moon, degrees [0, 360)."""
    t = (_tt(jd_ut) - J2000) / 36525.0
    lp = 218.3164477 + 481267.88123421 * t - 0.0015786 * t * t + t ** 3 / 538841
    d = 297.8501921 + 445267.1114034 * t - 0.0018819 * t * t + t ** 3 / 545868
    m = 357.5291092 + 35999.0502909 * t - 0.0001536 * t * t
    mp = 134.9633964 + 477198.8675055 * t + 0.0087414 * t * t + t ** 3 / 69699
    f = 93.2720950 + 483202.0175233 * t - 0.0036539 * t * t
    e = 1 - 0.002516 * t - 0.0000074 * t * t
    a1 = 119.75 + 131.849 * t
    a2 = 53.09 + 479264.290 * t
    s = 0.0
    for cd, cm, cmp, cf, coef in _MOON_TERMS:
        term = coef * _sin(cd * d + cm * m + cmp * mp + cf * f)
        if abs(cm) == 1:
            term *= e
        elif abs(cm) == 2:
            term *= e * e
        s += term
    s += 3958 * _sin(a1) + 1962 * _sin(lp - f) + 318 * _sin(a2)
    return (lp + s / 1e6 + _nutation_lon(t)) % 360.0


def _wrap(x: float) -> float:
    return (x + 180.0) % 360.0 - 180.0


def _solve(f, jd: float, rate: float) -> float:
    """Newton steps for f(jd) = 0 where f is an angle difference in degrees changing by about RATE degrees a day."""
    for _ in range(20):
        step = _wrap(f(jd)) / rate
        jd -= step
        if abs(step) < 1e-6:
            break
    return jd


def solar_term_jd(year: int, longitude: float) -> float:
    """JD (UT) when the Sun reaches LONGITUDE (degrees) in the given Gregorian year."""
    # the Sun is near 280 degrees on January 1, so the crossing lies this many days into the year
    days = ((longitude - 280.0) % 360.0) / 360.0 * 365.2422
    guess = jd_from_datetime(datetime(year, 1, 1, tzinfo=timezone.utc)) + days
    return _solve(lambda jd: sun_longitude(jd) - longitude, guess, 0.9856)


def new_moon_on_or_before(jd: float) -> float:
    """JD (UT) of the last new moon at or before JD."""
    guess = jd - (_wrap(moon_longitude(jd) - sun_longitude(jd)) % 360.0) / 12.19
    nm = _solve(lambda x: moon_longitude(x) - sun_longitude(x), guess, 12.19)
    if nm > jd + 1e-6:
        nm = _solve(lambda x: moon_longitude(x) - sun_longitude(x), nm - 29.53, 12.19)
    return nm


def korea_offset(day: date) -> timedelta:
    """Korean standard time offset from UTC on that civil date (history in the module docstring)."""
    if date(1908, 4, 1) <= day <= date(1911, 12, 31) or date(1954, 3, 21) <= day <= date(1961, 8, 9):
        return timedelta(hours=8, minutes=30)
    return timedelta(hours=9)


def korea_date(jd_ut: float) -> date:
    utc = datetime_from_jd(jd_ut)
    guess = (utc + timedelta(hours=9)).date()
    return (utc + korea_offset(guess)).date()


def korea_datetime(jd_ut: float) -> datetime:
    utc = datetime_from_jd(jd_ut)
    off = korea_offset((utc + timedelta(hours=9)).date())
    return utc.astimezone(timezone(off))


def _next_new_moon(nm: float) -> float:
    return _solve(lambda x: moon_longitude(x) - sun_longitude(x), nm + 29.53, 12.19)


@lru_cache(maxsize=256)
def month_table(year: int) -> tuple:
    """(number, is_leap, first Korean civil date) for each month from the 11th month that holds the winter solstice
    of YEAR-1 up to, not including, the 11th month that holds the winter solstice of YEAR."""
    ws_prev, ws_this = korea_date(solar_term_jd(year - 1, 270.0)), korea_date(solar_term_jd(year, 270.0))
    nm = new_moon_on_or_before(solar_term_jd(year - 1, 270.0) + 1.0)
    starts = []
    while True:
        starts.append(korea_date(nm))
        if len(starts) > 1 and starts[-2] <= ws_this < starts[-1]:
            break
        nm = _next_new_moon(nm)
    # starts[0] begins the month holding ws_prev (or the one after when the new moon falls the same day after it)
    while starts[0] > ws_prev:
        nm0 = new_moon_on_or_before(solar_term_jd(year - 1, 270.0) - 25)
        starts.insert(0, korea_date(nm0))
    i11 = max(i for i, s in enumerate(starts) if s <= ws_prev)
    j11 = max(i for i, s in enumerate(starts) if s <= ws_this)
    starts = starts[i11:j11 + 1]          # starts[-1] is the next 11th month
    count = len(starts) - 1
    principal = set()
    for k in range(-1, 13):
        lon = (270.0 + 30.0 * k) % 360.0
        y = year - 1 if k < 0 or (lon >= 270.0 and k == 0) else year
        for yy in (y - 1, y, y + 1):
            jd = solar_term_jd(yy, lon)
            d = korea_date(jd)
            if starts[0] <= d < starts[-1]:
                principal.add(d)
    out, number, leap_used = [], 11, False
    for k in range(count):
        a, b = starts[k], starts[k + 1]
        if count == 13 and not leap_used and k > 0 and not any(a <= d < b for d in principal):
            out.append((number, True, a))
            leap_used = True
            continue
        if k > 0:
            number = number % 12 + 1
        out.append((number, False, a))
    return tuple(out)


def _months(first_year: int, last_year: int) -> list:
    """(number, leap, start, end_exclusive, lunar_year) over winter-solstice years FIRST..LAST."""
    rows = []
    for y in range(first_year, last_year + 2):
        rows += list(month_table(y))
    rows = sorted(set(rows), key=lambda r: r[2])
    out, lunar_year = [], None
    for idx in range(len(rows) - 1):
        num, leap, start = rows[idx]
        if num == 1 and not leap:
            lunar_year = start.year
        out.append((num, leap, start, rows[idx + 1][2], lunar_year if lunar_year is not None else start.year - (1 if num >= 11 else 0)))
    return out


def solar_to_lunar(day: date) -> dict:
    """Korean lunar date of a Gregorian date: {year, month, day, is_leap_month, month_days}."""
    if not (MIN_YEAR <= day.year <= MAX_YEAR):
        raise ValueError(f"supported years are {MIN_YEAR}-{MAX_YEAR}")
    for num, leap, start, end, ly in _months(day.year - 1, day.year):
        if start <= day < end:
            return {"year": ly, "month": num, "day": (day - start).days + 1, "is_leap_month": leap,
                    "month_days": (end - start).days}
    raise ValueError("date outside the computed calendar")


def lunar_to_solar(year: int, month: int, day: int, is_leap_month: bool = False) -> date:
    """Gregorian date of a Korean lunar date; ValueError when the month (or its leap month) or the day does not exist."""
    if not (MIN_YEAR <= year <= MAX_YEAR - 1):
        raise ValueError(f"supported lunar years are {MIN_YEAR}-{MAX_YEAR - 1}")
    for num, leap, start, end, ly in _months(year, year + 1):
        if ly == year and num == month and leap == bool(is_leap_month):
            if not 1 <= day <= (end - start).days:
                raise ValueError(f"that lunar month has {(end - start).days} days")
            return start + timedelta(days=day - 1)
    raise ValueError("no such lunar month in that year" + (" (no leap month with that number)" if is_leap_month else ""))
