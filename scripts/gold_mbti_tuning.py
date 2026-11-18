"""Tuning answer set for the personality-fortune-brief substitutes (PM 11-18 14:5x: drafts by 11-19 12:00; holdout by ops).

    .venv/bin/python -m scripts.gold_mbti_tuning [--split substitute-tuning]

Writes gateway-data/necklaces/gold/personality-fortune-brief/<split>.jsonl from the fixed cases below (no network call).
Every truth is computed here from a public definition or the written contract, not from our agents:
- The 16 type codes and their four letters (Wikipedia "Myers-Briggs Type Indicator"); case and an -A/-T suffix are
  ignored by the contract (persona.mbti_profile.v1 input pattern).
- Keirsey's four temperaments from the letters: S+J = SJ, S+P = SP, N+F = NF, N+T = NT (Wikipedia "Keirsey
  Temperament Sorter").
- The age range: a person is exactly AGE ('man' age, the international count) on TODAY when born after the day
  AGE+1 years before TODAY and on or before the day AGE years before it (Wikipedia "East Asian age reckoning");
  29 February falls back to 28 February in a year without it.
- The sample birth date: the contract's sample_rule, recomputed here: first + sha256('mbti-fortune|v1|TYPE|AGE|TODAY')
  mod the range's length in days. A range outside 1912-01-01..2100-12-31 is refused as invalid_input.
- mbti-fortune: the reading is graded only by the gate's check_mbti_synthesis (leading disclaimer, notes, banned words,
  the sample, no-hour, Korean calendar, own-mapping and trademark notices, and each axis with the input's letter).
A split is never rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUG = "personality-fortune-brief"
TYPES = {"name": "Myers-Briggs Type Indicator (the 16 types)", "url": "https://en.wikipedia.org/wiki/Myers%E2%80%93Briggs_Type_Indicator"}
KEIRSEY = {"name": "Keirsey Temperament Sorter (SJ, SP, NF, NT)", "url": "https://en.wikipedia.org/wiki/Keirsey_Temperament_Sorter"}
AGE = {"name": "International ('man') age count", "url": "https://en.wikipedia.org/wiki/East_Asian_age_reckoning"}
RULE = {"name": "persona.mbti_profile.v1 sample_rule (sha256 draw inside the age range)",
        "url": "https://en.wikipedia.org/wiki/SHA-2"}
READING = {"name": "personality-fortune-brief gate rules (necklaces/mbti_gate.py, fortune_rules.py)",
           "url": "https://en.wikipedia.org/wiki/Myers%E2%80%93Briggs_Type_Indicator"}
REFUSED = {"refused": "invalid_input"}
SUPPORTED = (date(1912, 1, 1), date(2100, 12, 31))
AXES = ("energy", "information", "decisions", "structure")


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def profile_truth(mbti: str, age: int, today: str) -> dict:
    code = mbti.strip().upper().split("-")[0]
    t = date.fromisoformat(today)
    first, last = _years_before(t, age + 1) + timedelta(days=1), _years_before(t, age)
    if first < SUPPORTED[0] or last > SUPPORTED[1]:
        return dict(REFUSED)
    seed = int(hashlib.sha256(f"mbti-fortune|v1|{code}|{age}|{today}".encode()).hexdigest(), 16)
    sample = first + timedelta(days=seed % ((last - first).days + 1))
    temperament = code[1] + (code[3] if code[1] == "S" else code[2])
    return {"type": code, "axes": dict(zip(AXES, code)), "temperament": temperament,
            "sample_range": [first.isoformat(), last.isoformat()], "sample_birth_date": sample.isoformat()}


def profile(cid, mbti, age, today):
    truth = profile_truth(mbti, age, today)
    sources = [AGE] if truth.get("refused") else [TYPES, KEIRSEY, AGE, RULE]
    return {"case_id": f"mbti:{cid}", "agent": "mbti-profile", "input": {"mbti": mbti, "age": age, "today": today},
            "task_type": "substitute", "truth": truth, "truth_sources": sources}


def reading(cid, inp):
    return {"case_id": f"mbti:{cid}", "agent": "mbti-fortune", "input": inp, "task_type": "substitute",
            "truth": {"type": inp["type"]}, "truth_sources": [READING]}


CASES = [
    # mbti-profile (18): all 16 types once, with lower case, -A/-T, age 0 and 110, a 29 February today and year ends
    profile("intj-30", "INTJ", 30, "2026-11-18"),
    profile("intp-25", "intp", 25, "2026-11-18"),
    profile("entj-41", "ENTJ-A", 41, "2026-11-19"),
    profile("entp-19", "entp-t", 19, "2026-11-19"),
    profile("infj-33", "INFJ", 33, "2026-11-20"),
    profile("infp-0", "infp", 0, "2026-11-18"),
    profile("enfj-58", "ENFJ", 58, "2026-11-18"),
    profile("enfp-27", "ENFP-T", 27, "2026-12-31"),
    profile("istj-110", "ISTJ", 110, "2026-11-18"),
    profile("isfj-64", "isfj", 64, "2026-11-18"),
    profile("estj-45", "ESTJ", 45, "2027-01-01"),
    profile("esfj-22", "ESFJ-A", 22, "2026-11-18"),
    profile("istp-36", "ISTP", 36, "2028-02-29"),
    profile("isfp-17", "ISFP", 17, "2026-11-18"),
    profile("estp-50", "estp", 50, "2026-11-19"),
    profile("esfp-29", "ESFP", 29, "2026-11-18"),
    profile("refused-before-1912", "INTJ", 109, "2020-01-01"),
    profile("refused-after-2100", "ENFP", 0, "2101-01-01"),
    # mbti-fortune (12): the reading's structure and notices only, with and without the sun sign and day master
    reading("read-intj-full", {"type": "INTJ", "sign": "Leo", "element": "Fire", "day_master": "Gap 甲",
                               "today_day_pillar": "Byeong-sin 丙申", "today": "2026-11-18",
                               "sample_birth_date": "1996-08-01"}),
    reading("read-esfp-bare", {"type": "ESFP", "today": "2026-11-18"}),
    reading("read-infp-water", {"type": "INFP", "sign": "Pisces", "element": "Water", "day_master": "Im 壬",
                                "today_day_pillar": "Jeong-yu 丁酉", "today": "2026-11-19",
                                "sample_birth_date": "1990-03-05"}),
    reading("read-estj-earth", {"type": "ESTJ", "sign": "Capricorn", "element": "Earth", "day_master": "Mu 戊",
                                "today_day_pillar": "Byeong-sin 丙申", "today": "2026-11-18",
                                "sample_birth_date": "2001-01-05"}),
    reading("read-isfj-bare", {"type": "ISFJ", "today": "2026-11-20"}),
    reading("read-entp-air", {"type": "ENTP", "sign": "Libra", "element": "Air", "day_master": "Gyeong 庚",
                              "today_day_pillar": "Jeong-yu 丁酉", "today": "2026-11-19",
                              "sample_birth_date": "1995-10-10"}),
    reading("read-istp-sign-only", {"type": "ISTP", "sign": "Sagittarius", "element": "Fire", "today": "2026-11-18"}),
    reading("read-enfj-master-only", {"type": "ENFJ", "day_master": "Byeong 丙", "today_day_pillar": "Byeong-sin 丙申",
                                      "today": "2026-11-18"}),
    reading("read-intp-year-end", {"type": "INTP", "today": "2026-12-31"}),
    reading("read-esfj-new-year", {"type": "ESFJ", "today": "2027-01-01"}),
    reading("read-infj-leap-day", {"type": "INFJ", "today": "2028-02-29"}),
    reading("read-estp-fire", {"type": "ESTP", "sign": "Aries", "element": "Fire", "day_master": "Jeong 丁",
                               "today_day_pillar": "Mu-sul 戊戌", "today": "2026-11-21",
                               "sample_birth_date": "1985-04-01"}),
]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--split", default="substitute-tuning")
    ns = p.parse_args(argv)
    folder = ROOT / "gateway-data/necklaces/gold" / SLUG
    out = folder / f"{ns.split}.jsonl"
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    folder.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for c in CASES:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    manifest = folder / "manifest.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        data = {}
    by_agent = {}
    for c in CASES:
        by_agent[c["agent"]] = by_agent.get(c["agent"], 0) + 1
    data.setdefault("files", {})[ns.split] = {"cases": len(CASES), "by_agent": by_agent,
                                              "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                                              "for": "personality-fortune-brief substitutes (mbti-profile, mbti-fortune; contract input mbti), tuning only; holdout by ops"}
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"wrote {len(CASES)} cases to {out}: {by_agent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
