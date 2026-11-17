"""daily-fortune-brief: the synthesis rule table, the banned words, the output structure and the whole-task grader
(PM 11-17, user request; BRIEF reports/fortune-necklace-2026-11-17/BRIEF.md).

Who does what: the agent team's fortune-synthesis substitute writes the answer from this table (compose() is the
reference); the runner never writes text. The gate grades only the computed facts (Korean lunar date, leap month,
Sun sign, year/month/day pillars, the hour pillar when a birth hour is given, today's day pillar) against the answer
set; the synthesis text is checked only for its structure, the banned words and the leading disclaimer.

Rules of the table (traditional systems, stated in the docs):
- Ten Gods (十神): today's day stem against the day master, by the five elements (wood > fire > earth > metal > water,
  each producing the next and controlling the one after next) and yin/yang. The public names are neutral glosses; the
  literal English names some books use ("Seven Killings", "Rob Wealth") read as threats or money talk and never
  appear in an answer.
- Western: the Sun sign's element against today's Moon sign element: same element in tune; fire-air and earth-water
  supportive; any other pair contrasting.
Same input and same day -> same answer (no randomness, no model).
"""
from __future__ import annotations

import re

DISCLAIMER = "For entertainment; not advice."
SOURCE = "AgentValCon rule table: traditional Ten Gods (Korean saju) and Western sign elements; facts per KASI rules"

# (relation of today's stem to the day master, same polarity) -> (public name, line)
TEN_GOD_LINES = {
    ("same", True): ("Bigyeon 比肩 (Peer)", "Today's energy matches your own: a good day to work alongside others at your own pace."),
    ("same", False): ("Geopjae 劫財 (Rival)", "A day of friendly competition: share credit and keep plans simple."),
    ("output", True): ("Siksin 食神 (Expression)", "Ideas come easily today: make something, write, or cook for someone."),
    ("output", False): ("Sanggwan 傷官 (Bold voice)", "You may speak more directly than usual today: choose your words with care."),
    ("wealth", True): ("Pyeonjae 偏財 (Opportunity)", "Chances can come from unexpected directions today: stay curious."),
    ("wealth", False): ("Jeongjae 正財 (Steady effort)", "Routine work goes well today: finish what you started."),
    ("officer", True): ("Pyeongwan 偏官 (Challenge)", "Today brings a push from outside: meet it calmly, one step at a time."),
    ("officer", False): ("Jeonggwan 正官 (Order)", "Structure helps today: plans, lists and agreements go smoothly."),
    ("resource", True): ("Pyeonin 偏印 (Insight)", "A good day for unusual reading and quiet thinking."),
    ("resource", False): ("Jeongin 正印 (Support)", "Help comes from mentors and familiar people today: accept it gladly."),
}
ELEMENTS = ["wood", "fire", "earth", "metal", "water"]
RELATIONS = ["same", "output", "wealth", "officer", "resource"]
STEM_ELEMENT = {"甲": ("wood", "yang"), "乙": ("wood", "yin"), "丙": ("fire", "yang"), "丁": ("fire", "yin"),
                "戊": ("earth", "yang"), "己": ("earth", "yin"), "庚": ("metal", "yang"), "辛": ("metal", "yin"),
                "壬": ("water", "yang"), "癸": ("water", "yin")}
SIGN_ELEMENT = {"aries": "fire", "leo": "fire", "sagittarius": "fire", "taurus": "earth", "virgo": "earth",
                "capricorn": "earth", "gemini": "air", "libra": "air", "aquarius": "air", "cancer": "water",
                "scorpio": "water", "pisces": "water"}
ELEMENT_THEME = {"fire": "starting things", "earth": "practical tasks", "air": "conversations",
                 "water": "close relationships"}
SUPPORTIVE = {frozenset(("fire", "air")), frozenset(("earth", "water"))}

NOTE_LUNAR = "Lunar dates follow the Korean calendar (KASI rules), which differs from the Chinese calendar on some days."
NOTE_TIME = "Times are Korean standard time, with no true-solar-time correction."
NOTE_NO_HOUR = "No birth hour was given, so three pillars (six characters) are used and the hour pillar is left out."

# Never in an answer: health, money, legal or medical claims or advice, and frightening words (BRIEF section 3).
# "Cancer" is a Sun sign, so the illness is matched as tumour words and "cancerous" only.
BANNED = re.compile(r"\b(?:diagnos\w*|disease\w*|illness\w*|sick\w*|cancerous|tumou?rs?|surger\w*|medic\w*|doctor\w*|symptom\w*|"
                    r"cure\w*|therap\w*|pregnan\w*|invest\w*|stocks?|crypto\w*|bitcoin|lotter\w*|gambl\w*|loans?|debts?|"
                    r"buy\w*|sell\w*|trad(?:e|ing)|profit\w*|money|lawsuit\w*|sue|courts?|lawyer\w*|legal\w*|death\w*|"
                    r"dies?|dying|dead|accident\w*|disaster\w*|danger\w*|kill\w*|misfortune\w*|curse\w*|doom\w*|injur\w*|"
                    r"catastroph\w*|rob\w*)\b", re.I)

