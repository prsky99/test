"""daily-fortune-brief gate checks (PM 11-17): banned words, the synthesis structure and the whole-task grader on the
computed facts. Synthetic cases only; the reading's wording follows the agent team's fortune-daily (f7237c2a)."""
import importlib

import pytest

from agent_market.necklaces import fortune_rules as fr

READING = ("Today's stem shapes your day master: a brisk day that rewards focus and a short list of priorities. "
           "Your Aquarius Sun (air) and today's Gemini Moon (air) share the air element: an easy, familiar mood. "
           "Colour of the day: white (metal, today's stem element). "
           "No hour pillar was used (birth hour not given), so the reading uses three pillars. "
           "Dates follow the Korean lunar calendar (KASI rules) and Korea standard time.")


def synthesis(reading=READING, **over):
    out = {"disclaimer": fr.DISCLAIMER, "headline": "2099-02-10: clear priorities, familiar mood", "reading": reading,
           "answer": f"{fr.DISCLAIMER} 2099-02-10: clear priorities, familiar mood. {reading}",
           "source": "AgentValCon fixed rule table (fortune-rules-v1)"}
    out.update(over)
    return out


def test_a_reading_in_the_agents_wording_passes_and_bad_ones_do_not():
    assert fr.check_synthesis(synthesis(), has_hour=False) == []
    with_hour = READING.replace("No hour pillar was used (birth hour not given), so the reading uses three pillars. ", "")
    assert fr.check_synthesis(synthesis(with_hour), has_hour=True) == []
    assert "no_hour_note_missing" in fr.check_synthesis(synthesis(with_hour), has_hour=False)
    scary = synthesis(READING + " A Seven Killings day: buy stocks and see a doctor.")
    assert any(p.startswith("banned:") for p in fr.check_synthesis(scary, False))
    late = synthesis(answer=READING + " " + fr.DISCLAIMER)
    assert "disclaimer_not_first" in fr.check_synthesis(late, False)
    assert "missing_source" in fr.check_synthesis(synthesis(source=""), False)
    assert "basis_note_missing" in fr.check_synthesis(synthesis(READING.replace("Korean lunar calendar (KASI rules)", "lunar calendar")), False)


def test_signs_and_traditional_names_are_not_banned():
    assert not fr.BANNED.search("Cancer Sun with a Scorpio Moon; Pyeongwan 偏官, Geopjae 劫財, Jeongjae 正財")


def test_the_agents_own_tables_pass_our_banned_words():
    try:
        agent = importlib.import_module("agent_market.fallback_agents.fortune_rules")
    except ImportError:
        pytest.skip("the agent team's fortune rules are not on this branch yet (agent-team/fortune f7237c2a)")
    lines = [h + " " + t for h, t in agent.THEMES.values()] + list(agent.WESTERN.values())
    assert not [l for l in lines if fr.BANNED.search(l)]


CASE = {"case_id": "synthetic:1", "input": {"birth_date": "2099-02-04", "calendar": "solar"},
        "truth": {"lunar_date": "2098-12-28", "is_leap_month": False, "sign": "Aquarius", "year_pillar": "Gi-mi 己未",
                  "month_pillar": "Byeong-in 丙寅", "day_pillar": "Gap-ja 甲子", "today_day_pillar": "Gyeong-o 庚午",
                  "boundary": True}}


def output(**over):
    saju = {"year_pillar": "Gi-mi 己未", "month_pillar": "Byeong-in 丙寅", "day_pillar": "Gap-ja 甲子", "hour_pillar": None,
            "today_day_pillar": "Gyeong-o 庚午", "boundary_note": "Ipchun falls on the birth date; 12:00 was used."}
    saju.update(over.pop("saju", {}))
    out = {"calendar": {"answers": [{"lunar_date": "2098-12-28", "is_leap_month": False, "calendar_basis": "korean_kasi"}]},
           "western": {"answers": [{"sign": "Aquarius", "element": "Air"}]}, "saju": {"answers": [saju]},
           "synthesis": {"answers": [synthesis()]}}
    out.update(over)
    return out


def test_the_grader_checks_computed_facts_only():
    assert fr.grade_fortune_task(CASE, output())
    notes = {}
    assert not fr.grade_fortune_task(CASE, output(saju={"month_pillar": "Jeong-chuk 丁丑"}), notes)
    assert notes["wrong"] == ["month_pillar"]
    chinese = output(calendar={"answers": [{"lunar_date": "2098-12-29", "is_leap_month": False, "calendar_basis": "chinese"}]})
    assert not fr.grade_fortune_task(CASE, chinese)                       # a Chinese date that differs fails
    assert not fr.grade_fortune_task(CASE, output(saju={"boundary_note": None}))
    hour_case = {**CASE, "input": {**CASE["input"], "birth_hour": 9}, "truth": {**CASE["truth"], "hour_pillar": "Gi-sa 己巳"}}
    notes = {}
    assert not fr.grade_fortune_task(hour_case, output(), notes) and "hour_pillar" in notes["wrong"]
