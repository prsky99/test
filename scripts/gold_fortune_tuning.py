"""Tuning answer set for the daily-fortune-brief substitutes (PM 11-17 21:4x: 30 tuning tasks; holdout is built by ops).

    .venv/bin/python -m scripts.gold_fortune_tuning [--split tuning]

Writes gateway-data/necklaces/gold/daily-fortune-brief/<split>.jsonl from the fixed cases below (no network call).
Every truth comes from a public source, not from our code:
- Korean public holidays (the government calendar, set from the KASI almanac): Seollal (lunar 1-1), Chuseok (lunar
  8-15) and Buddha's Birthday (lunar 4-8) by year; the KASI leap months of 2020 (4th), 2023 (2nd), 2025 (6th).
- KASI solar terms: Ipchun 2024-02-04 17:27 and 2025-02-03 23:10 (KST); births a few hours before and after decide
  the year and month pillars.
- The sexagenary day table (Wikipedia "Sexagenary cycle": 2000-01-01 = 戊午, i.e. (JDN + 49) mod 60 with 0 = 甲子),
  the year stems and branches by Ipchun, the month stems by the five-tiger rule and the hour stems by the five-rat
  rule (standard saju texts); the search-and-RAG role tasks of 11-17 for three day pillars.
- Sun sign date ranges from the Wikipedia sign articles, for dates at least five days from a cusp.
Range and input checks are cases too: years before 1912 and after 2100, and a leap-month flag for a month that has no
leap month, are refused as invalid_input (never answered). A split is never rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUG = "daily-fortune-brief"
HOLIDAYS = {"name": "Korean public holidays (government calendar from the KASI almanac)",
            "url": "https://astro.kasi.re.kr/life/pageView/5"}
IPCHUN = {"name": "KASI solar terms (Ipchun, KST)", "url": "https://astro.kasi.re.kr/life/pageView/9"}
SEXAGENARY = {"name": "Sexagenary days table (2000-01-01 = 戊午)", "url": "https://en.wikipedia.org/wiki/Sexagenary_cycle"}
SIGNS = {"name": "Sun sign date ranges (Wikipedia sign articles)", "url": "https://en.wikipedia.org/wiki/Astrological_sign"}
REFUSED = {"refused": "invalid_input"}


def case(agent, cid, inp, truth, source):
    return {"case_id": f"fortune:{cid}", "agent": agent, "input": inp, "task_type": "substitute", "truth": truth,
            "truth_sources": [source]}


CASES = [
    # korean-lunar (10)
    case("korean-lunar", "seollal-2020", {"birth_date": "2020-01-25", "calendar": "solar"},
         {"solar_date": "2020-01-25", "lunar_date": "2020-01-01", "is_leap_month": False}, HOLIDAYS),
    case("korean-lunar", "seollal-2023", {"birth_date": "2023-01-22", "calendar": "solar"},
         {"solar_date": "2023-01-22", "lunar_date": "2023-01-01", "is_leap_month": False}, HOLIDAYS),
    case("korean-lunar", "seollal-2026", {"birth_date": "2026-02-17", "calendar": "solar"},
         {"solar_date": "2026-02-17", "lunar_date": "2026-01-01", "is_leap_month": False}, HOLIDAYS),
    case("korean-lunar", "seollal-2017", {"birth_date": "2017-01-28", "calendar": "solar"},
         {"solar_date": "2017-01-28", "lunar_date": "2017-01-01", "is_leap_month": False}, HOLIDAYS),
    case("korean-lunar", "chuseok-2021", {"birth_date": "2021-08-15", "calendar": "lunar"},
         {"solar_date": "2021-09-21", "lunar_date": "2021-08-15", "is_leap_month": False}, HOLIDAYS),
    case("korean-lunar", "chuseok-2024", {"birth_date": "2024-08-15", "calendar": "lunar"},
         {"solar_date": "2024-09-17", "lunar_date": "2024-08-15", "is_leap_month": False}, HOLIDAYS),
    case("korean-lunar", "buddha-2025", {"birth_date": "2025-04-08", "calendar": "lunar"},
         {"solar_date": "2025-05-05", "lunar_date": "2025-04-08", "is_leap_month": False}, HOLIDAYS),
    case("korean-lunar", "leap2-2023", {"birth_date": "2023-02-15", "calendar": "lunar", "is_leap_month": True},
         {"solar_date": "2023-04-05", "lunar_date": "2023-02-15", "is_leap_month": True}, HOLIDAYS),
    case("korean-lunar", "leap4-2020-solar", {"birth_date": "2020-06-06", "calendar": "solar"},
         {"solar_date": "2020-06-06", "lunar_date": "2020-04-15", "is_leap_month": True}, HOLIDAYS),
    case("korean-lunar", "no-leap4-2024", {"birth_date": "2024-04-08", "calendar": "lunar", "is_leap_month": True},
         REFUSED, HOLIDAYS),
    # western-sign (6)
    case("western-sign", "pisces-1990", {"birth_date": "1990-03-05"}, {"sign": "Pisces"}, SIGNS),
    case("western-sign", "capricorn-2001", {"birth_date": "2001-01-05"}, {"sign": "Capricorn"}, SIGNS),
    case("western-sign", "leo-1985", {"birth_date": "1985-07-30"}, {"sign": "Leo"}, SIGNS),
    case("western-sign", "libra-1995", {"birth_date": "1995-10-10"}, {"sign": "Libra"}, SIGNS),
    case("western-sign", "gemini-2010", {"birth_date": "2010-06-01"}, {"sign": "Gemini"}, SIGNS),
    case("western-sign", "sagittarius-1988", {"birth_date": "1988-12-01"}, {"sign": "Sagittarius"}, SIGNS),
    # saju-pillars (12)
    case("saju-pillars", "day-1990-03-15", {"birth_date": "1990-03-15", "today": "2026-11-18"},
         {"day_pillar": "己卯", "today_day_pillar": "丙申", "hour_pillar": None}, SEXAGENARY),
    case("saju-pillars", "day-1985-07-30", {"birth_date": "1985-07-30", "today": "2026-11-18"},
         {"day_pillar": "庚午", "today_day_pillar": "丙申", "hour_pillar": None}, SEXAGENARY),
    case("saju-pillars", "day-2001-12-25", {"birth_date": "2001-12-25", "today": "2026-11-19"},
         {"day_pillar": "壬戌", "today_day_pillar": "丁酉", "hour_pillar": None}, SEXAGENARY),
    case("saju-pillars", "three-2000-01-01", {"birth_date": "2000-01-01", "today": "2026-11-18"},
         {"year_pillar": "己卯", "month_pillar": "丙子", "day_pillar": "戊午", "hour_pillar": None}, SEXAGENARY),
    case("saju-pillars", "ipchun-2024-before", {"birth_date": "2024-02-04", "birth_hour": 15, "today": "2026-11-18"},
         {"year_pillar": "癸卯", "month_pillar": "乙丑", "day_pillar": "戊戌", "boundary": True}, IPCHUN),
    case("saju-pillars", "ipchun-2024-after", {"birth_date": "2024-02-04", "birth_hour": 19, "today": "2026-11-18"},
         {"year_pillar": "甲辰", "month_pillar": "丙寅", "day_pillar": "戊戌", "hour_pillar": "壬戌", "boundary": True},
         IPCHUN),
    case("saju-pillars", "ipchun-2025-before", {"birth_date": "2025-02-03", "birth_hour": 21, "today": "2026-11-18"},
         {"year_pillar": "甲辰", "month_pillar": "丁丑", "boundary": True}, IPCHUN),
    case("saju-pillars", "ipchun-2025-after", {"birth_date": "2025-02-03", "birth_hour": 23, "today": "2026-11-18"},
         {"year_pillar": "乙巳", "month_pillar": "戊寅", "boundary": True}, IPCHUN),
    case("saju-pillars", "hour-1990-05-15", {"birth_date": "1990-05-15", "birth_hour": 14, "today": "2026-11-18"},
         {"year_pillar": "庚午", "month_pillar": "辛巳", "day_pillar": "庚辰", "hour_pillar": "癸未"}, SEXAGENARY),
    case("saju-pillars", "three-1950-06-25", {"birth_date": "1950-06-25", "today": "2026-11-18"},
         {"year_pillar": "庚寅", "month_pillar": "壬午", "hour_pillar": None}, SEXAGENARY),
    case("saju-pillars", "before-1912", {"birth_date": "1911-12-31"}, REFUSED, SEXAGENARY),
    case("saju-pillars", "after-2100", {"birth_date": "2101-01-01"}, REFUSED, SEXAGENARY),
    # fortune-daily (2): structure, disclaimer, notes and banned words only (the reading text is not graded)
    case("fortune-daily", "no-hour", {"sign": "Pisces", "element": "Water", "day_master": "Gi 己",
                                      "today_day_pillar": "Byeong-sin 丙申", "today": "2026-11-18"},
         {"has_hour": False}, SIGNS),
    case("fortune-daily", "with-hour", {"sign": "Leo", "element": "Fire", "day_master": "Gyeong 庚",
                                        "today_day_pillar": "Jeong-yu 丁酉", "today": "2026-11-19",
                                        "hour_pillar": "Gye-mi 癸未"},
         {"has_hour": True}, SIGNS),
]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--split", default="tuning")
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
                                              "for": "daily-fortune-brief substitutes, tuning only (holdout by ops)"}
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"wrote {len(CASES)} cases to {out}: {by_agent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
