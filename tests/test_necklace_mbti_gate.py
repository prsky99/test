"""mbti-fortune-brief gate (PM 11-17): sample date in the age range and by the contract's rule, the KASI facts of that
date, the four axes, the notices and reproducibility. Synthetic cases only."""
import json
from datetime import date
from pathlib import Path

from agent_market.necklaces import fortune_rules as fr
from agent_market.necklaces import mbti_gate as g


def test_the_age_range_is_man_age_and_feb_29_falls_back():
    assert g.sample_range(30, date(2026, 11, 18)) == (date(1995, 11, 19), date(1996, 11, 18))
    assert g.sample_range(0, date(2026, 11, 18)) == (date(2025, 11, 19), date(2026, 11, 18))
    assert g.sample_range(1, date(2028, 2, 29)) == (date(2026, 3, 1), date(2027, 2, 28))


def test_the_sample_follows_the_rule_is_reproducible_and_stays_in_range():
    today = date(2026, 11, 18)
    a = g.sample_birth_date("intj-a", 30, today)
    assert a == g.sample_birth_date("INTJ", 30, today)                     # case and -A/-T do not matter
    first, last = g.sample_range(30, today)
    assert first <= a <= last
    assert g.sample_birth_date("INTJ", 30, date(2026, 11, 19)) is not None
    assert g.sample_birth_date("ABCD", 30, today) is None and g.sample_birth_date("INTJ", 115, today) is None
    days = {g.sample_birth_date(t, 30, today) for t in ("INTJ", "ENFP", "ISTJ", "ESFP", "INFJ", "ENTP")}
    assert len(days) > 1                                                   # the type changes the draw


def test_the_contract_states_the_same_rule():
    c = json.loads(Path("agent_market/necklaces/contracts/persona.mbti_profile.v1.json").read_text())
    assert "mbti-fortune|v1|" in c["sample_rule"] and "seed mod" in c["sample_rule"]
    assert c["output_schema"]["properties"]["sample_notice"]["const"] == g.SAMPLE_NOTICE


def reading(**over):
    answer = (f"{fr.DISCLAIMER} 2026-11-18: steady focus. Your Leo Sun and today's Moon share fire. "
              f"No hour pillar is used. Dates follow the Korean lunar calendar (KASI rules) and Korea standard time. "
              f"{g.SAMPLE_NOTICE} The type blend is our own mapping for fun. {g.TRADEMARK}")
    out = {"disclaimer": fr.DISCLAIMER, "answer": answer, "source": "AgentValCon fixed rule table",
           "axes": {"energy": {"letter": "I", "line": "share one idea you have been holding back"},
                    "information": {"letter": "N", "line": "follow a hunch"},
                    "decisions": {"letter": "T", "line": "decide with a short list"},
                    "structure": {"letter": "J", "line": "close one open task"}}}
    out.update(over)
    return out


def test_the_reading_needs_the_notices_and_four_axes_from_the_input():
    assert g.check_mbti_synthesis(reading(), "INTJ") == []
    assert "axis_energy" in g.check_mbti_synthesis(reading(), "ENTJ")
    no_tm = reading(answer=reading()["answer"].replace(g.TRADEMARK, ""))
    assert "trademark_notice_missing" in g.check_mbti_synthesis(no_tm, "INTJ")
    no_sample = reading(answer=reading()["answer"].replace(g.SAMPLE_NOTICE, ""))
    assert "sample_notice_missing" in g.check_mbti_synthesis(no_sample, "INTJ")
    bad = reading(answer=reading()["answer"] + " Invest today.")
    assert any(p.startswith("banned:") for p in g.check_mbti_synthesis(bad, "INTJ"))


TODAY = date(2026, 11, 18)
SAMPLE = g.sample_birth_date("INTJ", 30, TODAY).isoformat()
CASE = {"case_id": "synthetic:mbti-1", "input": {"mbti": "INTJ", "age": 30, "today": TODAY.isoformat()},
        "truth": {"sample_birth_date": SAMPLE, "lunar_date": "1996-01-01", "is_leap_month": False, "sign": "Leo",
                  "year_pillar": "Byeong-ja 丙子", "month_pillar": "Gap-o 甲午", "day_pillar": "Gap-ja 甲子",
                  "today_day_pillar": "Gyeong-o 庚午"}}


def output(sample=SAMPLE, **over):
    out = {"profile": {"answers": [{"type": "INTJ", "sample_birth_date": sample}]},
           "calendar": {"answers": [{"lunar_date": "1996-01-01", "is_leap_month": False, "calendar_basis": "korean_kasi"}]},
           "western": {"answers": [{"sign": "Leo", "element": "Fire"}]},
           "saju": {"answers": [{"year_pillar": "Byeong-ja 丙子", "month_pillar": "Gap-o 甲午", "day_pillar": "Gap-ja 甲子",
                                 "hour_pillar": None, "today_day_pillar": "Gyeong-o 庚午"}]},
           "synthesis": {"answers": [reading()]}}
    out.update(over)
    return out


def test_the_whole_task_grader():
    assert g.grade_mbti_task(CASE, output(), again=output())
    notes = {}
    assert not g.grade_mbti_task(CASE, output(sample="1980-01-01"), notes=notes) and "sample_out_of_age_range" in notes["wrong"]
    first, last = g.sample_range(30, TODAY)
    other = first.isoformat() if first.isoformat() != SAMPLE else last.isoformat()
    notes = {}
    assert not g.grade_mbti_task(CASE, output(sample=other), notes=notes) and notes["wrong"] == ["sample_not_by_rule"]
    notes = {}
    wrong_sign = output(western={"answers": [{"sign": "Virgo"}]})
    assert not g.grade_mbti_task(CASE, wrong_sign, notes=notes) and notes["wrong"] == ["sign"]
    changed = output(synthesis={"answers": [reading(answer=reading()["answer"] + " Extra.")]})
    notes = {}
    assert not g.grade_mbti_task(CASE, output(), again=changed, notes=notes) and "not_reproducible" in notes["wrong"]
