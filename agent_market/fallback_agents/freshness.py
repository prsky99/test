"""How old each local data file of the AgentValCon substitutes is (PM 11-15 14:57), for the ops watch alarm.

Live answers already carry freshness (data_as_of, age_seconds, max_age_seconds) and turn "stale" past MAX_AGE.
Files built or synced ahead of time do too once read, but a file nobody asked about would stay quiet; this lists
every one with its own date, its limit and who rebuilds it:

    .venv/bin/python -m agent_market.fallback_agents.freshness        # JSON lines, exit 1 when one is stale

No network call and no database: it reads the files' own build dates (or the file time when they keep none).
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DAY = 86400
# file -> (agents that read it, limit in days, how it is renewed)
FILES = {
    "airports.json": (["airport-lookup"], 8, "jobs: python -m agent_market.fallback_agents.airports --sync, daily"),
    "ofac-sdn.json": (["ofac-sdn"], 3, "jobs: python -m agent_market.fallback_agents.ofac --sync, daily"),
    "kev-catalog.json": (["cisa-kev"], 1, "refreshed by cisa-kev itself from the CISA feed (hourly cache)"),
    "nvd-cve.sqlite3": (["nvd-cve", "software-incident"], 2, "jobs: NVD snapshot refresh (fallback_agents.nvd_store)"),
    "tz-grid.bin": (["tz-time", "airport-lookup"], 400,
                    "scripts/build_tz_grid.py outside production when timezonefinder-data or tzdata changes"),
    "country-grid.bin": (["holiday-calendar"], 400,
                         "scripts/build_country_grid.py outside production when Natural Earth publishes"),
}


def _grid_built(path: Path) -> str | None:
    raw = path.open("rb").read(1 << 20)
    if not raw.startswith(b"AVCTZ1\n"):
        return None
    size = struct.unpack_from("<I", raw, 7)[0]
    return json.loads(raw[11:11 + size]).get("built")


def _date(path: Path) -> tuple[float | None, str]:
    """(seconds since epoch of the data, what the date is): the file's own date when it keeps one."""
    try:
        if path.suffix == ".bin":
            built = _grid_built(path)
            if built:
                return datetime.strptime(built, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp(), "built"
        if path.name == "airports.json":
            fetched = json.loads(path.read_text(encoding="utf-8")).get("fetched_at")
            if isinstance(fetched, (int, float)):
                return float(fetched), "fetched_at"
        return path.stat().st_mtime, "file time"
    except (OSError, ValueError):
        return None, "unreadable"


def report(data_dir: Path | str | None = None, now: float | None = None) -> list[dict]:
    root = Path(data_dir or os.environ.get("FALLBACK_AGENTS_DATA", "gateway-data/fallback-agents"))
    now = time.time() if now is None else now
    out = []
    for name, (agents, limit_days, renew) in FILES.items():
        path = root / name
        if not path.exists():
            out.append({"file": name, "agents": agents, "present": False, "stale": True, "limit_days": limit_days,
                        "renew": renew})
            continue
        at, kind = _date(path)
        age_days = None if at is None else round((now - at) / DAY, 2)
        out.append({"file": name, "agents": agents, "present": True, "date_kind": kind,
                    "data_date": None if at is None else datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "age_days": age_days, "limit_days": limit_days,
                    "stale": age_days is None or age_days > limit_days, "renew": renew})
    return out


def main() -> int:
    rows = report()
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 1 if any(r["stale"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
