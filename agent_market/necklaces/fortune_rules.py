"""daily-fortune-brief: the synthesis rule table, the banned words, the output structure and the whole-task grader
(PM 11-17, user request; BRIEF reports/fortune-necklace-2026-11-17/BRIEF.md).

Who does what: the agent team's fortune-daily substitute writes the reading from its fixed rule table
(fallback_agents/fortune_rules.py, f7237c2a; one table only); the runner never writes text. This module holds what the
gate checks: the banned words, the output structure and the whole-task grader. The gate grades only the computed facts (Korean lunar date, leap month,
Sun sign, year/month/day pillars, the hour pillar when a birth hour is given, today's day pillar) against the answer
set; the synthesis text is checked only for its structure, the banned words and the leading disclaimer.

The literal English names some books give two Ten Gods ("Seven Killings", "Rob Wealth") read as threats or money
talk: BANNED catches them, so an answer never carries them. Same input and same day -> same answer (no model).
"""
from __future__ import annotations

import re

DISCLAIMER = "For entertainment; not advice."

# Never in an answer: health, money, legal or medical claims or advice, and frightening words (BRIEF section 3).
# "Cancer" is a Sun sign, so the illness is matched as tumour words and "cancerous" only.
BANNED = re.compile(r"\b(?:diagnos\w*|disease\w*|illness\w*|sick\w*|cancerous|tumou?rs?|surger\w*|medic\w*|doctor\w*|symptom\w*|"
                    r"cure\w*|therap\w*|pregnan\w*|invest\w*|stocks?|crypto\w*|bitcoin|lotter\w*|gambl\w*|loans?|debts?|"
                    r"buy\w*|sell\w*|trad(?:e|ing)|profit\w*|money|lawsuit\w*|sue|courts?|lawyer\w*|legal\w*|death\w*|"
                    r"dies?|dying|dead|accident\w*|disaster\w*|danger\w*|kill\w*|misfortune\w*|curse\w*|doom\w*|injur\w*|"
                    r"catastroph\w*|rob\w*)\b", re.I)

# fortune.daily.v1 output (agent team f7237c2a): answer, disclaimer and source required; headline and reading are the
# reading's parts. The rule table itself lives in the agent (fallback_agents/fortune_rules.py, one table only).
OUTPUT_KEYS = ("disclaimer", "answer", "source")
BASIS_LUNAR = re.compile(r"Korean (?:lunar )?calendar|KASI", re.I)
BASIS_TIME = re.compile(r"Korea(?:n)? standard time|\bKST\b", re.I)
NO_HOUR = re.compile(r"no hour pillar|hour pillar (?:is|was) (?:left out|not used)", re.I)


def check_synthesis(output: dict, has_hour: bool) -> list[str]:
    """Problems of a synthesis answer: [] when the structure, the leading disclaimer, the notes and the words are
    right. Notes are matched by meaning (the agent's wording may change), never by one exact sentence."""
    if not isinstance(output, dict):
        return ["not_an_object"]
    problems = []
    answer = str(output.get("answer") or "")
    if not answer.startswith(DISCLAIMER) or output.get("disclaimer") != DISCLAIMER:
        problems.append("disclaimer_not_first")
    for key in OUTPUT_KEYS:
        if not output.get(key):
            problems.append("missing_" + key)
    text = " ".join(str(v) for v in output.values() if isinstance(v, (str, list)))
    found = sorted({m.group(0).lower() for m in BANNED.finditer(text)})
    if found:
        problems.append("banned:" + ",".join(found))
    if not BASIS_LUNAR.search(answer) or not BASIS_TIME.search(answer):
        problems.append("basis_note_missing")
    if not has_hour and not NO_HOUR.search(answer):
        problems.append("no_hour_note_missing")
    return problems


# ---------------------------------------------------------------- whole-task grader (computed facts only)
PILLAR = re.compile(r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]")
FACT_KEYS = {"lunar_date": ("calendar", ("lunar_date",)), "is_leap_month": ("calendar", ("is_leap_month",)),
             "sign": ("western", ("sign", "sun_sign")), "year_pillar": ("saju", ("year_pillar",)),
             "month_pillar": ("saju", ("month_pillar",)), "day_pillar": ("saju", ("day_pillar",)),
             "hour_pillar": ("saju", ("hour_pillar",)), "today_day_pillar": ("saju", ("today_day_pillar", "today_pillar"))}


def _values(node, keys: tuple) -> list:
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in keys and v not in (None, ""):
                out.append(v)
            out += _values(v, keys)
    elif isinstance(node, list):
        for v in node:
            out += _values(v, keys)
    return out


def _same(key: str, got, want) -> bool:
    if key.endswith("pillar"):
        found = PILLAR.findall(str(got))
        return bool(found) and found[0] == PILLAR.findall(str(want))[0]
    if key == "is_leap_month":
        return isinstance(got, bool) and got is bool(want)
    if key == "sign":
        return str(got).strip().lower() == str(want).strip().lower()
    return str(got).strip()[:10] == str(want).strip()[:10]


def grade_fortune_task(case: dict, output: dict, notes: dict | None = None) -> bool:
    """Every computed fact the truth holds must be given and equal (the hour pillar only when the case has a birth
    hour; a pillar the truth marks as decided by a boundary term also needs the answer's boundary note), and the
    synthesis must pass check_synthesis. A Chinese-calendar answer that differs from the Korean date fails."""
    notes = notes if notes is not None else {}
    truth, wrong = case["truth"], []
    for key, (slot, names) in FACT_KEYS.items():
        if key not in truth or (key == "hour_pillar" and case["input"].get("birth_hour") is None):
            continue
        got = _values((output or {}).get(slot), names)
        if not got or not _same(key, got[0], truth[key]):
            wrong.append(key)
    if truth.get("boundary") and not _values((output or {}).get("saju"), ("boundary_note",)):
        wrong.append("boundary_note")
    synth = (output or {}).get("synthesis") or {}
    answers = synth.get("answers") if isinstance(synth, dict) else None
    body = answers[0] if answers else synth
    problems = check_synthesis(body, case["input"].get("birth_hour") is not None)
    if problems:
        wrong.append("synthesis:" + "|".join(problems))
    if wrong:
        notes["wrong"] = wrong
    return not wrong
