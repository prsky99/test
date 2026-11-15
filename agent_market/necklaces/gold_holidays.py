"""Gold set for holidays-at-address (the location hub's holiday consumer, agent team country grid c378a302, 11-15).

The task: where an address is and that country's national public holidays in a year. Places are the airports of
the quakes-near-airport set (OurAirports reference point and ISO country, public domain), typed as
"<airport name>, <country code>"; overseas territories and disputed places are left out (the country grid answers
them with candidates, agent team). Truth holidays are Nager.Date's (date.nager.at, keyless public API, MIT): the
year's holidays marked global and of type Public, one request per country and year, through the shared ledger as
reference_checks. That share is 10 a domain a day, so the builder keeps every country it fetched under
gold/raw/nager-<year>/ and asks only for the missing ones; the set is written once it can hold 90 cases.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gold import _now, split, write_set
from .gold_filings import fetch_text
from .judge import DEFAULT_ROOT

SLUG = "holidays-at-address"
ANSWER_SET = "holidays-at-address-v1"
NAGER = "https://date.nager.at/api/v3/PublicHolidays/{year}/{cc}"
YEAR = 2026
NEEDED = 90
TERRITORIES = {"GU", "PR", "VI", "AS", "MP", "NC", "PF", "RE", "GF", "GP", "MQ", "YT", "PM", "BL", "MF", "WF", "BQ",
               "CW", "AW", "SX", "CC", "CX", "NF", "HK", "MO", "GI", "IM", "JE", "GG", "FO", "GL", "AX", "PS", "EH", "XK"}


def places(root: Path) -> list[dict]:
    raw = Path(root) / "gold" / "raw" / "airports-20261115" / "airport-cases.json"
    rows = json.loads(raw.read_text(encoding="utf-8"))["cases"]
    return [r for r in rows if r["truth"].get("country") and r["truth"]["country"] not in TERRITORIES]


def national(days: list[dict]) -> list[str]:
    return sorted({d["date"] for d in days if d.get("global", True) and "Public" in (d.get("types") or ["Public"])})


def fetch_missing(root: Path, countries: list[str], year: int = YEAR, get=fetch_text) -> dict:
    """Ask Nager.Date for the countries not kept yet, until the ledger share is used; returns what is kept."""
    cache = Path(root) / "gold" / "raw" / f"nager-{year}"
    cache.mkdir(parents=True, exist_ok=True)
    kept, stopped = {}, None
    for cc in countries:
        path = cache / f"{cc}.json"
        if not path.exists() and stopped is None:
            try:
                path.write_text(get(NAGER.format(year=year, cc=cc)), encoding="utf-8")
            except RuntimeError as exc:                 # provider budget: try again tomorrow
                stopped = str(exc)
            except Exception as exc:                    # noqa: BLE001 - 404 = Nager has no such country
                path.write_text(json.dumps({"unavailable": type(exc).__name__}), encoding="utf-8")
        if path.exists():
            body = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(body, list) and national(body):
                kept[cc] = national(body)
    return {"kept": kept, "stopped": stopped}


def build(root: Path = DEFAULT_ROOT, get=fetch_text, year: int = YEAR) -> dict:
    rows = places(root)
    countries = sorted({r["truth"]["country"] for r in rows}, key=lambda c: -sum(r["truth"]["country"] == c for r in rows))
    fetched = fetch_missing(root, countries, year, get)
    cases = []
    for r in rows:
        cc = r["truth"]["country"]
        if cc not in fetched["kept"]:
            continue
        t = r["truth"]
        cases.append({"case_id": f"holidays:{r['input']['code']}", "task_type": "whole_task", "stratum": r["stratum"],
                      "input": {"address": f"{t['name']}, {cc}", "year": year},
                      "truth": {"lat": t["lat"], "lon": t["lon"], "kind": "airport", "tolerance_km": 5,
                                "country_code": cc, "year": year, "holidays": fetched["kept"][cc]},
                      "truth_sources": [{"name": "OurAirports airports.csv (public domain)",
                                         "url": "https://davidmegginson.github.io/ourairports-data/airports.csv"},
                                        {"name": "Nager.Date public holidays (global, Public)",
                                         "url": NAGER.format(year=year, cc=cc), "fetched_at": _now()}]})
    out = {"cases": len(cases), "countries_kept": len(fetched["kept"]), "countries": len(countries),
           "stopped": fetched["stopped"]}
    if len(cases) >= NEEDED:
        out["manifest"] = write_set(Path(root), SLUG, split(cases),
                                    {"answer_set": ANSWER_SET, "built_from": len(cases), "year": year})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
