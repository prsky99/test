"""16-type personality fortune (mbti-fortune-brief, PM 11-17, user request): the sample birthday and the rule tables.

Public wording says "16-type personality code"; MBTI is a trademark of The Myers-Briggs Company and we are not
affiliated. The type descriptions here are our own few words, not anyone's published text. There is no recognised
mapping from the 16 types to the five elements or to sign elements: the tables below are our own mapping for fun.

Sample birthday (PM decision): the date lies in (today - (age + 1) years, today - age years], so the age in full years
on today is exactly AGE; the day is drawn by a reproducible pseudo-random number seeded with
sha256("mbti-fortune|v1|" + TYPE + "|" + age + "|" + today). The same type, age and day give the same date; another
day gives another date. February 29 and leap-month dates can be drawn like any other day. A date before 1912 (outside
the almanac) is refused, never redrawn (persona.mbti_profile.v1 sample_rule; necklaces.mbti_gate checks it apart).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta

TYPES = frozenset(a + b + c + d for a in "EI" for b in "SN" for c in "TF" for d in "JP")
SEED_PREFIX = "mbti-fortune|v1|"
RULES_VERSION = "mbti-fortune-rules-v1"
SAMPLE_NOTE = "The birth date is a sample drawn from your age, not your real birthday."
MAPPING_NOTE = "The 16-type part is our own mapping for fun."
TRADEMARK_NOTE = "MBTI is a trademark of The Myers-Briggs Company; not affiliated."


def normalize_type(text) -> str:
    """'intj', 'INTJ-A', ' Enfp-T ' -> the four letters; ValueError when it is not one of the 16 types."""
    code = re.sub(r"[-_ ]?[AaTt]$", "", str(text or "").strip()) if len(str(text or "").strip()) > 4 else str(text or "").strip()
    code = code.upper()
    if code not in TYPES:
        raise ValueError("Use one of the 16 four-letter type codes, such as INTJ or ENFP.")
    return code


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:                      # February 29 in a year without one
        return day.replace(year=day.year - years, day=28)


FIRST_DAY, LAST_DAY = date(1912, 1, 1), date(2100, 12, 31)     # the almanac's range


def sample_range(age: int, today: date) -> tuple[date, date]:
    """(first, last) dates whose full-year age on TODAY is AGE."""
    if not isinstance(age, int) or isinstance(age, bool) or not 0 <= age <= 110:
        raise ValueError("Age must be a whole number from 0 to 110.")
    return _years_before(today, age + 1) + timedelta(days=1), _years_before(today, age)


def sample_birthday(code: str, age: int, today: date) -> date:
    """persona.mbti_profile.v1 sample_rule (workflow 11-17): the range's dates in ascending order at index
    int(sha256(...).hexdigest(), 16) mod the range's length; a range outside 1912-2100 is refused, never redrawn."""
    first, last = sample_range(age, today)
    if first < FIRST_DAY or last > LAST_DAY:
        raise ValueError("The age range falls outside the supported calendar years (1912-2100).")
    seed = int(hashlib.sha256(f"{SEED_PREFIX}{code}|{age}|{today.isoformat()}".encode()).hexdigest(), 16)
    return first + timedelta(days=seed % ((last - first).days + 1))


def temperament(code: str) -> str:
    """NT, NF, SJ or SP."""
    return code[1] + (code[2] if code[1] == "N" else code[3])


# axis letter x the ten-god relation of today's stem to the day master (same, output, wealth, officer, resource)
AXIS_LINES = {
    "E": {"same": "a good day to bring people together", "output": "say the idea out loud in a group",
          "wealth": "turn a chat into a small plan", "officer": "lead the meeting you would usually join",
          "resource": "ask a friend for their view"},
    "I": {"same": "keep a steady pace on your own terms", "output": "share one idea you have been holding back",
          "wealth": "finish one quiet task you started", "officer": "set one clear boundary kindly",
          "resource": "read or reflect before deciding"},
    "S": {"same": "trust the routine that works", "output": "make something with your hands",
          "wealth": "tidy one practical detail", "officer": "follow the checklist step by step",
          "resource": "learn from a worked example"},
    "N": {"same": "follow the pattern you already see", "output": "sketch the idea before it fades",
          "wealth": "connect two plans into one", "officer": "pick one big idea and give it a frame",
          "resource": "look for the bigger picture in a book or talk"},
    "T": {"same": "weigh the options on their merits", "output": "explain your reasoning plainly",
          "wealth": "simplify one process", "officer": "test your plan against the facts",
          "resource": "ask a sharp question and listen"},
    "F": {"same": "stay true to what matters to you", "output": "say thank you to someone specific",
          "wealth": "make room for a small kindness", "officer": "keep a promise you care about",
          "resource": "accept support when it is offered"},
    "J": {"same": "keep the schedule you set", "output": "close one open loop",
          "wealth": "plan the week in a short list", "officer": "deliver what you agreed on time",
          "resource": "review before you commit"},
    "P": {"same": "leave room for a pleasant surprise", "output": "try a new approach just for today",
          "wealth": "say yes to a small detour", "officer": "pick one thing to finish among many",
          "resource": "explore before you choose"},
}
# E/I x today's Moon element
MOON_LINES = {
    "E": {"fire": "Today's fire Moon suits lively company.", "earth": "Today's earth Moon suits a shared practical task.",
          "air": "Today's air Moon suits easy conversation.", "water": "Today's water Moon suits warm one-to-one talks."},
    "I": {"fire": "Today's fire Moon suits a short personal project.", "earth": "Today's earth Moon suits a calm, orderly day.",
          "air": "Today's air Moon suits reading and ideas.", "water": "Today's water Moon suits quiet time to recharge."},
}
TEMPERAMENT_LINES = {
    "NT": "Today's line for NT types: curiosity is your best tool; ask why once more.",
    "NF": "Today's line for NF types: a small gesture of meaning goes a long way.",
    "SJ": "Today's line for SJ types: steady care keeps the day on track.",
    "SP": "Today's line for SP types: a hands-on try beats a long plan.",
}
