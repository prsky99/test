"""daily-fortune-brief substitutes (PM 11-17, user request): offline calendar, Sun sign, saju and rule-table reading."""
import json
from datetime import datetime, timezone

import pytest

from agent_market.fallback_agents.agents import FallbackAgents, FallbackUnavailable


def agents(tmp_path, now=datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)):   # 2026-11-18 01:00 in Seoul
    return FallbackAgents(data_dir=tmp_path, utc_now=lambda: now)


def test_lunar_conversion_both_ways_and_leap_month(tmp_path):
    a = agents(tmp_path)
    r = a.execute("korean-lunar", {"birth_date": "2024-02-10", "calendar": "solar"})["result"]
    assert (r["lunar_date"], r["is_leap_month"], r["calendar_basis"]) == ("2024-01-01", False, "korean_kasi")
    leap = a.execute("korean-lunar", {"birth_date": "2020-04-15", "calendar": "lunar", "is_leap_month": True})["result"]
    assert leap["solar_date"] == "2020-06-06" and leap["is_leap_month"] is True and "leap month" in leap["answer"]
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("korean-lunar", {"birth_date": "2021-04-15", "calendar": "lunar", "is_leap_month": True})
    assert err.value.code == "invalid_input"


def test_sign_and_pillars_fill_the_flat_fields(tmp_path):
    a = agents(tmp_path)
    w = a.execute("western-sign", {"birth_date": "1990-03-21"})["result"]
    assert w["sign"] == "Aries" and w["element"] == "Fire" and w["cusp"] is True and w["today"] == "2026-11-18"
    s = a.execute("saju-pillars", {"birth_date": "2000-01-01"})["result"]
    assert (s["year_pillar"], s["month_pillar"], s["day_pillar"]) == ("Gi-myo 己卯", "Byeong-ja 丙子", "Mu-o 戊午")
    assert s["hour_pillar"] is None and "hour pillar not given" in s["basis"] and s["day_master"] == "Mu 戊"
    assert s["today_day_pillar"] == "Byeong-sin 丙申" and "Three pillars" in s["answer"]
    h = a.execute("saju-pillars", {"birth_date": "2024-02-04", "birth_hour": 20, "today": "2026-11-18"})["result"]
    assert h["year_pillar"] == "Gap-jin 甲辰" and h["hour_pillar"] == "Im-sul 壬戌" and "Ipchun" in h["basis"]
    assert all(isinstance(v, (str, int, float, bool)) or v is None for v in s.values())   # flat values for the runner


def test_reading_is_the_workflow_rule_table_fixed_and_safe(tmp_path):
    """workflow 11-17: fortune-daily is necklaces.fortune_rules.compose; check_synthesis is [] for every answer."""
    from agent_market.necklaces.fortune_rules import check_synthesis
    a = agents(tmp_path)
    args = {"sign": "Pisces", "moon_sign": "Cancer", "day_pillar": "Gi-myo 己卯", "today_day_pillar": "Gap-ja 甲子",
            "today": "2026-11-18"}
    one, two = a.execute("fortune-daily", args)["result"], a.execute("fortune-daily", dict(args))["result"]
    assert one == two and one["answer"].startswith("For entertainment; not advice.")
    assert one["ten_god"] == "Jeonggwan 正官 (Order)" and one["moon_relation"] == "in_tune"
    assert "hour pillar is left out" in one["answer"] and check_synthesis(one, False) == []
    hour = a.execute("fortune-daily", {**args, "hour_pillar": "Sin-mi 辛未"})["result"]
    assert "hour pillar is left out" not in hour["answer"] and check_synthesis(hour, True) == []
    computed = a.execute("fortune-daily", {k: v for k, v in args.items() if k != "moon_sign"})["result"]
    assert computed["answer"].startswith("For entertainment; not advice.")       # today's Moon computed here


def test_the_three_steps_feed_the_reading(tmp_path):
    """The flat values of the calendar, western and saju steps are exactly what the reading takes."""
    from agent_market.necklaces.fortune_rules import BANNED
    a = agents(tmp_path)
    cal = a.execute("korean-lunar", {"birth_date": "1990-03-15", "calendar": "solar"})["result"]
    west = a.execute("western-sign", {"birth_date": cal["solar_date"]})["result"]
    saju = a.execute("saju-pillars", {"birth_date": cal["solar_date"]})["result"]
    out = a.execute("fortune-daily", {"sign": west["sign"], "moon_sign": west["moon_sign"],
                                      "day_pillar": saju["day_pillar"], "today_day_pillar": saju["today_day_pillar"],
                                      "today": saju["today"]})["result"]
    assert west["moon_sign"] and saju["today"] == "2026-11-18" and out["notes"]
    assert not BANNED.search(saju["today_relation"]) and "Killing" not in saju["today_relation"]


def test_birth_date_never_reaches_the_usage_log(tmp_path):
    a = agents(tmp_path)
    a.execute("saju-pillars", {"birth_date": "1987-06-05", "birth_hour": 9})
    a.execute("korean-lunar", {"birth_date": "1987-06-05"})
    text = "".join(p.read_text() for p in (tmp_path / "usage").glob("*.jsonl")) if (tmp_path / "usage").exists() else ""
    logs = [json.loads(line) for line in text.splitlines()]
    assert "1987" not in text and all(set(x) <= {"at", "agent", "ok", "code", "ms", "cache", "exception"} for x in logs)


def test_years_outside_the_supported_range_are_refused(tmp_path):
    with pytest.raises(FallbackUnavailable) as err:
        agents(tmp_path).execute("saju-pillars", {"birth_date": "1899-12-31"})
    assert err.value.code == "invalid_input"
