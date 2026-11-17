"""daily-fortune-brief: the one rule table (PM 11-17 21:4x: the agent imports it), banned words, structure and the
whole-task grader. Synthetic cases only."""
from agent_market.necklaces import fortune_rules as fr

FACTS = {"sign": "Leo", "moon_sign": "Gemini", "day_pillar": "Gap-ja 甲子", "today_day_pillar": "Gyeong-o 庚午",
         "hour_pillar": None}


def test_the_rule_table_is_traditional_and_the_answer_is_reproducible():
    name, _line, rel = fr.ten_god("Gap-ja 甲子", "Gyeong-o 庚午")          # metal controls wood, both yang
    assert rel == "officer" and name.startswith("Pyeongwan 偏官")
    assert fr.ten_god("甲子", "乙丑")[2] == "same" and fr.ten_god("甲子", "丙寅")[2] == "output"
    assert fr.ten_god("甲子", "戊辰")[2] == "wealth" and fr.ten_god("甲子", "壬申")[2] == "resource"
    assert fr.moon_relation("Leo", "Gemini") == "supportive" and fr.moon_relation("Leo", "Aries") == "in_tune"
    assert fr.moon_relation("Leo", "Cancer") == "contrasting"
    assert fr.compose(FACTS) == fr.compose(dict(FACTS))                    # same input, same answer
    assert len(fr.TEN_GOD_LINES) == 10


def test_every_line_of_the_table_is_free_of_banned_words():
    lines = [n + " " + t for n, t in fr.TEN_GOD_LINES.values()]
    for sign in fr.SIGN_ELEMENT:
        for moon in fr.SIGN_ELEMENT:
            lines.append(fr.western_line(sign.title(), moon.title()))
    lines += [fr.NOTE_LUNAR, fr.NOTE_TIME, fr.NOTE_NO_HOUR, fr.DISCLAIMER, fr.SOURCE]
    assert not [l for l in lines if fr.BANNED.search(l)]


def test_the_composed_answer_passes_its_own_check_and_bad_ones_do_not():
    out = fr.compose(FACTS)
    assert out["answer"].startswith(fr.DISCLAIMER) and set(fr.OUTPUT_KEYS) <= set(out)
    assert fr.check_synthesis(out, has_hour=False) == []
    assert "no_hour_note_missing" in fr.check_synthesis(fr.compose({**FACTS, "hour_pillar": "Gap-ja 甲子"}), False)
    assert fr.check_synthesis(fr.compose({**FACTS, "hour_pillar": "Gap-ja 甲子"}), True) == []
    scary = {**out, "answer": out["answer"] + " Seven Killings day; buy stocks and see a doctor."}
    assert any(p.startswith("banned:") for p in fr.check_synthesis(scary, False))
    late = {**out, "answer": out["answer"].replace(fr.DISCLAIMER + " ", "") + " " + fr.DISCLAIMER}
    assert "disclaimer_not_first" in fr.check_synthesis(late, False)


def test_the_agent_inputs_and_contract_fields():
    out = fr.compose({"sign": "Leo", "moon_sign": "Gemini", "day_master": "Gap 甲", "today_day_pillar": "Gyeong-o 庚午",
                      "hour_pillar": "", "today": "2099-02-10"})
    assert out["headline"].startswith("2099-02-10: ") and out["reading"] in out["answer"]
    assert out["ten_god"].startswith("Pyeongwan") and out["rules_version"] == fr.RULES_VERSION
    assert fr.check_synthesis(out, has_hour=False) == []


def test_notes_are_checked_by_meaning():
    reading = ("No hour pillar was used (birth hour not given), so the reading uses three pillars. "
               "Dates follow the Korean lunar calendar (KASI rules) and Korea standard time.")
    other = {"disclaimer": fr.DISCLAIMER, "answer": fr.DISCLAIMER + " A day. " + reading, "source": "x"}
    assert fr.check_synthesis(other, has_hour=False) == []
    assert "basis_note_missing" in fr.check_synthesis({**other, "answer": fr.DISCLAIMER + " A day."}, has_hour=True)


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
           "synthesis": {"answers": [fr.compose({"sign": "Aquarius", "moon_sign": "Gemini", "day_master": "Gap 甲",
                                                 "today_day_pillar": "Gyeong-o 庚午", "hour_pillar": None})]}}
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
