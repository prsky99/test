"""Offline almanac and fortune facts (daily-fortune-brief substitutes, PM 11-17). Expected values are public Korean
dates from the KASI almanac (Seollal, Chuseok, leap months) and textbook sexagenary anchors."""
from datetime import date

import pytest

from agent_market.fallback_agents import almanac, fortune_calc as f

SEOLLAL = {2015: date(2015, 2, 19), 2016: date(2016, 2, 8), 2017: date(2017, 1, 28), 2018: date(2018, 2, 16),
           2019: date(2019, 2, 5), 2020: date(2020, 1, 25), 2021: date(2021, 2, 12), 2022: date(2022, 2, 1),
           2023: date(2023, 1, 22), 2024: date(2024, 2, 10), 2025: date(2025, 1, 29), 2026: date(2026, 2, 17)}
CHUSEOK = {2020: date(2020, 10, 1), 2021: date(2021, 9, 21), 2022: date(2022, 9, 10), 2023: date(2023, 9, 29),
           2024: date(2024, 9, 17), 2025: date(2025, 10, 6)}


@pytest.mark.parametrize("year", sorted(SEOLLAL))
def test_seollal_is_lunar_new_year(year):
    assert almanac.lunar_to_solar(year, 1, 1) == SEOLLAL[year]
    assert almanac.solar_to_lunar(SEOLLAL[year]) == {"year": year, "month": 1, "day": 1, "is_leap_month": False,
                                                       "month_days": almanac.solar_to_lunar(SEOLLAL[year])["month_days"]}


@pytest.mark.parametrize("year", sorted(CHUSEOK))
def test_chuseok_is_the_15th_of_the_8th_month(year):
    assert almanac.lunar_to_solar(year, 8, 15) == CHUSEOK[year]


@pytest.mark.parametrize("year,month,start", [(2020, 4, date(2020, 5, 23)), (2023, 2, date(2023, 3, 22)),
                                              (2025, 6, date(2025, 7, 25))])
def test_leap_months(year, month, start):
    assert almanac.lunar_to_solar(year, month, 1, is_leap_month=True) == start
    assert almanac.solar_to_lunar(start)["is_leap_month"] is True
    with pytest.raises(ValueError):
        almanac.lunar_to_solar(year, month % 12 + 1, 1, is_leap_month=True)    # no leap month with that number


def test_round_trip_and_range():
    for d in (date(1950, 6, 25), date(1988, 9, 17), date(2026, 11, 17), date(2099, 12, 31)):
        lu = almanac.solar_to_lunar(d)
        assert almanac.lunar_to_solar(lu["year"], lu["month"], lu["day"], lu["is_leap_month"]) == d
    with pytest.raises(ValueError):
        almanac.solar_to_lunar(date(1900, 1, 1))
    with pytest.raises(ValueError):
        almanac.lunar_to_solar(2026, 2, 31)


def test_solar_terms_within_fifteen_minutes():
    """KASI: Ipchun 2024-02-04 17:27, 2025-02-03 23:10, 2026-02-04 05:02 (KST); winter solstice 2024-12-21 18:21."""
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))
    for (y, lon), want in {(2024, 315): datetime(2024, 2, 4, 17, 27, tzinfo=kst),
                           (2025, 315): datetime(2025, 2, 3, 23, 10, tzinfo=kst),
                           (2026, 315): datetime(2026, 2, 4, 5, 2, tzinfo=kst),
                           (2024, 270): datetime(2024, 12, 21, 18, 21, tzinfo=kst)}.items():
        got = almanac.korea_datetime(almanac.solar_term_jd(y, lon))
        assert abs((got - want).total_seconds()) < 15 * 60


def test_four_pillars():
    p = f.four_pillars(date(2000, 1, 1))
    assert [p[k]["name"] for k in ("year", "month", "day")] == ["Gi-myo 己卯", "Byeong-ja 丙子", "Mu-o 戊午"]
    assert p["hour"] is None and "boundary_note" not in p
    before, after = f.four_pillars(date(2024, 2, 4), 3), f.four_pillars(date(2024, 2, 4), 20)
    assert before["year"]["name"] == "Gye-myo 癸卯" and after["year"]["name"] == "Gap-jin 甲辰"   # Ipchun 17:27
    assert after["month"]["name"] == "Byeong-in 丙寅" and after["hour"]["name"] == "Im-sul 壬戌"   # five-rat rule
    assert "birth hour" in after["boundary_note"] and "12:00" in f.four_pillars(date(2024, 2, 4))["boundary_note"]
    assert f.day_pillar(date(2000, 1, 2))["name"] == "Gi-mi 己未"


def test_ten_god_and_signs():
    dm = f.day_pillar(date(2000, 1, 1))                       # Mu 戊 earth yang
    assert f.ten_god(dm, 1)["name"] == "Jeonggwan 正官"         # Eul 乙 wood yin controls earth, other polarity
    assert f.ten_god(dm, 4)["name"] == "Bigyeon 比肩"
    assert f.sun_sign(date(1990, 7, 1))["sign"] == "Cancer"
    assert "cusp" in f.sun_sign(date(1990, 3, 21))
    m = f.moon_today(date(2026, 11, 17))
    assert m["moon_sign"] in {s for s, _ in f.SIGNS} and m["phase"]
