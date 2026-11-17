"""mbti-fortune-brief gate (PM 11-17, user request; BRIEF reports/mbti-fortune-necklace-2026-11-17/BRIEF.md).

Grading is independent of the code that answers: the sample birth date is recomputed here from the rule written in
the contract (persona.mbti_profile.v1 sample_rule), and the computed facts of that date (Korean lunar date, leap
month, Sun sign, year/month/day pillars, today's day pillar) come from the answer set (KASI rules), not from our
agents. The reading is checked for its structure, the banned words and the notices only, with the daily fortune's
gate module (necklaces/fortune_rules.py) plus the 16-type notices.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from . import fortune_rules as fr

SAMPLE_NOTICE = "The birth date is a sample drawn from your age, not your real birthday."
TRADEMARK = "MBTI is a trademark of The Myers-Briggs Company; not affiliated."
OWN_MAPPING = "our own mapping for fun"
AXES = (("energy", "EI"), ("information", "SN"), ("decisions", "TF"), ("structure", "JP"))
SUPPORTED = (date(1912, 1, 1), date(2100, 12, 31))       # the Korean lunar calendar's supported range (BRIEF 3)


def normalize_type(mbti: str) -> str | None:
    t = str(mbti or "").strip().upper().split("-")[0]
    ok = len(t) == 4 and all(t[i] in pair for i, (_, pair) in enumerate(AXES))
    return t if ok else None


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:                                     # 29 February in a non-leap year
        return day.replace(year=day.year - years, day=28)


def sample_range(age: int, today: date) -> tuple[date, date]:
    """(first, last) dates on which a person born then is exactly AGE today (Korean 'man' age)."""
    return _years_before(today, age + 1) + timedelta(days=1), _years_before(today, age)


def sample_birth_date(mbti: str, age: int, today: date) -> date | None:
    """The contract's rule; None when the type is not a 16-type code or the range leaves 1912-2100."""
    t = normalize_type(mbti)
    first, last = sample_range(age, today)
    if t is None or first < SUPPORTED[0] or last > SUPPORTED[1]:
        return None
    seed = int(hashlib.sha256(f"mbti-fortune|v1|{t}|{age}|{today.isoformat()}".encode()).hexdigest(), 16)
    return first + timedelta(days=seed % ((last - first).days + 1))


def check_mbti_synthesis(output: dict, mbti: str) -> list[str]:
    """fortune_rules.check_synthesis (no birth hour: three pillars) plus the 16-type notices and the four axes, each
    with the input's letter and a line."""
    problems = fr.check_synthesis(output, has_hour=False)
    answer = str((output or {}).get("answer") or "")
    for notice, code in ((SAMPLE_NOTICE, "sample_notice_missing"), (TRADEMARK, "trademark_notice_missing")):
        if notice not in answer:
            problems.append(code)
    if OWN_MAPPING not in answer.lower():
        problems.append("own_mapping_notice_missing")
    t = normalize_type(mbti) or ""
    axes = (output or {}).get("axes") or {}
    for i, (name, _pair) in enumerate(AXES):
        axis = axes.get(name) if isinstance(axes, dict) else None
        if not isinstance(axis, dict) or axis.get("letter") != t[i:i + 1] or not str(axis.get("line") or "").strip():
            problems.append("axis_" + name)
    return problems


def _first(slot_out, key):
    vals = fr._values(slot_out, (key,))
    return vals[0] if vals else None


def grade_mbti_task(case: dict, output: dict, again: dict | None = None, notes: dict | None = None) -> bool:
    """CASE input: mbti, age, today; truth: sample_birth_date (from the rule) and the KASI facts of that date.
    The answer passes when its sample date is in the age range and equals the rule's, its facts match the truth, the
    reading passes check_mbti_synthesis, and a second run of the same input (AGAIN) gives the same date and words."""
    notes = notes if notes is not None else {}
    inp, truth, wrong = case["input"], case["truth"], []
    today = date.fromisoformat(inp["today"])
    first, last = sample_range(int(inp["age"]), today)
    got = _first((output or {}).get("profile"), "sample_birth_date")
    try:
        got_day = date.fromisoformat(str(got)[:10])
    except ValueError:
        got_day = None
    if got_day is None or not first <= got_day <= last:
        wrong.append("sample_out_of_age_range")
    elif got_day.isoformat() != truth["sample_birth_date"]:
        wrong.append("sample_not_by_rule")
    facts = {k: v for k, v in truth.items() if k in fr.FACT_KEYS and k != "hour_pillar"}
    fact_case = {"input": {"birth_hour": None}, "truth": facts}
    fact_notes = {}
    out_facts = {k: v for k, v in (output or {}).items() if k in ("calendar", "western", "saju")}
    out_facts["synthesis"] = {"disclaimer": fr.DISCLAIMER, "answer": fr.DISCLAIMER + " Korean calendar, Korean standard "
                              "time, no hour pillar.", "source": "-"}     # the reading is checked below, not here
    if not fr.grade_fortune_task(fact_case, out_facts, fact_notes):
        wrong += fact_notes.get("wrong", [])
    synth = (output or {}).get("synthesis") or {}
    body = (synth.get("answers") or [synth])[0] if isinstance(synth, dict) else {}
    problems = check_mbti_synthesis(body, inp["mbti"])
    if problems:
        wrong.append("synthesis:" + "|".join(problems))
    if again is not None:
        a_synth = (again.get("synthesis") or {})
        a_body = (a_synth.get("answers") or [a_synth])[0] if isinstance(a_synth, dict) else {}
        if (_first(again.get("profile"), "sample_birth_date") != got or a_body.get("answer") != body.get("answer")):
            wrong.append("not_reproducible")
    if wrong:
        notes["wrong"] = wrong
    return not wrong
