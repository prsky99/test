"""Necklace metering for the paid-switch condition (PM 11-16 21:13: per necklace, 30 days of outside successes
300+ and callers 20+). One reader of the run events: agent_market.necklaces.north_star.count per day (run_id
de-duplication, our tests and monitors count 0, cached answers are not runs), summed over the window.

    .venv/bin/python -m scripts.necklace_meter [--end YYYYMMDD] [--days 30] [--root gateway-data/necklaces]

Callers are not counted yet: the run events hold no caller field and the 11-10 user decision keeps names, mail,
IP and user agent out; the counting rule is the PM's (and possibly the user's) decision, so "callers" is null with
the reason until then.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

SUCCESS_BAR = 300
CALLER_BAR = 20


def meter(root: Path, end: str, days: int = 30) -> dict:
    from agent_market.necklaces.north_star import count, read_day
    last = datetime.strptime(end, "%Y%m%d")
    window = [(last - timedelta(days=i)).strftime("%Y%m%d") for i in range(days - 1, -1, -1)]
    per: dict[str, dict] = {}
    for day in window:
        out = count(read_day(root, day))
        for slug, row in out["by_slug"].items():
            acc = per.setdefault(slug, {"external_runs": 0, "succeeded": 0, "days_with_success": 0})
            acc["external_runs"] += row["external_runs"]
            acc["succeeded"] += row["succeeded"]
            acc["days_with_success"] += 1 if row["succeeded"] else 0
    for acc in per.values():
        acc["success_bar_met"] = acc["succeeded"] >= SUCCESS_BAR
        acc["callers"] = None
    return {"window": [window[0], window[-1]], "days": days, "bars": {"succeeded": SUCCESS_BAR, "callers": CALLER_BAR},
            "callers_note": "not counted: run events hold no caller field (11-10 decision); rule pending (PM)",
            "necklaces": dict(sorted(per.items()))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--end", default=(datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d"),
                        help="last day (UTC file day, YYYYMMDD); default yesterday")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    args = parser.parse_args(argv)
    print(json.dumps(meter(args.root, args.end, args.days), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