# fortune.daily.v1 output of the synthesis step (answer, source and disclaimer required by the contract draft)
OUTPUT_KEYS = ("disclaimer", "answer", "source", "summary", "western_line", "saju_line", "ten_god", "moon_relation",
               "notes")


def stem_of(pillar: str) -> str | None:
    """The heavenly stem character of a pillar written "Gap-ja 甲子" (or "甲子")."""
    m = re.search(r"([甲乙丙丁戊己庚辛壬癸])[子丑寅卯辰巳午未申酉戌亥]", str(pillar or ""))
    return m.group(1) if m else None


def ten_god(day_pillar: str, today_pillar: str) -> tuple[str, str, str]:
    """(public name, line, relation) of today's stem against the day master."""
    me, other = STEM_ELEMENT[stem_of(day_pillar)], STEM_ELEMENT[stem_of(today_pillar)]
    rel = RELATIONS[(ELEMENTS.index(other[0]) - ELEMENTS.index(me[0])) % 5]
    name, line = TEN_GOD_LINES[(rel, other[1] == me[1])]
    return name, line, rel


def moon_relation(sign: str, moon_sign: str) -> str:
    a, b = SIGN_ELEMENT[sign.lower()], SIGN_ELEMENT[moon_sign.lower()]
    return "in_tune" if a == b else "supportive" if frozenset((a, b)) in SUPPORTIVE else "contrasting"


def western_line(sign: str, moon_sign: str) -> str:
    element, moon_element = SIGN_ELEMENT[sign.lower()], SIGN_ELEMENT[moon_sign.lower()]
    rel = moon_relation(sign, moon_sign)
    if rel == "in_tune":
        return f"The Moon in {moon_sign} shares your {element} element: feelings and plans line up today."
    if rel == "supportive":
        return (f"The Moon in {moon_sign} ({moon_element}) supports your {sign} ({element}): a good mood for "
                f"{ELEMENT_THEME[element]}.")
    return (f"The Moon in {moon_sign} ({moon_element}) contrasts with your {sign} ({element}): take a moment before "
            f"reacting today.")


def compose(facts: dict) -> dict:
    """Reference synthesis. FACTS: sign, moon_sign, day_pillar, today_day_pillar, hour_pillar (None without a birth
    hour) and boundary_note (optional), as the calendar, western and saju steps give them."""
    name, s_line, _rel = ten_god(facts["day_pillar"], facts["today_day_pillar"])
    w_line = western_line(facts["sign"], facts["moon_sign"])
    s_text = f"Today's day pillar {facts['today_day_pillar']} meets your day pillar {facts['day_pillar']} as {name}. {s_line}"
    notes = [NOTE_LUNAR, NOTE_TIME] + ([] if facts.get("hour_pillar") else [NOTE_NO_HOUR])
    if facts.get("boundary_note"):
        notes.append(str(facts["boundary_note"]))
    summary = f"{facts['sign']} with the Moon in {facts['moon_sign']}; today is a {name.split(' (')[-1].rstrip(')')} day in saju."
    answer = " ".join([DISCLAIMER, summary, w_line, s_text] + notes)
    return {"disclaimer": DISCLAIMER, "answer": answer, "source": SOURCE, "summary": summary, "western_line": w_line,
            "saju_line": s_text, "ten_god": name, "moon_relation": moon_relation(facts["sign"], facts["moon_sign"]),
            "notes": notes}


def check_synthesis(output: dict, has_hour: bool) -> list[str]:
    """Problems of a synthesis answer: [] when the structure, the disclaimer, the notes and the words are right."""
    if not isinstance(output, dict):
        return ["not_an_object"]
    problems = []
    answer = str(output.get("answer") or "")
    if not answer.startswith(DISCLAIMER) or output.get("disclaimer") != DISCLAIMER:
        problems.append("disclaimer_not_first")
    for key in ("answer", "source", "disclaimer"):
        if not output.get(key):
            problems.append("missing_" + key)
    text = " ".join(str(v) for v in output.values() if isinstance(v, (str, list)))
    found = sorted({m.group(0).lower() for m in BANNED.finditer(text)})
    if found:
        problems.append("banned:" + ",".join(found))
    if "Korean calendar" not in answer or "Korean standard time" not in answer:
        problems.append("basis_note_missing")
    if not has_hour and "hour pillar is left out" not in answer:
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
