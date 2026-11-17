"""mbti-fortune-brief substitutes (PM 11-17, user request): type check, seeded sample birthday, rule-table reading."""
from datetime import date, timedelta

import pytest

from agent_market.fallback_agents import mbti as M
from agent_market.fallback_agents.agents import FallbackAgents, FallbackUnavailable
from agent_market.necklaces import mbti_gate as G
from agent_market.necklaces.fortune_rules import BANNED


def full_years(born, today):
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


@pytest.mark.parametrize("text,code", [("INTJ", "INTJ"), ("intj", "INTJ"), ("ENFP-T", "ENFP"), (" estj-a ", "ESTJ")])
def test_type_codes_are_read_loosely(text, code):
    assert M.normalize_type(text) == code


@pytest.mark.parametrize("bad", ["", "INTX", "INTJX", "ABCD", "INT", None])
def test_other_codes_are_refused(bad):
    with pytest.raises(ValueError):
        M.normalize_type(bad)


def test_the_sample_birthday_always_has_the_given_age_and_is_reproducible():
    for today in (date(2026, 11, 18), date(2028, 2, 29), date(2026, 1, 1), date(2026, 12, 31)):
        for age in (0, 1, 17, 30, 64, 110):
            for code in ("INTJ", "ESFP"):
                born = M.sample_birthday(code, age, today)
                assert full_years(born, today) == age and born <= today
                assert M.sample_birthday(code, age, today) == born               # same input, same day
    days = {M.sample_birthday("INTJ", 30, date(2026, 11, 18) + timedelta(days=d)) for d in range(10)}
    assert len(days) > 5                                                         # another day, another date
    with pytest.raises(ValueError):
        M.sample_birthday("INTJ", 111, date(2026, 11, 18))
    with pytest.raises(ValueError):
        M.sample_birthday("INTJ", 110, date(2021, 6, 1))      # the range starts in 1911: refused, never redrawn


def test_the_sample_matches_the_gate_rule_computed_apart():
    """workflow 11-17: necklaces.mbti_gate.sample_birth_date computes the contract's rule on its own."""
    for today in (date(2026, 11, 18), date(2028, 2, 29), date(2027, 3, 1)):
        for age in (0, 5, 30, 64, 110):
            for code in ("INTJ", "ESFP", "ENFJ"):
                assert M.sample_birthday(code, age, today) == G.sample_birth_date(code, age, today)


def test_profile_and_reading_chain(tmp_path):
    a = FallbackAgents(data_dir=tmp_path)
    p = a.execute("mbti-profile", {"mbti": "enfp-t", "age": 25, "today": "2026-11-18"})["result"]
    assert (p["type"], p["temperament"], p["axes"]) == ("ENFP", "NF", {"energy": "E", "information": "N",
                                                                        "decisions": "F", "structure": "P"})
    assert full_years(date.fromisoformat(p["sample_birth_date"]), date(2026, 11, 18)) == 25
    assert p["sample_notice"] == M.SAMPLE_NOTE and p["sample_range"][0] <= p["sample_birth_date"] <= p["sample_range"][1]
    w = a.execute("western-sign", {"birth_date": p["sample_birth_date"], "today": "2026-11-18"})["result"]
    s = a.execute("saju-pillars", {"birth_date": p["sample_birth_date"], "today": "2026-11-18"})["result"]
    args = {"type": p["type"], "sign": w["sign"], "element": w["element"], "day_master": s["day_master"],
            "today_day_pillar": s["today_day_pillar"], "today": "2026-11-18", "sample_birth_date": p["sample_birth_date"]}
    one, two = a.execute("mbti-fortune", args)["result"], a.execute("mbti-fortune", dict(args))["result"]
    assert one == two and one["answer"].startswith("For entertainment; not advice.")
    assert G.check_mbti_synthesis(one, "ENFP") == []                       # the gate's own check (workflow 5599a2b0)
    assert [one["axes"][k]["letter"] for k in ("energy", "information", "decisions", "structure")] == list("ENFP")
    with pytest.raises(FallbackUnavailable) as err:
        a.execute("mbti-profile", {"mbti": "XXXX", "age": 25})
    assert err.value.code == "invalid_input"


def test_every_table_line_is_clean():
    lines = [x for row in M.AXIS_LINES.values() for x in row.values()]
    lines += [x for row in M.MOON_LINES.values() for x in row.values()] + list(M.TEMPERAMENT_LINES.values())
    lines += [M.SAMPLE_NOTE, M.MAPPING_NOTE, M.TRADEMARK_NOTE]
    assert all(not BANNED.search(x) for x in lines)
    assert set(M.AXIS_LINES) == set("EISNTFJP") and all(len(r) == 5 for r in M.AXIS_LINES.values())
