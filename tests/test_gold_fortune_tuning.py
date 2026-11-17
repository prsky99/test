"""daily-fortune-brief tuning set (PM 11-17 21:4x): 30 fixed cases from public calendars, and the judges."""
from collections import Counter

from agent_market.fallback_agents.agents import FallbackAgents, FallbackUnavailable
from agent_market.fallback_agents.gold_check import SLUG, applies, case_arguments, judge
from scripts.gold_fortune_tuning import CASES


def run(a, c):
    try:
        return a.execute(c["agent"], case_arguments(c["agent"], c))["result"], None
    except FallbackUnavailable as exc:
        return None, exc.code


def test_thirty_cases_cover_the_four_agents_and_their_boundaries():
    by = Counter(c["agent"] for c in CASES)
    assert len(CASES) == 30 and set(by) == {"korean-lunar", "western-sign", "saju-pillars", "fortune-daily"}
    assert len({c["case_id"] for c in CASES}) == 30
    assert sum(1 for c in CASES if c["truth"].get("refused")) == 3            # before 1912, after 2100, bad leap flag
    assert sum(1 for c in CASES if c["truth"].get("boundary")) == 4           # Ipchun day, before and after
    in_hour = next(c for c in CASES if c["case_id"] == "fortune:ipchun-2025-in-hour")
    assert set(in_hour["truth"]) == {"boundary"}                              # 23:10 Ipchun: pillars not graded
    assert all(SLUG[c["agent"]] == "daily-fortune-brief" and c["truth_sources"][0]["url"].startswith("https://")
               for c in CASES)


def test_the_substitutes_pass_every_tuning_case(tmp_path):
    a = FallbackAgents(data_dir=tmp_path)
    for c in CASES:
        assert applies(c["agent"], c) and not applies("korean-lunar" if c["agent"] != "korean-lunar" else "saju-pillars", c)
        result, error = run(a, c)
        assert judge(c["agent"], c, result, error)["pass"], c["case_id"]


def test_the_judges_fail_wrong_or_invented_answers():
    by_id = {c["case_id"]: c for c in CASES}
    lunar = by_id["fortune:seollal-2020"]
    assert not judge("korean-lunar", lunar, {"solar_date": "2020-01-25", "lunar_date": "2019-12-30",
                                             "is_leap_month": False}, None)["pass"]          # a Chinese-style slip
    refused = by_id["fortune:no-leap4-2024"]
    assert not judge("korean-lunar", refused, {"solar_date": "2024-05-15"}, None)["pass"]   # answered instead
    assert not judge("korean-lunar", refused, None, "source_unavailable")["pass"]           # wrong code
    ipchun = by_id["fortune:ipchun-2024-after"]
    good = {"year_pillar": "Gap-jin 甲辰", "month_pillar": "Byeong-in 丙寅", "day_pillar": "Mu-sul 戊戌",
            "hour_pillar": "Im-sul 壬戌", "boundary_note": "Ipchun falls on the birth date"}
    assert judge("saju-pillars", ipchun, good, None)["pass"]
    assert not judge("saju-pillars", ipchun, {**good, "boundary_note": ""}, None)["pass"]
    assert not judge("saju-pillars", by_id["fortune:three-2000-01-01"],
                     {"year_pillar": "Gi-myo 己卯", "month_pillar": "Byeong-ja 丙子", "day_pillar": "Mu-o 戊午",
                      "hour_pillar": "Im-ja 壬子"}, None)["pass"]                               # no hour without a birth hour
    reading = by_id["fortune:no-hour"]
    assert not judge("fortune-daily", reading, {"answer": "Lucky day for money.", "disclaimer": "x", "source": "y"},
                     None)["pass"]
